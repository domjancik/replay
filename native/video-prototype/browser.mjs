import {
  CanvasSource, Mp4OutputFormat, Output, Quality, StreamTarget, WebMOutputFormat, canEncodeVideo,
} from 'mediabunny';
import { BoundedVideoBuffer, createReplayEncoder } from './encoder.mjs';

export const encodeReplay = createReplayEncoder({
  async canEncode({ codec }, { width, height, fps, bitrate }) {
    return typeof VideoEncoder !== 'undefined' && typeof OffscreenCanvas !== 'undefined'
      && await canEncodeVideo(codec, {
        width, height, frameRate: fps, quality: new Quality({ bitrate }),
      });
  },

  create({ codec, container }, { width, height, fps, bitrate, maxBytes }) {
    const canvas = new OffscreenCanvas(width, height);
    const context = canvas.getContext('2d', { alpha: false });
    if (!context) throw new Error('The browser could not allocate an encoding canvas.');
    const image = context.createImageData(width, height);
    const sink = new BoundedVideoBuffer(maxBytes);
    const output = new Output({
      format: container === 'mp4' ? new Mp4OutputFormat({ fastStart: false }) : new WebMOutputFormat(),
      target: new StreamTarget(new WritableStream({
        write({ data, position }) { sink.write(data, position); },
      })),
    });
    const source = new CanvasSource(canvas, { codec, quality: new Quality({ bitrate }) });
    output.addVideoTrack(source, { frameRate: fps });
    return {
      start: () => output.start(),
      async add(bytes, timestamp, duration, keyFrame) {
        image.data.set(bytes);
        context.putImageData(image, 0, 0);
        await source.add(timestamp, duration, { keyFrame });
      },
      async finish() {
        await output.finalize();
        return sink.finish();
      },
      cancel: () => output.state === 'finalized' ? Promise.resolve() : output.cancel(),
    };
  },
});
