/* auth.js - sign in, sign up, guest mode, feedback and thank-you screens.
   Loaded BEFORE script.js. script.js reads  window.FND  to know who is using the app. */
(() => {
  "use strict";

  const API_BASE = location.port === "5000" ? "" : "http://localhost:5000";
  const SESSION_KEY = "fnd-session";
  const SERVER_MSG = "Cannot reach the server. Start it with:  python api.py";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const FND = (window.FND = {
    guest: false,
    token: "",
    resetApp: null,                                  // set by script.js
    authHeaders() { return FND.token ? { Authorization: "Bearer " + FND.token } : {}; },
    sessionExpired() {
      endSession();
      showAuth("signin", "Your session has expired. Please sign in again.");
    },
  });

  /* ---------------- saved session (token only; no personal data is kept in the browser) ---------------- */
  function saveSession(session, remember) {
    clearSession();
    try { (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, JSON.stringify(session)); } catch { /* ignore */ }
  }
  function loadSession() {
    for (const store of [sessionStorage, localStorage]) {
      try {
        const s = JSON.parse(store.getItem(SESSION_KEY) || "null");
        if (s && (s.mode === "guest" || (s.mode === "user" && s.token))) return s;
      } catch { /* ignore */ }
    }
    return null;
  }
  function clearSession() {
    try { sessionStorage.removeItem(SESSION_KEY); localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
  }
  function endSession() {
    clearSession();
    FND.token = "";
    FND.guest = false;
  }

  /* ---------------- helpers ---------------- */
  const setScreen = (name) => { document.body.dataset.screen = name; };

  function showMsg(id, text) {
    const el = $(id);
    el.textContent = text || "";
    el.classList.toggle("hidden", !text);
  }

  function busy(btn, on, label) {
    const span = $("span", btn);
    if (on) { btn.dataset.label = span.textContent; span.textContent = label; }
    else if (btn.dataset.label) span.textContent = btn.dataset.label;
    btn.disabled = on;
  }

  async function post(path, body, withToken = false) {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(withToken ? FND.authHeaders() : {}) },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    return { res, data };
  }

  /* ---------------- sign in / sign up screen ---------------- */
  function showAuth(view, message = "") {
    setScreen("auth");
    $("#signinForm").classList.toggle("hidden", view !== "signin");
    $("#signupForm").classList.toggle("hidden", view !== "signup");
    showMsg("#siError", view === "signin" ? message : "");
    showMsg("#suError", view === "signup" ? message : "");
    ["#siPass", "#suPass", "#suConfirm"].forEach((s) => ($(s).value = ""));
    $(view === "signin" ? "#siEmail" : "#suEmail").focus();
  }
  $$("[data-go]").forEach((b) => b.addEventListener("click", () => showAuth(b.dataset.go)));

  function enterApp(mode, token = "") {
    FND.guest = mode === "guest";
    FND.token = token;
    $("#modeBadge").classList.toggle("hidden", !FND.guest);
    $$('.nav-btn[data-page="history"], .nav-btn[data-page="analytics"]')
      .forEach((b) => b.classList.toggle("locked", FND.guest));
    $("#mongoCard").classList.toggle("hidden", FND.guest);          // guests never see the database section
    setScreen("app");
    if (FND.resetApp) FND.resetApp();
  }

  function finishLogin(token, remember) {
    saveSession({ mode: "user", token }, remember);
    ["#siEmail", "#siPass", "#suEmail", "#suPass", "#suConfirm"].forEach((s) => ($(s).value = ""));
    enterApp("user", token);
  }

  $("#signinForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#siEmail").value.trim(), password = $("#siPass").value;
    const remember = $("#siRemember").checked;
    showMsg("#siError", "");
    if (!email || !password) return showMsg("#siError", "Please enter your email and password.");
    const btn = $("#siBtn");
    busy(btn, true, "Signing in...");
    try {
      const { res, data } = await post("/api/auth/signin", { email, password, remember });
      if (!res.ok) throw new Error(data.error || "Sign in failed.");
      finishLogin(data.token, remember);
    } catch (err) {
      showMsg("#siError", err instanceof TypeError ? SERVER_MSG : err.message);
    } finally {
      busy(btn, false);
    }
  });

  $("#signupForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#suEmail").value.trim(), password = $("#suPass").value, confirm = $("#suConfirm").value;
    showMsg("#suError", "");
    if (!email || !password || !confirm) return showMsg("#suError", "Please fill in all the fields.");
    if (password !== confirm) return showMsg("#suError", "The two passwords do not match.");
    const btn = $("#suBtn");
    busy(btn, true, "Creating account...");
    try {
      const { res, data } = await post("/api/auth/signup", { email, password, confirm, remember: false });
      if (!res.ok) throw new Error(data.error || "Sign up failed.");
      finishLogin(data.token, false);
    } catch (err) {
      showMsg("#suError", err instanceof TypeError ? SERVER_MSG : err.message);
    } finally {
      busy(btn, false);
    }
  });

  /* ---------------- guest mode ---------------- */
  $("#guestBtn").addEventListener("click", () => {
    saveSession({ mode: "guest" }, false);
    enterApp("guest");
  });
  $("#lockedSignin").addEventListener("click", () => { endSession(); showAuth("signin"); });
  $("#lockedSignup").addEventListener("click", () => { endSession(); showAuth("signup"); });

  /* ---------------- exit -> feedback (signed-in) / thanks (guest) ---------------- */
  $("#exitBtn").addEventListener("click", () => {
    if (FND.guest) {
      endSession();
      showThanks("guest");
    } else {
      openFeedback();
    }
  });

  /* ---------------- feedback ---------------- */
  let rating = 0;
  const starsBox = $("#stars");
  for (let n = 1; n <= 5; n++) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "\u2605";
    b.setAttribute("aria-label", `${n} star${n > 1 ? "s" : ""}`);
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => setRating(n));
    starsBox.appendChild(b);
  }
  function setRating(n) {
    rating = n;
    $$("button", starsBox).forEach((b, i) => {
      b.classList.toggle("on", i < n);
      b.setAttribute("aria-pressed", i + 1 === n);
    });
  }
  const comment = $("#fbComment");
  comment.addEventListener("input", () => { $("#fbCount").textContent = `${comment.value.length} / 500`; });

  function openFeedback() {
    setRating(0);
    comment.value = "";
    $("#fbCount").textContent = "0 / 500";
    showMsg("#fbError", "");
    setScreen("feedback");
  }

  $("#fbSubmit").addEventListener("click", async () => {
    const text = comment.value.trim();
    showMsg("#fbError", "");
    if (!rating && !text) return showMsg("#fbError", "Please choose a star rating or write a short comment.");
    const btn = $("#fbSubmit");
    busy(btn, true, "Sending...");
    try {
      const { res, data } = await post("/api/feedback", { rating, comment: text }, true);
      if (res.status === 401) { endSession(); return showThanks("user", false); }
      if (!res.ok) throw new Error(data.error || "Feedback could not be saved.");
      endSession();
      showThanks("user", true);
    } catch (err) {
      showMsg("#fbError", err instanceof TypeError ? SERVER_MSG : err.message);
    } finally {
      busy(btn, false);
    }
  });

  // Closing the feedback page without sending: signed-in user also goes to the thank-you page
  const skipFeedback = () => { endSession(); showThanks("user", false); };
  $("#fbSkip").addEventListener("click", skipFeedback);
  $("#fbClose").addEventListener("click", skipFeedback);

  /* ---------------- thanks ---------------- */
  function showThanks(kind, gaveFeedback = false) {
    const primary = $("#thanksPrimary"), secondary = $("#thanksSecondary");
    if (kind === "guest") {
      $("#thanksText").textContent =
        "You explored the app as a guest. Create a free account to unlock History, Analytics and saved predictions.";
      $("span", primary).textContent = "Create an account";
      primary.onclick = () => showAuth("signup");
      secondary.textContent = "I already have an account \u2013 Sign in";
      secondary.classList.remove("hidden");
      secondary.onclick = () => showAuth("signin");
    } else {
      $("#thanksText").textContent = gaveFeedback
        ? "Your feedback was saved. Thank you \u2013 we hope to see you again soon!"
        : "You have been signed out. We hope to see you again soon!";
      $("span", primary).textContent = "Back to Sign In";
      primary.onclick = () => showAuth("signin");
      secondary.classList.add("hidden");
      secondary.onclick = null;
    }
    setScreen("thanks");
  }

  /* ---------------- start ---------------- */
  (async function init() {
    const saved = loadSession();
    if (!saved) return showAuth("signin");
    if (saved.mode === "guest") return enterApp("guest");

    setScreen("loading");                                      // nothing flashes while the token is checked
    try {
      const res = await fetch(API_BASE + "/api/auth/check", { headers: { Authorization: "Bearer " + saved.token } });
      if (res.ok) return enterApp("user", saved.token);
      clearSession();
      showAuth("signin");
    } catch {
      showAuth("signin", SERVER_MSG);
    }
  })();
})();
