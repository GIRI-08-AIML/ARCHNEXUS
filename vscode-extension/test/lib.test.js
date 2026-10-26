"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const lib = require("../lib");

test("esc neutralises HTML from the model", () => {
  assert.equal(lib.esc('<img src=x onerror="a()">&\''), "&lt;img src=x onerror=&quot;a()&quot;&gt;&amp;&#39;");
  assert.equal(lib.esc(null), "");
});

test("normalizeUrl", () => {
  assert.equal(lib.normalizeUrl("localhost:8000/"), "http://localhost:8000");
  assert.equal(lib.normalizeUrl(""), "http://127.0.0.1:8000");
  assert.equal(lib.normalizeUrl("https://x.example.com//"), "https://x.example.com");
});

test("projectNameFromFile and checkRfcText", () => {
  assert.equal(lib.projectNameFromFile("/a/b/order-service.rfc.md"), "order-service.rfc");
  assert.equal(lib.projectNameFromFile(""), "Untitled RFC");
  assert.ok(lib.checkRfcText("too short"));
  assert.equal(lib.checkRfcText("x".repeat(60)), null);
});

test("waitForReview polls until completed and honours cancel", async () => {
  const seq = [{ status: "pending" }, { status: "running" }, { status: "completed", id: 1 }];
  let i = 0, updates = 0;
  const done = await lib.waitForReview(async () => seq[i++], { sleep: async () => {}, onUpdate: () => updates++ });
  assert.equal(done.status, "completed");
  assert.equal(updates, 2);

  let calls = 0;
  const stopped = await lib.waitForReview(async () => { calls++; return { status: "running" }; },
    { sleep: async () => {}, isCancelled: () => calls >= 2 });
  assert.equal(stopped, null);
});

test("result page escapes untrusted text and shows the verdict", () => {
  const review = {
    id: 7,
    report: { decision: "reject", score: 40, summary: "Bad. [Adjusted by review rules: 2 critical findings require rejection.]",
      recommendations: ["<script>alert(1)</script>"], key_risks: ["Token <b>theft</b>"] },
    findings: [
      { id: 2, severity: "low", agent_name: "Database Agent", title: "minor", description: "d", recommendation: "r" },
      { id: 1, severity: "critical", agent_name: "Security Agent", title: "<svg onload=x>", description: "d", recommendation: "r", tradeoffs: "t" },
    ],
  };
  const html = lib.buildResultHtml(review, "http://127.0.0.1:8000/");
  assert.ok(!html.includes("<script>alert"));
  assert.ok(!html.includes("<svg onload"));
  assert.ok(html.includes("Rejected"));
  assert.ok(html.includes("Adjusted by review rules"));
  assert.ok(html.indexOf("Critical") < html.indexOf("Low"), "worst findings first");
  assert.ok(html.includes("Content-Security-Policy"));
  assert.ok(html.includes("http://127.0.0.1:8000/#/review/7"));
});

test("result page copes with a review that has no report", () => {
  const html = lib.buildResultHtml({ id: 1, report: null, findings: [] }, "http://x");
  assert.ok(html.includes("No verdict"));
});

// ------------------------------------------------------------- finding -> line in the editor
const RFC = [
  "# RFC-002: Notification Service",
  "",
  "Callers send a request to the Notification API, which validates it,",
  "stores it in PostgreSQL, and puts a job on a durable queue.",
  "",
  "User contact details are encrypted at rest.",
].join("\n");

function spanOf(text, quote) {
  const loc = lib.locateQuote(lib.indexText(text), quote);
  return loc && text.slice(loc.start, loc.end);
}

test("locateQuote finds the quote whatever its case and wherever the lines break", () => {
  assert.equal(
    spanOf(RFC, "Callers send a request to the Notification API, which validates it, stores it in PostgreSQL"),
    "Callers send a request to the Notification API, which validates it,\nstores it in PostgreSQL"
  );
  assert.equal(spanOf(RFC, "USER CONTACT DETAILS   are encrypted at rest"), "User contact details are encrypted at rest");
});

test("locateQuote ignores quote marks and the final full stop around the quote", () => {
  assert.equal(spanOf(RFC, "“User contact details are encrypted at rest.”"), "User contact details are encrypted at rest");
});

test("locateQuote works with Windows line endings", () => {
  const crlf = RFC.replace(/\n/g, "\r\n");
  assert.equal(
    spanOf(crlf, "which validates it, stores it in PostgreSQL"),
    "which validates it,\r\nstores it in PostgreSQL"
  );
});

test("locateQuote survives letters whose lower case is longer", () => {
  const text = "Intro.\nİstanbul workers send messages quickly. Done.";
  assert.equal(spanOf(text, "workers send messages quickly"), "workers send messages quickly");
  assert.equal(spanOf(text, "İstanbul workers send messages"), "İstanbul workers send messages");
});

test("locateQuote gives up on missing, empty or very short quotes", () => {
  const idx = lib.indexText(RFC);
  assert.equal(lib.locateQuote(idx, "a sentence that is not in the RFC at all"), null);
  assert.equal(lib.locateQuote(idx, ""), null);
  assert.equal(lib.locateQuote(idx, null), null);
  assert.equal(lib.locateQuote(idx, "the"), null); // too short to point at one place
});

test("locateQuote sees through Markdown bold, code and table marks", () => {
  const md = "Rollback is **a single configuration flag** per team, and `idempotency_key` is unique.\n\n| Notification API | Validate, store, enqueue | Horizontal |";
  assert.equal(
    spanOf(md, "Rollback is a single configuration flag per team"),
    "Rollback is **a single configuration flag** per team"
  );
  assert.ok(spanOf(md, "the idempotency_key is unique") === null, "different words still do not match");
  assert.ok(spanOf(md, "idempotency_key is unique").includes("idempotency_key` is unique"));
  assert.ok(spanOf(md, "Notification API Validate, store, enqueue").startsWith("Notification API"));
});

test("locateQuote falls back to the start of a long quote whose end was reworded", () => {
  const text = "Delivery calls use a 5 second timeout and up to five retries with exponential backoff. More text.";
  const quote = "Delivery calls use a 5 second timeout and up to five retries, using exponential backoff and jitter";
  const loc = lib.locateQuote(lib.indexText(text), quote);
  assert.ok(loc, "the beginning of the quote should still be found");
  assert.ok(text.slice(loc.start, loc.end).startsWith("Delivery calls use a 5 second"));
});

test("offsetToPosition counts lines and columns from zero", () => {
  const loc = lib.locateQuote(lib.indexText(RFC), "User contact details are encrypted at rest");
  assert.deepEqual(lib.offsetToPosition(RFC, loc.start), { line: 5, character: 0 });
  const mid = lib.locateQuote(lib.indexText(RFC), "stores it in PostgreSQL");
  assert.deepEqual(lib.offsetToPosition(RFC, mid.start), { line: 3, character: 0 });
  assert.deepEqual(lib.offsetToPosition("abc\ndef", 5), { line: 1, character: 1 });
});

test("the result page shows the quote, escaped", () => {
  const html = lib.buildResultHtml({
    id: 3, report: null,
    findings: [{ id: 1, severity: "high", agent_name: "Security Agent", title: "t", description: "d", recommendation: "r",
                 quote: "Tokens <img src=x onerror=a()> expire" }],
  }, "http://x");
  assert.ok(html.includes("RFC says"));
  assert.ok(html.includes("Tokens &lt;img src=x onerror=a()&gt; expire"));
  assert.ok(!html.includes("<img src=x"));
});

test("every quote from two real reviews is found in the RFC they reviewed", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const rfc = fs.readFileSync(path.join(__dirname, "fixtures", "rfc-002.txt"), "utf8");
  const index = lib.indexText(rfc);
  let total = 0;
  for (const name of ["review6", "review7"]) {
    const file = path.join(__dirname, "..", "..", "tests", "fixtures", `${name}_findings.json`);
    for (const f of JSON.parse(fs.readFileSync(file, "utf8"))) {
      total++;
      const loc = lib.locateQuote(index, f.quote);
      assert.ok(loc, `quote not located for "${f.title}"`);
      assert.ok(loc.end > loc.start && loc.end <= rfc.length);
    }
  }
  assert.equal(total, 33);
});
