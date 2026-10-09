(() => {
  "use strict";

  // When opened from the Python server (port 5000) use relative URLs,
  // otherwise (e.g. VS Code Live Server) talk to the Python server on localhost:5000.
  const API_BASE = location.port === "5000" ? "" : "http://localhost:5000";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const state = { lang: null, shift: false, keyboardOn: false };

  /* ================= Live clock ================= */
  const pad = (n) => String(n).padStart(2, "0");
  function tick() {
    const d = new Date();
    let h = d.getHours();
    const ap = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    $("#clock").textContent =
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(h)}:${pad(d.getMinutes())}:${pad(d.getSeconds())} ${ap}`;
  }
  setInterval(tick, 1000);
  tick();

  /* ================= Navigation ================= */
  function showPage(name) {
    const menuItem = name;                              // the sidebar button that was pressed
    if (FND.guest && (name === "history" || name === "analytics")) name = "locked";
    $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
    $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.page === menuItem));
    if (name === "history") loadHistory();
    if (name === "analytics") loadAnalytics();
    if (name === "settings" && !FND.guest) loadMongo();   // guests never see the MongoDB section
  }
  $$(".nav-btn").forEach((b) => b.addEventListener("click", () => showPage(b.dataset.page)));

  /* ================= On-screen keyboards ================= */
  const EN_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm,.?"].map((r) => [...r]);
  const EN_SHIFT = [[..."!@#$%^&*()"], ...EN_ROWS.slice(1).map((r) => r.map((c) => (/[a-z]/.test(c) ? c.toUpperCase() : c)))];
  const UR_BASE = [
    [..."۱۲۳۴۵۶۷۸۹۰"],
    ["ق", "و", "ع", "ر", "ت", "ے", "ء", "ی", "ہ", "پ"],
    ["ا", "س", "د", "ف", "گ", "ھ", "ج", "ک", "ل", "ں"],
    ["ز", "ش", "چ", "ط", "ب", "ن", "م", "،", "۔", "؟"],
  ];
  const UR_SHIFT = [
    ["!", "٪", "(", ")", "-", ":", "؛", "\"", "'", "/"],
    ["ٹ", "ؤ", "غ", "ڑ", "ث", "ۓ", "ئ", "ۃ", "ۂ", "؟"],
    ["آ", "ص", "ڈ", "ف", "گ", "ح", "ض", "خ", "ذ", "ظ"],
    ["ژ", "ش", "چ", "ء", "ب", "ن", "م", "۔", "،", "؛"],
  ];
  const LAYOUTS = {
    english: { base: EN_ROWS, shift: EN_SHIFT, title: "English keyboard" },
    urdu: { base: UR_BASE, shift: UR_SHIFT, title: "Urdu keyboard (اردو)" },
  };

  function makeKey(label, action, cls = "key") {
    const b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    b.textContent = label;
    b.dataset.action = action;
    return b;
  }

  function renderKeyboard() {
    const L = LAYOUTS[state.lang];
    const holder = $("#keys");
    holder.textContent = "";
    (state.shift ? L.shift : L.base).forEach((row) => {
      const div = document.createElement("div");
      div.className = "key-row";
      row.forEach((ch) => div.appendChild(makeKey(ch, "char:" + ch)));
      holder.appendChild(div);
    });
    const last = document.createElement("div");
    last.className = "key-row";
    last.append(
      makeKey("Shift", "shift", "key wide" + (state.shift ? " on" : "")),
      makeKey("Space", "space", "key space"),
      makeKey("\u232B", "back", "key wide"),
      makeKey("Enter", "enter", "key wide"),
      makeKey("Clear", "clear", "key wide")
    );
    holder.appendChild(last);
    $("#kbTitle").textContent = L.title;
  }

  function setKeyboardVisible(on) {
    state.keyboardOn = on && !!state.lang;
    $("#keyboard").classList.toggle("hidden", !state.keyboardOn);
  }

  const box = () => $("#newsText");

  function insert(str) {
    const t = box();
    t.setRangeText(str, t.selectionStart, t.selectionEnd, "end");
    t.focus();
    updateButtons();
  }
  function backspace() {
    const t = box();
    const s = t.selectionStart, e = t.selectionEnd;
    if (s !== e) t.setRangeText("", s, e, "end");
    else if (s > 0) t.setRangeText("", s - 1, s, "end");
    t.focus();
    updateButtons();
  }

  $("#keys").addEventListener("mousedown", (e) => e.preventDefault()); // keep caret in the text box
  $("#keys").addEventListener("click", (e) => {
    const key = e.target.closest("button");
    if (!key) return;
    const a = key.dataset.action;
    if (a.startsWith("char:")) insert(a.slice(5));
    else if (a === "space") insert(" ");
    else if (a === "enter") insert("\n");
    else if (a === "back") backspace();
    else if (a === "clear") { box().value = ""; updateButtons(); box().focus(); }
    else if (a === "shift") { state.shift = !state.shift; renderKeyboard(); }
  });
  $("#kbHide").addEventListener("click", () => setKeyboardVisible(false));
  $("#kbToggle").addEventListener("click", () => setKeyboardVisible(!state.keyboardOn));

  /* ================= Language selection ================= */
  function setLanguage(lang) {
    state.lang = lang;
    state.shift = false;
    $$(".lang-btn").forEach((b) => {
      const on = b.dataset.lang === lang;
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on);
    });
    const t = box();
    t.disabled = false;
    t.classList.toggle("urdu", lang === "urdu");
    t.dir = lang === "urdu" ? "rtl" : "ltr";
    t.lang = lang === "urdu" ? "ur" : "en";
    t.placeholder = lang === "urdu" ? "یہاں خبر لکھیں یا پیسٹ کریں..." : "Type or paste the news here...";
    $("#kbToggle").disabled = false;
    renderKeyboard();
    setKeyboardVisible(true);
    hideError();
    updateButtons();
    t.focus();
  }
  $$(".lang-btn").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));
  box().addEventListener("input", updateButtons);

  function updateButtons() {
    $("#predictBtn").disabled = !(state.lang && box().value.trim());
  }

  /* ================= Prediction ================= */
  function showError(msg) {
    const e = $("#error");
    e.textContent = msg;
    e.classList.remove("hidden");
  }
  function hideError() { $("#error").classList.add("hidden"); }

  function showResult(data) {
    const isTrue = data.label === "REAL";
    const pct = (Number(data.score) * 100).toFixed(2);
    const r = $("#result");
    r.classList.remove("hidden", "true", "false");
    r.classList.add(isTrue ? "true" : "false");
    $("#resultLabel").textContent = isTrue ? "TRUE" : "FALSE";
    $("#resultScore").textContent = pct + "%";
    $("#scoreBar").style.width = "0";
    requestAnimationFrame(() => ($("#scoreBar").style.width = pct + "%"));
  }

  async function predict() {
    hideError();
    const text = box().value.trim();
    if (!state.lang) return showError("Please select a language first.");
    if (!text) return showError("Please type or paste the news text.");

    const btn = $("#predictBtn");
    btn.disabled = true;
    btn.textContent = "Predicting...";
    $("#result").classList.add("hidden");
    try {
      const res = await fetch(API_BASE + "/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...FND.authHeaders() },
        body: JSON.stringify({ text, language: state.lang }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 401) return FND.sessionExpired();
      if (!res.ok) throw new Error(data.error || "Prediction failed.");
      showResult(data);
      if (data.history_saved === false) showError("Result shown, but history.csv could not be saved. Close it if it is open in Excel.");
    } catch (err) {
      showError(err instanceof TypeError
        ? "Cannot reach the prediction server. Start it with:  python api.py"
        : err.message);
    } finally {
      btn.textContent = "Predict News";
      updateButtons();
    }
  }
  $("#predictBtn").addEventListener("click", predict);
  $("#clearBtn").addEventListener("click", () => {
    box().value = "";
    $("#result").classList.add("hidden");
    hideError();
    updateButtons();
    if (state.lang) box().focus();
  });

  /* ================= Time-range buttons ================= */
  const ranges = { history: "all", analytics: "7" };
  function syncRange(row) {
    $$(".range-btn", row).forEach((b) => {
      const on = b.dataset.range === ranges[row.dataset.group];
      b.classList.toggle("active", on);
      b.setAttribute("aria-pressed", on);
    });
  }
  $$(".range-row").forEach((row) => {
    syncRange(row);
    row.addEventListener("click", (e) => {
      const b = e.target.closest(".range-btn");
      if (!b) return;
      ranges[row.dataset.group] = b.dataset.range;
      syncRange(row);
      if (row.dataset.group === "history") loadHistory(); else loadAnalytics();
    });
  });

  /* ================= History ================= */
  const TRASH_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg>';
  const SERVER_MSG = "Cannot reach the server. Start it with:  python api.py";

  async function fetchJson(url, failMsg) {
    const res = await fetch(API_BASE + url, { headers: FND.authHeaders() });
    if (res.status === 401) { FND.sessionExpired(); throw new Error("Please sign in again."); }
    if (!res.ok) throw new Error(failMsg);
    return res.json();
  }
  const labelPill = (label) => {
    const s = document.createElement("span");
    const t = label === "REAL";
    s.className = "pill " + (t ? "true" : "false");
    s.textContent = t ? "TRUE" : "FALSE";
    return s;
  };
  const percent = (v) => (Number(v) * 100).toFixed(2) + "%";
  const langName = (l) => (l === "urdu" ? "Urdu" : l === "english" ? "English" : "\u2014");

  function messageRow(body, text) {
    body.textContent = "";
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 6;
    td.className = "empty";
    td.textContent = text;
    tr.appendChild(td);
    body.appendChild(tr);
  }

  async function loadHistory() {
    const body = $("#historyBody");
    messageRow(body, "Loading...");
    try {
      const rows = await fetchJson("/api/history?range=" + ranges.history, "Could not load history.");
      if (!rows.length) return messageRow(body, "No records for this period.");
      body.textContent = "";
      rows.forEach((r) => {
        const tr = document.createElement("tr");
        const fact = document.createElement("td");
        fact.className = "fact";
        fact.dir = "auto";
        fact.textContent = r.text;                       // textContent: user text is never run as HTML
        const lang = document.createElement("td");
        const lp = document.createElement("span");
        lp.className = "pill lang";
        lp.textContent = langName(r.language);
        lang.appendChild(lp);
        const label = document.createElement("td");
        label.appendChild(labelPill(r.label));
        const score = document.createElement("td");
        score.textContent = percent(r.score);
        const added = document.createElement("td");
        added.textContent = r.added || "\u2014";
        const act = document.createElement("td");
        const del = document.createElement("button");
        del.className = "icon-btn";
        del.title = "Delete from history";
        del.setAttribute("aria-label", "Delete from history");
        del.innerHTML = TRASH_SVG;                       // static icon markup only
        del.addEventListener("click", () => deleteRecord(r.id));
        act.appendChild(del);
        tr.append(fact, lang, label, score, added, act);
        body.appendChild(tr);
      });
    } catch (err) {
      messageRow(body, err instanceof TypeError ? SERVER_MSG : err.message);
    }
  }

  async function deleteRecord(id) {
    if (!confirm("Delete this record from History and Analytics?\n(It stays saved in the trusted facts file.)")) return;
    try {
      const res = await fetch(API_BASE + "/api/history/" + id, { method: "DELETE", headers: FND.authHeaders() });
      if (!res.ok) throw new Error();
    } catch {
      alert("Could not delete the record.");
    }
    loadHistory();
  }

  /* ================= Charts (plain SVG, no libraries) ================= */
  const NS = "http://www.w3.org/2000/svg";
  function svgEl(tag, attrs = {}, text) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function niceStep(max) {
    if (max <= 5) return 1;
    const raw = max / 5, p = 10 ** Math.floor(Math.log10(raw)), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }

  // data: [{label, segs: [{v, cls, name}]}]  (segments are stacked)
  function barChart(holder, data, opts = {}) {
    holder.textContent = "";
    const W = 700, H = 260, L = 40, R = 10, T = 12, B = 30;
    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "Bar chart" });
    const max = Math.max(1, ...data.map((d) => d.segs.reduce((a, s) => a + s.v, 0)));
    const step = niceStep(max);
    const top = Math.ceil(max / step) * step;
    const ph = H - T - B, pw = W - L - R;
    for (let v = 0; v <= top; v += step) {
      const y = T + ph - (v / top) * ph;
      svg.append(
        svgEl("line", { x1: L, x2: W - R, y1: y, y2: y, class: "grid-line" }),
        svgEl("text", { x: L - 6, y: y + 4, class: "axis", "text-anchor": "end" }, v)
      );
    }
    const slot = pw / data.length;
    const bw = Math.min(opts.maxBar || 46, slot * 0.7);
    const every = Math.ceil(data.length / 12);
    data.forEach((d, i) => {
      const cx = L + slot * i + slot / 2;
      let y = T + ph;
      const g = svgEl("g");
      g.append(svgEl("title", {}, `${d.label}: ` + d.segs.map((s) => `${s.name} ${s.v}`).join(", ")));
      d.segs.forEach((s) => {
        if (!s.v) return;
        const h = (s.v / top) * ph;
        y -= h;
        g.append(svgEl("rect", { x: cx - bw / 2, y, width: bw, height: h, class: s.cls, rx: 2 }));
      });
      svg.append(g);
      if (i % every === 0) svg.append(svgEl("text", { x: cx, y: H - 10, class: "axis", "text-anchor": "middle" }, d.label));
    });
    holder.append(svg);
  }

  function donut(holder, real, fake) {
    holder.textContent = "";
    const total = real + fake, r = 70, C = 2 * Math.PI * r;
    const svg = svgEl("svg", { viewBox: "0 0 200 200", role: "img",
      "aria-label": `True ${real}, False ${fake}` });
    svg.append(svgEl("circle", { cx: 100, cy: 100, r, class: "ring-bg" }));
    let offset = 0;
    [[real, "ring-good"], [fake, "ring-bad"]].forEach(([v, cls]) => {
      if (!v) return;
      const len = (v / total) * C;
      svg.append(svgEl("circle", { cx: 100, cy: 100, r, class: cls,
        "stroke-dasharray": `${len} ${C - len}`, "stroke-dashoffset": -offset,
        transform: "rotate(-90 100 100)" }));
      offset += len;
    });
    svg.append(
      svgEl("text", { x: 100, y: 105, "text-anchor": "middle", class: "donut-total" }, total),
      svgEl("text", { x: 100, y: 124, "text-anchor": "middle", class: "donut-sub" }, "records")
    );
    holder.append(svg);
  }

  /* ================= Analytics ================= */
  async function loadAnalytics() {
    const stats = $("#stats"), note = $("#analyticsNote");
    const holders = ["#chartTime", "#chartDonut", "#chartLang", "#chartScore"].map((s) => $(s));
    stats.textContent = note.textContent = "";
    try {
      const a = await fetchJson("/api/analytics?range=" + ranges.analytics, "Could not load analytics.");
      [["Total records", a.total], ["True", a.real], ["False", a.fake],
       ["Average score", (a.avg_score * 100).toFixed(1) + "%"]]
        .forEach(([name, value]) => {
          const d = document.createElement("div");
          d.className = "stat";
          const b = document.createElement("b");
          b.textContent = value;
          const s = document.createElement("span");
          s.textContent = name;
          d.append(b, s);
          stats.appendChild(d);
        });

      if (!a.total) {
        holders.forEach((h) => (h.textContent = ""));
        note.textContent = "No records for this period. Predict some news first.";
        return;
      }
      barChart($("#chartTime"), a.timeline.map((t) => ({
        label: t.label,
        segs: [{ v: t.real, cls: "b-good", name: "True" }, { v: t.fake, cls: "b-bad", name: "False" }],
      })), { label: "Records over time" });
      donut($("#chartDonut"), a.real, a.fake);
      barChart($("#chartLang"), [
        { label: "English", segs: [{ v: a.languages.english, cls: "b-acc", name: "records" }] },
        { label: "Urdu", segs: [{ v: a.languages.urdu, cls: "b-acc", name: "records" }] },
      ], { label: "Records by language", maxBar: 70 });
      barChart($("#chartScore"), a.scores.map((s) => ({
        label: s.label, segs: [{ v: s.count, cls: "b-acc", name: "records" }],
      })), { label: "Records by prediction score", maxBar: 70 });
    } catch (err) {
      holders.forEach((h) => (h.textContent = ""));
      note.textContent = err instanceof TypeError ? SERVER_MSG : err.message;
    }
  }

  /* ================= MongoDB status (Settings page) ================= */
  async function loadMongo() {
    const line = $("#mongoStatus"), stats = $("#mongoStats"), recent = $("#mongoRecent"), msg = $("#mongoMsg");
    stats.textContent = recent.textContent = "";
    try {
      const m = await fetchJson("/api/mongo/status", "Could not read the MongoDB status.");
      line.className = "mongo-line " + (m.connected ? "ok" : "off");
      if (!m.connected) {
        line.textContent = "MongoDB: not connected (the CSV files are being used)";
        msg.textContent = "Start the MongoDB service, then press Refresh. Server: " + m.uri;
        return;
      }
      line.textContent = `MongoDB: connected \u2022 database "${m.database}" on ${m.uri}`;
      msg.textContent = "";
      [["History records", m.history], ["Deleted (kept in MongoDB)", m.history_deleted],
       ["Trusted facts", m.trusted_facts]].forEach(([name, value]) => {
        const d = document.createElement("div");
        d.className = "stat";
        const b = document.createElement("b");
        b.textContent = value;
        const s = document.createElement("span");
        s.textContent = name;
        d.append(b, s);
        stats.appendChild(d);
      });
      if (m.recent && m.recent.length) {
        const table = document.createElement("table");
        const head = document.createElement("tr");
        ["Latest records in MongoDB", "Language", "Label", "Score", "Added"].forEach((t) => {
          const th = document.createElement("th");
          th.textContent = t;
          head.appendChild(th);
        });
        const thead = document.createElement("thead");
        thead.appendChild(head);
        const tbody = document.createElement("tbody");
        m.recent.forEach((r) => {
          const tr = document.createElement("tr");
          const t = document.createElement("td");
          t.className = "fact";
          t.dir = "auto";
          t.textContent = r.text;
          const l = document.createElement("td");
          l.textContent = langName(r.language);
          const lb = document.createElement("td");
          lb.appendChild(labelPill(r.label));
          const sc = document.createElement("td");
          sc.textContent = percent(r.score);
          const ad = document.createElement("td");
          ad.textContent = r.added;
          tr.append(t, l, lb, sc, ad);
          tbody.appendChild(tr);
        });
        table.append(thead, tbody);
        recent.appendChild(table);
      }
    } catch (err) {
      line.className = "mongo-line off";
      line.textContent = err instanceof TypeError ? SERVER_MSG : err.message;
    }
  }

  async function syncMongo() {
    const msg = $("#mongoMsg");
    msg.textContent = "Copying...";
    try {
      const res = await fetch(API_BASE + "/api/mongo/sync", { method: "POST", headers: FND.authHeaders() });
      const data = await res.json();
      await loadMongo();
      msg.textContent = res.ok
        ? `Done: ${data.history} history records and ${data.facts} trusted facts copied to MongoDB.`
        : data.error || "Copy failed.";
    } catch {
      msg.textContent = SERVER_MSG;
    }
  }
  $("#mongoRefresh").addEventListener("click", loadMongo);
  $("#mongoSync").addEventListener("click", syncMongo);

  /* ================= Settings (limited color choices) ================= */
  const TEXT_COLORS = [
    ["White", "#ffffff"], ["Soft gray", "#cbd5e1"], ["Cyan", "#22d3ee"], ["Green", "#4ade80"],
    ["Yellow", "#facc15"], ["Orange", "#fb923c"], ["Black", "#000000"],
  ];
  const BG_COLORS = [
    ["Black", "#0a0d12"], ["Dark gray", "#1f2430"], ["Navy", "#0b1730"], ["Dark green", "#0b2a1f"],
    ["Dark purple", "#20123a"], ["Dark brown", "#2a1a10"], ["Light gray", "#e5e7eb"], ["White", "#ffffff"],
  ];
  const DEFAULT_THEME = { text: "#ffffff", bg: "#0a0d12" };
  const KEY = "fnd-theme";
  let theme = { ...DEFAULT_THEME };
  try { theme = { ...DEFAULT_THEME, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { /* ignore */ }

  function luminance(hex) {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function contrast(a, b) {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  }

  function applyTheme() {
    const root = document.documentElement.style;
    root.setProperty("--text", theme.text);
    root.setProperty("--bg", theme.bg);
    $$("#textSwatches .swatch").forEach((s) => s.classList.toggle("selected", s.dataset.value === theme.text));
    $$("#bgSwatches .swatch").forEach((s) => s.classList.toggle("selected", s.dataset.value === theme.bg));
    try { localStorage.setItem(KEY, JSON.stringify(theme)); } catch { /* ignore */ }
  }

  function buildSwatches(holderId, list, kind) {
    const holder = $(holderId);
    list.forEach(([name, value]) => {
      const wrap = document.createElement("div");
      wrap.className = "swatch-wrap";
      const b = document.createElement("button");
      b.type = "button";
      b.className = "swatch";
      b.style.background = value;
      b.dataset.value = value;
      b.title = name;
      b.setAttribute("aria-label", name);
      b.addEventListener("click", () => {
        const next = { ...theme, [kind]: value };
        if (contrast(next.text, next.bg) < 3) {
          $("#settingsMsg").textContent = "That combination is hard to read. Please choose a different color.";
          return;
        }
        $("#settingsMsg").textContent = "";
        theme = next;
        applyTheme();
      });
      const cap = document.createElement("span");
      cap.textContent = name;
      wrap.append(b, cap);
      holder.appendChild(wrap);
    });
  }
  buildSwatches("#textSwatches", TEXT_COLORS, "text");
  buildSwatches("#bgSwatches", BG_COLORS, "bg");
  $("#resetTheme").addEventListener("click", () => {
    theme = { ...DEFAULT_THEME };
    $("#settingsMsg").textContent = "";
    applyTheme();
  });
  if (contrast(theme.text, theme.bg) < 3) theme = { ...DEFAULT_THEME };
  applyTheme();

  FND.resetApp = () => {
    box().value = "";
    $("#result").classList.add("hidden");
    hideError();
    updateButtons();
    showPage("dashboard");
  };
  showPage("dashboard");
})();