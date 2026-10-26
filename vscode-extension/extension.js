"use strict";
const vscode = require("vscode");
const lib = require("./lib");

const TOKEN_KEY = "archnexus.token";
const USER_KEY = "archnexus.user";

let diagnostics;
let panel;

function serverUrl() {
  return lib.normalizeUrl(vscode.workspace.getConfiguration("archnexus").get("serverUrl"));
}

class NeedSignIn extends Error {}

async function api(context, path, options) {
  const token = await context.secrets.get(TOKEN_KEY);
  const headers = Object.assign({}, options && options.headers);
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(serverUrl() + path, Object.assign({}, options, { headers }));
  } catch (e) {
    throw new Error(`Can't reach the ArchNexus server at ${serverUrl()}. Is it running?`);
  }
  if (res.ok) return res.json();
  let detail = "";
  try {
    const body = await res.json();
    detail = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail;
  } catch (e) { /* not JSON */ }
  if (res.status === 401 && path.indexOf("/auth/login") !== 0) {
    await context.secrets.delete(TOKEN_KEY);
    await context.globalState.update(USER_KEY, undefined);
    throw new NeedSignIn("Your ArchNexus session ended. Please sign in again.");
  }
  throw new Error(detail || `The server returned an error (${res.status}).`);
}

async function signIn(context) {
  const email = await vscode.window.showInputBox({ title: "ArchNexus: Sign in", prompt: "Email", ignoreFocusOut: true });
  if (!email) return false;
  const password = await vscode.window.showInputBox({ title: "ArchNexus: Sign in", prompt: "Password", password: true, ignoreFocusOut: true });
  if (!password) return false;
  try {
    const res = await api(context, "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim(), password }),
    });
    await context.secrets.store(TOKEN_KEY, res.access_token);
    await context.globalState.update(USER_KEY, res.user.name);
    vscode.window.showInformationMessage(`Signed in to ArchNexus as ${res.user.name}.`);
    return true;
  } catch (e) {
    vscode.window.showErrorMessage(`ArchNexus sign-in failed: ${e.message}`);
    return false;
  }
}

async function ensureSignedIn(context) {
  if (await context.secrets.get(TOKEN_KEY)) return true;
  const choice = await vscode.window.showInformationMessage(
    "Sign in to ArchNexus to review this RFC.", "Sign in", "Create an account"
  );
  if (choice === "Sign in") return signIn(context);
  if (choice === "Create an account") await vscode.env.openExternal(vscode.Uri.parse(`${serverUrl()}/#/register`));
  return false;
}

function showResult(review) {
  const html = lib.buildResultHtml(review, serverUrl());
  if (panel) {
    panel.title = `Review ${review.id}`;
    panel.webview.html = html;
    panel.reveal(vscode.ViewColumn.Beside, true);
    return;
  }
  panel = vscode.window.createWebviewPanel("archnexusResult", `Review ${review.id}`, { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true }, { enableScripts: false });
  panel.onDidDispose(() => { panel = undefined; });
  panel.webview.html = html;
}

function showProblems(document, review) {
  diagnostics.clear();
  if (!vscode.workspace.getConfiguration("archnexus").get("showProblems")) return;
  // Look the quotes up in the text as it is now, so lines are right even if the file was edited during the review.
  const index = lib.indexText(document.getText());
  const firstLine = new vscode.Range(0, 0, 0, Math.max(1, document.lineAt(0).text.length));
  const items = lib.sortedFindings(review).map((f) => {
    const loc = lib.locateQuote(index, f.quote);
    const range = loc ? new vscode.Range(document.positionAt(loc.start), document.positionAt(loc.end)) : firstLine;
    const sev = f.severity === "critical" || f.severity === "high"
      ? vscode.DiagnosticSeverity.Error
      : f.severity === "medium" ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Information;
    const d = new vscode.Diagnostic(range, `[${lib.agentShort(f.agent_name)}] ${f.title}. Fix: ${f.recommendation}`, sev);
    d.source = "ArchNexus";
    return d;
  });
  diagnostics.set(document.uri, items);
}

async function reviewRfc(context) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("Open the RFC file first, then run the review.");
    return;
  }
  const doc = editor.document;
  const text = editor.selection.isEmpty ? doc.getText() : doc.getText(editor.selection);
  const problem = lib.checkRfcText(text);
  if (problem) { vscode.window.showWarningMessage(problem); return; }
  if (!(await ensureSignedIn(context))) return;

  try {
    const review = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "ArchNexus", cancellable: true },
      async (progress, token) => {
        progress.report({ message: "Sending the RFC…" });
        const project = await api(context, "/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: lib.projectNameFromFile(doc.fileName), rfc_text: text }),
        });
        const started = await api(context, `/projects/${project.id}/reviews`, { method: "POST" });
        return lib.waitForReview(() => api(context, `/reviews/${started.id}`), {
          isCancelled: () => token.isCancellationRequested,
          onUpdate: (r) => progress.report({ message: lib.stageText(r) + ". This takes a few minutes." }),
        });
      }
    );
    if (!review) {
      vscode.window.showInformationMessage("Stopped waiting. The review keeps running on the server and will appear in the web app.");
      return;
    }
    if (review.status === "failed") {
      vscode.window.showErrorMessage(`The review did not finish: ${review.error || "unknown error"}`);
      return;
    }
    showResult(review);
    showProblems(doc, review);
    const d = lib.decisionInfo(review.report && review.report.decision);
    vscode.window.showInformationMessage(`ArchNexus: ${d.label}${review.report ? ` (score ${review.report.score})` : ""}.`);
  } catch (e) {
    if (e instanceof NeedSignIn) {
      const again = await vscode.window.showWarningMessage(e.message, "Sign in");
      if (again) await signIn(context);
    } else {
      vscode.window.showErrorMessage(`ArchNexus: ${e.message}`);
    }
  }
}

function activate(context) {
  diagnostics = vscode.languages.createDiagnosticCollection("archnexus");
  context.subscriptions.push(
    diagnostics,
    vscode.commands.registerCommand("archnexus.reviewRfc", () => reviewRfc(context)),
    vscode.commands.registerCommand("archnexus.signIn", () => signIn(context)),
    vscode.commands.registerCommand("archnexus.register", () =>
      vscode.env.openExternal(vscode.Uri.parse(`${serverUrl()}/#/register`))),
    vscode.commands.registerCommand("archnexus.signOut", async () => {
      await context.secrets.delete(TOKEN_KEY);
      await context.globalState.update(USER_KEY, undefined);
      vscode.window.showInformationMessage("Signed out of ArchNexus.");
    }),
    vscode.commands.registerCommand("archnexus.clearProblems", () => diagnostics.clear())
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
