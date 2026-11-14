import assert from 'node:assert/strict';
import test from 'node:test';

const importEncoder = () => import('./encoder.mjs').catch((error) => {
  assert.fail(`Expected a replay encoder module: ${error.message}`);
});

const settings = { width: 2, height: 2, fps: 12, frameCount: 2 };
const frame = () => new Uint8Array(16).fill(255);

function runtime(supported = 'vp9') {
  const events = [];
  return {
    events,
    async canEncode(candidate) {
      events.push(candidate.codec);
      return candidate.codec === supported;
    },
    create(candidate) {
      events.push(candidate.container);
      return {
        async start() { events.push('start'); },
        async add(bytes, timestamp, duration, keyFrame) {
          events.push([bytes[0], timestamp, duration, keyFrame]);
          await Promise.resolve();
          events.push('encoded');
        },
        async finish() { events.push('finish'); return new ArrayBuffer(2); },
        async cancel() { events.push('cancel'); },
      };
    },
  };
}

test('negotiates WebM fallback and submits one exact timed frame at a time', async () => {
  const { createReplayEncoder } = await importEncoder();
  const mocked = runtime();
  const encode = createReplayEncoder(mocked);
  const result = await encode({ ...settings, frames: [frame(), frame()] });
  assert.deepEqual(mocked.events, [
    'avc', 'vp9', 'webm', 'start',
    [255, 0, 1 / 12, true], 'encoded',
    [255, 1 / 12, 1 / 12, false], 'encoded', 'finish',
  ]);
  assert.equal(result.mimeType, 'video/webm');
  assert.equal(result.codec, 'vp9');
  assert.equal(result.buffer.byteLength, 2);
});

test('cancels a short frame stream and rejects invalid settings before encoding', async () => {
  const { createReplayEncoder } = await importEncoder();
  const mocked = runtime('avc');
  const encode = createReplayEncoder(mocked);
  await assert.rejects(encode({ ...settings, width: 3, frames: [] }), /dimensions/);
  assert.deepEqual(mocked.events, []);
  await assert.rejects(encode({ ...settings, frames: [frame()] }), /2 frames/);
  assert.equal(mocked.events.at(-1), 'cancel');
  assert.ok(!mocked.events.includes('finish'));
});

test('stops fetching frames when the progress handler aborts', async () => {
  const { createReplayEncoder } = await importEncoder();
  const controller = new AbortController();
  const mocked = runtime('avc');
  let yielded = 0;
  async function* frames() {
    yielded++;
    yield frame();
    yielded++;
    yield frame();
  }
  await assert.rejects(createReplayEncoder(mocked)({
    ...settings,
    frames: frames(),
    signal: controller.signal,
    onProgress: () => controller.abort(),
  }), { name: 'AbortError' });
  assert.equal(yielded, 1);
  assert.equal(mocked.events.at(-1), 'cancel');
});

test('bounds the muxed bytes before copying and supports seekable writes', async () => {
  const { BoundedVideoBuffer } = await importEncoder();
  const sink = new BoundedVideoBuffer(4);
  sink.write(new Uint8Array([3, 4]), 2);
  sink.write(new Uint8Array([1, 2]), 0);
  assert.throws(() => sink.write(new Uint8Array([5]), 4), /byte limit/);
  assert.deepEqual([...new Uint8Array(sink.finish())], [1, 2, 3, 4]);
});

 test('supports full and double resolution with longer loop exports',async()=>{
 const {createReplayEncoder}=await importEncoder();const mocked=runtime('avc');
 await assert.rejects(createReplayEncoder(mocked)({width:2808,height:3744,fps:6,frameCount:400,frames:[]}),/400 frames/);
 assert.ok(mocked.events.includes('start'));
 });

test('fractional bitrate estimates become positive integers for capability checks and encoding', async () => {
  const {createReplayEncoder} = await importEncoder();
  const config = {width:1404,height:1872,fps:12,frameCount:1};
  let checks=0;
  const mocked=runtime('avc');
  const create=mocked.create;
  mocked.canEncode=async (_candidate,options)=>{
    assert.equal(Number.isInteger(options.bitrate),true);
    assert.equal(options.bitrate,3784735); checks++;return true;
  };
  mocked.create=(candidate,options)=>{assert.equal(options.bitrate,3784735);checks++;return create(candidate);};
  await createReplayEncoder(mocked)({...config,frames:[new Uint8Array(config.width*config.height*4)]});
  assert.equal(checks,2);
});
