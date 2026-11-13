import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { instantiateRenderer } from './renderer.mjs';

const base = new URL('../../artifacts/rust-renderer/', import.meta.url);
const { values: flags } = parseArgs({ options: {
  wasm: { type: 'string' }, native: { type: 'string' },
  suite: { type: 'string', default: 'synthetic' },
  filter: { type: 'string' }, report: { type: 'string' },
  'keep-outputs': { type: 'boolean', default: false },
} });
if (!flags.wasm && !flags.native) throw new Error('Pass --wasm FILE, --native FILE, or both');
if (!['synthetic', 'private'].includes(flags.suite)) throw new Error('Unknown corpus suite');
if (flags.report && !/^[a-zA-Z0-9_-]+$/.test(flags.report)) {
  throw new Error('Report name must contain only letters, digits, hyphens or underscores');
}

const suite = new URL(`${flags.suite}/`, base);
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const manifest = JSON.parse(await readFile(new URL('cases.json', suite), 'utf8'));
const cases = manifest.cases.filter(({ id }) => !flags.filter || id.includes(flags.filter));
assert.ok(cases.length, 'No cases match the filter');
const wasmBytes = flags.wasm && await readFile(resolve(flags.wasm));
const module = wasmBytes && await instantiateRenderer(wasmBytes);
const output = new URL(`verification/${flags.suite}/`, base);
await mkdir(output, { recursive: true });
const inputs = {};
if (wasmBytes) inputs.wasm = sha256(wasmBytes);
if (flags.native) inputs.native = sha256(await readFile(resolve(flags.native)));

function compare(expected, actual, width) {
  assert.equal(actual.length, expected.length);
  let changedPixels = 0;
  let maxChannelDelta = 0;
  let firstDifference = null;
  const absoluteChannelError = [0, 0, 0, 0];
  for (let index = 0; index < expected.length; index += 4) {
    let changed = false;
    for (let channel = 0; channel < 4; channel++) {
      const delta = Math.abs(expected[index + channel] - actual[index + channel]);
      if (delta === 0) continue;
      changed = true;
      absoluteChannelError[channel] += delta;
      maxChannelDelta = Math.max(maxChannelDelta, delta);
    }
    if (changed) {
      changedPixels++;
      firstDifference ??= {
        x: index / 4 % width,
        y: Math.floor(index / 4 / width),
        expected: [...expected.subarray(index, index + 4)],
        actual: [...actual.subarray(index, index + 4)],
      };
    }
  }
  return {
    exact: changedPixels === 0, changedPixels, maxChannelDelta, firstDifference,
    channelMae: absoluteChannelError.map((error) => error / (expected.length / 4)),
    rgbaSha256: sha256(actual),
  };
}

async function nativeRender(item) {
  const request = new URL(item.request, suite);
  const out = new URL(`${item.id}-native.rgba`, output);
  const result = spawnSync(resolve(flags.native), [
    fileURLToPath(request), fileURLToPath(out),
  ], { encoding: 'utf8', timeout: 10 * 60_000 });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, result.stderr);
  return { ...JSON.parse(result.stdout), rgba: await readFile(out) };
}

const results = [];
for (const item of cases) {
  const expected = await readFile(new URL(item.rgba, suite));
  assert.equal(sha256(expected), item.sha256, `Golden hash mismatch for ${item.id}`);
  const record = {
    id: item.id, width: item.width, height: item.height, expected: item.sha256,
    pythonSeconds: item.python_seconds,
  };
  const rendered = {};
  for (const [backend, operation] of Object.entries({
    ...(module && { wasm: async () => module.renderJson(await readFile(new URL(item.request, suite))) }),
    ...(flags.native && { native: async () => nativeRender(item) }),
  })) {
    try {
      const start = performance.now();
      const result = await operation();
      const elapsedMs = performance.now() - start;
      assert.deepEqual([result.width, result.height], [item.width, item.height]);
      rendered[backend] = result.rgba;
      record[backend] = { ...compare(expected, result.rgba, item.width), elapsedMs };
      if (backend === 'wasm' && (flags['keep-outputs'] || !record[backend].exact)) {
        await writeFile(new URL(`${item.id}-wasm.rgba`, output), result.rgba);
      }
    } catch (error) {
      record[backend] = { exact: false, error: error.message };
    }
  }
  if (rendered.wasm && rendered.native) {
    record.nativeWasm = compare(rendered.native, rendered.wasm, item.width);
  }
  results.push(record);
}

const methods = ['native', 'wasm', 'nativeWasm'];
if (inputs.native) {
  assert.equal(sha256(await readFile(resolve(flags.native))), inputs.native,
    'Native executable changed during verification');
}
const summary = Object.fromEntries(methods.flatMap((name) => {
  const available = results.map((entry) => entry[name]).filter(Boolean);
  return available.length ? [[name, {
    cases: available.length, exact: available.filter(({ exact }) => exact).length,
    errors: available.filter(({ error }) => error).length,
    maxChannelDelta: Math.max(0, ...available.map(({ maxChannelDelta }) => maxChannelDelta ?? 0)),
  }]] : [];
}));
const report = new URL(`${flags.report ?? 'report'}.json`, output);
await writeFile(report, JSON.stringify({
  schema: 1, suite: flags.suite, pillow: manifest.pillow, binarySha256: inputs, summary, results,
}, null, 2));
console.log(JSON.stringify({ summary, report: fileURLToPath(report) }, null, 2));
if (Object.values(summary).some(({ cases, exact }) => exact !== cases)) process.exitCode = 1;
