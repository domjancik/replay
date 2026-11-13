const MAX_REQUEST_BYTES = 32 * 1024 * 1024;
const MAX_RGBA_BYTES = 128 * 1024 * 1024;
const encoder = new TextEncoder();
const decoder = new TextDecoder();

export async function instantiateRenderer(source) {
  const result = await WebAssembly.instantiate(source, {});
  return bindRenderer((result.instance ?? result).exports);
}

export function bindRenderer(exports) {
  const {
    memory,
    rm_renderer_abi_version: version,
    rm_renderer_alloc: alloc,
    rm_renderer_free: free,
    rm_renderer_render_json: render,
    rm_renderer_output_ptr: outputPointer,
    rm_renderer_output_len: outputLength,
    rm_renderer_width: widthOf,
    rm_renderer_height: heightOf,
    rm_renderer_error_ptr: errorPointer,
    rm_renderer_error_len: errorLength,
  } = exports;
  const functions = [version, alloc, free, render, outputPointer, outputLength,
    widthOf, heightOf, errorPointer, errorLength];
  if (!(memory instanceof WebAssembly.Memory) || functions.some((fn) => typeof fn !== 'function')) {
    throw new TypeError('Incomplete WASM renderer exports');
  }
  const abiVersion = version();
  if (abiVersion !== 1) throw new Error(`Unsupported renderer ABI version ${abiVersion}`);

  function renderJson(json) {
    const bytes = typeof json === 'string' ? encoder.encode(json) : json;
    if (!(bytes instanceof Uint8Array) || !bytes.byteLength || bytes.byteLength > MAX_REQUEST_BYTES) {
      throw new RangeError('Renderer request must be nonempty JSON of at most 32 MiB');
    }
    const length = bytes.byteLength;
    const pointer = alloc(length) >>> 0;
    if (!pointer) throw new Error('WASM renderer could not allocate the request');
    try {
      new Uint8Array(memory.buffer, pointer, length).set(bytes);
      const status = render(pointer, length) >>> 0;
      if (status) {
        const message = decoder.decode(new Uint8Array(memory.buffer, errorPointer() >>> 0, errorLength() >>> 0));
        throw new Error(message || `WASM renderer rejected the request (${status})`);
      }
      const width = widthOf() >>> 0;
      const height = heightOf() >>> 0;
      const size = outputLength() >>> 0;
      if (!width || !height || size !== width * height * 4 || size > MAX_RGBA_BYTES) {
        throw new RangeError('WASM renderer returned an invalid RGBA length');
      }
      const rgba = new Uint8Array(memory.buffer, outputPointer() >>> 0, size).slice();
      return { width, height, rgba };
    } finally {
      free(pointer, length);
    }
  }

  return {
    abiVersion,
    get memoryBytes() { return memory.buffer.byteLength; },
    render: (request) => renderJson(JSON.stringify(request)),
    renderJson,
  };
}
