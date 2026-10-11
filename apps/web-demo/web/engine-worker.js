// Inference Worker: owns the wasm engine and the model bytes in its linear memory.
// Commands: init, load (network|cache), evaluate. Progress is posted as events.
"use strict";

let instance = null;
let panic = null;
const loaded = {};
const decoder = new TextDecoder();
const encoder = new TextEncoder();
const view = () => new Uint8Array(instance.exports.memory.buffer);
const hex = (buffer) => [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");

function output(code) {
  const e = instance.exports;
  const value = JSON.parse(decoder.decode(view().slice(e.demo_output_ptr(), e.demo_output_ptr() + e.demo_output_len())));
  return { code, value };
}

function put(bytes) {
  const ptr = instance.exports.demo_alloc(bytes.byteLength);
  view().set(bytes, ptr);
  return [ptr, bytes.byteLength];
}

// Streams one asset into linear memory, hashing each chunk in the engine as it lands.
async function stream(asset, body, onBytes) {
  const e = instance.exports;
  const ptr = e.demo_alloc(asset.bytes);
  if (ptr === 0) throw new Error(`メモリを確保できませんでした（${asset.path}）`);
  if (asset.slot !== null) e.demo_hash_begin(asset.slot, asset.bytes);
  const reader = body.getReader();
  let offset = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (offset + value.byteLength > asset.bytes) throw new Error(`${asset.path}: サイズが想定より大きい`);
    view().set(value, ptr + offset);
    if (asset.slot !== null && e.demo_hash_update(asset.slot, offset, ptr + offset, value.byteLength) !== 0) {
      throw new Error(`${asset.path}: hash更新の順序が不正`);
    }
    offset += value.byteLength;
    onBytes(value.byteLength);
  }
  if (offset !== asset.bytes) throw new Error(`${asset.path}: ${offset} / ${asset.bytes} bytesで終了`);
  return [ptr, asset.bytes];
}

const commands = {
  async init({ config }) {
    const bytes = await (await fetch(config.engine.url, { cache: "no-store" })).arrayBuffer();
    const sha = hex(await crypto.subtle.digest("SHA-256", bytes));
    if (sha !== config.engine.sha256) throw new Error("推論エンジン（wasm）のhashが一致しません");
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
    instance.exports.demo_init();
    return {};
  },

  async load({ config, source }) {
    const cache = await caches.open(config.cache_name);
    const assets = [{ ...config.manifest, slot: null }, ...config.assets];
    const total = assets.reduce((sum, a) => sum + a.bytes, 0);
    let done = 0;
    let lastPost = 0;
    const onBytes = (n) => {
      done += n;
      const now = performance.now();
      if (now - lastPost > 100 || done === total) {
        lastPost = now;
        self.postMessage({ event: "progress", done, total, source });
      }
    };
    const started = performance.now();
    for (const asset of assets) {
      let body;
      let saving = null;
      if (source === "cache") {
        const cached = await cache.match(asset.url);
        if (!cached) throw new Error(`保存済みデータに ${asset.path} がありません`);
        body = cached.body;
      } else {
        const response = await fetch(asset.url, { cache: "no-store" });
        if (!response.ok) throw new Error(`${asset.path} を取得できません（HTTP ${response.status}）`);
        const [toMemory, toCache] = response.body.tee();
        body = toMemory;
        saving = cache.put(asset.url, new Response(toCache, {
          headers: { "content-type": "application/octet-stream", "content-length": String(asset.bytes) } }));
      }
      loaded[asset.path] = await stream(asset, body, onBytes);
      if (saving) await saving;
    }
    const loadMs = performance.now() - started;
    // One memory.grow instead of many small ones during tokenizer setup and inference (W1).
    const reserve = instance.exports.demo_alloc(config.heap_reserve_bytes);
    if (reserve === 0) throw new Error("推論用のメモリを確保できませんでした");
    instance.exports.demo_free(reserve, config.heap_reserve_bytes);
    self.postMessage({ event: "verifying" });
    const m = config.manifest;
    const a = Object.fromEntries(config.assets.map((x) => [x.path, loaded[x.path]]));
    const code = instance.exports.demo_open(
      ...loaded[m.path], ...a["decision_config.json"], ...a["tokenizer.json"],
      ...a["readout.safetensors"], ...a["model.safetensors"],
      ...put(encoder.encode(m.sha256)), ...put(encoder.encode(config.engine.sha256)));
    const result = output(code);
    if (code !== 0) throw new Error(`検証に失敗しました: ${result.value.error}`);
    return { load_ms: loadMs, open: result.value, linear_memory_bytes: instance.exports.memory.buffer.byteLength };
  },

  async evaluate({ request, max_input_bytes, max_input_tokens }) {
    const [ptr, len] = put(encoder.encode(request));
    const started = performance.now();
    const code = instance.exports.demo_evaluate(ptr, len, max_input_bytes, max_input_tokens);
    const elapsed = performance.now() - started;
    instance.exports.demo_free(ptr, len);
    return { ...output(code), elapsed_ms: elapsed, linear_memory_bytes: instance.exports.memory.buffer.byteLength };
  },
};

self.onmessage = async ({ data }) => {
  panic = null;
  try {
    const reply = await commands[data.cmd](data);
    self.postMessage({ id: data.id, ok: true, ...reply, panic });
  } catch (error) {
    self.postMessage({ id: data.id, ok: false, error: String(error && error.message || error), panic });
  }
};
