// W3 end-to-end: drives the real demo UI through the Chrome DevTools Protocol.
// Usage: node e2e_w3.mjs <browser-ws-url> <page-url> <output-dir> [--abort-download]
import fs from "node:fs";
import path from "node:path";

const [browserWs, pageUrl, outDir] = process.argv.slice(2);
const abortDownload = process.argv.includes("--abort-download");
const downloads = path.join(outDir, "downloads");
fs.mkdirSync(downloads, { recursive: true });
const results = { marks: [], network: [], steps: {} };
const mark = (name) => results.marks.push({ name, time: Date.now() / 1000 });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const ws = new WebSocket(browserWs);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let nextId = 1;
const pending = new Map();
const handlers = [];
ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  } else if (msg.method) handlers.forEach((h) => h(msg));
};
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = nextId++;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
});

const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const page = (method, params) => send(method, params, sessionId);
await page("Page.enable");
await page("Runtime.enable");
await page("Network.enable");
await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: path.resolve(downloads), eventsEnabled: true });
// Every request the page or its Workers start (Workers are auto-attached below).
handlers.push((msg) => {
  if (msg.method === "Network.requestWillBeSent") {
    results.network.push({ time: Date.now() / 1000, url: msg.params.request.url, method: msg.params.request.method });
  }
});
await page("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
handlers.push((msg) => {
  if (msg.method === "Target.attachedToTarget") {
    send("Network.enable", {}, msg.params.sessionId).catch(() => {});
    send("Runtime.runIfWaitingForDebugger", {}, msg.params.sessionId).catch(() => {});
  }
});

async function js(expression) {
  const { result, exceptionDetails } = await page("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (exceptionDetails) throw new Error(`${expression}: ${JSON.stringify(exceptionDetails)}`);
  return result.value;
}
async function waitFor(expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await js(expression).catch(() => false);
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timeout waiting for ${label}`);
    await sleep(250);
  }
}
async function shot(name) {
  const { data } = await page("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  fs.writeFileSync(path.join(outDir, `${name}.png`), Buffer.from(data, "base64"));
}
const click = (id) => js(`document.getElementById(${JSON.stringify(id)}).click()`);
const pick = (index) => js(`(() => { const s = document.getElementById("sample"); s.value = "${index}";
  s.dispatchEvent(new Event("change")); return s.value; })()`);
const text = (id) => js(`document.getElementById(${JSON.stringify(id)}).textContent`);
const model = () => js("window.kazeDemo.model");

// Runs one evaluation through the UI while sampling main-thread timer gaps.
async function evaluateUi(label, timeoutMs = 300000) {
  await js(`window.__gaps = []; window.__t = performance.now();
    window.__hb = setInterval(() => { const n = performance.now(); window.__gaps.push(n - window.__t); window.__t = n; }, 50);
    window.kazeDemo.last = null; true`);
  mark(`${label}:start`);
  await click("evaluate");
  await waitFor("window.kazeDemo.last !== null && !window.kazeDemo.running", timeoutMs, label);
  mark(`${label}:end`);
  const gaps = await js("clearInterval(window.__hb); window.__gaps");
  const last = await js("window.kazeDemo.last");
  return { attempt: last.attempt, elapsed_ms: last.elapsed_ms, stages: last.stages,
           max_main_thread_gap_ms: Math.max(...gaps), gap_samples: gaps.length,
           judgment_text: await text("judgment"), run_status: await text("run-status") };
}

try {
  await page("Page.navigate", { url: pageUrl });
  await waitFor("window.kazeDemo && window.kazeDemo.model === 'absent'", 60000, "initial state");
  results.steps.initial = { model: await model(), status: await text("model-status"), privacy: await text("privacy"),
    download_label: await text("download") };
  await shot("01-initial");
  if (abortDownload) {
    // Stop a download once the large model file is streaming; nothing partial may count as saved.
    mark("abort:click");
    await click("download");
    await waitFor("document.getElementById('model-bar').value > 0.15", 600000, "download progress");
    await click("stop-load");
    mark("abort:stopped");
    await waitFor("['absent', 'partial'].includes(window.kazeDemo.model)", 60000, "state after stopping");
    const config = await js("window.kazeDemo.config");
    const stateAfterStop = await model();
    results.steps.abort = {
      state: stateAfterStop,
      delete_enabled: !(await js("document.getElementById('delete-cache').disabled")),
      status: await text("model-status"),
      model_in_cache: await js(`caches.has(${JSON.stringify(config.cache_name)}).then(async (has) => has &&
        !!(await (await caches.open(${JSON.stringify(config.cache_name)})).match(
          ${JSON.stringify(config.assets.find((a) => a.path === "model.safetensors").url)})))`),
      evaluate_disabled: await js("document.getElementById('evaluate').disabled"),
    };
    await shot("01b-aborted");
    if (stateAfterStop === "partial") {
      // The files finished before the stop must be removable from the page.
      await click("delete-cache");
      await waitFor("window.kazeDemo.model === 'absent'", 60000, "partial data deleted");
    }
    results.steps.abort.cache_after_cleanup = await js(`caches.has(${JSON.stringify(config.cache_name)})`);
    await sleep(1000);
  }
  mark("download:click");
  await click("download");
  await waitFor("window.kazeDemo.model === 'ready-cached'", 1800000, "download");
  mark("download:ready");
  results.steps.download = { status: await text("model-status"), report: await js("window.kazeDemo.loadReport"),
    storage: await text("storage") };
  await shot("02-ready");

  await pick(0);
  results.steps.eval_sample0 = await evaluateUi("eval0");
  await shot("03-result");
  mark("save:click");
  await click("save-json");
  const saved = await (async () => {
    for (let i = 0; i < 80; i++) {
      const files = fs.readdirSync(downloads).filter((f) => f.endsWith(".json"));
      if (files.length) return files[0];
      await sleep(250);
    }
    return null;
  })();
  results.steps.save = { file: saved, content: saved ? fs.readFileSync(path.join(downloads, saved), "utf8") : null };

  for (const index of [2, 5, 6]) {
    await pick(index);
    results.steps[`eval_sample${index}`] = await evaluateUi(`eval${index}`);
  }
  await shot("04-budget");

  await pick(0);
  await js(`document.getElementById("reason").value = ""; true`);
  results.steps.eval_no_reason = await evaluateUi("eval-no-reason");

  await pick(0);
  await js(`document.querySelectorAll("#candidates .cid").forEach((el) => { el.value = "same"; }); true`);
  mark("invalid:start");
  await click("evaluate");
  await sleep(500);
  mark("invalid:end");
  results.steps.ui_validation = { run_status: await text("run-status"), running: await js("window.kazeDemo.running") };

  await pick(5);
  mark("cancel:start");
  await click("evaluate");
  await sleep(3000);
  await click("cancel");
  mark("cancel:clicked");
  await waitFor("window.kazeDemo.model === 'ready-cached'", 600000, "reload after cancel");
  mark("cancel:reloaded");
  results.steps.cancel = { run_status: await text("run-status") };
  await pick(0);
  results.steps.eval_after_cancel = await evaluateUi("eval-after-cancel");

  mark("page-reload");
  await page("Page.reload", {});
  await waitFor("window.kazeDemo && window.kazeDemo.model === 'cached'", 60000, "cached state after reload");
  results.steps.after_reload = { status: await text("model-status") };
  await shot("05-after-reload");
  mark("load-cached:click");
  await click("load-cached");
  await waitFor("window.kazeDemo.model === 'ready-cached'", 600000, "load from cache");
  mark("load-cached:ready");
  results.steps.load_cached = { report: await js("window.kazeDemo.loadReport") };
  await pick(0);
  results.steps.eval_after_reload = await evaluateUi("eval-after-reload");

  const before = await js("navigator.storage.estimate().then((e) => e.usage)");
  await click("delete-cache");
  await waitFor("window.kazeDemo.model === 'ready'", 60000, "delete");
  results.steps.delete = { status: await text("model-status"),
    cache_names: await js("caches.keys()"), usage_before: before,
    usage_after: await js("navigator.storage.estimate().then((e) => e.usage)") };
  await page("Page.reload", {});
  await waitFor("window.kazeDemo && window.kazeDemo.model === 'absent'", 60000, "absent after delete");
  results.steps.after_delete_reload = { status: await text("model-status") };
  await shot("06-deleted");
  results.completed = true;
} catch (error) {
  results.error = String(error.stack || error);
  await shot("99-error").catch(() => {});
}
fs.writeFileSync(path.join(outDir, "e2e.json"), JSON.stringify(results, null, 1));
ws.close();
process.exit(results.completed ? 0 : 1);
