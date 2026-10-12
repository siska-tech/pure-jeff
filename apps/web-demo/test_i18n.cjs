// node --test apps/web-demo/test_i18n.cjs
// The three languages define the same keys with the same placeholders, every key the page,
// the Worker and the build use exists, and English/Vietnamese contain no Japanese text.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { LANGUAGES, MESSAGES, t, pickLanguage } = require("./web/i18n.js");

const read = (name) => fs.readFileSync(path.join(__dirname, name), "utf8");
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const JAPANESE = /[぀-ヿ㐀-鿿！-｠]/;
const FAILURES = ["budget_exceeded", "invalid_request", "invalid_output", "unavailable", "timeout"];

test("every language has the same keys and placeholders", () => {
  assert.deepEqual(Object.keys(MESSAGES).sort(), Object.keys(LANGUAGES).sort());
  const keys = Object.keys(MESSAGES.ja).sort();
  for (const lang of Object.keys(LANGUAGES)) {
    assert.deepEqual(Object.keys(MESSAGES[lang]).sort(), keys, lang);
    for (const key of keys) {
      assert.deepEqual(placeholders(MESSAGES[lang][key]), placeholders(MESSAGES.ja[key]), `${lang} ${key}`);
      assert.ok(MESSAGES[lang][key].trim(), `${lang} ${key} is empty`);
    }
  }
});

test("every referenced key is defined", () => {
  const used = new Set();
  for (const m of read("web/index.html").matchAll(/data-i18n="([\w.-]+)"/g)) used.add(m[1]);
  // Any string literal in a message namespace, including conditional keys.
  const namespaces = new Set(Object.keys(MESSAGES.ja).map((k) => k.split(".")[0]));
  for (const m of read("web/app.js").matchAll(/"([a-z]+)\.([\w-]+)"/g)) {
    if (namespaces.has(m[1])) used.add(`${m[1]}.${m[2]}`);
  }
  for (const m of read("web/engine-worker.js").matchAll(/Localized\("([\w.-]+)"/g)) used.add(m[1]);
  for (const m of read("build_demo.py").matchAll(/^\s+\("([\w-]+)", "/gm)) used.add(`sample.${m[1]}`);
  FAILURES.forEach((f) => used.add(`failure.${f}`));
  assert.ok(used.size > 60, `only ${used.size} keys found`);
  for (const key of used) assert.ok(key in MESSAGES.ja, `missing ${key}`);
  for (const key of Object.keys(MESSAGES.ja)) assert.ok(used.has(key), `unused ${key}`);
});

test("English and Vietnamese contain no Japanese text", () => {
  for (const lang of ["en", "vi"]) {
    for (const [key, text] of Object.entries(MESSAGES[lang])) assert.ok(!JAPANESE.test(text), `${lang} ${key}: ${text}`);
  }
});

test("messages render, including nested messages and plain text", () => {
  assert.equal(t("en", "result.selected", { id: "a" }), "Selected: a");
  assert.equal(t("vi", "model.loadFailed", { error: { key: "worker.reserve" } }),
    "Nạp thất bại: Không thể cấp phát bộ nhớ cho suy luận");
  assert.equal(t("ja", "run.failed", { error: { text: "engine says no" } }), "判断できませんでした：engine says no");
  assert.equal(t("xx", "input.evaluate"), "Decide");
});

test("the language comes from the URL, then the saved choice, then the browser", () => {
  assert.equal(pickLanguage("?lang=vi", "ja", ["en-US"]), "vi");
  assert.equal(pickLanguage("?lang=fr", "ja", ["en-US"]), "ja");
  assert.equal(pickLanguage("", null, ["fr-FR", "vi-VN", "en"]), "vi");
  assert.equal(pickLanguage("", null, ["ja-JP"]), "ja");
  assert.equal(pickLanguage("", null, ["fr-FR"]), "en");
});
