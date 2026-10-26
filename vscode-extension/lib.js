"use strict";
/* Pure helpers: no VS Code imports, so they can be tested with plain Node.
   Everything that comes from the model or server is untrusted and is escaped before it reaches HTML. */

const SEVERITIES = ["critical", "high", "medium", "low"];
const MIN_RFC_CHARS = 50;

function esc(value) {
  return String(value === null || value === undefined ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeUrl(url) {
  let u = String(url || "").trim();
  if (!u) u = "http://127.0.0.1:8000";
  if (!/^https?:\/\//i.test(u)) u = "http://" + u;
  return u.replace(/\/+$/, "");
}

function pretty(s) {
  return String(s || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

function agentShort(name) {
  return String(name || "").replace(/\s*agent\s*$/i, "");
}

function decisionInfo(decision) {
  if (decision === "approve") return { tone: "good", label: "Approved" };
  if (decision === "reject") return { tone: "bad", label: "Rejected" };
  return { tone: "warn", label: "Approved with changes" };
}

function projectNameFromFile(fileName) {
  const base = String(fileName || "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "").trim();
  return (base || "Untitled RFC").slice(0, 200);
}

function checkRfcText(text) {
  const t = String(text || "").trim();
  if (t.length < MIN_RFC_CHARS) {
    return `The RFC needs at least ${MIN_RFC_CHARS} characters so the agents have something to review.`;
  }
  return null;
}

function stageText(review) {
  if (!review || review.status === "pending") return "Waiting to start";
  const f = (review.findings || []).length;
  const d = (review.debates || []).length;
  if (d > 0) return `Agents are debating (${f} findings so far)`;
  if (f > 0) return `Specialists are analyzing (${f} findings so far)`;
  return "Reading the RFC";
}

const sleepMs = (ms) => new Promise((r) => setTimeout(r, ms));

/** Polls until the review is completed or failed. Returns the final review, or null if cancelled. */
async function waitForReview(getReview, opts) {
  const o = Object.assign({ intervalMs: 3000, isCancelled: () => false, onUpdate: () => {}, sleep: sleepMs }, opts);
  for (;;) {
    if (o.isCancelled()) return null;
    const review = await getReview();
    if (review.status === "completed" || review.status === "failed") return review;
    o.onUpdate(review);
    await o.sleep(o.intervalMs);
  }
}

function splitAdjustment(summary) {
  const m = String(summary || "").match(/\s*\[Adjusted by review rules:[^\]]*\]\s*$/);
  if (!m) return { text: String(summary || ""), note: null };
  return {
    text: String(summary).slice(0, m.index),
    note: m[0].trim().replace(/^\[|\]$/g, ""),
  };
}

/** Findings sorted worst-first, for the Problems panel and the result page. */
function sortedFindings(review) {
  const rank = (s) => {
    const i = SEVERITIES.indexOf(s);
    return i < 0 ? SEVERITIES.length : i;
  };
  return (review.findings || []).slice().sort((a, b) => rank(a.severity) - rank(b.severity) || a.id - b.id);
}

const MIN_QUOTE_CHARS = 12;
// Markdown marks (bold, code, tables, headings, quotes) are left out when matching, on both sides,
// because the model usually quotes the plain words without them.
const MARKDOWN_MARKS = /[*_`|#>]/;
const MARKDOWN_MARKS_G = /[*_`|#>]/g;

/** A lower-cased, whitespace-collapsed copy of the text, plus a map from each of its characters back to the original offset. */
function indexText(text) {
  const src = String(text || "");
  let norm = "";
  const map = [];
  let prevSpace = true;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (MARKDOWN_MARKS.test(ch)) continue;
    if (/\s/.test(ch)) {
      if (!prevSpace) { norm += " "; map.push(i); prevSpace = true; }
      continue;
    }
    const lc = ch.toLowerCase(); // can be longer than one character for a few letters
    for (let k = 0; k < lc.length; k++) { norm += lc[k]; map.push(i); }
    prevSpace = false;
  }
  return { norm, map };
}

function normalizeQuote(q) {
  return String(q || "")
    .replace(MARKDOWN_MARKS_G, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase()
    .replace(/^[\s."'\u201c\u201d]+|[\s."'\u201c\u201d]+$/g, "");
}

/**
 * Where does the finding's quote sit in the text? Returns {start, end} offsets into the original text, or null.
 * Case, line breaks, extra spaces and Markdown marks (** ` | # >) do not matter. If the whole quote is not
 * found (the model may have reworded the end of it), the start of the quote is tried.
 */
function locateQuote(index, quote) {
  const q = normalizeQuote(quote);
  if (q.length < MIN_QUOTE_CHARS) return null;
  let pos = index.norm.indexOf(q);
  let len = q.length;
  if (pos < 0 && q.length > 40) {
    const head = q.slice(0, 40).replace(/\s+\S*$/, "");
    if (head.length >= MIN_QUOTE_CHARS) { pos = index.norm.indexOf(head); len = head.length; }
  }
  if (pos < 0) return null;
  return { start: index.map[pos], end: index.map[pos + len - 1] + 1 };
}

/** {line, character} (both counted from 0) of an offset in the text. */
function offsetToPosition(text, offset) {
  const before = String(text).slice(0, offset);
  const line = (before.match(/\n/g) || []).length;
  return { line, character: offset - (before.lastIndexOf("\n") + 1) };
}

function buildResultHtml(review, serverUrl) {
  const report = review.report;
  const findings = sortedFindings(review);
  const link = `${normalizeUrl(serverUrl)}/#/review/${encodeURIComponent(String(review.id))}`;

  let head = "";
  if (report) {
    const d = decisionInfo(report.decision);
    const s = splitAdjustment(report.summary);
    head = `
      <section class="card">
        <div class="score ${d.tone}">${esc(report.score)}</div>
        <div class="verdict">
          <h1 class="${d.tone}">${esc(d.label)}</h1>
          <p>${esc(s.text)}</p>
          ${s.note ? `<p class="muted small">${esc(s.note)}</p>` : ""}
        </div>
      </section>
      <div class="cols">
        <section class="card"><h2>Key risks</h2>${list(report.key_risks, "ul")}</section>
        <section class="card"><h2>What to do</h2>${list(report.recommendations, "ol")}</section>
      </div>`;
  } else {
    head = `<section class="card"><p>No verdict was saved for this review.</p></section>`;
  }

  const groups = SEVERITIES.map((sev) => {
    const items = findings.filter((f) => f.severity === sev);
    if (!items.length) return "";
    return `<h2>${esc(pretty(sev))} <span class="muted">${items.length}</span></h2>` +
      items.map((f) => `
        <details class="finding ${esc(sev)}">
          <summary><span class="dot ${esc(sev)}"></span>${esc(f.title)}
            <span class="muted agent">${esc(agentShort(f.agent_name))}</span></summary>
          <div class="body">
            ${f.quote ? `<h3>RFC says</h3><p class="quote">\u201c${esc(f.quote)}\u201d</p>` : ""}
            <h3>Problem</h3><p>${esc(f.description)}</p>
            <h3>Suggested fix</h3><p>${esc(f.recommendation)}</p>
            ${f.tradeoffs ? `<h3>Trade-offs</h3><p>${esc(f.tradeoffs)}</p>` : ""}
          </div>
        </details>`).join("");
  }).join("");

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 16px 22px 40px; line-height: 1.5; }
  h1 { font-size: 26px; margin: 0 0 6px; }
  h2 { font-size: 16px; margin: 26px 0 8px; }
  h3 { font-size: 12px; margin: 12px 0 2px; color: var(--vscode-descriptionForeground); text-transform: uppercase; letter-spacing: .04em; }
  p { margin: 0 0 6px; }
  .muted { color: var(--vscode-descriptionForeground); }
  .small { font-size: 12px; }
  .card { background: var(--vscode-editorWidget-background, rgba(128,128,128,.1)); border: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); border-radius: 10px; padding: 16px 18px; display: flex; gap: 20px; align-items: center; margin-bottom: 12px; }
  .cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .cols .card { display: block; margin: 0; }
  .cols h2 { margin-top: 0; }
  ul, ol { margin: 0; padding-left: 20px; } li { margin: 4px 0; }
  .score { font-size: 38px; font-weight: 600; min-width: 84px; height: 84px; border-radius: 50%; display: grid; place-items: center; border: 6px solid currentColor; }
  .good { color: var(--vscode-testing-iconPassed, #3fb950); }
  .warn { color: var(--vscode-editorWarning-foreground, #d29922); }
  .bad { color: var(--vscode-editorError-foreground, #f85149); }
  .finding { border-top: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); padding: 8px 0; }
  .finding summary { cursor: pointer; font-weight: 500; }
  .agent { float: right; font-weight: 400; font-size: 12px; }
  .quote { font-style: italic; border-left: 3px solid var(--vscode-widget-border, rgba(128,128,128,.4)); padding-left: 10px; }
  .body { padding: 4px 0 8px 20px; max-width: 70ch; }
  .dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 9px; background: var(--vscode-descriptionForeground); }
  .dot.critical, .dot.high { background: var(--vscode-editorError-foreground, #f85149); }
  .dot.medium { background: var(--vscode-editorWarning-foreground, #d29922); }
  .foot { margin-top: 28px; font-size: 12px; }
</style></head><body>
${head}
${groups || '<p class="muted">The agents did not report any findings.</p>'}
<p class="foot muted">Open the full review in your browser: ${esc(link)}</p>
</body></html>`;
}

function list(items, tag) {
  const arr = Array.isArray(items) ? items : [];
  if (!arr.length) return '<p class="muted">None listed.</p>';
  return `<${tag}>${arr.map((i) => `<li>${esc(i)}</li>`).join("")}</${tag}>`;
}

module.exports = {
  SEVERITIES, esc, normalizeUrl, pretty, agentShort, decisionInfo, projectNameFromFile,
  checkRfcText, stageText, waitForReview, splitAdjustment, sortedFindings, buildResultHtml,
  MIN_QUOTE_CHARS, indexText, normalizeQuote, locateQuote, offsetToPosition,
};
