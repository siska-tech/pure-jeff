// W0 Worker: instantiates one probe variant over the raw ABI and runs the fixtures.
"use strict";

// Smallest module using a v128 instruction; validates only where SIMD128 is supported.
const SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0,
  10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);

self.onmessage = async (event) => {
  const variant = event.data;
  const result = { variant: variant.name, steps: [], panic: null };
  let instance = null;
  const memoryBytes = () => (instance ? instance.exports.memory.buffer.byteLength : null);
  const step = (name, started, extra) => result.steps.push(
    { name, ms: performance.now() - started, linear_memory_bytes: memoryBytes(), ...extra });
  try {
    result.simd128_supported = WebAssembly.validate(SIMD_PROBE);
    let t = performance.now();
    const bytes = await (await fetch(variant.wasm, { cache: "no-store" })).arrayBuffer();
    step("fetch_wasm", t, { bytes: bytes.byteLength });
    if (variant.requires_simd128 && !result.simd128_supported) {
      result.skipped = "SIMD128 not supported by this browser";
      self.postMessage(result);
      return;
    }
    const decoder = new TextDecoder();
    const view = () => new Uint8Array(instance.exports.memory.buffer);
    const imports = { env: {
      kj_now_ms: () => performance.now(),
      kj_random_fill: (ptr, len) => {
        for (let offset = 0; offset < len; offset += 65536) {
          crypto.getRandomValues(view().subarray(ptr + offset, ptr + Math.min(len, offset + 65536)));
        }
        return 0;
      },
      kj_panic: (ptr, len) => { result.panic = decoder.decode(view().slice(ptr, ptr + len)); },
    } };
    t = performance.now();
    ({ instance } = await WebAssembly.instantiate(bytes, imports));
    step("instantiate", t);
    const e = instance.exports;
    e.kj_init();
    const output = (code) => {
      const value = JSON.parse(decoder.decode(view().slice(e.kj_output_ptr(), e.kj_output_ptr() + e.kj_output_len())));
      if (code !== 0) throw new Error(`probe error: ${value.error}`);
      return value;
    };
    const put = (data) => {
      const ptr = e.kj_alloc(data.byteLength);
      view().set(data, ptr);
      return ptr;
    };
    result.environment = output(e.kj_environment());
    for (const repeat of [0, 1]) {
      t = performance.now();
      result[`ops_${repeat}`] = output(e.kj_ops());
      step(`ops_${repeat}`, t);
    }
    t = performance.now();
    const tokenizer = new Uint8Array(await (await fetch(variant.tokenizer, { cache: "no-store" })).arrayBuffer());
    const job = new Uint8Array(await (await fetch(variant.job, { cache: "no-store" })).arrayBuffer());
    step("fetch_tokenizer_and_job", t, { bytes: tokenizer.byteLength + job.byteLength });
    t = performance.now();
    const tokenizerPtr = put(tokenizer);
    const jobPtr = put(job);
    result.tokenize = output(e.kj_tokenize(tokenizerPtr, tokenizer.byteLength, jobPtr, job.byteLength));
    step("tokenize", t);
    e.kj_free(tokenizerPtr, tokenizer.byteLength);
    e.kj_free(jobPtr, job.byteLength);
  } catch (error) {
    result.error = String(error && error.stack || error);
  }
  result.final_linear_memory_bytes = memoryBytes();
  self.postMessage(result);
};
