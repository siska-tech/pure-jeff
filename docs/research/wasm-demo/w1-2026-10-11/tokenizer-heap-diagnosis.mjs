// Isolates tokenizer load time with and without a 1.7 GB allocation already in linear memory.
import fs from "node:fs";
import { webcrypto } from "node:crypto";
const [wasmPath, tokPath, jobPath, bigBytes] = process.argv.slice(2);
const wasm = fs.readFileSync(wasmPath), tok = fs.readFileSync(tokPath), job = fs.readFileSync(jobPath);
async function trial(big, reserve = 0) {
  let inst;
  const view = () => new Uint8Array(inst.exports.memory.buffer);
  ({ instance: inst } = await WebAssembly.instantiate(wasm, { env: {
    kj_now_ms: () => performance.now(),
    kj_random_fill: (p, l) => { for (let o = 0; o < l; o += 65536) webcrypto.getRandomValues(view().subarray(p + o, p + Math.min(l, o + 65536))); return 0; },
    kj_panic: (p, l) => console.log("panic", new TextDecoder().decode(view().slice(p, p + l))) } }));
  const e = inst.exports; e.kj_init();
  if (big) { const p = e.kj_alloc(big); view().fill(1, p, p + big); }
  if (reserve) { const r = e.kj_alloc(reserve); e.kj_free(r, reserve); }
  const put = (b) => { const p = e.kj_alloc(b.length); view().set(b, p); return p; };
  const t = performance.now();
  const code = e.kj_tokenize(put(tok), tok.length, put(job), job.length);
  const out = JSON.parse(new TextDecoder().decode(view().slice(e.kj_output_ptr(), e.kj_output_ptr() + e.kj_output_len())));
  console.log(JSON.stringify({ big, reserve, code, total_ms: Math.round(performance.now() - t), hash_ms: Math.round(out.hash_ms), load_ms: Math.round(out.load_ms), mem_mib: e.memory.buffer.byteLength >> 20 }));
}
await trial(Number(bigBytes), 805306368); await trial(Number(bigBytes));
