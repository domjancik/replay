import { instantiateRenderer } from './renderer.mjs';

async function fetchLocal(path, read) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Could not read ${path} (${response.status})`);
  return response[read]();
}

const equal = (left, right) => left.length === right.length
  && left.every((value, index) => value === right[index]);

self.onmessage = async ({ data: { encode } }) => {
  try {
    const [binary, cases] = await Promise.all([
      fetchLocal('/renderer.wasm', 'arrayBuffer'), fetchLocal('/sample/cases.json', 'json'),
    ]);
    const renderer = await instantiateRenderer(binary);
    const staticCase = cases.find(({ id }) => id === 'replay-static');
    const frames = cases.filter(({ id }) => id !== 'replay-static');
    const { width, height } = staticCase;
    const start = performance.now();
    let parityCount = 0;
    let last;
    async function renderCase(item) {
      const [json, raw] = await Promise.all([
        fetchLocal(`/sample/${item.request}`, 'text'), fetchLocal(`/sample/${item.rgba}`, 'arrayBuffer'),
      ]);
      const result = renderer.renderJson(json);
      if (result.width !== width || result.height !== height) throw new Error('Unexpected dimensions');
      if (equal(result.rgba, new Uint8Array(raw))) parityCount++;
      return result.rgba;
    }
    async function* renderFrames() {
      for (let index = 0; index < frames.length; index++) {
        last = await renderCase(frames[index]);
        postMessage({ progress: index + 1, frameCount: frames.length });
        yield last;
      }
    }
    let video;
    if (encode) {
      const { encodeReplay } = await import('/encoder.mjs');
      video = await encodeReplay({ frames: renderFrames(), width, height, frameCount: frames.length, fps: 12 });
    } else {
      for await (const _frame of renderFrames()) {
        // Rendering and parity checks run when the generator advances.
      }
    }
    const rgba = await renderCase(staticCase);
    const transfer = [rgba.buffer];
    if (video) transfer.push(video.buffer);
    postMessage({
      rgba, width, height, video, parityCount, caseCount: cases.length,
      finalEqualsStatic: equal(last, rgba), elapsedMs: performance.now() - start,
      memoryBytes: renderer.memoryBytes,
    }, transfer);
  } catch (error) {
    postMessage({ error: error.message });
  }
};
