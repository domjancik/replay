import assert from 'node:assert/strict';
import test from 'node:test';

const load = () => import('./renderer.mjs').catch((error) => assert.fail(error.message));

function mock({ fail = false, invalidLength = false, version = 1 } = {}) {
  const calls = [];
  const memory = new WebAssembly.Memory({ initial: 1 });
  return { calls, exports: {
    memory,
    rm_renderer_abi_version: () => version,
    rm_renderer_alloc: (size) => { calls.push(['alloc', size]); return 128; },
    rm_renderer_free: (ptr, size) => calls.push(['free', ptr, size]),
    rm_renderer_render_json: (ptr, size) => {
      calls.push(['render', new TextDecoder().decode(new Uint8Array(memory.buffer, ptr, size))]);
      memory.grow(1);
      const bytes = new Uint8Array(memory.buffer, 256, 4);
      bytes.set(fail ? new TextEncoder().encode('oops') : [1, 2, 3, 4]);
      return Number(fail);
    },
    rm_renderer_output_ptr: () => 256,
    rm_renderer_output_len: () => invalidLength ? 8 : 4,
    rm_renderer_width: () => 1,
    rm_renderer_height: () => 1,
    rm_renderer_error_ptr: () => 256,
    rm_renderer_error_len: () => 4,
  } };
}

test('copies RGBA after WASM memory growth, frees input and retains earlier output', async () => {
  const { bindRenderer } = await load();
  const { calls, exports } = mock();
  const renderer = bindRenderer(exports);
  const first = renderer.render({ page: 'sample' });
  assert.deepEqual([first.width, first.height, ...first.rgba], [1, 1, 1, 2, 3, 4]);
  assert.equal(renderer.abiVersion, 1);
  assert.deepEqual(calls, [['alloc', 17], ['render', '{"page":"sample"}'], ['free', 128, 17]]);
  renderer.renderJson('{"page":"again"}');
  assert.deepEqual([...first.rgba], [1, 2, 3, 4]);
});

test('reports WASM errors, frees invalid input, and rejects malformed output and ABI', async () => {
  const { bindRenderer } = await load();
  const failing = mock({ fail: true });
  assert.throws(() => bindRenderer(failing.exports).renderJson('{}'), /oops/);
  assert.deepEqual(failing.calls.at(-1), ['free', 128, 2]);
  assert.throws(() => bindRenderer(mock({ invalidLength: true }).exports).renderJson('{}'), /length/);
  assert.throws(() => bindRenderer(mock({ version: 2 }).exports), /version 2/);
});
