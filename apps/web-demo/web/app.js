// Main thread: UI, model cache management and the inference Worker's lifecycle.
// Texts come from i18n.js; every shown message is kept as { key, params } so a language
// change re-renders it.
"use strict";

const $ = (id) => document.getElementById(id);
const SIMD_PROBE = new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0,
  10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]);
const LANGUAGE_KEY = "pure-jeff-language";

// Read-only view of the state for people and automated checks.
const state = { model: "unknown", running: false, last: null, config: null, lang: null };
window.kazeDemo = state;

let config = null;
let samples = [];
let worker = null;
let lang = FALLBACK_LANGUAGE;
const tr = (key, params) => t(lang, key, params);
const msg = (key, params) => ({ key, params });
// Currently shown messages, re-rendered on a language change.
const shown = { model: msg("model.checking"), modelSuffixes: [], run: [], storage: null, storageLag: false };
let lastReply = null;

function formatBytes(n) {
  return n >= 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${n} bytes`;
}

function savedLanguage() {
  try { return localStorage.getItem(LANGUAGE_KEY); } catch { return null; }
}

function setLanguage(code, remember) {
  lang = code;
  state.lang = code;
  if (remember) {
    try { localStorage.setItem(LANGUAGE_KEY, code); } catch { /* storage unavailable: keep the URL only */ }
    const url = new URL(location.href);
    url.searchParams.set("lang", code);
    history.replaceState(null, "", url);
  }
  applyLanguage();
}

function applyLanguage() {
  document.documentElement.lang = lang;
  document.title = tr("app.title");
  $("lang").value = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = tr(el.dataset.i18n); });
  const size = config ? formatBytes(config.total_download_bytes) : "1.7 GB";
  const modelOrigin = config ? new URL(config.model_base_url || "model/", location.href) : null;
  const host = modelOrigin && modelOrigin.origin !== location.origin ? modelOrigin.host : msg("model.thisSite");
  $("privacy").textContent = tr("model.privacy", { size, host });
  $("download").textContent = tr("model.download", { size });
  [...$("sample").options].slice(1).forEach((option) => {
    const sample = samples[Number(option.value)];
    option.textContent = sample.id ? tr(`sample.${sample.id}`) : sample.label;
  });
  [...$("candidates").children].forEach(labelCandidate);
  renderModelStatus();
  renderRunStatus();
  renderStorage();
  if (lastReply) renderResult(lastReply);
}

function renderModelStatus() {
  $("model-status").textContent = [shown.model, ...shown.modelSuffixes].map((m) => render(lang, m)).join("");
}

function renderRunStatus() {
  $("run-status").textContent = shown.run.map((m) => render(lang, m)).join(" ");
}

function renderStorage() {
  $("storage").textContent = shown.storage ? tr("storage.usage", shown.storage) + (shown.storageLag ? tr("storage.lag") : "") : "";
}

function showRun(...messages) {
  shown.run = messages;
  renderRunStatus();
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
    for (const resolve of pending.values()) resolve({ ok: false, error: msg("worker.error", { message: event.message }) });
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
  shown.storage = { usage: formatBytes(usage), quota: formatBytes(quota) };
  shown.storageLag = false;
  renderStorage();
}

function setModel(model, message) {
  state.model = model;
  shown.model = message;
  shown.modelSuffixes = [];
  renderModelStatus();
  const busy = model === "loading";
  $("download").disabled = busy || model === "unsupported" || model.startsWith("ready");
  $("load-cached").disabled = busy || !["cached", "ready-cached"].includes(model) || model.startsWith("ready");
  $("delete-cache").disabled = busy || !["cached", "ready-cached", "partial"].includes(model);
  $("stop-load").hidden = !busy;
  $("model-progress").hidden = !busy;
  $("evaluate").disabled = !model.startsWith("ready") || state.running;
}

function setModelMessage(message, ...suffixes) {
  shown.model = message;
  shown.modelSuffixes = suffixes;
  renderModelStatus();
}

async function refreshModel() {
  const cached = await cachedComplete();
  if (state.model.startsWith("ready")) {
    setModel(cached ? "ready-cached" : "ready", msg(cached ? "model.readyCached" : "model.readyNoCache"));
  } else if (cached) {
    setModel("cached", msg("model.cached"));
  } else if ("caches" in self && await caches.has(config.cache_name)) {
    // A stopped download can leave the smaller files; they are useless alone, so offer deletion.
    setModel("partial", msg("model.partial"));
  } else {
    setModel("absent", msg("model.absent"));
  }
  await showStorage();
}

async function loadModel(source) {
  if (worker) worker.terminate();
  worker = spawn();
  setModel("loading", msg(source === "cache" ? "model.loadingCache" : "model.loadingNetwork"));
  worker.listen((event) => {
    if (event.event === "progress") {
      $("model-bar").value = event.done / event.total;
      $("model-progress-text").textContent = `${formatBytes(event.done)} / ${formatBytes(event.total)}`;
    } else if (event.event === "verifying") {
      setModelMessage(msg("model.verifying"));
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
    setModelMessage(msg("model.loadFailed", { error: reply.error }));
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
  setModelMessage(shown.model, msg("model.stopped"));
}

async function deleteCache() {
  await caches.delete(config.cache_name);
  await refreshModel();
  setModelMessage(shown.model, msg("model.deleted"));
  shown.storageLag = true;
  renderStorage();
}

function labelCandidate(row, index) {
  const n = index + 1;
  row.querySelector(".cid").setAttribute("aria-label", tr("input.candidateId", { n }));
  row.querySelector(".ctext").setAttribute("aria-label", tr("input.candidateText", { n }));
  row.querySelector(".ctext").placeholder = tr("input.candidateTextPlaceholder");
  const remove = row.querySelector(".remove");
  remove.setAttribute("aria-label", tr("input.removeLabel", { n }));
  remove.textContent = tr("input.remove");
}

function addCandidate(id = "", text = "") {
  const rows = $("candidates");
  if (rows.children.length >= 8) return;
  const row = document.createElement("div");
  row.className = "candidate";
  row.innerHTML = `<input type="text" class="cid" placeholder="ID">` +
    // textarea, not input: an input element would silently drop line breaks in the candidate.
    `<textarea class="ctext" rows="1"></textarea>` +
    `<button type="button" class="secondary remove"></button>`;
  row.querySelector(".cid").value = id;
  row.querySelector(".ctext").value = text;
  row.querySelector(".remove").addEventListener("click", () => { row.remove(); syncCandidates(); });
  rows.appendChild(row);
  syncCandidates();
}

function syncCandidates() {
  const rows = [...$("candidates").children];
  rows.forEach((row, i) => {
    row.querySelector(".remove").disabled = rows.length <= 2;
    labelCandidate(row, i);
  });
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
  if (!original.trim()) problems.push(msg("problem.original"));
  if (candidates.length < 2) problems.push(msg("problem.count"));
  if (candidates.some((c) => !c.id || !c.text.trim())) problems.push(msg("problem.empty"));
  if (new Set(candidates.map((c) => c.id)).size !== candidates.length) problems.push(msg("problem.duplicate"));
  if (problems.length) return { problems };
  const source = $("source").value;
  return { request: {
    request_id: `demo-${Date.now()}`, document_id: "demo-document", segment_id: "segment-1",
    original_text: original, source, profile_id: `ja.${source}.demo`, domain: null,
    question_id: "transcription-candidate.v1", candidates, reason: $("reason").value || null } };
}

function renderResult(reply) {
  lastReply = reply;
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
    judgment.textContent = selected ? tr("result.selected", { id: selected }) : tr("result.abstained");
    const best = Math.max(...obs.scores.map((s) => s.option_probability));
    obs.scores.forEach((s, i) => {
      const tr_ = document.createElement("tr");
      if (s.option_probability === best) tr_.className = "best";
      const pct = (s.option_probability * 100).toFixed(1);
      tr_.innerHTML = `<td></td><td class="text"></td><td class="bar"><i style="width:${pct}%"></i><span>${pct}%</span></td>`;
      tr_.children[0].textContent = s.candidate_id;
      tr_.children[1].textContent = attempt.request.candidates[i].text;
      body.appendChild(tr_);
    });
    $("result-meta").textContent = tr("result.meta", { tokens: obs.input_tokens, forwards: obs.forwards,
      temperature: obs.temperature.toFixed(4), seconds: (reply.elapsed_ms / 1000).toFixed(1) });
  } else if (outcome.status === "failed") {
    judgment.className = "judgment failed";
    judgment.textContent = tr("result.failed", { reason: msg(`failure.${outcome.value}`) });
    $("result-meta").textContent = tr("result.failedMeta");
  } else {
    judgment.className = "judgment";
    judgment.textContent = tr("result.notSelected");
    $("result-meta").textContent = tr("result.notSelectedMeta");
  }
  $("attempt-json").textContent = JSON.stringify(attempt, null, 2);
  $("result").hidden = false;
}

async function evaluate() {
  const built = buildRequest();
  if (built.problems) { showRun(...built.problems); return; }
  state.running = true;
  $("evaluate").disabled = true;
  $("cancel").hidden = false;
  const started = performance.now();
  const timer = setInterval(() => {
    showRun(msg("run.running", { seconds: ((performance.now() - started) / 1000).toFixed(1) }));
  }, 100);
  const reply = await worker.call("evaluate", { request: JSON.stringify(built.request),
    max_input_bytes: config.max_input_bytes, max_input_tokens: config.max_input_tokens });
  clearInterval(timer);
  state.running = false;
  $("cancel").hidden = true;
  if (reply.terminated) return;
  if (!reply.ok || reply.code !== 0) {
    showRun(msg("run.failed", { error: reply.error || { text: reply.value.error } }));
  } else {
    showRun(msg("run.done"));
    renderResult(reply);
  }
  await refreshModel();
}

async function cancelRun() {
  worker.terminate();
  worker = null;
  state.running = false;
  $("cancel").hidden = true;
  showRun(msg("run.cancelled"));
  state.model = "unknown";
  if (await cachedComplete()) {
    await loadModel("cache");
    showRun(msg("run.cancelledReloaded"));
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
  Object.entries(LANGUAGES).forEach(([code, name]) => $("lang").add(new Option(name, code)));
  $("lang").addEventListener("change", (e) => setLanguage(e.target.value, true));
  setLanguage(pickLanguage(location.search, savedLanguage(), navigator.languages || [navigator.language]), false);
  config = await (await fetch("demo-config.json", { cache: "no-store" })).json();
  state.config = config;
  samples = await (await fetch("samples.json", { cache: "no-store" })).json();
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
  applyLanguage();
  if (!WebAssembly.validate(SIMD_PROBE)) {
    setModel("unsupported", msg("model.unsupportedSimd"));
    return;
  }
  if (!("caches" in self)) {
    setModel("unsupported", msg("model.unsupportedCache"));
    return;
  }
  await removeOldCaches();
  await refreshModel();
})().catch((error) => { setModelMessage(msg("model.initFailed", { error: { text: error.message } })); });
