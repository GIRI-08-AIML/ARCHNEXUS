# ArchNexus RFC Review for VS Code

Review the RFC you are writing without leaving the editor. Five specialist agents (Architecture, Security, Database, Scalability, Reliability) and a judge read it and give a verdict, a score and a list of changes.

## Use it

1. Start your ArchNexus server (default address `http://127.0.0.1:8000`; change it in Settings > ArchNexus > Server Url).
2. Run **ArchNexus: Sign in** from the Command Palette (or **Create an account** to open the sign-up page).
3. Open your RFC (Markdown or text). To review only part of it, select that part.
4. Run **ArchNexus: Review this RFC**, or use the button at the top right of the editor.
5. When the review finishes (a few minutes on a local model), the verdict opens beside your file and the findings appear in the Problems panel.

## Notes

- Your RFC is sent to the server you configured and nowhere else.
- Your login token is kept in VS Code's secret storage. **ArchNexus: Sign out** removes it.
- Each finding in the Problems panel sits on the text of your RFC it quotes, so clicking it jumps to that spot. The match ignores differences in spacing and Markdown marks (`**`, `` ` ``, `|`). If the quote cannot be found (for example you edited the RFC after the review), the finding appears on line 1 instead.
- The result page shows the quote under each finding as "RFC says".
- The review keeps running on the server if you cancel the wait. Find it later in the web app.

## Install from a file

Build the package once (needs Node 20 or newer), then install it:

```bash
cd vscode-extension
npx @vscode/vsce package --no-dependencies     # creates archnexus-<version>.vsix
code --install-extension archnexus-0.2.0.vsix
```

Or in VS Code: Extensions panel > the "..." menu > **Install from VSIX...**.

## Tests

```bash
npm test        # runs test/lib.test.js with Node's built-in test runner; no packages to install
```
