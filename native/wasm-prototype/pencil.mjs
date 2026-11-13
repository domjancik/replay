const GAIN_COUNT = 65536;
const MAX_BUFFER_BYTES = 64 * 1024 * 1024;

export async function instantiatePencil(module) {
  const instance = await WebAssembly.instantiate(module);
  const {
    memory, pencil_abi_version, pencil_alloc, pencil_free, rm_pencil_draw,
  } = instance.exports;
  const abiVersion = pencil_abi_version();
  if (abiVersion !== 1) {
    throw new Error(`Unsupported pencil ABI version ${abiVersion}`);
  }

  return {
    abiVersion,
    get memoryBytes() { return memory.buffer.byteLength; },
    draw(initial, { width, height, originX, originY, scaleX, scaleY, opacity }, samples, gains) {
      if (!(initial instanceof Uint8Array)
          || !Number.isSafeInteger(width) || width <= 0
          || !Number.isSafeInteger(height) || height <= 0
          || initial.length !== width * height
          || !Number.isSafeInteger(originX) || !Number.isSafeInteger(originY)
          || !Number.isInteger(opacity) || opacity < 0 || opacity > 255
          || !(samples instanceof Float64Array) || samples.length % 4 !== 0
          || !(gains instanceof Float64Array) || gains.length !== GAIN_COUNT) {
        throw new TypeError('Invalid pencil mask, origin, opacity, samples, or gains');
      }

      // The allocation and both Float64Array views need eight-byte alignment.
      const sampleOffset = Math.ceil(initial.length / 8) * 8;
      const gainOffset = sampleOffset + samples.byteLength;
      const byteLength = gainOffset + gains.byteLength;
      if (byteLength > MAX_BUFFER_BYTES) {
        throw new RangeError('Pencil prototype input exceeds 64 MiB');
      }
      const pointer = pencil_alloc(byteLength) >>> 0;
      if (pointer === 0) {
        throw new RangeError('Could not allocate pencil buffers');
      }

      try {
        new Uint8Array(memory.buffer, pointer, initial.length).set(initial);
        new Float64Array(memory.buffer, pointer + sampleOffset, samples.length).set(samples);
        new Float64Array(memory.buffer, pointer + gainOffset, gains.length).set(gains);
        const status = rm_pencil_draw(
          pointer, width, height, BigInt(originX), BigInt(originY), scaleX, scaleY,
          opacity, pointer + sampleOffset, samples.length / 4, pointer + gainOffset, gains.length,
        );
        if (status !== 0) {
          throw new Error(`WASM pencil kernel rejected the batch (status ${status})`);
        }
        // The kernel's tile allocations may grow memory and detach earlier views.
        return new Uint8Array(memory.buffer, pointer, initial.length).slice();
      } finally {
        pencil_free(pointer, byteLength);
      }
    },
  };
}
