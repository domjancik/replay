import { renderProbe } from './replay.mjs';

async function readAsset(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load ${url.pathname} (${response.status})`);
  return new Uint8Array(await response.arrayBuffer());
}

self.onmessage = async ({ data: { encode } }) => {
  try {
    const { manifest, rgba } = await renderProbe(new URL('/data/pyodide/', location.href), readAsset);
    const expected = await readAsset(new URL('/data/expected.rgba', location.href));
    const [width, height] = manifest.viewport;
    const frameSize = width * height * 4;
    if (rgba.length !== expected.length || rgba.length !== (manifest.frameCount + 1) * frameSize
        || !rgba.every((value, index) => value === expected[index])) {
      throw new Error('RGBA frames differ from the desktop Python baseline');
    }
    if (!manifest.finalEqualsStatic) throw new Error('The final frame differs from the static frame');
    const finalRgba = rgba.slice(-frameSize);
    self.postMessage({ manifest, finalRgba }, [finalRgba.buffer]);
    if (encode) {
      const { encodeReplay } = await import('/encoder.mjs');
      const { fps, frameCount } = manifest;
      async function* frames() {
        for (let index = 0; index < frameCount; index++) {
          yield rgba.subarray(index * frameSize, (index + 1) * frameSize);
        }
      }
      const video = await encodeReplay({ frames: frames(), width, height, fps, frameCount });
      self.postMessage({ video }, [video.buffer]);
    }
  } catch (error) {
    self.postMessage({ error: error.stack ?? String(error) });
  }
};
