// W2 Worker: command protocol over one wasm instance with page-owned asset buffers.
"use strict";

let instance = null;
let panic = null;
const assets = {};
const decoder = new TextDecoder();
const encoder = new TextEncoder();
const view = () => new Uint8Array(instance.exports.memory.buffer);
const memoryBytes = () => (instance ? instance.exports.memory.buffer.byteLength : null);
const output = () => {
  const e = instance.exports;
  return JSON.parse(decoder.decode(view().slice(e.kj_output_ptr(), e.kj_output_ptr() + e.kj_output_len())));
};

async function loadAsset(asset) {
  const response = await fetch(asset.url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${asset.url}: HTTP ${response.status}`);
  const ptr = instance.exports.kj_alloc(asset.bytes);
  if (ptr === 0) throw new Error(`${asset.url}: allocation failed`);
  const reader = response.body.getReader();
  let offset = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (offset + value.byteLength > asset.bytes) throw new Error(`${asset.url}: longer than expected`);
    view().set(value, ptr + offset);
    offset += value.byteLength;
  }
  if (offset !== asset.bytes) throw new Error(`${asset.url}: ${offset} of ${asset.bytes} bytes`);
  assets[asset.name] = [ptr, asset.bytes];
}

const commands = {
  async init({ wasm }) {
    const bytes = await (await fetch(wasm, { cache: "no-store" })).arrayBuffer();
    ({ instance } = await WebAssembly.instantiate(bytes, { env: {
      kj_now_ms: () => performance.now(),
      kj_random_fill: (ptr, len) => {
        for (let offset = 0; offset < len; offset += 65536) {
          crypto.getRandomValues(view().subarray(ptr + offset, ptr + Math.min(len, offset + 65536)));
        }
        return 0;
      },
      kj_panic: (ptr, len) => { panic = decoder.decode(view().slice(ptr, ptr + len)); },
    } }));
    instance.exports.kj_init();
    return {};
  },
  async load({ list, heap_reserve_bytes }) {
    for (const asset of list) await loadAsset(asset);
    if (heap_reserve_bytes > 0) {
      // One memory.grow instead of many small ones (see W1 results).
      const reserve = instance.exports.kj_alloc(heap_reserve_bytes);
      if (reserve === 0) throw new Error("heap reserve allocation failed");
      instance.exports.kj_free(reserve, heap_reserve_bytes);
    }
    return {};
  },
  async corrupt({ asset, offset }) {
    const [ptr, len] = assets[asset];
    if (offset >= len) throw new Error("offset outside asset");
    view()[ptr + offset] ^= 0xff; // applying twice restores the byte
    return {};
  },
  async open() {
    const a = assets;
    const code = instance.exports.kj_session_open(...a.manifest, ...a.decision_config, ...a.tokenizer,
                                                  ...a.readout, ...a.model);
    return { code, output: output() };
  },
  async decide({ id, url, text, max_input_tokens }) {
    const bytes = text !== undefined ? encoder.encode(text)
      : new Uint8Array(await (await fetch(url, { cache: "no-store" })).arrayBuffer());
    const ptr = instance.exports.kj_alloc(bytes.byteLength);
    view().set(bytes, ptr);
    self.postMessage({ event: "decide_started", id });
    const code = instance.exports.kj_session_decide(ptr, bytes.byteLength, max_input_tokens);
    instance.exports.kj_free(ptr, bytes.byteLength);
    return { code, output: output() };
  },
};

self.onmessage = async ({ data }) => {
  const started = performance.now();
  panic = null;
  try {
    const reply = await commands[data.cmd](data);
    self.postMessage({ id: data.id, ...reply, panic, ms: performance.now() - started,
                       linear_memory_bytes: memoryBytes() });
  } catch (error) {
    self.postMessage({ id: data.id, error: String(error && error.stack || error), panic,
                       ms: performance.now() - started, linear_memory_bytes: memoryBytes() });
  }
};
