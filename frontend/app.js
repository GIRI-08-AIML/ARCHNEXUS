/* ArchNexus frontend. Plain JS, no build step.
   LLM output is untrusted, so every piece of text goes in through textContent. */
(function () {
  "use strict";

  var app = document.getElementById("app");
  var banner = document.getElementById("banner");
  var pollTimer = null;
  var authNotice = "";
  var session = loadSession();

  function loadSession() {
    try {
      var raw = localStorage.getItem("archnexus.session");
      var s = raw ? JSON.parse(raw) : null;
      return s && s.token ? s : null;
    } catch (e) { return null; }
  }
  function saveSession(s) {
    session = s;
    try {
      if (s) localStorage.setItem("archnexus.session", JSON.stringify(s));
      else localStorage.removeItem("archnexus.session");
    } catch (e) { /* storage blocked: stay signed in until reload */ }
    renderUserBox();
  }
  var SEVERITIES = ["critical", "high", "medium", "low"];
  var SPECIALISTS = ["Architecture", "Security", "Database", "Scalability", "Reliability"];
  var STEPS = ["Reading the RFC", "Specialists analyze", "Debate", "Final verdict"];

  var SAMPLE_RFC =
    "# Order Service Redesign\n\n## Overview\nWe will split the monolith into an order service and a payment service, " +
    "connected through a message queue.\n\n## Architecture\nThe order service exposes a REST API. Payments are handled " +
    "asynchronously through the queue.\n\n## Data\nBoth services share one PostgreSQL database.\n\n## Security\n" +
    "Clients authenticate with a JWT that does not expire.\n\n## Scalability\nWe expect 10x traffic during sales and will run a single instance.";

  /* ---------- helpers ---------- */
  function el(tag, props, children) {
    var node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        var v = props[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.indexOf("on") === 0) node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? "" : v);
      });
    }
    [].concat.apply([], children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function svg(tag, attrs) {
    var n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }

  function render(nodes) {
    app.replaceChildren.apply(app, nodes);
  }

  function setBanner(msg) {
    if (msg) { banner.textContent = msg; banner.hidden = false; }
    else { banner.hidden = true; }
  }

  function stopPolling() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  function api(path, options) {
    options = options || {};
    options.headers = Object.assign({}, options.headers);
    if (session) options.headers.Authorization = "Bearer " + session.token;
    return fetch(path, options).then(function (res) {
      if (res.ok) { setBanner(null); return res.status === 204 ? null : res.json(); }
      return failure(res, path);
    }, function () {
      var err = new Error("Can't reach the ArchNexus server. Check that it is still running.");
      err.network = true;
      throw err;
    });
  }

  function failure(res, path) {
    {
      if (res.status === 401 && path.indexOf("/auth/") !== 0) {
        saveSession(null);
        authNotice = "Your session ended. Please sign in again.";
        location.hash = "#/login";
        var gone = new Error("Please sign in to continue.");
        gone.status = 401; gone.handled = true;
        throw gone;
      }
      return res.json().catch(function () { return {}; }).then(function (body) {
        var detail = body && body.detail;
        if (Array.isArray(detail)) {
          detail = detail.map(function (d) { return d.msg || String(d); }).join("; ");
        }
        var err = new Error(detail || "The server returned an error (" + res.status + ").");
        err.status = res.status;
        throw err;
      });
    }
  }

  /* POST and read a server-sent-event stream. onEvent gets each parsed event; resolves with the "done" event. */
  function streamPost(path, payload, onEvent) {
    var headers = { "Content-Type": "application/json" };
    if (session) headers.Authorization = "Bearer " + session.token;
    return fetch(path, { method: "POST", headers: headers, body: JSON.stringify(payload) }).then(function (res) {
      if (!res.ok) return failure(res, path);
      var reader = res.body.getReader(), decoder = new TextDecoder(), buf = "", result = null;
      function pump() {
        return reader.read().then(function (chunk) {
          buf += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done });
          var parts = buf.split("\n\n");
          buf = parts.pop();
          parts.forEach(function (block) {
            var line = block.split("\n").filter(function (l) { return l.indexOf("data:") === 0; })[0];
            if (!line) return;
            var ev = JSON.parse(line.slice(5));
            if (ev.type === "error") throw new Error(ev.message);
            if (ev.type === "done") result = ev;
            onEvent(ev);
          });
          return chunk.done ? result : pump();
        });
      }
      return pump();
    }, function () {
      var err = new Error("Can't reach the ArchNexus server. Check that it is still running.");
      err.network = true;
      throw err;
    });
  }

  function pretty(s) {
    return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); });
  }

  function agentShort(name) {
    return String(name || "").replace(/\s*agent\s*$/i, "");
  }

  var AGENT_COLORS = { Architecture: "#5e5ce6", Security: "#ff453a", Database: "#30b0c7", Scalability: "#ff9f0a", Reliability: "#34c759", Judge: "#af52de" };
  function agentColor(name) { return AGENT_COLORS[agentShort(name)] || "#8e8e93"; }

  function when(iso) {
    if (!iso) return "";
    var d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
    if (isNaN(d)) return "";
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  function sevTone(sev) {
    return { critical: "red", high: "orange", medium: "blue", low: "gray" }[sev] || "gray";
  }

  function decisionInfo(decision) {
    if (decision === "approve") return { tone: "green", label: "Approved", line: "Ready to build." };
    if (decision === "reject") return { tone: "red", label: "Rejected", line: "Needs a rethink before building." };
    return { tone: "orange", label: "Approved with changes", line: "Fix the issues below first." };
  }

  function chip(text, tone) {
    return el("span", { class: "chip chip-" + tone, text: text });
  }

  function statusChip(r) {
    if (r.status === "completed" && r.decision) {
      var d = decisionInfo(r.decision);
      return chip(d.label, d.tone);
    }
    if (r.status === "failed") return chip("Failed", "red");
    if (r.status === "completed") return chip("Completed", "green");
    return chip(r.status === "pending" ? "Queued" : "Running", "blue");
  }

  /* ---------- sign in / register ---------- */
  /* ---------- icons, theme and app shell (sidebar + top bar) ---------- */
  var ICONS = {
    dashboard: "M3 3h7v9H3z M14 3h7v5h-7z M14 12h7v9h-7z M3 16h7v5H3z",
    plus: "M12 5v14 M5 12h14",
    list: "M8 6h13 M8 12h13 M8 18h13 M3 6h.01 M3 12h.01 M3 18h.01",
    users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M23 21v-2a4 4 0 0 0-3-3.87 M16 3.13a4 4 0 0 1 0 7.75",
    code: "M16 18l6-6-6-6 M8 6l-6 6 6 6",
    logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9",
    search: "M21 21l-4.3-4.3 M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16",
    sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10 M12 1v2 M12 21v2 M4.2 4.2l1.4 1.4 M18.4 18.4l1.4 1.4 M1 12h2 M21 12h2 M4.2 19.8l1.4-1.4 M18.4 5.6l1.4-1.4",
    moon: "M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z",
    menu: "M3 6h18 M3 12h18 M3 18h18",
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    check: "M22 11.1V12a10 10 0 1 1-5.9-9.1 M22 4L12 14l-3-3",
    star: "M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.9L12 17.8 5.8 21.1 7 14.2 2 9.3l6.9-1z",
    alert: "M12 9v4 M12 17h.01 M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
    clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20 M12 6v6l4 2",
    file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8"
  };
  function icon(name) {
    var s = svg("svg", { "class": "ic", viewBox: "0 0 24 24", "aria-hidden": "true" });
    s.appendChild(svg("path", { d: ICONS[name] || "" }));
    return s;
  }

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }
  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("archnexus.theme", t); } catch (e) { /* storage blocked: theme lasts until reload */ }
    [].forEach.call(document.querySelectorAll(".theme-toggle button"), function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-theme") === t));
    });
  }

  var sideEl = document.getElementById("side");
  var topEl = document.getElementById("topbar");
  var scrim = document.getElementById("scrim");

  function setDrawer(open) {
    document.body.classList.toggle("drawer-open", !!open);
    if (scrim) scrim.hidden = !open;
  }
  if (scrim) scrim.addEventListener("click", function () { setDrawer(false); });

  function initials(name) {
    var parts = String(name || "?").trim().split(/\s+/);
    return ((parts[0] || "?").charAt(0) + (parts.length > 1 ? parts[parts.length - 1].charAt(0) : "")).toUpperCase();
  }

  function activeNav(path) {
    if (path === "/" || path === "") return "/";
    if (path === "/new") return "/new";
    if (path === "/workspace") return "/workspace";
    if (path === "/history" || path.indexOf("/review/") === 0) return "/history";
    return "";
  }

  function navItem(href, ic, label, active, external) {
    var a = el("a", {
      class: "nav-item" + (active ? " active" : ""), href: href,
      "aria-current": active ? "page" : null,
      target: external ? "_blank" : null, rel: external ? "noopener" : null,
      onclick: function () { setDrawer(false); }
    }, [icon(ic), label]);
    return a;
  }

  function renderUserBox(path, query) {
    if (path === undefined) path = (location.hash.replace(/^#/, "").split("?")[0]) || "/";
    document.body.classList.toggle("guest", !session);
    var theme = currentTheme();
    var toggle = el("div", { class: "theme-toggle", role: "group", "aria-label": "Colour theme" }, [
      el("button", { type: "button", "data-theme": "light", "aria-label": "Light theme", title: "Light", "aria-pressed": String(theme === "light"), onclick: function () { setTheme("light"); } }, [icon("sun")]),
      el("button", { type: "button", "data-theme": "dark", "aria-label": "Dark theme", title: "Dark", "aria-pressed": String(theme === "dark"), onclick: function () { setTheme("dark"); } }, [icon("moon")])
    ]);

    if (!session) {
      sideEl.replaceChildren();
      topEl.replaceChildren(
        el("a", { class: "brand", href: "#/login" }, ["ArchNexus"]),
        el("span", { class: "top-spacer" }),
        toggle
      );
      return;
    }

    var act = activeNav(path);
    sideEl.replaceChildren(
      el("a", { class: "brand", href: "#/", onclick: function () { setDrawer(false); } }, ["ArchNexus"]),
      el("h4", { text: "Main menu" }),
      navItem("#/", "dashboard", "Dashboard", act === "/"),
      navItem("#/new", "plus", "New review", act === "/new"),
      navItem("#/history", "list", "All reviews", act === "/history"),
      el("h4", { text: "Team and tools" }),
      navItem("#/workspace", "users", "Workspace", act === "/workspace"),
      navItem("/docs", "code", "API docs", false, true),
      el("div", { class: "side-spacer" }),
      el("div", { class: "side-card" }, [
        el("div", { class: "orb" }, [icon("chat")]),
        el("strong", { text: "Ask the assistant" }),
        el("p", { text: "Open a finished review and use its Ask tab to question any finding." }),
        el("a", { class: "btn btn-primary", href: "#/history", text: "Browse reviews", onclick: function () { setDrawer(false); } })
      ]),
      el("button", { class: "nav-item", type: "button", onclick: function () { setDrawer(false); signOut(); } }, [icon("logout"), "Sign out"])
    );

    var q = el("input", { type: "search", placeholder: "Search reviews…", "aria-label": "Search reviews", value: query || "" });
    var searchForm = el("form", { class: "top-search", role: "search" }, [icon("search"), q]);
    searchForm.addEventListener("submit", function (e) {
      e.preventDefault();
      var v = q.value.trim();
      location.hash = "#/history" + (v ? "?q=" + encodeURIComponent(v) : "");
    });

    var user = session.user || {};
    topEl.replaceChildren(
      el("button", { class: "menu-btn", type: "button", "aria-label": "Open menu", onclick: function () { setDrawer(true); } }, [icon("menu")]),
      searchForm,
      el("span", { class: "top-spacer" }),
      toggle,
      el("div", { class: "user-chip", title: user.email || "" }, [
        el("span", { class: "initials", text: initials(user.name), "aria-hidden": "true" }),
        el("div", { class: "who" }, [el("b", { text: user.name || "Signed in" }), el("span", { text: user.company || "Review board" })])
      ])
    );
  }

  function signOut() {
    stopPolling();
    saveSession(null);
    authNotice = "";
    location.hash = "#/login";
  }

  function authView(mode) {
    stopPolling();
    var isReg = mode === "register";
    var fields = {};
    function field(key, label, attrs) {
      fields[key] = el("input", Object.assign({ id: "f-" + key }, attrs));
      return el("label", { class: "field" }, [el("span", { text: label }), fields[key]]);
    }
    var errBox = el("p", { class: "form-error", role: "alert", text: authNotice });
    authNotice = "";
    var submit = el("button", { class: "btn btn-primary", type: "submit", text: isReg ? "Create account" : "Sign in" });

    var rows = [];
    if (isReg) {
      rows.push(field("name", "Your name", { type: "text", autocomplete: "name", maxlength: "200" }));
      rows.push(field("company", "Company (optional)", { type: "text", autocomplete: "organization", maxlength: "200" }));
    }
    rows.push(field("email", "Email", { type: "email", autocomplete: "email", maxlength: "320" }));
    rows.push(field("password", isReg ? "Password (8 characters or more)" : "Password",
      { type: "password", autocomplete: isReg ? "new-password" : "current-password", maxlength: "128" }));
    rows.push(errBox);
    rows.push(el("div", { class: "form-actions" }, [
      el("a", { href: isReg ? "#/login" : "#/register", text: isReg ? "I already have an account" : "Create an account" }),
      submit
    ]));
    var form = el("form", { class: "form", novalidate: true }, rows);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      errBox.textContent = "";
      var body = { email: fields.email.value.trim(), password: fields.password.value };
      if (isReg) {
        body.name = fields.name.value.trim();
        body.company = fields.company.value.trim() || null;
        if (!body.name) { errBox.textContent = "Enter your name."; fields.name.focus(); return; }
      }
      if (!body.email) { errBox.textContent = "Enter your email."; fields.email.focus(); return; }
      if (!body.password) { errBox.textContent = "Enter your password."; fields.password.focus(); return; }
      if (isReg && body.password.length < 8) { errBox.textContent = "Use a password with at least 8 characters."; fields.password.focus(); return; }
      submit.disabled = true;
      submit.textContent = isReg ? "Creating\u2026" : "Signing in\u2026";
      api(isReg ? "/auth/register" : "/auth/login", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
      }).then(function (res) {
        saveSession({ token: res.access_token, user: res.user });
        location.hash = "#/";
      }).catch(function (err) {
        errBox.textContent = err.message;
        submit.disabled = false;
        submit.textContent = isReg ? "Create account" : "Sign in";
      });
    });

    render([el("div", { class: "wrap narrow" }, [
      el("section", { class: "hero" }, [
        el("h1", { text: isReg ? "Create your account." : "Sign in." }),
        el("p", { text: isReg ? "Your RFCs and reviews stay private to your account." : "Welcome back to ArchNexus." })
      ]),
      el("div", { class: "card" }, [form])
    ])]);
    fields[isReg ? "name" : "email"].focus();
  }

  /* ---------- home ---------- */
  /* ---------- dashboard ---------- */
  function boardStack() {
    return el("div", { class: "board-stack" }, SPECIALISTS.map(function (n) {
      return el("span", { class: "avatar", title: n + " Agent", style: "background:" + agentColor(n), text: n.charAt(0) });
    }).concat([el("small", { text: "5 specialists and a judge, ready to review" })]));
  }

  function kpi(tone, ic, label, value, sub) {
    return el("div", { class: "kpi" }, [
      el("div", { class: "kpi-top" }, [el("span", { class: "kpi-ico " + tone }, [icon(ic)]), el("span", { class: "kpi-label", text: label })]),
      el("div", { class: "kpi-val", text: String(value) }),
      el("div", { class: "kpi-sub", text: sub })
    ]);
  }

  function reviewBlurb(r) {
    if (r.status === "failed") return "This review could not finish. Open it to see why.";
    if (r.status === "pending") return "Queued. The specialists will start in a moment.";
    if (r.status === "running") return "The specialists are reading the RFC and debating.";
    return r.decision ? decisionInfo(r.decision).line : "Completed.";
  }

  function miniCard(r) {
    var total = r.total_findings || 0;
    var pct = total ? Math.round((r.resolved_findings || 0) * 100 / total) : 0;
    return el("a", { class: "mini", href: "#/review/" + r.id }, [
      el("div", { class: "chips" }, [statusChip(r), chip("Review " + r.id, "gray")]),
      el("h3", { text: r.project_name }),
      el("p", { text: reviewBlurb(r) }),
      el("div", { class: "prog" + (pct === 100 ? " green" : ""), role: "img", "aria-label": pct + " percent of findings resolved" }, [el("i", { style: "width:" + pct + "%" })]),
      el("div", { class: "prog-note", text: total ? pct + "% resolved (" + r.resolved_findings + " of " + total + ")" : "No findings yet" }),
      el("div", { class: "mini-foot" }, [
        el("span", {}, ["Score ", el("b", { text: r.score !== null && r.score !== undefined ? String(r.score) : "–" })]),
        el("span", { text: when(r.created_at) })
      ])
    ]);
  }

  function scoreChart(rows) {
    var scored = rows.filter(function (r) { return r.status === "completed" && r.score !== null && r.score !== undefined; })
      .slice(0, 12).reverse();
    if (!scored.length) return el("p", { class: "empty", text: "Finish a review and its score will show up here." });
    var cols = scored.map(function (r) {
      var filled = Math.round(r.score / 10);
      var tone = decisionInfo(r.decision).tone;
      var dots = [];
      for (var i = 0; i < 10; i++) dots.push(el("span", { class: "chart-dot" + (i < filled ? " on " + tone : "") }));
      return el("a", { class: "chart-col", href: "#/review/" + r.id, title: r.project_name + ": " + r.score + "/100, " + decisionInfo(r.decision).label }, [
        el("div", { class: "chart-dots" }, dots),
        el("span", { class: "chart-x", text: "#" + r.id })
      ]);
    });
    return el("div", {}, [
      el("div", { class: "chart", role: "img", "aria-label": "Score of each recent review out of 100" }, [
        el("div", { class: "chart-y" }, ["100", "80", "60", "40", "20"].map(function (t) { return el("span", { text: t }); })),
        el("div", { class: "chart-cols" }, cols)
      ])
    ]);
  }

  function boardPanel(agents) {
    var list = (agents && agents.length ? agents : SPECIALISTS.map(function (n) { return { name: n + " Agent", role: "specialist" }; }).concat([{ name: "Judge Agent", role: "judge" }]));
    return el("div", { class: "board-list" }, list.map(function (a) {
      return el("div", { class: "agent-row" }, [
        el("span", { class: "avatar", style: "background:" + agentColor(a.name), text: agentShort(a.name).charAt(0).toUpperCase() }),
        el("div", {}, [el("b", { text: a.name }), el("span", { text: pretty(a.role) })]),
        el("span", { class: "ready", text: "Ready" })
      ]);
    }));
  }

  function reviewTable(rows) {
    var body = el("tbody");
    var search = el("input", { type: "search", placeholder: "Search by project…", "aria-label": "Search recent reviews" });
    function draw() {
      var q = search.value.trim().toLowerCase();
      var list = rows.filter(function (r) { return !q || String(r.project_name).toLowerCase().indexOf(q) >= 0; }).slice(0, 8);
      if (!list.length) {
        body.replaceChildren(el("tr", {}, [el("td", { colspan: "7", class: "empty", text: "No reviews match your search." })]));
        return;
      }
      body.replaceChildren.apply(body, list.map(function (r) {
        var tr = el("tr", { tabindex: "0", onclick: function () { location.hash = "#/review/" + r.id; } }, [
          el("td", {}, [el("div", { class: "pname", text: r.project_name })]),
          el("td", { text: "#" + r.id }),
          el("td", { text: when(r.created_at) }),
          el("td", {}, [statusChip(r)]),
          el("td", { class: "score", text: r.score !== null && r.score !== undefined ? String(r.score) : "–" }),
          el("td", { text: r.total_findings ? r.resolved_findings + " / " + r.total_findings : "–" }),
          el("td", {}, [el("a", { class: "open-link", href: "#/review/" + r.id, text: "Open" })])
        ]);
        tr.addEventListener("keydown", function (e) { if (e.key === "Enter") location.hash = "#/review/" + r.id; });
        return tr;
      }));
    }
    search.addEventListener("input", draw);
    draw();
    return el("div", { class: "panel" }, [
      el("div", { class: "panel-head" }, [
        el("h2", { text: "Recent reviews" }),
        el("div", { class: "tbl-search" }, [icon("search"), search])
      ]),
      el("div", { class: "tbl-wrap" }, [
        el("table", { class: "tbl" }, [
          el("thead", {}, [el("tr", {}, ["Project", "Review", "Date", "Decision", "Score", "Resolved", ""].map(function (h) { return el("th", { text: h }); }))]),
          body
        ])
      ])
    ]);
  }

  function dashBody(rows, agents) {
    if (!rows.length) {
      return el("div", { class: "panel dash-empty" }, [
        el("h2", { text: "Your first review starts here" }),
        el("p", { text: "Paste or upload an RFC and five specialist agents will review it, debate it, and give you a verdict." }),
        el("a", { class: "btn btn-primary", href: "#/new" }, [icon("plus"), "Start a review"])
      ]);
    }
    var weekAgo = Date.now() - 7 * 24 * 3600 * 1000;
    var thisWeek = rows.filter(function (r) { return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(r.created_at) ? r.created_at : r.created_at + "Z").getTime() >= weekAgo; }).length;
    var scored = rows.filter(function (r) { return r.score !== null && r.score !== undefined; });
    var avg = scored.length ? Math.round(scored.reduce(function (a, r) { return a + r.score; }, 0) / scored.length) : null;
    var totalF = rows.reduce(function (a, r) { return a + (r.total_findings || 0); }, 0);
    var resolvedF = rows.reduce(function (a, r) { return a + (r.resolved_findings || 0); }, 0);
    var running = rows.filter(function (r) { return r.status === "pending" || r.status === "running"; }).length;
    var failed = rows.filter(function (r) { return r.status === "failed"; }).length;
    var more = rows.length >= 100 ? "+" : "";

    var legend = el("div", { class: "legend" }, [
      el("span", {}, [el("i", { style: "background:var(--green)" }), "Approved"]),
      el("span", {}, [el("i", { style: "background:var(--orange)" }), "Approved with changes"]),
      el("span", {}, [el("i", { style: "background:var(--red)" }), "Rejected"])
    ]);

    return el("div", {}, [
      el("div", { class: "dash-grid" }, [
        el("div", { class: "stat-grid" }, [
          kpi("", "file", "Total reviews", rows.length + more, thisWeek + " in the last 7 days"),
          kpi("violet", "star", "Average score", avg === null ? "–" : avg, scored.length ? "across " + scored.length + " scored review" + (scored.length === 1 ? "" : "s") : "no scores yet"),
          kpi("orange", "alert", "Open findings", Math.max(0, totalF - resolvedF), resolvedF + " of " + totalF + " resolved"),
          kpi("green", "clock", "In progress", running, failed ? failed + " failed" : "nothing has failed")
        ]),
        el("div", { class: "panel" }, [
          el("div", { class: "panel-head" }, [el("h2", { text: "Latest reviews" }), el("a", { href: "#/history", text: "See all" })]),
          el("div", { class: "mini-grid" }, rows.slice(0, 2).map(miniCard))
        ])
      ]),
      el("div", { class: "two-col stack-gap" }, [
        el("div", { class: "panel grow" }, [
          el("div", { class: "panel-head" }, [el("h2", { text: "Review scores" }), legend]),
          el("div", { class: "chart-wrap" }, [scoreChart(rows)])
        ]),
        el("div", { class: "panel" }, [
          el("div", { class: "panel-head" }, [el("h2", { text: "Review board" })]),
          boardPanel(agents)
        ])
      ]),
      el("div", { class: "stack-gap" }, [reviewTable(rows)])
    ]);
  }

  function dashboardView() {
    stopPolling();
    var holder = el("div", {}, [el("p", { class: "empty pulse", text: "Loading your dashboard…" })]);
    var first = session && session.user && session.user.name ? String(session.user.name).split(/\s+/)[0] : "there";
    render([el("div", { class: "wrap" }, [
      el("div", { class: "dash-head" }, [
        el("div", {}, [
          el("div", { class: "dash-date", text: new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" }) }),
          el("h1", { text: "Welcome back, " + first }),
          boardStack()
        ]),
        el("div", { class: "dash-actions" }, [
          el("a", { class: "btn btn-primary", href: "#/new" }, [icon("plus"), "New review"]),
          el("a", { class: "btn btn-outline", href: "#/history" }, [icon("list"), "All reviews"])
        ])
      ]),
      holder
    ])]);
    Promise.all([api("/reviews?limit=100"), api("/agents").catch(function () { return []; })]).then(function (res) {
      holder.replaceChildren(dashBody(res[0], res[1]));
    }).catch(function (err) {
      if (err.handled) return;
      if (err.network) setBanner(err.message);
      holder.replaceChildren(el("p", { class: "empty", text: err.message }));
    });
  }

  function newReviewView() {
    stopPolling();
    var nameInput = el("input", { id: "name", type: "text", maxlength: "200", placeholder: "Order Service Redesign", required: true });
    var rfcInput = el("textarea", { id: "rfc", placeholder: "Paste your RFC or architecture proposal here (Markdown or plain text).", required: true });
    var errBox = el("p", { class: "form-error", role: "alert" });
    var submit = el("button", { class: "btn btn-primary", type: "submit", text: "Start review" });
    var sample = el("button", {
      class: "btn btn-quiet", type: "button", text: "Try an example",
      onclick: function () { nameInput.value = "Order Service Redesign"; rfcInput.value = SAMPLE_RFC; }
    });

    var fileInput = el("input", { type: "file", accept: ".pdf,.docx,.md,.txt", style: "display:none;" });
    var uploadBtn = el("button", {
      class: "btn btn-quiet", type: "button", text: "Upload file (.pdf, .docx, .md, .txt)",
      onclick: function () { fileInput.click(); }
    });

    fileInput.addEventListener("change", function () {
      if (!fileInput.files || !fileInput.files[0]) return;
      var file = fileInput.files[0];
      errBox.textContent = "";
      uploadBtn.disabled = true;
      uploadBtn.textContent = "Extracting…";

      var fd = new FormData();
      fd.append("file", file);

      var headers = {};
      if (session) headers.Authorization = "Bearer " + session.token;

      fetch("/projects/upload", { method: "POST", headers: headers, body: fd })
        .then(function (res) {
          if (!res.ok) {
            return res.json().catch(function () { return {}; }).then(function (b) {
              throw new Error(b.detail || "Could not extract text from document.");
            });
          }
          return res.json();
        })
        .then(function (data) {
          rfcInput.value = data.text;
          if (!nameInput.value) {
            nameInput.value = file.name.replace(/\.[^/.]+$/, "").replace(/[-_]/g, " ");
          }
          uploadBtn.disabled = false;
          uploadBtn.textContent = "Upload file (.pdf, .docx, .md, .txt)";
        })
        .catch(function (err) {
          errBox.textContent = err.message;
          uploadBtn.disabled = false;
          uploadBtn.textContent = "Upload file (.pdf, .docx, .md, .txt)";
        });
    });

    var form = el("form", { class: "form", novalidate: true }, [
      el("label", { class: "field" }, [el("span", { text: "Project name" }), nameInput]),
      el("label", { class: "field" }, [el("span", { text: "RFC" }), rfcInput]),
      errBox,
      fileInput,
      el("div", { class: "form-actions" }, [
        el("div", { style: "display:flex;gap:8px;flex-wrap:wrap;" }, [uploadBtn, sample]),
        submit
      ])
    ]);

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      errBox.textContent = "";
      var name = nameInput.value.trim();
      var rfc = rfcInput.value.trim();
      if (!name) { errBox.textContent = "Give the project a name."; nameInput.focus(); return; }
      if (rfc.length < 50) { errBox.textContent = "The RFC needs at least 50 characters so the agents have something to review."; rfcInput.focus(); return; }
      submit.disabled = true;
      submit.textContent = "Starting…";
      api("/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, rfc_text: rfc })
      }).then(function (project) {
        return api("/projects/" + project.id + "/reviews", { method: "POST" });
      }).then(function (review) {
        location.hash = "#/review/" + review.id;
      }).catch(function (err) {
        if (err.handled) return;
        errBox.textContent = err.message;
        submit.disabled = false;
        submit.textContent = "Start review";
      });
    });

    var recent = el("div", { class: "section" });
    render([
      el("div", { class: "wrap" }, [
        el("section", { class: "hero" }, [
          el("span", { class: "eyebrow", text: "AI architecture review board" }),
          el("h1", {}, ["Review your design ", el("span", { class: "grad", text: "before you build it." })]),
          el("p", { text: "Five specialist agents read your RFC, argue it out, and a judge gives the verdict. Then ask the assistant anything about it." })
        ]),
        el("div", { class: "card card-lift" }, [form]),
        el("div", { class: "how" }, [
          ["1", "Paste your RFC", "Write it or upload a PDF, Word or Markdown file."],
          ["2", "Specialists review", "Architecture, Security, Database, Scalability and Reliability each find problems and quote your RFC."],
          ["3", "Agents debate", "They check each other's findings, and weak ones are dropped."],
          ["4", "Verdict and Q&A", "Get a score and a fix list, then ask the assistant why."]
        ].map(function (s) {
          return el("div", { class: "how-step" }, [
            el("span", { class: "how-n", text: s[0] }), el("h3", { text: s[1] }), el("p", { text: s[2] })
          ]);
        })),
        recent
      ])
    ]);

    api("/reviews?limit=5").then(function (rows) {
      if (!rows.length) return;
      recent.appendChild(el("h2", { text: "Recent reviews" }));
      recent.appendChild(reviewList(rows));
      recent.appendChild(el("p", { class: "fineprint" }, [el("a", { href: "#/history", text: "See all reviews" })]));
    }).catch(function (err) { if (err.network) setBanner(err.message); });
  }

  function reviewList(rows) {
    return el("div", { class: "list" }, rows.map(function (r) {
      var resolvedText = (r.total_findings !== undefined && r.total_findings > 0)
        ? r.resolved_findings + " of " + r.total_findings + " resolved"
        : null;

      return el("a", { class: "row", href: "#/review/" + r.id }, [
        el("div", { class: "row-main" }, [
          el("div", { class: "row-title", text: r.project_name }),
          el("div", { class: "row-sub", text: "Review " + r.id + " · " + when(r.created_at) })
        ]),
        el("div", { class: "row-end" }, [
          resolvedText ? el("span", { class: "chip chip-gray", style: "font-size:12px;", text: resolvedText }) : null,
          r.score !== null && r.score !== undefined ? el("span", { class: "row-score", text: String(r.score) }) : null,
          statusChip(r),
          el("span", { class: "chev" })
        ])
      ]);
    }));
  }

  /* ---------- history ---------- */
  function historyView(query) {
    stopPolling();
    var q = "";
    String(query || "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i > 0 && kv.slice(0, i) === "q") { try { q = decodeURIComponent(kv.slice(i + 1).replace(/\+/g, " ")); } catch (e) { q = kv.slice(i + 1); } }
    });
    var holder = el("div", {}, [el("p", { class: "empty pulse", text: "Loading\u2026" })]);
    var sub = el("p", { class: "muted" });
    render([el("div", { class: "wrap" }, [
      el("section", { class: "hero" }, [el("h1", { text: "All reviews" }), sub]),
      holder
    ])]);
    api("/reviews?limit=100").then(function (rows) {
      var shown = q ? rows.filter(function (r) { return String(r.project_name).toLowerCase().indexOf(q.toLowerCase()) >= 0; }) : rows;
      if (q) {
        sub.replaceChildren(shown.length + " result" + (shown.length === 1 ? "" : "s") + " for \u201c" + q + "\u201d. ", el("a", { href: "#/history", text: "Clear search" }));
      }
      holder.replaceChildren(shown.length
        ? reviewList(shown)
        : el("p", { class: "empty" }, [q ? "No reviews match your search." : "No reviews yet. ", el("a", { href: "#/new", text: "Start one" }), "."]));
    }).catch(function (err) {
      if (err.handled) return;
      holder.replaceChildren(el("p", { class: "empty", text: err.message }));
    });
  }

  /* ---------- review ---------- */
  var tabState = { review: null, tab: "verdict", sev: "all", agent: "all", focus: null, draft: "" };
  var chatCache = {};

  function reviewView(id) {
    stopPolling();
    if (tabState.review !== id) tabState = { review: id, tab: "verdict", sev: "all", agent: "all", focus: null, draft: "" };
    var projectCache = null;

    function load() {
      api("/reviews/" + id).then(function (review) {
        if (projectCache) return review;
        return projectName(review).then(function () { return review; });
      }).then(function (review) {
        if (review.status === "pending" || review.status === "running") {
          renderProgress(review);
          pollTimer = setTimeout(load, 3000);
        } else if (review.status === "failed") {
          renderFailed(review);
        } else {
          renderResults(review);
        }
      }).catch(function (err) {
        if (err.handled) return;
        if (err.network) {
          setBanner(err.message);
          pollTimer = setTimeout(load, 5000);
        } else {
          render([el("div", { class: "wrap" }, [
            el("section", { class: "hero" }, [
              el("h1", { text: err.status === 404 ? "Review not found" : "Something went wrong" }),
              el("p", { text: err.message })
            ]),
            el("a", { class: "btn btn-primary", href: "#/", text: "Back to start" })
          ])]);
        }
      });
    }

    function projectName(review) {
      return api("/projects/" + review.project_id).then(function (p) { projectCache = p; return p; })
        .catch(function () { return null; });
    }

    function header(review, name) {
      var rereviewBtn = (review.status === "completed" || review.status === "failed")
        ? el("button", {
            class: "btn btn-primary", type: "button", text: "Edit RFC & Re-review",
            onclick: function () { showReReviewModal(review); }
          })
        : null;

      var resText = (review.total_findings !== undefined && review.total_findings > 0)
        ? (review.resolved_findings + " of " + review.total_findings + " resolved")
        : null;

      return el("div", { class: "review-head" }, [
        el("a", { class: "back", href: "#/history", text: "‹ All reviews" }),
        el("div", { class: "head-row" }, [
          el("div", {}, [
            el("div", { style: "display:flex;align-items:center;gap:12px;flex-wrap:wrap;" }, [
              el("h1", { class: "title", text: name || ("Review " + review.id) }),
              resText ? el("span", { class: "chip chip-gray", style: "font-size:14px;padding:4px 12px;", text: resText }) : null
            ]),
            review.rfc_version_id ? el("div", { class: "rfc-ver-tag muted", text: "RFC snapshot v" + review.rfc_version_id }) : null
          ]),
          el("div", { class: "head-actions" }, [
            review.status === "completed" ? el("button", {
              class: "btn btn-quiet", type: "button", text: "Export MD",
              onclick: function () {
                window.open("/reviews/" + review.id + "/export/markdown" + (session ? "?token=" + session.token : ""), "_blank");
              }
            }) : null,
            review.status === "completed" ? el("button", {
              class: "btn btn-quiet", type: "button", text: "Export PDF",
              onclick: function () {
                window.open("/reviews/" + review.id + "/export/pdf" + (session ? "?token=" + session.token : ""), "_blank");
              }
            }) : null,
            rereviewBtn,
            el("a", { class: "btn btn-quiet", href: "#/new", text: "New project" })
          ])
        ])
      ]);
    }

    function showReReviewModal(review) {
      projectName(review).then(function (proj) {
        if (!proj) return;
        var rfcBox = el("textarea", { required: true, style: "min-height: 280px;" });
        rfcBox.value = proj.rfc_text;
        var errP = el("p", { class: "form-error" });
        var submitBtn = el("button", { class: "btn btn-primary", type: "submit", text: "Save & Start Re-review" });
        var cancelBtn = el("button", { class: "btn btn-quiet", type: "button", text: "Cancel", onclick: closeBackdrop });

        var modalForm = el("form", { class: "form" }, [
          el("h2", { text: "Edit RFC for " + proj.name }),
          el("p", { class: "muted", text: "Edit the proposal below. A new RFC version will be saved and reviewed by the agents." }),
          el("label", { class: "field" }, [el("span", { text: "RFC Content" }), rfcBox]),
          errP,
          el("div", { class: "form-actions" }, [cancelBtn, submitBtn])
        ]);

        var modal = el("div", { class: "modal-card card" }, [modalForm]);
        var backdrop = el("div", { class: "modal-backdrop" }, [modal]);

        function closeBackdrop() {
          if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
        }

        modalForm.addEventListener("submit", function (e) {
          e.preventDefault();
          errP.textContent = "";
          var text = rfcBox.value.trim();
          if (text.length < 50) {
            errP.textContent = "The RFC needs at least 50 characters.";
            return;
          }
          submitBtn.disabled = true;
          submitBtn.textContent = "Updating…";
          api("/projects/" + proj.id, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rfc_text: text })
          }).then(function () {
            submitBtn.textContent = "Starting review…";
            return api("/projects/" + proj.id + "/reviews", { method: "POST" });
          }).then(function (newRev) {
            closeBackdrop();
            location.hash = "#/review/" + newRev.id;
          }).catch(function (err) {
            errP.textContent = err.message;
            submitBtn.disabled = false;
            submitBtn.textContent = "Save & Start Re-review";
          });
        });

        document.body.appendChild(backdrop);
      });
    }

    function renderProgress(review) {
      var findings = review.findings || [];
      var debates = review.debates || [];
      var stage = 0;
      if (review.status === "running") stage = 1;
      if (findings.length && SPECIALISTS.every(function (s) { return hasAgent(findings, s); })) stage = 2;
      if (debates.length >= SPECIALISTS.length) stage = 3;
      var title = review.status === "pending" ? "Waiting to start" : ["Reading the RFC", "Specialists are analyzing", "Agents are debating", "Judge is deciding"][stage];
      var hint = review.status === "pending"
        ? "The review is queued."
        : "This usually takes a few minutes on a local model. You can leave this page open.";

      var steps = el("ol", { class: "steps" }, STEPS.map(function (s, i) {
        return el("li", { class: i < stage ? "done" : (i === stage ? "active" : ""), text: s });
      }));

      var board = el("div", { class: "board" }, SPECIALISTS.map(function (s) {
        var n = findings.filter(function (f) { return matches(f.agent_name, s); }).length;
        var d = debates.filter(function (x) { return matches(x.agent_name, s); }).length;
        var state = n === 0 ? (stage >= 1 ? "Analyzing…" : "Waiting") : n + " finding" + (n === 1 ? "" : "s");
        if (d) state += " · " + d + " debate " + (d === 1 ? "turn" : "turns");
        return el("div", { class: "tile" + (n === 0 && stage === 1 ? " active" : "") }, [
          el("div", { class: "tile-name", text: s }),
          el("div", { class: "tile-state" + (n === 0 && stage === 1 ? " pulse" : ""), text: state })
        ]);
      }));

      var cached = projectCache;
      render([el("div", { class: "wrap" }, [
        header(review, cached && cached.name),
        el("section", { class: "progress" }, [
          el("h2", { class: "stage" + (stage < 3 ? "" : ""), text: title }),
          el("p", { class: "stage-hint pulse", text: hint }),
          steps, board,
          el("p", { class: "fineprint", text: "Please don't edit files in the app folder while a review runs. The server restarts and the review is lost." })
        ])
      ])]);
    }

    function renderFailed(review) {
      projectName(review).then(function (p) {
        render([el("div", { class: "wrap" }, [
          header(review, p && p.name),
          el("div", { class: "notice" }, [
            el("h2", { text: "This review didn't finish" }),
            el("p", { class: "muted", text: review.error || "Something went wrong while the agents were working." }),
            el("p", { class: "muted", text: "Check that Ollama is running and the model is installed, then start a new review." }),
            el("a", { class: "btn btn-primary", href: "#/new", text: "Start a new review" })
          ])
        ])]);
      });
    }

    function renderResults(review) {
      projectName(review).then(function (p) {
        var content = el("div");
        var tabs = el("div", { class: "tabs" });

        function show() {
          var defs = [
            ["verdict", "Verdict"],
            ["findings", "Findings", (review.findings || []).length],
            ["ask", "Ask"]
          ];
          if (review.comparison) {
            defs.push(["comparison", "Comparison"]);
          }
          defs.push(["debate", "Debate", (review.debates || []).length]);
          defs.push(["rfc", "RFC"]);

          tabs.replaceChildren(el("div", { class: "seg", role: "tablist" }, defs.map(function (d) {
            return el("button", {
              role: "tab", type: "button", "aria-selected": String(tabState.tab === d[0]),
              onclick: function () { tabState.tab = d[0]; show(); }
            }, [d[1], d[2] !== undefined ? el("span", { class: "count", text: String(d[2]) }) : null]);
          })));
          var tabMap = {
            verdict: verdictTab,
            findings: findingsTab,
            ask: askTab,
            comparison: comparisonTab,
            debate: debateTab,
            rfc: rfcTab
          };
          var body = tabMap[tabState.tab] || verdictTab;
          content.replaceChildren(body(review, p, show));
          if (tabState.focus) {
            var target = content.querySelector('[data-finding="' + tabState.focus + '"]');
            tabState.focus = null;
            if (target) { target.open = true; target.scrollIntoView({ block: "center" }); }
          }
        }

        render([el("div", { class: "wrap" }, [header(review, p && p.name), tabs, content])]);
        show();
      });
    }

    load();
  }

  function matches(agentName, spec) {
    return String(agentName || "").toLowerCase().indexOf(spec.toLowerCase()) === 0;
  }
  function hasAgent(findings, spec) {
    return findings.some(function (f) { return matches(f.agent_name, spec); });
  }

  /* ---------- verdict tab ---------- */
  function ring(score, tone) {
    var C = 2 * Math.PI * 54;
    var bar = svg("circle", { class: "ring-bar", cx: 64, cy: 64, r: 54, "stroke-dasharray": C.toFixed(1), "stroke-dashoffset": C.toFixed(1) });
    var num = svg("text", { class: "ring-num", x: 64, y: 64, "text-anchor": "middle", "dominant-baseline": "central" });
    num.textContent = String(score);
    var s = svg("svg", { class: "ring ring-" + tone, viewBox: "0 0 128 128", role: "img", "aria-label": "Score " + score + " out of 100" });
    s.appendChild(svg("circle", { class: "ring-track", cx: 64, cy: 64, r: 54 }));
    s.appendChild(bar);
    s.appendChild(num);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { bar.setAttribute("stroke-dashoffset", (C * (1 - score / 100)).toFixed(1)); });
    });
    return s;
  }

  function listCard(title, items, ordered) {
    var list = el(ordered ? "ol" : "ul", {}, items.map(function (t) { return el("li", { text: t }); }));
    return el("div", { class: "card" }, [el("h3", { text: title }), items.length ? list : el("p", { class: "muted", text: "None listed." })]);
  }

  function verdictTab(review) {
    var rep = review.report;
    if (!rep) return el("p", { class: "empty", text: "No verdict was saved for this review." });
    var d = decisionInfo(rep.decision);
    var summary = rep.summary || "";
    var note = null;
    var m = summary.match(/\s*\[Adjusted by review rules:[^\]]*\]\s*$/);
    if (m) { note = m[0].trim().replace(/^\[|\]$/g, ""); summary = summary.slice(0, m.index); }

    var counts = {};
    (review.findings || []).forEach(function (f) { counts[f.severity] = (counts[f.severity] || 0) + 1; });
    var sev = SEVERITIES.filter(function (s) { return counts[s]; }).map(function (s) {
      return chip(counts[s] + " " + s, sevTone(s));
    });

    var all = review.findings || [];
    var resolved = all.filter(function (f) { return ["accepted", "rejected", "fixed"].indexOf(f.status) >= 0; }).length;
    var bar = el("div", { class: "distbar", role: "img", "aria-label": "Findings by severity" }, SEVERITIES.filter(function (s) { return counts[s]; }).map(function (s) {
      return el("span", { class: "dist dist-" + sevTone(s), style: "flex:" + counts[s], title: counts[s] + " " + s });
    }));
    var tiles = el("div", { class: "tiles" }, [
      ["Score", rep.score + "/100"], ["Findings", String(all.length)],
      ["Critical + high", String((counts.critical || 0) + (counts.high || 0))],
      ["Resolved", resolved + "/" + all.length]
    ].map(function (x) {
      return el("div", { class: "stat" }, [el("div", { class: "stat-val", text: x[1] }), el("div", { class: "stat-label", text: x[0] })]);
    }));

    return el("div", {}, [
      el("div", { class: "card verdict" }, [
        ring(rep.score, d.tone),
        el("div", { class: "verdict-text" }, [
          el("h2", { class: "decision tone-" + d.tone, text: d.label }),
          el("p", { class: "verdict-line", text: d.line }),
          el("p", { class: "summary", text: summary }),
          note ? el("p", { class: "rule-note", text: note }) : null,
          sev.length ? el("div", { class: "sev-row" }, sev) : null
        ])
      ]),
      tiles,
      all.length ? el("div", { class: "card dist-card" }, [el("div", { class: "f-label", text: "Findings by severity" }), bar]) : null,
      el("div", { class: "cols" }, [
        listCard("Key risks", rep.key_risks || [], false),
        listCard("What to do", rep.recommendations || [], true)
      ])
    ]);
  }

  /* ---------- comparison tab ---------- */
  function comparisonTab(review) {
    var comp = review.comparison;
    if (!comp) return el("p", { class: "empty", text: "No previous review available to compare." });

    var diffText = "Score unchanged";
    var diffClass = "chip-gray";
    if (comp.score_diff !== null && comp.score_diff !== undefined) {
      if (comp.score_diff > 0) {
        diffText = "+" + comp.score_diff + " points";
        diffClass = "chip-green";
      } else if (comp.score_diff < 0) {
        diffText = comp.score_diff + " points";
        diffClass = "chip-red";
      }
    }

    var counts = comp.counts || { fixed: 0, still_open: 0, new: 0 };
    var statsCard = el("div", { class: "card comp-summary" }, [
      el("div", { class: "comp-stats-row" }, [
        el("div", { class: "comp-stat" }, [
          el("div", { class: "comp-stat-val", text: String(comp.previous_score !== null ? comp.previous_score : "--") }),
          el("div", { class: "muted", text: "Previous score" })
        ]),
        el("div", { class: "comp-arrow", text: "→" }),
        el("div", { class: "comp-stat" }, [
          el("div", { class: "comp-stat-val", text: String(comp.current_score !== null ? comp.current_score : "--") }),
          el("div", { class: "muted", text: "Current score" })
        ]),
        el("div", { class: "chip " + diffClass, style: "font-size:16px;padding:6px 14px;align-self:center;", text: diffText })
      ]),
      el("div", { class: "comp-badge-row" }, [
        el("span", { class: "chip chip-green", text: counts.fixed + " Fixed" }),
        el("span", { class: "chip chip-orange", text: counts.still_open + " Still open" }),
        el("span", { class: "chip chip-blue", text: counts.new + " New" })
      ])
    ]);

    var groups = [
      { key: "fixed", title: "Fixed issues", tone: "chip-green", desc: "Issues from the previous review that are no longer reported." },
      { key: "still_open", title: "Still open", tone: "chip-orange", desc: "Issues that were present in the previous review and remain unresolved." },
      { key: "new", title: "New findings", tone: "chip-blue", desc: "New issues identified in this revision." }
    ];

    var sections = [statsCard];
    groups.forEach(function (g) {
      var items = (comp.matches || []).filter(function (m) { return m.status === g.key; });
      if (!items.length) return;

      var rows = items.map(function (item) {
        var f = item.finding;
        return el("details", { class: "finding" }, [
          el("summary", {}, [
            el("span", { class: "dot dot-" + sevTone(f.severity) }),
            el("span", { class: "f-title", text: f.title }),
            el("span", { class: "chip " + g.tone, style: "margin-right:8px;", text: pretty(g.key) }),
            el("span", { class: "f-agent", text: agentShort(f.agent_name) + (f.category ? " · " + f.category : "") }),
            el("span", { class: "chev" })
          ]),
          el("div", { class: "f-body" }, [
            el("div", {}, [el("div", { class: "f-label", text: "Problem" }), el("p", { text: f.description })]),
            el("div", {}, [el("div", { class: "f-label", text: "Recommendation" }), el("p", { text: f.recommendation })])
          ])
        ]);
      });

      sections.push(el("div", { class: "comp-group-section" }, [
        el("div", { class: "sev-head" }, [
          el("h3", { text: g.title }),
          el("span", { class: "muted", text: String(items.length) })
        ]),
        el("p", { class: "muted", style: "font-size:14px;margin-bottom:10px;", text: g.desc }),
        el("div", { class: "list" }, rows)
      ]));
    });

    return el("div", {}, sections);
  }

  /* ---------- findings tab ---------- */
  function findingsTab(review, p, redraw) {
    var findings = review.findings || [];
    if (!findings.length) return el("p", { class: "empty", text: "The agents didn't report any findings." });

    var agents = [];
    findings.forEach(function (f) { if (agents.indexOf(f.agent_name) < 0) agents.push(f.agent_name); });

    var sevSeg = el("div", { class: "seg" }, ["all"].concat(SEVERITIES).map(function (s) {
      return el("button", {
        type: "button", "aria-pressed": String(tabState.sev === s), text: s === "all" ? "All" : pretty(s),
        onclick: function () { tabState.sev = s; redraw(); }
      });
    }));
    var agentSel = el("select", { "aria-label": "Filter by agent", onchange: function (e) { tabState.agent = e.target.value; redraw(); } },
      [el("option", { value: "all", text: "All agents" })].concat(agents.map(function (a) {
        return el("option", { value: a, text: agentShort(a), selected: tabState.agent === a });
      })));
    agentSel.value = tabState.agent;

    var wrap = el("div", {}, [el("div", { class: "controls" }, [sevSeg, agentSel])]);
    var shown = 0;
    SEVERITIES.forEach(function (sev) {
      if (tabState.sev !== "all" && tabState.sev !== sev) return;
      var group = findings.filter(function (f) {
        return f.severity === sev && (tabState.agent === "all" || f.agent_name === tabState.agent);
      });
      if (!group.length) return;
      shown += group.length;
      wrap.appendChild(el("div", { class: "sev-head" }, [
        el("span", { class: "dot dot-" + sevTone(sev) }),
        el("h3", { text: pretty(sev) }),
        el("span", { class: "muted", text: String(group.length) })
      ]));
      wrap.appendChild(el("div", { class: "list" }, group.map(function (f) {
      return findingRow(f, review, redraw);
    })));
    });
    if (!shown) wrap.appendChild(el("p", { class: "empty", text: "No findings match these filters." }));
    return wrap;
  }

  function statusTone(status) {
    return { open: "blue", accepted: "green", rejected: "red", fixed: "gray" }[status] || "blue";
  }

  function findingRow(f, review, redraw) {
    var statusBadge = chip(pretty(f.status || "open"), statusTone(f.status || "open"));
    var reasonNote = f.status_reason
      ? el("div", { class: "status-reason-box" }, [
          el("div", { class: "f-label", text: "Rejection reason" }),
          el("p", { text: f.status_reason })
        ])
      : null;

    var actions = el("div", { class: "f-status-actions" }, [
      el("span", { class: "f-label", style: "align-self:center;margin:0;", text: "Change status:" }),
      ["open", "accepted", "rejected", "fixed"].map(function (st) {
        if (st === (f.status || "open")) return null;
        return el("button", {
          class: "link-btn", type: "button",
          style: "font-size:13px;padding:3px 8px;border-radius:6px;background:var(--track);",
          text: pretty(st),
          onclick: function (e) {
            e.preventDefault();
            e.stopPropagation();
            changeFindingStatus(review.id, f, st, redraw);
          }
        });
      })
    ]);

    var commentsWrap = el("div", { class: "f-comments-section" });
    function renderComments() {
      var commList = (f.comments || []).map(function (c) {
        return el("div", { class: "comment-item" }, [
          el("div", { class: "comment-head" }, [
            el("span", { class: "comment-author", text: c.user_name || "Member" }),
            el("span", { class: "comment-time muted", text: when(c.created_at) })
          ]),
          el("p", { class: "comment-body", text: c.comment })
        ]);
      });

      var commInput = el("input", { type: "text", placeholder: "Add a comment on this finding…", style: "font-size:14px;padding:8px 12px;" });
      var commBtn = el("button", { class: "btn btn-quiet", type: "button", style: "font-size:14px;padding:6px 14px;", text: "Post" });
      var commForm = el("form", { style: "display:flex;gap:8px;margin-top:10px;" }, [commInput, commBtn]);

      commForm.addEventListener("submit", function (e) {
        e.preventDefault();
        var val = commInput.value.trim();
        if (!val) return;
        commBtn.disabled = true;
        api("/reviews/" + review.id + "/findings/" + f.id + "/comments", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: val })
        }).then(function (newComm) {
          f.comments = (f.comments || []).concat([newComm]);
          renderComments();
        }).catch(function (err) {
          alert("Could not post comment: " + err.message);
          commBtn.disabled = false;
        });
      });

      commentsWrap.replaceChildren(
        el("div", { class: "f-label", style: "margin-top:10px;", text: "Team comments (" + (f.comments || []).length + ")" }),
        commList.length ? el("div", { class: "comments-list" }, commList) : el("p", { class: "muted", style: "font-size:13px;", text: "No comments yet." }),
        commForm
      );
    }
    renderComments();

    return el("details", { class: "finding sev-" + sevTone(f.severity), "data-finding": String(f.id) }, [
      el("summary", {}, [
        el("span", { class: "dot dot-" + sevTone(f.severity) }),
        el("span", { class: "f-title", text: f.title }),
        statusBadge,
        el("span", { class: "f-agent" }, [el("i", { class: "agent-dot", style: "background:" + agentColor(f.agent_name) }), agentShort(f.agent_name) + (f.category ? " · " + f.category : "")]),
        el("span", { class: "chev" })
      ]),
      el("div", { class: "f-body" }, [
        f.quote ? el("div", { class: "f-quote-box" }, [
          el("span", { class: "f-quote-tag", text: "Quoted RFC Passage" }),
          el("blockquote", { class: "f-quote-text", text: "“" + f.quote + "”" })
        ]) : null,
        el("div", {}, [el("div", { class: "f-label", text: "Problem" }), el("p", { text: f.description })]),
        el("div", {}, [el("div", { class: "f-label", text: "Suggested fix" }), el("p", { text: f.recommendation })]),
        f.tradeoffs ? el("div", {}, [el("div", { class: "f-label", text: "Trade-offs" }), el("p", { text: f.tradeoffs })]) : null,
        reasonNote,
        el("div", {}, [el("button", {
          class: "link-btn", type: "button", text: "Ask the assistant about this finding",
          onclick: function () {
            tabState.tab = "ask";
            tabState.draft = "Explain this finding in simple words and tell me how to fix it: " + f.title;
            redraw();
          }
        })]),
        actions,
        commentsWrap
      ])
    ]);
  }

  function changeFindingStatus(reviewId, finding, newStatus, redraw) {
    if (newStatus === "rejected") {
      var reason = prompt("Enter a reason for rejecting this finding (required):");
      if (reason === null) return; // user cancelled
      reason = reason.trim();
      if (!reason) {
        alert("A reason is required to reject a finding.");
        return;
      }
      sendUpdate(reason);
    } else {
      sendUpdate(null);
    }

    function sendUpdate(reason) {
      api("/reviews/" + reviewId + "/findings/" + finding.id, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus, reason: reason })
      }).then(function (updated) {
        finding.status = updated.status;
        finding.status_reason = updated.status_reason;
        if (redraw) redraw();
      }).catch(function (err) {
        alert("Could not update finding status: " + err.message);
      });
    }
  }


  /* ---------- ask the assistant about a review ---------- */
  var STARTERS = [
    "What should I fix first?",
    "Why did the review reach this verdict?",
    "Which findings could I safely postpone?",
    "Where did the agents disagree?",
    "Give me a short action plan for my team"
  ];

  function chatInline(text, byId, redraw) {
    var out = [];
    String(text).split(/(\*\*[^*\n]+\*\*|\[#\d+\])/).forEach(function (part) {
      if (!part) return;
      var m = /^\[#(\d+)\]$/.exec(part);
      if (m) {
        var f = byId[m[1]];
        if (!f) return;
        var label = f.title.length > 42 ? f.title.slice(0, 41) + "…" : f.title;
        out.push(el("button", {
          class: "cite", type: "button", title: "Open this finding", text: label,
          onclick: function () {
            tabState.tab = "findings"; tabState.sev = "all"; tabState.agent = "all"; tabState.focus = f.id;
            redraw();
          }
        }));
      } else if (/^\*\*.+\*\*$/.test(part)) {
        out.push(el("strong", { text: part.slice(2, -2) }));
      } else {
        out.push(part);
      }
    });
    return out;
  }

  function chatRich(text, byId, redraw) {
    var nodes = [];
    text = String(text).replace(/\[\[\s*propose[^\]]*(\]\]?)?/gi, "");
    text = text.replace(/[【［]\s*#(\d+)\s*[】］]/g, "[#$1]").replace(/(\[#\d+\])(\s*\1)+/g, "$1");
    String(text).split(/\n{2,}/).forEach(function (block) {
      var list = null, para = [];
      function flush() {
        if (para.length) { nodes.push(el("p", {}, chatInline(para.join(" "), byId, redraw))); para = []; }
      }
      block.split("\n").filter(function (l) { return l.trim(); }).forEach(function (line) {
        var li = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(line);
        if (li) {
          flush();
          if (!list) { list = el("ul", {}); nodes.push(list); }
          list.appendChild(el("li", {}, chatInline(li[1], byId, redraw)));
        } else { list = null; para.push(line.trim()); }
      });
      flush();
    });
    return nodes;
  }

  function askTab(review, p, redraw) {
    var id = review.id;
    var byId = {};
    (review.findings || []).forEach(function (f) { byId[f.id] = f; });
    var busy = false;
    var thread = el("div", { class: "chat-thread", "aria-live": "polite" });
    var errP = el("p", { class: "form-error", role: "alert" });
    var box = el("textarea", {
      class: "chat-input", rows: "2", maxlength: "1500",
      placeholder: "Ask anything about this review…", "aria-label": "Your question"
    });
    var send = el("button", { class: "btn btn-primary", type: "submit", text: "Ask" });
    var form = el("form", { class: "chat-form" }, [box, send]);

    function chatActions(m) {
      var open = (m.actions || []).filter(function (a) { return byId[a.finding_id] && byId[a.finding_id].status !== a.status; });
      if (!open.length) return null;
      return el("div", { class: "proposals" }, open.map(function (a) {
        var f = byId[a.finding_id];
        var btn = el("button", { class: "btn btn-primary btn-sm", type: "button", text: "Apply" });
        btn.addEventListener("click", function () {
          var reason = a.reason;
          if (a.status === "rejected" && !reason) {
            reason = (prompt("A reason is required to reject this finding:") || "").trim();
            if (!reason) return;
          }
          btn.disabled = true; errP.textContent = "";
          api("/reviews/" + id + "/findings/" + f.id, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: a.status, reason: reason || null })
          }).then(function (updated) {
            f.status = updated.status; f.status_reason = updated.status_reason;
            renderThread();
          }).catch(function (err) {
            btn.disabled = false;
            if (!err.handled) errP.textContent = err.status === 403 ? "Your role can't change finding statuses." : err.message;
          });
        });
        return el("div", { class: "proposal" }, [
          el("div", { class: "proposal-text" }, [
            el("span", { class: "f-label", text: "Suggested change" }),
            el("div", {}, ["Mark ", el("strong", { text: f.title }), " as ", chip(pretty(a.status), statusTone(a.status))]),
            a.reason ? el("div", { class: "muted", text: "Reason: " + a.reason }) : null
          ]),
          btn
        ]);
      }));
    }

    function renderThread() {
      var msgs = chatCache[id];
      var nodes = [];
      if (!msgs) {
        nodes.push(el("p", { class: "muted pulse", text: "Loading…" }));
      } else if (!msgs.length && !busy) {
        nodes.push(el("p", { class: "chat-intro", text:
          "Ask about the findings, the verdict, the debate or the RFC. Answers come from this review only, so check anything important yourself." }));
        nodes.push(el("div", { class: "starters" }, STARTERS.map(function (s) {
          return el("button", { class: "starter", type: "button", text: s, onclick: function () { submit(s); } });
        })));
      }
      (msgs || []).forEach(function (m) {
        nodes.push(m.role === "user"
          ? el("div", { class: "bubble bubble-me" }, [el("p", { text: m.content })])
          : el("div", { class: "bot-row" }, [el("span", { class: "bot-avatar sm", "aria-hidden": "true", text: "✦" }),
              el("div", { class: "bot-stack" }, [
                el("div", { class: "bubble bubble-bot" }, chatRich(m.content, byId, redraw)),
                chatActions(m)
              ])]));
      });
      if (busy) nodes.push(el("div", { class: "bot-row" }, [el("span", { class: "bot-avatar sm", "aria-hidden": "true", text: "✦" }),
        el("div", { class: "bubble bubble-bot" }, [el("span", { class: "typing", "aria-label": "Reading the review" }, [el("i"), el("i"), el("i")])])]));
      if (msgs && msgs.length && !busy) {
        nodes.push(el("button", {
          class: "link-btn chat-clear", type: "button", text: "Clear conversation",
          onclick: function () {
            if (!confirm("Delete this conversation?")) return;
            api("/reviews/" + id + "/chat", { method: "DELETE" }).then(function () {
              chatCache[id] = []; renderThread();
            }).catch(function (err) { if (!err.handled) errP.textContent = err.message; });
          }
        }));
      }
      thread.replaceChildren.apply(thread, nodes);
    }

    var frame = false;
    function scheduleRender() {
      if (frame) return;
      frame = true;
      requestAnimationFrame(function () { frame = false; renderThread(); form.scrollIntoView({ block: "nearest" }); });
    }

    function submit(question) {
      var q = String(question || "").trim();
      if (!q || busy || !chatCache[id]) return;
      busy = true; send.disabled = true; errP.textContent = ""; box.value = "";
      var list = chatCache[id];
      list.push({ role: "user", content: q });
      var live = null;
      renderThread();
      form.scrollIntoView({ block: "nearest" });
      streamPost("/reviews/" + id + "/chat/stream", { message: q }, function (ev) {
        if (ev.type !== "delta") return;
        if (!live) { live = { role: "assistant", content: "" }; list.push(live); }
        live.content += ev.text;
        scheduleRender();
      }).then(function (done) {
        if (!done) throw new Error("The answer was cut off. Please ask again.");
        if (live && list.indexOf(live) >= 0) list.splice(list.indexOf(live), 1);
        list.pop(); // the temporary question
        list.push(done.question, done.answer);
      }).catch(function (err) {
        if (live && list.indexOf(live) >= 0) list.splice(list.indexOf(live), 1);
        list.pop();
        if (!err.handled) { errP.textContent = err.message; box.value = q; }
      }).then(function () {
        busy = false; send.disabled = false; renderThread();
        form.scrollIntoView({ block: "nearest" });
      });
    }

    form.addEventListener("submit", function (e) { e.preventDefault(); submit(box.value); });
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submit(box.value); }
    });

    if (tabState.draft) { box.value = tabState.draft; tabState.draft = ""; setTimeout(function () { box.focus(); }, 0); }
    renderThread();
    if (!chatCache[id]) {
      api("/reviews/" + id + "/chat").then(function (rows) { chatCache[id] = rows; renderThread(); })
        .catch(function (err) { if (!err.handled) { chatCache[id] = []; errP.textContent = err.message; renderThread(); } });
    }
    return el("div", { class: "chat card" }, [
      el("div", { class: "chat-head" }, [
        el("span", { class: "bot-avatar", "aria-hidden": "true", text: "✦" }),
        el("div", {}, [el("div", { class: "chat-title", text: "Review assistant" }), el("div", { class: "chat-sub", text: "Answers from this review's findings, debate and RFC" })])
      ]),
      thread, errP, form
    ]);
  }

  /* ---------- workspace management ---------- */
  function workspaceView() {
    stopPolling();
    var holder = el("div", {}, [el("p", { class: "empty pulse", text: "Loading workspace…" })]);
    render([el("div", { class: "wrap" }, [
      el("section", { class: "hero" }, [
        el("h1", { text: "Company Workspace" }),
        el("p", { text: "Manage organization members and permissions (Owner, Reviewer, Viewer)." })
      ]),
      holder
    ])]);

    api("/organizations/me").then(function (orgs) {
      if (!orgs.length) {
        holder.replaceChildren(el("p", { class: "empty", text: "No workspace found." }));
        return;
      }
      var org = orgs[0];
      loadOrgMembers(org);
    }).catch(function (err) {
      holder.replaceChildren(el("p", { class: "empty", text: err.message }));
    });

    function loadOrgMembers(org) {
      api("/organizations/" + org.id + "/members").then(function (members) {
        var emailInput = el("input", { type: "email", placeholder: "colleague@company.com", required: true });
        var roleSelect = el("select", {}, [
          el("option", { value: "reviewer", text: "Reviewer (can edit RFCs & reviews)" }),
          el("option", { value: "viewer", text: "Viewer (read only, comments)" })
        ]);
        var inviteErr = el("p", { class: "form-error" });
        var inviteBtn = el("button", { class: "btn btn-primary", type: "submit", text: "Invite member" });

        var inviteForm = el("form", { class: "form card", style: "margin-bottom:28px;" }, [
          el("h3", { text: "Invite team member to " + org.name }),
          el("label", { class: "field" }, [el("span", { text: "Email address" }), emailInput]),
          el("label", { class: "field" }, [el("span", { text: "Role" }), roleSelect]),
          inviteErr,
          el("div", { class: "form-actions" }, [inviteBtn])
        ]);

        inviteForm.addEventListener("submit", function (e) {
          e.preventDefault();
          inviteErr.textContent = "";
          var em = emailInput.value.trim();
          if (!em) return;
          inviteBtn.disabled = true;
          inviteBtn.textContent = "Inviting…";

          api("/organizations/" + org.id + "/invites", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: em, role: roleSelect.value })
          }).then(function () {
            emailInput.value = "";
            inviteBtn.disabled = false;
            inviteBtn.textContent = "Invite member";
            loadOrgMembers(org);
          }).catch(function (err) {
            inviteErr.textContent = err.message;
            inviteBtn.disabled = false;
            inviteBtn.textContent = "Invite member";
          });
        });

        var memberRows = members.map(function (m) {
          return el("div", { class: "row" }, [
            el("div", { class: "row-main" }, [
              el("div", { class: "row-title", text: m.user_name }),
              el("div", { class: "row-sub", text: m.user_email })
            ]),
            el("div", { class: "row-end" }, [
              chip(pretty(m.role), m.role === "owner" ? "blue" : (m.role === "reviewer" ? "green" : "gray"))
            ])
          ]);
        });

        holder.replaceChildren(
          inviteForm,
          el("div", { class: "section" }, [
            el("h2", { text: "Current members (" + members.length + ")" }),
            el("div", { class: "list" }, memberRows)
          ])
        );
      });
    }
  }

  /* ---------- debate tab ---------- */
  function debateTab(review) {
    var debates = review.debates || [];
    if (!debates.length) return el("p", { class: "empty", text: "No debate took place for this review." });
    var wrap = el("div");
    var rounds = [];
    debates.forEach(function (d) { if (rounds.indexOf(d.round) < 0) rounds.push(d.round); });
    rounds.sort(function (a, b) { return a - b; });
    rounds.forEach(function (r) {
      if (rounds.length > 1) wrap.appendChild(el("div", { class: "round", text: "Round " + r }));
      wrap.appendChild(el("div", { class: "list", style: rounds.length > 1 ? null : "" }, debates.filter(function (d) { return d.round === r; }).map(function (d) {
        var tone = { agree: "green", disagree: "red", refine: "blue" }[d.stance] || "gray";
        return el("div", { class: "msg" }, [
          el("div", { class: "avatar", "aria-hidden": "true", style: "background:" + agentColor(d.agent_name), text: agentShort(d.agent_name).charAt(0).toUpperCase() }),
          el("div", {}, [
            el("div", { class: "msg-head" }, [
              el("span", { text: agentShort(d.agent_name) }),
              d.target_agent_name ? el("span", { class: "muted", text: "to " + agentShort(d.target_agent_name) }) : null,
              chip(pretty(d.stance), tone)
            ]),
            el("p", { text: d.message })
          ])
        ]);
      })));
    });
    return wrap;
  }

  /* ---------- RFC tab ---------- */
  function rfcTab(review, p) {
    var secs = review.parsed_sections && review.parsed_sections.sections ? review.parsed_sections.sections : null;
    var keys = secs ? Object.keys(secs).filter(function (k) { return secs[k]; }) : [];
    var wrap = el("div");
    if (keys.length) {
      wrap.appendChild(el("div", { class: "list" }, keys.map(function (k) {
        return el("div", { class: "rfc-sec" }, [el("h3", { text: pretty(k) }), el("pre", { text: String(secs[k]) })]);
      })));
    } else if (p && p.rfc_text) {
      wrap.appendChild(el("div", { class: "callout", text: "The parser didn't find standard sections, so this is the full text." }));
      wrap.appendChild(el("div", { class: "card" }, [el("pre", { class: "muted", style: "margin:0;white-space:pre-wrap", text: p.rfc_text })]));
    } else {
      wrap.appendChild(el("p", { class: "empty", text: "The RFC text isn't available." }));
    }
    return wrap;
  }

  /* ---------- router ---------- */
  function route() {
    var raw = location.hash.replace(/^#/, "") || "/";
    var qi = raw.indexOf("?");
    var h = qi < 0 ? raw : raw.slice(0, qi);
    var query = qi < 0 ? "" : raw.slice(qi + 1);
    var m = h.match(/^\/review\/(\d+)$/);
    window.scrollTo(0, 0);
    setDrawer(false);
    var isAuthPage = h === "/login" || h === "/register";
    if (!session && !isAuthPage) { location.hash = "#/login"; return; }
    if (session && isAuthPage) { location.hash = "#/"; return; }
    var q = "";
    if (h === "/history") query.split("&").forEach(function (kv) { if (kv.indexOf("q=") === 0) { try { q = decodeURIComponent(kv.slice(2).replace(/\+/g, " ")); } catch (e) { q = kv.slice(2); } } });
    renderUserBox(h, q);
    if (h === "/login") authView("login");
    else if (h === "/register") authView("register");
    else if (m) reviewView(parseInt(m[1], 10));
    else if (h === "/history") historyView(query);
    else if (h === "/workspace") workspaceView();
    else if (h === "/new") newReviewView();
    else dashboardView();
    app.focus({ preventScroll: true });
  }

  renderUserBox();
  window.addEventListener("hashchange", route);
  route();
})();
