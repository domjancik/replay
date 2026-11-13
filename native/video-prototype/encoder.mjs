const candidates = [
  { container: 'mp4', codec: 'avc', mimeType: 'video/mp4' },
  { container: 'webm', codec: 'vp9', mimeType: 'video/webm' },
  { container: 'webm', codec: 'vp8', mimeType: 'video/webm' },
];

export const MAX_VIDEO_BYTES = 64 * 1024 * 1024;

export class BoundedVideoBuffer {
  #bytes = new Uint8Array();
  #length = 0;
  #limit;

  constructor(limit = MAX_VIDEO_BYTES) {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_VIDEO_BYTES) {
      throw new RangeError('Invalid video byte limit.');
    }
    this.#limit = limit;
  }

  write(data, position) {
    const end = position + data.length;
    if (!Number.isSafeInteger(position) || position < 0 || end > this.#limit) {
      throw new RangeError('Export exceeded the video byte limit.');
    }
    if (end > this.#bytes.length) {
      const capacity = Math.min(this.#limit, Math.max(end, 1024, this.#bytes.length * 2));
      const next = new Uint8Array(capacity);
      next.set(this.#bytes);
      this.#bytes = next;
    }
    this.#bytes.set(data, position);
    this.#length = Math.max(this.#length, end);
  }

  finish() {
    const result = this.#bytes.buffer.slice(0, this.#length);
    this.#bytes = new Uint8Array();
    this.#length = 0;
    return result;
  }
}

export function createReplayEncoder(runtime) {
  return async function encodeReplay({
    frames, width, height, fps, frameCount, signal, onProgress,
    container = 'auto', maxBytes = MAX_VIDEO_BYTES,
  }) {
    if (![width, height].every((n) => Number.isInteger(n) && n >= 2 && n <= 1280 && n % 2 === 0)
        || width * height > 1280 * 720) {
      throw new RangeError('Use even video dimensions within a 1280×720 pixel budget.');
    }
    if (!Number.isInteger(fps) || fps < 1 || fps > 30
        || !Number.isInteger(frameCount) || frameCount < 1 || frameCount > 60 * fps) {
      throw new RangeError('Use 1–30 fps and a video duration of at most 60 seconds.');
    }
    if (!['auto', 'mp4', 'webm'].includes(container)) {
      throw new RangeError('Choose automatic, MP4 or WebM output.');
    }
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > MAX_VIDEO_BYTES) {
      throw new RangeError('Invalid video byte limit.');
    }

    const config = { width, height, fps, bitrate: 2_000_000, maxBytes };
    let selection;
    for (const candidate of candidates) {
      signal?.throwIfAborted();
      if ((container === 'auto' || container === candidate.container)
          && await runtime.canEncode(candidate, config)) {
        selection = candidate;
        break;
      }
    }
    signal?.throwIfAborted();
    if (!selection) throw new Error('No browser video encoder supports the selected format.');

    const writer = runtime.create(selection, config);
    try {
      await writer.start();
      signal?.throwIfAborted();
      let index = 0;
      for await (const bytes of frames) {
        signal?.throwIfAborted();
        if (index >= frameCount) throw new RangeError(`Expected exactly ${frameCount} frames.`);
        if (!(bytes instanceof Uint8Array || bytes instanceof Uint8ClampedArray)
            || bytes.byteLength !== width * height * 4) {
          throw new TypeError('Frame must contain exactly width × height × 4 RGBA bytes.');
        }
        await writer.add(bytes, index / fps, 1 / fps, index % (2 * fps) === 0);
        index++;
        onProgress?.(index, frameCount);
        signal?.throwIfAborted();
      }
      if (index !== frameCount) throw new RangeError(`Expected exactly ${frameCount} frames.`);
      const buffer = await writer.finish();
      signal?.throwIfAborted();
      return {
        buffer, mimeType: selection.mimeType, extension: `.${selection.container}`,
        codec: selection.codec, frameCount,
      };
    } catch (error) {
      await writer.cancel().catch(() => {});
      throw error;
    }
  };
}
