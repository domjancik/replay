import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const artifacts = new URL('../../artifacts/browser-prototype-20261113/', import.meta.url);

test('Pyodide reproduces the native mixed-tool replay and final static frame', async () => {
  const { renderProbe } = await import('./replay.mjs');
  const expected = new Uint8Array(await readFile(new URL('expected.rgba', artifacts)));
  const { manifest, rgba } = await renderProbe(new URL('pyodide/', artifacts), readFile);
  assert.equal(manifest.python.slice(0, 5), '3.13.');
  assert.equal(manifest.pyodide, '0.29.5');
  assert.deepEqual(manifest.viewport, [96, 72]);
  assert.deepEqual(manifest.paperSize, [128, 96]);
  assert.equal(manifest.layers, 2);
  assert.deepEqual(manifest.tools, [6, 12, 14, 17, 18, 21]);
  assert.equal(manifest.frameCount, 29);
  assert.equal(manifest.changedFrames, 23);
  assert.equal(manifest.finalEqualsStatic, true);
  const frameSize = manifest.viewport[0] * manifest.viewport[1] * 4;
  assert.equal(rgba.length, (manifest.frameCount + 1) * frameSize);
  assert.deepEqual(rgba.slice(-frameSize), rgba.slice(-2 * frameSize, -frameSize));
  assert.equal(rgba.length, expected.length);
  for (let offset = 0; offset < rgba.length; offset += frameSize) {
    assert.equal(
      Buffer.compare(rgba.subarray(offset, offset + frameSize), expected.subarray(offset, offset + frameSize)),
      0,
      `RGBA mismatch at frame ${offset / frameSize}`,
    );
  }
  console.log(JSON.stringify(manifest, null, 2));
});
