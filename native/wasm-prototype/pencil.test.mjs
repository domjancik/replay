import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const artifactRoot = new URL('../../artifacts/wasm-feasibility-20261113/', import.meta.url);

test('the WASM pencil reproduces the Python/native mask bytes for each synthetic input', async () => {
  const { instantiatePencil } = await import('./pencil.mjs');
  const module = await WebAssembly.compile(await readFile(new URL(
    'target/wasm32-unknown-unknown/release/rm_pencil_wasm_prototype.wasm', artifactRoot,
  )));
  assert.deepEqual(WebAssembly.Module.imports(module), []);
  const pencil = await instantiatePencil(module);
  const gainBytes = await readFile(new URL('goldens/gains.f64', artifactRoot));
  const gains = new Float64Array(gainBytes.buffer, gainBytes.byteOffset, 65536);
  const cases = JSON.parse(await readFile(new URL('goldens/cases.json', artifactRoot), 'utf8'));

  assert.equal(pencil.abiVersion, 1);
  assert.equal(cases.length, 6);
  const report = [];
  for (const fixture of cases) {
    const initial = await readFile(new URL(`goldens/${fixture.name}.initial`, artifactRoot));
    const expected = await readFile(new URL(`goldens/${fixture.name}.mask`, artifactRoot));
    const samples = Float64Array.from(fixture.samples.flat());
    const start = performance.now();
    const actual = pencil.draw(initial, fixture, samples, gains);
    const elapsedMs = performance.now() - start;
    assert.deepEqual(Buffer.from(actual), expected, fixture.name);
    assert.equal(initial.every((value) => value === fixture.initial), true, fixture.name);
    report.push({
      case: fixture.name,
      samples: fixture.samples.length,
      pixels: expected.length,
      elapsed_ms: Number(elapsedMs.toFixed(3)),
      linear_memory_bytes: pencil.memoryBytes,
      sha256: fixture.sha256,
    });
  }

  const fixture = cases[0];
  const initial = new Uint8Array([19]);
  assert.throws(() => pencil.draw(initial, { ...fixture, scaleX: 0 }, new Float64Array(), gains),
    /status 2/);
  assert.deepEqual(initial, new Uint8Array([19]));
  assert.deepEqual(pencil.draw(initial, fixture, new Float64Array(), gains), initial);
  console.log(JSON.stringify({
    wasm_bytes: (await readFile(new URL(
      'target/wasm32-unknown-unknown/release/rm_pencil_wasm_prototype.wasm', artifactRoot,
    ))).byteLength,
    cases: report,
  }, null, 2));
});
