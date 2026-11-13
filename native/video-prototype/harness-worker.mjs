import { encodeReplay } from './encoder.mjs';

const width = 96;
const height = 72;
const fps = 12;
const frameCount = 29;
let controller;

async function* syntheticFrames() {
  for (let frame = 0; frame < frameCount; frame++) {
    const rgba = new Uint8Array(width * height * 4).fill(255);
    for (let y = 14; y < 58; y++) {
      for (let x = 12; x < 12 + frame * 2; x++) {
        const pixel = (y * width + x) * 4;
        rgba[pixel] = 34;
        rgba[pixel + 1] = 80;
        rgba[pixel + 2] = 57;
      }
    }
    yield rgba;
  }
}

self.onmessage = async ({ data }) => {
  if (data.cancel) {
    controller?.abort();
    return;
  }
  controller = new AbortController();
  try {
    const result = await encodeReplay({
      frames: syntheticFrames(), width, height, fps, frameCount,
      container: data.container, signal: controller.signal,
      onProgress: (progress) => postMessage({ progress, frameCount }),
    });
    postMessage(result, [result.buffer]);
  } catch (error) {
    postMessage({ error: error.name === 'AbortError' ? 'Canceled' : error.message });
  }
};
