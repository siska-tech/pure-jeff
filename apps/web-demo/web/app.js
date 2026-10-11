// Main thread: UI, model cache management and the inference Worker's lifecycle.
"use strict";

const $ = (id) => document.getElementById(id);
const SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0,
  10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);
const FAILURES = {
  budget_exceeded: "予算超過：入力が長すぎます（最大512 tokens）",
  invalid_request: "入力が不正です",
  invalid_output: "出力の検証に失敗しました",
  unavailable: "推論できませんでした",
  timeout: "時間切れです",
};

// Read-only view of the state for people and automated checks.
const state = { model: "unknown", running: false, last: null, config: null };
window.kazeDemo = state;

let config = null;
let samples = [];
let worker = null;

function formatBytes(n) {
  return n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${n} bytes`;
}

function spawn() {
  const w = new Worker("engine-worker.js");
  const pending = new Map();
  const listeners = new Set();
  let next = 0;
  w.onmessage = ({ data }) => {
    if (data.event) { listeners.forEach((f) => f(data)); return; }
    const resolve = pending.get(data.id);
    pending.delete(data.id);
    if (resolve) resolve(data);
  };
  w.onerror = (event) => {
    for (const resolve of pending.values()) resolve({ ok: false, error: `Workerエラー: ${event.message}` });
    pending.clear();
  };
  return {
    call(cmd, args = {}) {
      return new Promise((resolve) => { const id = next++; pending.set(id, resolve); w.postMessage({ id, cmd, ...args }); });
    },
    listen(f) { listeners.add(f); },
    terminate() {
      w.terminate();
      for (const resolve of pending.values()) resolve({ ok: false, terminated: true });
      pending.clear();
    },
  };
}

async function cachedComplete() {
  // caches.open would create an empty cache, so check existence first.
  if (!("caches" in self) || !(await caches.has(config.cache_name))) return false;
  const cache = await caches.open(config.cache_name);
  const hits = await Promise.all([config.manifest, ...config.assets].map((a) => cache.match(a.url)));
  return hits.every(Boolean);
}

async function removeOldCaches() {
  for (const name of await caches.keys()) {
    if (name.startsWith("pure-jeff-model-") && name !== config.cache_name) await caches.delete(name);
  }
}

async function showStorage() {
  if (!navigator.storage || !navigator.storage.estimate) return;
  const { usage, quota } = await navigator.storage.estimate();
  $("storage").textContent = `このサイトの保存領域：${formatBytes(usage)} 使用 / 上限の目安 ${formatBytes(quota)}`;
}

function setModel(model, message) {
  state.model = model;
  $("model-status").textContent = message;
  const busy = model === "loading";
  $("download").disabled = busy || model === "unsupported" || model.startsWith("ready");
  $("load-cached").disabled = busy || !["cached", "ready-cached"].includes(model) || model.startsWith("ready");
  $("delete-cache").disabled = busy || !["cached", "ready-cached"].includes(model);
  $("stop-load").hidden = !busy;
  $("model-progress").hidden = !busy;
  $("evaluate").disabled = !model.startsWith("ready") || state.running;
}

async function refreshModel() {
  const cached = await cachedComplete();
  if (state.model.startsWith("ready")) {
    setModel(cached ? "ready-cached" : "ready",
      cached ? "読み込み済み（このブラウザに保存済み）" : "読み込み済み（保存データはありません）");
  } else if (cached) {
    setModel("cached", "このブラウザに保存済みです。読み込むと使えます（通信は発生しません）。");
  } else {
    setModel("absent", "モデルはまだ取得していません。");
  }
  await showStorage();
}

async function loadModel(source) {
  if (worker) worker.terminate();
  worker = spawn();
  setModel("loading", source === "cache" ? "保存済みモデルを読み込んでいます…" : "モデルを取得しています…");
  worker.listen((event) => {
    if (event.event === "progress") {
      $("model-bar").value = event.done / event.total;
      $("model-progress-text").textContent = `${formatBytes(event.done)} / ${formatBytes(event.total)}`;
    } else if (event.event === "verifying") {
      $("model-status").textContent = "モデルを検証しています（hash・設定・tokenizer）…";
    }
  });
  const init = await worker.call("init", { config });
  const reply = init.ok ? await worker.call("load", { config, source }) : init;
  if (reply.terminated) return;
  if (!reply.ok) {
    worker.terminate();
    worker = null;
    state.model = "error";
    await refreshModel();
    $("model-status").textContent = `読み込みに失敗しました：${reply.error}`;
    return;
  }
  state.model = "ready";
  state.loadReport = reply;
  await refreshModel();
}

async function stopLoad() {
  if (worker) worker.terminate();
  worker = null;
  state.model = "unknown";
  await refreshModel();
  $("model-status").textContent += "（読み込みを中止しました）";
}

async function deleteCache() {
  await caches.delete(config.cache_name);
  await refreshModel();
  $("model-status").textContent += "　保存データを削除しました。";
  $("storage").textContent += "（使用量の表示は、ブラウザが見積もりを更新するまで少し遅れることがあります）";
}

function addCandidate(id = "", text = "") {
  const rows = $("candidates");
  if (rows.children.length >= 8) return;
  const row = document.createElement("div");
  row.className = "candidate";
  const n = rows.children.length + 1;
  row.innerHTML = `<input type="text" class="cid" aria-label="候補${n}のID" placeholder="ID">` +
    // textarea, not input: an input element would silently drop line breaks in the candidate.
    `<textarea class="ctext" rows="1" aria-label="候補${n}の文字列" placeholder="候補の文字列"></textarea>` +
    `<button type="button" class="secondary remove" aria-label="候補${n}を削除">削除</button>`;
  row.querySelector(".cid").value = id;
  row.querySelector(".ctext").value = text;
  row.querySelector(".remove").addEventListener("click", () => { row.remove(); syncCandidates(); });
  rows.appendChild(row);
  syncCandidates();
}

function syncCandidates() {
  const rows = [...$("candidates").children];
  rows.forEach((row) => { row.querySelector(".remove").disabled = rows.length <= 2; });
  $("add-candidate").disabled = rows.length >= 8;
}

function fillSample(index) {
  const sample = samples[index];
  if (!sample) return;
  const r = sample.request;
  $("original").value = r.original_text;
  $("source").value = r.source;
  $("reason").value = r.reason ?? "";
  $("candidates").replaceChildren();
  r.candidates.forEach((c) => addCandidate(c.id, c.text));
}

function buildRequest() {
  const candidates = [...$("candidates").children].map((row) => ({
    id: row.querySelector(".cid").value.trim(), text: row.querySelector(".ctext").value }));
  const original = $("original").value;
  const problems = [];
  if (!original.trim()) problems.push("原文を入力してください。");
  if (candidates.length < 2) problems.push("候補は2件以上必要です。");
  if (candidates.some((c) => !c.id || !c.text.trim())) problems.push("候補のIDと文字列をすべて入力してください。");
  if (new Set(candidates.map((c) => c.id)).size !== candidates.length) problems.push("候補IDが重複しています。");
  if (problems.length) return { problems };
  const source = $("source").value;
  return { request: {
    request_id: `demo-${Date.now()}`, document_id: "demo-document", segment_id: "segment-1",
    original_text: original, source, profile_id: `ja.${source}.demo`, domain: null,
    question_id: "transcription-candidate.v1", candidates, reason: $("reason").value || null } };
}

function renderResult(reply) {
  const attempt = reply.value.attempt;
  state.last = { attempt, elapsed_ms: reply.elapsed_ms, stages: reply.value.stages };
  const outcome = attempt.outcome;
  const judgment = $("judgment");
  const body = $("scores").querySelector("tbody");
  body.replaceChildren();
  $("scores").hidden = outcome.status !== "completed";
  $("distribution-note").hidden = outcome.status !== "completed";
  if (outcome.status === "completed") {
    const obs = outcome.value;
    const selected = obs.judgment.kind === "selected" ? obs.judgment.candidate_id : null;
    judgment.className = `judgment ${obs.judgment.kind}`;
    judgment.textContent = selected ? `選択：${selected}` : "保留：候補を決めきれませんでした";
    const best = Math.max(...obs.scores.map((s) => s.option_probability));
    obs.scores.forEach((s, i) => {
      const tr = document.createElement("tr");
      if (s.option_probability === best) tr.className = "best";
      const pct = (s.option_probability * 100).toFixed(1);
      tr.innerHTML = `<td></td><td class="text"></td><td class="bar"><i style="width:${pct}%"></i><span>${pct}%</span></td>`;
      tr.children[0].textContent = s.candidate_id;
      tr.children[1].textContent = attempt.request.candidates[i].text;
      body.appendChild(tr);
    });
    $("result-meta").textContent =
      `入力 ${obs.input_tokens} tokens・forward ${obs.forwards}回・温度 ${obs.temperature.toFixed(4)}・所要 ${(reply.elapsed_ms / 1000).toFixed(1)}秒`;
  } else if (outcome.status === "failed") {
    judgment.className = "judgment failed";
    judgment.textContent = `失敗：${FAILURES[outcome.value] ?? outcome.value}`;
    $("result-meta").textContent = "失敗は判断として扱いません。";
  } else {
    judgment.className = "judgment";
    judgment.textContent = "評価しませんでした（評価する理由が「なし」）";
    $("result-meta").textContent = "モデルは呼び出していません。";
  }
  $("attempt-json").textContent = JSON.stringify(attempt, null, 2);
  $("result").hidden = false;
}

async function evaluate() {
  const built = buildRequest();
  if (built.problems) { $("run-status").textContent = built.problems.join(" "); return; }
  state.running = true;
  $("evaluate").disabled = true;
  $("cancel").hidden = false;
  const started = performance.now();
  const timer = setInterval(() => {
    $("run-status").textContent = `推論中… ${((performance.now() - started) / 1000).toFixed(1)}秒`;
  }, 100);
  const reply = await worker.call("evaluate", { request: JSON.stringify(built.request),
    max_input_bytes: config.max_input_bytes, max_input_tokens: config.max_input_tokens });
  clearInterval(timer);
  state.running = false;
  $("cancel").hidden = true;
  if (reply.terminated) return;
  if (!reply.ok || reply.code !== 0) {
    $("run-status").textContent = `判断できませんでした：${reply.error || reply.value.error}`;
  } else {
    $("run-status").textContent = "完了しました。";
    renderResult(reply);
  }
  await refreshModel();
}

async function cancelRun() {
  worker.terminate();
  worker = null;
  state.running = false;
  $("cancel").hidden = true;
  $("run-status").textContent = "取消しました。";
  state.model = "unknown";
  if (await cachedComplete()) {
    await loadModel("cache");
    $("run-status").textContent = "取消しました。保存済みモデルを読み込み直しました。";
  } else {
    await refreshModel();
  }
}

function saveJson() {
  if (!state.last) return;
  const blob = new Blob([JSON.stringify(state.last.attempt, null, 2) + "\n"], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `attempt-${state.last.attempt.request.request_id}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

(async () => {
  config = await (await fetch("demo-config.json", { cache: "no-store" })).json();
  state.config = config;
  samples = await (await fetch("samples.json", { cache: "no-store" })).json();
  document.querySelectorAll("[data-total-size]").forEach((el) => { el.textContent = formatBytes(config.total_download_bytes); });
  const modelOrigin = new URL(config.model_base_url || "model/", location.href);
  if (modelOrigin.origin !== location.origin) $("model-host").textContent = modelOrigin.host;
  samples.forEach((s, i) => $("sample").add(new Option(s.label, String(i))));
  $("sample").addEventListener("change", (e) => fillSample(Number(e.target.value)));
  $("add-candidate").addEventListener("click", () => addCandidate());
  $("download").addEventListener("click", () => loadModel("network"));
  $("load-cached").addEventListener("click", () => loadModel("cache"));
  $("stop-load").addEventListener("click", stopLoad);
  $("delete-cache").addEventListener("click", deleteCache);
  $("evaluate").addEventListener("click", evaluate);
  $("cancel").addEventListener("click", cancelRun);
  $("save-json").addEventListener("click", saveJson);
  addCandidate(); addCandidate();
  if (!WebAssembly.validate(SIMD_PROBE)) {
    setModel("unsupported", "このブラウザはWebAssembly SIMDに対応していないため、使用できません。");
    return;
  }
  if (!("caches" in self)) {
    setModel("unsupported", "このブラウザではCache Storageを使用できません（HTTPSまたはlocalhostで開いてください）。");
    return;
  }
  await removeOldCaches();
  await refreshModel();
})().catch((error) => { $("model-status").textContent = `初期化に失敗しました：${error.message}`; });
