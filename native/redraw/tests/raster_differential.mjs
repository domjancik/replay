import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { instantiateRenderer } from '../renderer.mjs';

const [wasm] = process.argv.slice(2);
if (!wasm) throw new Error('Pass the standalone renderer WASM binary');
const artifact = new URL('../../../artifacts/rust-renderer-raster/randomized.json', import.meta.url);
const cases = JSON.parse(await readFile(artifact, 'utf8'));
const renderer = await instantiateRenderer(await readFile(wasm));
assert.equal(cases.length, 700);
for (const [tool, index, request, expected] of cases) {
  const actual = createHash('sha256').update(renderer.renderJson(request).rgba).digest('hex');
  assert.equal(actual, expected, `tool ${tool}, case ${index}`);
}
console.log(`${cases.length} synthetic cases matched Pillow exactly in WASM`);
