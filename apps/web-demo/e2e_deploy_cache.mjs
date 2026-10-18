// Deploy check across versions, in one persistent browser profile, through the Chrome DevTools
// Protocol. Usage: node e2e_deploy_cache.mjs <browser-ws-url> <page-url> <output.json> prepare|reuse
//   prepare  open the site, download the model into Cache Storage, decide samples 0 and 5
//   reuse    open the (redeployed) site in the same profile: the model must show as saved and
//            load from Cache Storage without any model-host request; then, with the network
//            cut for the page and its Workers, decide samples 0 and 5 again
import fs from "node:fs";

const [browserWs, pageUrl, output, mode] = process.argv.slice(2);
const result = { mode, network: [], marks: {}, decisions: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => Date.now() / 1000;

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
const sessions = new Set([sessionId]);
let offline = false;
const conditions = () => ({ offline, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
await page("Page.enable");
await page("Runtime.enable");
await page("Network.enable");
handlers.push((msg) => {
  if (msg.method === "Network.requestWillBeSent") {
    result.network.push({ time: now(), url: msg.params.request.url, offline });
  } else if (msg.method === "Network.loadingFailed") {
    result.network.push({ time: now(), failed: msg.params.errorText, offline });
  }
});
await page("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
handlers.push((msg) => {
  if (msg.method === "Target.attachedToTarget") {
    // Workers: log their requests; the network is only cut later, for every session at once.
    const id = msg.params.sessionId;
    sessions.add(id);
    send("Network.enable", {}, id).catch(() => {});
    send("Runtime.runIfWaitingForDebugger", {}, id).catch(() => {});
  }
});

async function js(expression) {
  const { result: value, exceptionDetails } = await page("Runtime.evaluate",
    { expression, awaitPromise: true, returnByValue: true });
  if (exceptionDetails) throw new Error(`${expression}: ${JSON.stringify(exceptionDetails)}`);
  return value.value;
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
const click = (id) => js(`document.getElementById(${JSON.stringify(id)}).click()`);
async function decide(index) {
  await js(`(() => { const s = document.getElementById("sample"); s.value = "${index}";
    s.dispatchEvent(new Event("change")); window.kazeDemo.last = null; return true; })()`);
  await click("evaluate");
  await waitFor("window.kazeDemo.last !== null && !window.kazeDemo.running", 300000, `sample ${index}`);
  const last = await js("window.kazeDemo.last");
  result.decisions.push({ sample: index, offline, attempt: last.attempt });
}
async function setOffline(value) {
  offline = value;
  for (const id of sessions) await send("Network.emulateNetworkConditions", conditions(), id).catch(() => {});
}

try {
  await page("Page.navigate", { url: pageUrl });
  await waitFor("window.kazeDemo && !['unknown', 'checking'].includes(window.kazeDemo.model)", 120000, "page state");
  result.config = await js("fetch('demo-config.json', { cache: 'no-store' }).then((r) => r.json())");
  result.model_state_at_open = await js("window.kazeDemo.model");
  result.marks.load_click = now();
  if (mode === "prepare") {
    await click("download");
  } else {
    await click("load-cached");
  }
  await waitFor("window.kazeDemo.model === 'ready-cached'", Number(process.env.READY_TIMEOUT_MS || 1800000), "model ready");
  result.marks.ready = now();
  result.cache_names = await js("caches.keys()");
  await decide(0);
  await decide(5);
  if (mode === "reuse") {
    await setOffline(true);
    result.marks.offline = now();
    result.offline_fetch_fails = await js(`fetch('demo-config.json?offline-check', { cache: 'no-store' })
      .then(() => false, () => true)`);
    await decide(0);
    await decide(5);
  }
  result.completed = true;
} catch (error) {
  result.completed = false;
  result.error = String(error && error.stack || error);
  result.page_state = await js(`({ model: window.kazeDemo && window.kazeDemo.model,
    status: (document.getElementById("model-status") || {}).textContent })`).catch((e) => String(e));
}
fs.writeFileSync(output, JSON.stringify(result, null, 1));
ws.close();
process.exit(0);
