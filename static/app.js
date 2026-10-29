/* ═══════════ رفيق — منطق الواجهة ═══════════ */
(() => {
"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let token = localStorage.getItem("raf_token") || null;
let me = null;
let models = {};

/* ---------- توست ---------- */
let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), isErr ? 5000 : 2800);
}

/* ---------- API ---------- */
async function api(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers);
  if (token) opts.headers["Authorization"] = "Bearer " + token;
  if (opts.json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const r = await fetch(path, opts);
  if (r.status === 401 && token) { logout(true); throw new Error("انتهت الجلسة"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || ("خطأ " + r.status));
  return data;
}

/* ---------- الحالة العامة ---------- */
async function refreshStatus(silent = true) {
  try {
    const s = await api("/api/status");
    models = s.models || {};
    renderModelChips();
    const loading = Object.values(models).filter((m) => m.status === "loading");
    const errs = Object.values(models).filter((m) => m.status === "error");
    const banner = $("loadingBanner"), eb = $("errorBanner");
    if (loading.length) {
      banner.classList.remove("hidden");
      $("loadingText").textContent = "جاري تحميل النماذج: " + loading.map((m) => m.label).join("، ") + " …";
    } else banner.classList.add("hidden");
    if (errs.length && errs.some((m) => m.key !== "asr" || !Object.values(models).some((x) => x.key === "llm" && x.status === "loading"))) {
      eb.classList.remove("hidden");
      eb.innerHTML = errs.map((m) => `⚠️ ${esc(m.label)}: ${esc(m.error || "")}`).join("<br>");
    } else eb.classList.add("hidden");
    return s;
  } catch (e) { if (!silent) toast(e.message, true); return null; }
}

function renderModelChips() {
  const box = $("modelStatus");
  box.innerHTML = Object.values(models).map((m) => {
    const st = { ready: "جاهز", loading: "تحميل…", error: "خطأ", idle: "متوقف" }[m.status] || m.status;
    return `<span class="mchip ${m.status}">${esc(m.label)} — ${st}</span>`;
  }).join("");
}

/* ---------- المصادقة ---------- */
function saveAuth(tok, user) {
  token = tok; me = user;
  localStorage.setItem("raf_token", tok);
  localStorage.setItem("raf_user", JSON.stringify(user));
}
function logout(silent) {
  token = null; me = null; localStorage.clear();
  if (!silent) toast("تم تسجيل الخروج");
  $("appView").classList.add("hidden");
  $("authView").classList.remove("hidden");
}

async function boot() {
  const s = await refreshStatus(true);
  if (me || token) {
    try { me = await api("/api/auth/me"); startApp(); return; } catch (e) { /* token قديم */ }
  }
  // إظهار شاشة الدخول (الطبقة مخفية افتراضيًا في HTML)
  $("authView").classList.remove("hidden");
  $("appView").classList.add("hidden");  // ضمان إخفاء التطبيق إن كانت جلسة قديمة
  if (s && s.owner_exists === false) {
    $("setupBox").classList.remove("hidden");
    $("loginBox").classList.add("hidden");
    $("authSubtitle").textContent = "مرحبًا — لنبدأ بإنشاء حساب المالك";
  } else {
    $("loginBox").classList.remove("hidden");
    if (s && s.allow_register === false) $("registerTab").classList.add("hidden");
    if (s && s.billing) $("freeMinutesHint").textContent = "٣٠";
  }
}

$("setupBtn").onclick = async () => {
  $("authError").classList.add("hidden");
  try {
    const r = await api("/api/auth/setup", { json: { email: $("setupEmail").value.trim(), password: $("setupPass").value, name: $("setupName").value.trim() } });
    saveAuth(r.access_token, r.user); startApp();
  } catch (e) { $("authError").textContent = e.message; $("authError").classList.remove("hidden"); }
};
$("loginBtn").onclick = async () => {
  $("authError").classList.add("hidden");
  try {
    const r = await api("/api/auth/login", { json: { email: $("loginEmail").value.trim(), password: $("loginPass").value } });
    saveAuth(r.access_token, r.user); startApp();
  } catch (e) { $("authError").textContent = e.message; $("authError").classList.remove("hidden"); }
};
$("regBtn").onclick = async () => {
  $("authError").classList.add("hidden");
  try {
    const r = await api("/api/auth/register", { json: { email: $("regEmail").value.trim(), password: $("regPass").value, name: $("regName").value.trim() } });
    if (r.granted_minutes) toast(`مرحبًا! حصلت على ${r.granted_minutes} دقيقة مجانًا`);
    saveAuth(r.access_token, r.user); startApp();
  } catch (e) { $("authError").textContent = e.message; $("authError").classList.remove("hidden"); }
};
$("logoutBtn").onclick = () => logout();
document.querySelectorAll("#loginBox .tab").forEach((tab) => {
  tab.onclick = () => {
    document.querySelectorAll("#loginBox .tab").forEach((t) => t.classList.toggle("active", t === tab));
    $("loginPane").classList.toggle("hidden", tab.dataset.tab !== "login");
    $("registerPane").classList.toggle("hidden", tab.dataset.tab !== "register");
  };
});

/* ---------- بدء التطبيق ---------- */
function startApp() {
  $("authView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  $("userName").textContent = me.display_name || me.email;
  $("userRole").textContent = me.role_label + (me.free ? " — استخدام مجاني" : "");
  $("userAvatar").textContent = (me.display_name || me.email)[0];
  $("adminNavLink").classList.toggle("hidden", !(me.perms.includes("stats.view")));
  updateMinutes(me.minutes);
  loadSessions();
  go((location.hash || "#/chat").replace("#/", ""));
  setInterval(() => { refreshStatus(true); }, 6000);
}

function updateMinutes(state) {
  if (!state) return;
  const el = $("minutesPill");
  if (me && me.free) { el.textContent = "استخدام مجاني (فريق الإدارة)"; el.classList.remove("low"); return; }
  const total = state.total_left;
  el.textContent = `${total} دقيقة متبقية` + (state.plan_name ? ` — ${state.plan_name}` : "");
  el.classList.toggle("low", total <= 10);
}

/* ---------- التوجيه ---------- */
const VIEWS = ["chat", "billing", "keys", "admin"];
const renderers = { billing: loadBilling, keys: loadKeys, admin: routeAdmin };
function go(route) {
  if (!VIEWS.includes(route)) route = "chat";
  location.hash = "#/" + route;
  VIEWS.forEach((v) => $("view-" + v).classList.toggle("hidden", v !== route));
  document.querySelectorAll(".side-nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  if (route !== "chat") loadSessions();
  (renderers[route] || (() => {}))();
  $("sidebar").classList.remove("open");
}
window.addEventListener("hashchange", () => go(location.hash.replace("#/", "")));
document.querySelectorAll(".side-nav a").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); go(a.dataset.route); }));
$("menuBtn").onclick = () => $("sidebar").classList.toggle("open");

/* ═══════════════ المحادثة النصية ═══════════════ */
let sessions = [], currentSession = null;

async function loadSessions() {
  try {
    const r = await api("/api/sessions");
    sessions = r.sessions || [];
    $("convList").innerHTML = sessions.map((s) =>
      `<div class="conv ${currentSession === s.id ? "active" : ""}" data-id="${s.id}" title="${esc(s.title)}">
        <span>${esc(s.title)}</span><button class="del" data-del="${s.id}" title="حذف">✕</button></div>`
    ).join("");
    $("convList").querySelectorAll(".conv").forEach((el) => {
      el.onclick = (e) => {
        const del = e.target.closest("[data-del]");
        if (del) { deleteSession(del.dataset.del, e.stopPropagation()); return; }
        openSession(+el.dataset.id);
      };
    });
  } catch (e) { toast(e.message, true); }
}

async function deleteSession(id) {
  try { await api("/api/sessions/" + id, { method: "DELETE" }); if (currentSession === +id) { currentSession = null; freshChat(); } }
  catch (e) { toast(e.message, true); }
  loadSessions();
}

function freshChat() {
  currentSession = null;
  $("welcome").classList.remove("hidden");
  const list = $("messages");
  list.querySelectorAll(".msg").forEach((n) => n.remove());
}

async function openSession(id) {
  currentSession = id;
  try {
    const r = await api(`/api/sessions/${id}/messages`);
    const list = $("messages");
    list.querySelectorAll(".msg").forEach((n) => n.remove());
    $("welcome").classList.add("hidden");
    (r.messages || []).forEach((m) => {
      const b = addBubble(m.role, m.content);
      if (m.role === "assistant" && m.content) setSpeakable(b, m.content);
    });
    list.scrollTop = list.scrollHeight;
  } catch (e) { toast(e.message, true); }
  loadSessions();
}

$("newChatBtn").onclick = () => { currentSession = null; freshChat(); go("chat"); };
document.querySelectorAll(".sug").forEach((b) => b.onclick = () => { $("input").value = b.textContent; sendChat(); });

function addBubble(role, text) {
  const list = $("messages");
  $("welcome").classList.add("hidden");
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `
    <div class="m-avatar">${role === "user" ? "🧑" : "🌙"}</div>
    <div class="m-body">${role === "user" ? esc(text) : mdRender(text)}${role === "assistant" && text === "" ? '<span class="caret">&nbsp;</span>' : ""}</div>
    <div class="m-actions"></div>`;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
  return div;
}

function setSpeakable(bubble, text) {
  const box = bubble.querySelector(".m-actions");
  if (!box || box.dataset.on) { const b = bubble.querySelector(".m-speak"); if (b) b.dataset.tts = text; return; }
  const btn = document.createElement("button");
  btn.className = "m-speak";
  btn.title = "نطق الرد 🔊";
  btn.textContent = "🔊";
  btn.dataset.tts = text;
  btn.onclick = () => speak(btn.dataset.tts, btn);
  box.dataset.on = "1";
  box.appendChild(btn);
}

async function speak(text, btn) {
  if (!text) return;
  if (btn) { btn.disabled = true; btn.textContent = "⏳"; }
  try {
    const r = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ text }),
    });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || "خطأ " + r.status); }
    const b = await r.blob();
    const au = new Audio(URL.createObjectURL(b));
    au.onended = () => { if (btn) { btn.disabled = false; btn.textContent = "🔊"; } };
    au.play().catch(() => {});
  } catch (e) {
    toast(e.message, true);
    if (btn) { btn.disabled = false; btn.textContent = "🔊"; }
  }
}

function mdRender(t) {
  t = esc(t);
  t = t.replace(/```([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  // جداول مبسطة
  t = t.replace(/^(\|.*\|)\n\|[-| :]+\|\n((?:\|.*\|\n?)*)/gm, (_, head, rows) => {
    const cells = (row) => row.split("|").filter(x => x.trim() !== "").map(x => `<td>${x.trim()}</td>`).join("");
    const ths = head.split("|").filter(x => x.trim() !== "").map(x => `<th>${x.trim()}</th>`).join("");
    const trs = rows.trim().split("\n").map((r) => `<tr>${cells(r)}</tr>`).join("");
    return `<table><thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
  });
  t = t.replace(/^- (.+)$/gm, "• $1");
  t = t.split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
  return t;
}

/* إرسال نصي (SSE) */
const input = $("input");
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); } });
input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; });
$("sendBtn").onclick = sendChat;

async function sendChat() {
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; input.style.height = "auto";
  addBubble("user", text);
  const bubble = addBubble("assistant", "");
  const body = bubble.querySelector(".m-body");
  let acc = "";
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: JSON.stringify({ message: text, session_id: currentSession, voice: false }),
    });
    if (!resp.ok || !resp.body) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || "خطأ " + resp.status);
    }
    currentSession = null;
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) > -1) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 2);
        if (!line.startsWith("data: ")) continue;
        const ev = JSON.parse(line.slice(6));
        if (ev.type === "start") currentSession = ev.session_id;
        else if (ev.type === "delta") { acc += ev.text; body.innerHTML = mdRender(acc) + '<span class="caret">&nbsp;</span>'; scrollMsgs(); }
        else if (ev.type === "done") { updateMinutes(ev.usage ? null : null); }
        else if (ev.type === "error") throw new Error(ev.message || "خطأ");
        else if (ev.type === "billing_exhausted") toast("نفدت دقائقك — من صفحة الاشتراكات يمكنك الشحن", true);
      }
    }
    body.innerHTML = mdRender(acc || "…لا أستطيع الرد الآن.");
    if (acc) setSpeakable(bubble, acc);
  } catch (e) {
    body.innerHTML = `<span class="st-bad">⚠️ ${esc(e.message)}</span>`;
    toast(e.message, true);
  }
  loadSessions();
  const st = await api("/api/billing/me").catch(() => null);
  if (st) updateMinutes(st.state);
}
function scrollMsgs() { const l = $("messages"); l.scrollTop = l.scrollHeight; }

/* ═══════════════ الوضع الصوتي (WebSocket) ═══════════════ */
let ws = null, micOn = false, audioCtx = null, srcNode = null, procNode = null, micStream = null;
let playQueue = [], playing = false, currentAudio = null;

$("micBtn").onclick = () => (micOn ? stopMic() : startMic());

function wsend(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

async function startMic() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (e) { toast("تعذر الوصول إلى الميكروفون — اسمح بالإذن", true); return; }
  $("micBtn").classList.add("live");
  $("micBtn").title = "إيقاف الاستماع";
  micOn = true;
  interruptAudio();
  openWS();
}

function stopMic() {
  micOn = false;
  $("micBtn").classList.remove("live");
  $("micBtn").title = "اضغط للتحدث";
  $("liveTranscript").classList.add("hidden");
  try { if (procNode) procNode.disconnect(); } catch (_) {}
  try { if (srcNode) srcNode.disconnect(); } catch (_) {}
  if (audioCtx) { try { audioCtx.close(); } catch (_) {} audioCtx = null; }
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  if (ws) { try { ws.close(1000); } catch (_) {} ws = null; }
}

let asrInfo = null;
function openWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/voice?token=${encodeURIComponent(token)}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => {
    asrInfo = null;
    // تجهيز التقاط الصوت
    audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    srcNode = audioCtx.createMediaStreamSource(micStream);
    procNode = audioCtx.createScriptProcessor(2048, 1, 1);
    procNode.onaudioprocess = (e) => {
      if (!micOn || ws.readyState !== 1) return;
      const f = e.inputBuffer.getChannelData(0);
      const pcm = new Int16Array(f.length);
      for (let i = 0; i < f.length; i++) {
        const v = Math.max(-1, Math.min(1, f[i]));
        pcm[i] = v < 0 ? v * 32768 : v * 32767;
      }
      ws.send(pcm.buffer);
    };
    srcNode.connect(procNode);
    procNode.connect(audioCtx.destination);   // بعض المتصفحات تتطلب إيصالاً لأجل المعالجة
    wsend({ type: "start" });
    toast("🎤 أستمع إليك الآن — تكلّم بحرية، واضغط زر الميكروفون للإنهاء");
  };
  ws.onmessage = (e) => {
    if (typeof e.data !== "string") return;
    let m; try { m = JSON.parse(e.data); } catch (_) { return; }
    onVoiceMsg(m);
  };
  ws.onclose = () => { if (micOn) { setTimeout(() => { if (micOn) openWS(); }, 800); } };
  ws.onerror = () => {};
}

function onVoiceMsg(m) {
  switch (m.type) {
    case "session":
      if (!me.free && m.minutes) updateMinutes(m.minutes);
      break;
    case "speech":
      if (m.state === "start") {
        const lt = $("liveTranscript");
        lt.classList.remove("hidden");
        lt.innerHTML = `<span class="dot"></span> أستمع… تحدّث الآن`;
        interruptAudio();          // مقاطعة ردك سمعيًا (barge-in)
      } else {
        $("liveTranscript").innerHTML = "⏳ أُفكر…";
      }
      break;
    case "transcript": {
      const lt = $("liveTranscript");
      if (m.empty) { lt.classList.add("hidden"); break; }
      lt.innerHTML = `🗣️ ${esc(m.text)}`;
      break;
    }
    case "delta": {
      let b = lastVoiceBubble();
      if (!b) { b = addBubble("assistant", ""); b.classList.add("live-msg"); b.dataset.live = "1"; }
      const body = b.querySelector(".m-body");
      body.textContent = (body.textContent || "") + m.text;
      scrollMsgs();
      break;
    }
    case "audio": {
      const bytes = base64ToBytes(m.data);
      const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
      queueAudio(url);
      break;
    }
    case "audio_end": break;
    case "done": {
      finalizeVoiceBubble();
      const lt = $("liveTranscript");
      if (!micOn) lt.classList.add("hidden");
      if (m.minutes) updateMinutes(m.minutes);
      loadSessions();
      break;
    }
    case "status": {
      const stages = {
        asr: "🎧 أستمع…", llm: "🧠 أفكر…", thinking: "🧠 أفكر…", tts: "🔊 أصيغ الرد…",
        speaking: "💬 أرد الآن…", idle: "جاهز",
      };
      const chip = $("stageChip");
      chip.classList.toggle("busy", m.stage !== "idle");
      $("stageText").textContent = stages[m.stage] || m.stage;
      break;
    }
    case "billing": if (m.minutes) updateMinutes(m.minutes); break;
    case "error": toast(m.message || "خطأ", true); $("liveTranscript").classList.add("hidden"); break;
    case "interrupt": interruptAudio(); break;
    case "closed": break;
  }
}
function lastVoiceBubble() { return $("messages").querySelector('.msg.live-msg'); }
function finalizeVoiceBubble() {
  const b = lastVoiceBubble();
  if (b) { delete b.dataset.live; b.classList.remove("live-msg"); }
}
function base64ToBytes(b64) {
  const s = atob(b64), a = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
  return a;
}

/* ---------- تشغيل الصوت المتتابع ---------- */
function queueAudio(url) {
  if (!$("voiceReplyToggle").checked) return;
  playQueue.push(url);
  if (!playing) playNext();
}
function playNext() {
  if (!playQueue.length) { playing = false; currentAudio = null; micLoopResume(); return; }
  playing = true;
  const url = playQueue.shift();
  const a = new Audio(url);
  currentAudio = a;
  a.play().catch(() => playNext());
  a.onended = () => { URL.revokeObjectURL(url); playNext(); };
}
function interruptAudio() {
  playQueue = [];
  if (currentAudio) { try { currentAudio.pause(); } catch (_) {} currentAudio = null; }
  playing = false;
  finalizeVoiceBubble();
  lastVoiceBubble() && null;
}
function micLoopResume() {
  // استئناف التقاط المايك (متوقف مؤقتًا أثناء التشغيل لمنع صدى النظام)
  if (micOn && audioCtx && audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) micLoopResume(); });

// إيقاف الالتقاط أثناء الكلام الخارج (منع الرد على ما يقوله رفيق نفسه)
window.addEventListener("beforeunload", () => stopMic());
input.addEventListener("focus", () => {});

// منع تكرار الرسائل "delta" والكتابة داخل فقاعتي متزامنتين — مساعدة داخلية
function ensureSingleLiveBubble() { return lastVoiceBubble() || addBubble("assistant", ""); }

$("voiceReplyToggle").addEventListener("change", (e) => {
  if (!e.target.checked) { playQueue = []; if (currentAudio) { currentAudio.pause(); currentAudio = null; } playing = false; }
});

/* ═══════════════ الاشتراكات والدقائق ═══════════════ */
async function loadBilling() {
  try {
    const [plansData, mineData] = await Promise.all([api("/api/billing/plans"), api("/api/billing/me")]);
    const s = mineData.state, cur = mineData.currency;
    const fmt = (n) => n.toLocaleString("ar");
    $("billingSummary").innerHTML = [
      { big: s.plan_name || "بدون باقة", lbl: "الخط الحالي" },
      { big: fmt(s.plan_left), lbl: "دقائق الباقة المتبقية" },
      { big: fmt(s.balance_left), lbl: "دقائق الرصيد الإضافي" },
      { big: `${mineData.price_per_minute} ${cur}`, lbl: "سعر دقيقة إضافية خارج الباقة" },
    ].map((c, i) => `<div class="card"><div class="big ${i === 3 ? "" : ""}" ${i === 0 ? 'style="font-size:1.15rem"' : ""}>${esc(String(c.big))}</div><div class="lbl">${esc(c.lbl)}</div></div>`).join("");

    $("plansGrid").innerHTML = (plansData.plans || []).map((p) => `
      <div class="plan ${s.plan_name === p.name ? "current" : ""}">
        ${s.plan_name === p.name ? '<span class="badge-now">خطك الحالي</span>' : ""}
        <h3>${esc(p.name)}</h3>
        <div class="price">${fmt(p.price)} <small>${cur} / شهر</small></div>
        <p class="hint">${esc(p.description)}</p>
        <ul><li>✔ ${fmt(p.minutes)} دقيقة سمعية شهريًا</li><li>✔ فوترة بالدقيقة لا بالتوكن</li><li>✔ جودة صوت عالية</li></ul>
        ${me.free ? "" : `<button class="btn ${s.plan_name === p.name ? "primary" : ""} wide" data-sub="${p.id}">${s.plan_name === p.name ? "متجدد تلقائيًا (تمتلكه)" : "اشترك الآن"}</button>`}
      </div>`).join("");
    $("plansGrid").querySelectorAll("[data-sub]").forEach((b) => b.onclick = async () => {
      try { await api("/api/billing/subscribe", { json: { plan_id: +b.dataset.sub } }); toast("تم الاشتراك بنجاح 🎉"); loadBilling(); }
      catch (e) { toast(e.message, true); }
    });

    $("topupGrid").innerHTML = (plansData.topup_packs || []).map((t) => `
      <div class="topup"><div class="min">+${fmt(t.minutes)} دقيقة</div>
      <div class="muted" style="margin:6px 0">${fmt(t.amount)} ${cur}</div>
      ${me.free ? "" : `<button class="btn wide" data-top="${t.index}">شحن</button>`}</div>`).join("");
    $("topupGrid").querySelectorAll("[data-top]").forEach((b) => b.onclick = async () => {
      try { const r = await api("/api/billing/topup", { json: { pack: +b.dataset.top } }); toast("تم الشحن ✓"); updateMinutes(r.state); loadBilling(); }
      catch (e) { toast(e.message, true); }
    });

    $("billingNote").textContent = plansData.billing_note || "";
    const ch = { voice: "🎙️ صوت", chat: "💬 محادثة", api_chat: "🔌 API", speech: "🔊 نطق", transcribe: "🎧 تفريغ" };
    $("usageTable").querySelector("tbody").innerHTML = (mineData.history || []).map((h) => `
      <tr><td>${ch[h.channel] || h.channel}</td><td>${h.seconds}</td><td>${h.minutes_charged}</td>
      <td>${h.plan_left} + ${h.balance_left}</td><td>${fmtDate(h.created_at)}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">لا يوجد استهلاك بعد</td></tr>';
  } catch (e) { toast(e.message, true); }
}
function fmtDate(iso) {
  try { return new Date(iso).toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" }); } catch (_) { return iso; }
}
window.fmtDate = fmtDate;

/* ═══════════════ مفاتيح API ═══════════════ */
async function loadKeys() {
  try {
    const r = await api("/api/keys");
    $("keysTable").querySelector("tbody").innerHTML = (r.keys || []).map((k) => `
      <tr><td>${esc(k.name)}</td><td dir="ltr" class="muted">${esc(k.key_prefix)}</td>
      <td>${fmtDate(k.created_at)}</td><td>${k.last_used_at ? fmtDate(k.last_used_at) : "—"}</td>
      <td>${k.revoked_at ? '<span class="st-bad">ملغى</span>' : `<button class="btn sm danger" data-rev="${k.id}">إلغاء</button>`}</td></tr>`).join("")
      || '<tr><td colspan="5" class="muted">لا مفاتيح بعد</td></tr>';
    $("keysTable").querySelectorAll("[data-rev]").forEach((b) => b.onclick = async () => {
      try { await api("/api/keys/" + b.dataset.rev, { method: "DELETE" }); toast("أُلغي المفتاح"); loadKeys(); } catch (e) { toast(e.message, true); }
    });
  } catch (e) { toast(e.message, true); }
}
$("createKeyBtn").onclick = async () => {
  try {
    const r = await api("/api/keys", { json: { name: $("keyName").value.trim() || "مفتاح جديد" } });
    $("keyName").value = "";
    $("modalTitle").textContent = r.name;
    $("modalKey").textContent = r.key;
    $("modal").classList.remove("hidden");
    loadKeys();
  } catch (e) { toast(e.message, true); }
};
$("modalCopy").onclick = () => { navigator.clipboard.writeText($("modalKey").textContent).then(() => toast("نُسخ ✓")); };
$("modalClose").onclick = () => $("modal").classList.add("hidden");
$("modal").addEventListener("click", (e) => { if (e.target === $("modal")) $("modal").classList.add("hidden"); });

/* ═══════════════ لوحة المالك/المشرف ═══════════════ */
let adminLoaded = false;
function routeAdmin() {
  if (!me.perms.includes("stats.view")) { toast("ليست لديك صلاحية الدخول", true); go("chat"); return; }
  document.querySelectorAll("#adminTabs .tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.atab === (t.classList.contains("active") ? t.dataset.atab : (document.activeElement, currentAtab || "stats")));
  });
  showAtab(currentAtab || "stats");
}
let currentAtab = "stats";
document.querySelectorAll("#adminTabs .tab").forEach((t) => { t.classList.add("x"); t.onclick = () => showAtab(t.dataset.atab); });
function showAtab(name) {
  currentAtab = name;
  document.querySelectorAll("#adminTabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.atab === name));
  document.querySelectorAll(".atab").forEach((el) => el.classList.add("hidden"));
  const box = $("atab-" + name);
  if (box) box.classList.remove("hidden");
  const loaders = { stats: loadStats, users: loadUsers, plans: loadAdminPlans, akeys: loadAllKeys, settings: loadSettings, audit: loadAudit };
  (loaders[name] || (() => {}))();
}

async function loadStats() {
  try {
    const s = await api("/api/admin/stats");
    $("statCards").innerHTML = [
      ["المستخدمون", s.users_total], ["مشتركون نشطون", s.active_subscriptions],
      ["دقائق اليوم", s.minutes_today], ["دقائق شهر", s.minutes_30d],
      [`إيراد تقديري (${s.currency})`, s.revenue_est_30d], ["مفاتيح نشطة", s.api_keys_active],
    ].map(([l, v]) => `<div class="card"><div class="big">${Number(v).toLocaleString("ar")}</div><div class="lbl">${l}</div></div>`).join("");
    const max = Math.max(1, ...(s.daily || []).map((d) => d.m));
    $("usageChart").innerHTML = (s.daily || []).map((d) =>
      `<div class="bar" data-tip="${d.day} — ${d.m} دقيقة" style="height:${Math.round((d.m / max) * 100)}%"></div>`).join("")
      || '<div class="muted">لا بيانات بعد</div>';
    const chMax = Math.max(1, ...(s.channels || []).map((c) => c.m));
    $("channelBars").innerHTML = (s.channels || []).map((c) =>
      `<div class="cbar"><div class="name">${c.channel}</div><div class="track"><div class="fill" style="width:${Math.round((c.m / chMax) * 100)}%"></div></div><div>${c.m} د / ${c.n}×</div></div>`).join("")
      || '<div class="muted">لا بيانات بعد</div>';
  } catch (e) { toast(e.message, true); }
}

const ROLES = { owner: "المالك", admin: "مشرف", user: "مستخدم" };
async function loadUsers() {
  try {
    const r = await api("/api/admin/users?search=" + encodeURIComponent($("userSearch").value.trim()));
    $("usersTable").querySelector("tbody").innerHTML = (r.users || []).map((u) => `
      <tr>
        <td>${u.id}</td><td dir="ltr">${esc(u.email)}</td><td>${esc(u.display_name)}</td>
        <td><span class="role-tag ${u.role}">${ROLES[u.role] || u.role}</span></td>
        <td>${u.status === "active" ? '<span class="st-ok">نشط</span>' : '<span class="st-bad">موقوف</span>'}</td>
        <td>${u.balance_minutes} د</td>
        <td>${esc(u.plan_name || "—")}</td>
        <td class="actions">
          <select data-role="${u.id}" class="btn sm" ${u.role === "owner" && me.role !== "owner" ? "disabled" : ""}>
            ${Object.entries(ROLES).map(([v, l]) => `<option value="${v}" ${u.role === v ? "selected" : ""}>${l}</option>`).join("")}
          </select>
          <button class="btn sm" data-min="${u.id}" title="إضافة دقائق">＋د</button>
          <button class="btn sm" data-ban="${u.id}" data-state="${u.status}">${u.status === "active" ? "إيقاف" : "تشغيل"}</button>
          ${u.role === "owner" ? "" : `<button class="btn sm danger" data-userdel="${u.id}">حذف</button>`}
        </td>
      </tr>`).join("") || '<tr><td colspan="8" class="muted">لا مستخدمين</td></tr>';

    $("usersTable").querySelectorAll("[data-role]").forEach((sel) => sel.onchange = async () => {
      if (sel.value === "owner" && !confirm("منح رتبة المالك؟ سيملك صلاحيات كاملة دون استثناء.")) { loadUsers(); return; }
      try { await api("/api/admin/users/" + sel.dataset.role, { method: "PATCH", json: { role: sel.value } }); toast("تم تحديث الرتبة"); } catch (e) { toast(e.message, true); }
      loadUsers();
    });
    $("usersTable").querySelectorAll("[data-min]").forEach((b) => b.onclick = async () => {
      const v = prompt("عدد الدقائق المضافة (يمكن سالبًا للخصم):");
      if (v === null) return;
      try { await api("/api/admin/users/" + b.dataset.min, { method: "PATCH", json: { add_minutes: +v } }); toast("تم تعديل الرصيد"); loadUsers(); } catch (e) { toast(e.message, true); }
    });
    $("usersTable").querySelectorAll("[data-ban]").forEach((b) => b.onclick = async () => {
      const state = b.dataset.state === "active" ? "banned" : "active";
      try { await api("/api/admin/users/" + b.dataset.ban, { method: "PATCH", json: { status: state } }); toast("تم"); loadUsers(); } catch (e) { toast(e.message, true); }
    });
    $("usersTable").querySelectorAll("[data-userdel]").forEach((b) => b.onclick = async () => {
      if (!confirm("حذف المستخدم نهائيًا مع كل بياناته؟")) return;
      try { await api("/api/admin/users/" + b.dataset.userdel, { method: "DELETE" }); toast("حُذف"); loadUsers(); } catch (e) { toast(e.message, true); }
    });
  } catch (e) { toast(e.message, true); }
}
$("userSearchBtn").onclick = loadUsers;
$("userSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") loadUsers(); });

async function loadAdminPlans() {
  try {
    const r = await api("/api/admin/plans");
    $("plansTable").querySelector("tbody").innerHTML = (r.plans || []).map((p) => `
      <tr><td>${esc(p.name)}</td><td>${p.price}</td><td>${p.minutes.toLocaleString("ar")}</td>
      <td>${esc(p.description)}</td><td>${p.is_active ? '<span class="st-ok">فعالة</span>' : "معطلة"}</td><td>${p.subscribers}</td>
      <td><button class="btn sm" data-pedit="${p.id}">تعديل</button> <button class="btn sm danger" data-pdel="${p.id}">حذف</button></td></tr>`).join("");
    $("plansTable").querySelectorAll("[data-pdel]").forEach((b) => b.onclick = async () => {
      if (!confirm("حذف الباقة؟")) return;
      try { await api("/api/admin/plans/" + b.dataset.pdel, { method: "DELETE" }); loadAdminPlans(); } catch (e) { toast(e.message, true); }
    });
    $("plansTable").querySelectorAll("[data-pedit]").forEach((b) => b.onclick = async () => {
      const p = (r.plans || []).find((x) => x.id === +b.dataset.pedit);
      const name = prompt("اسم الباقة:", p.name); if (name === null) return;
      const price = prompt("السعر:", p.price); if (price === null) return;
      const minutes = prompt("عدد الدقائق:", p.minutes); if (minutes === null) return;
      const desc = prompt("الوصف:", p.description) ?? p.description;
      try { await api("/api/admin/plans/" + p.id, { method: "PATCH", json: { name, price: +price, minutes: +minutes, description: desc, is_active: !!p.is_active, sort: p.sort } }); toast("تم الحفظ"); loadAdminPlans(); } catch (e) { toast(e.message, true); }
    });
  } catch (e) { toast(e.message, true); }
}
$("addPlanBtn").onclick = async () => {
  const name = prompt("اسم الباقة:"); if (!name) return;
  const price = +prompt("السعر (شهري):", "0"); const minutes = +prompt("عدد الدقائق:", "0");
  const desc = prompt("الوصف:", "") || "";
  try { await api("/api/admin/plans", { json: { name, price, minutes, description: desc, is_active: true, sort: 9 } }); loadAdminPlans(); } catch (e) { toast(e.message, true); }
};

async function loadAllKeys() {
  try {
    const r = await api("/api/admin/keys");
    $("allKeysTable").querySelector("tbody").innerHTML = (r.keys || []).map((k) => `
      <tr><td dir="ltr">${esc(k.email)}</td><td>${esc(k.name)}</td><td dir="ltr" class="muted">${esc(k.key_prefix)}</td>
      <td>${fmtDate(k.created_at)}</td><td>${k.last_used_at ? fmtDate(k.last_used_at) : "—"}</td>
      <td>${k.revoked_at ? '<span class="st-bad">ملغى</span>' : `<button class="btn sm danger" data-krev="${k.id}">إلغاء</button>`}</td></tr>`).join("")
      || '<tr><td colspan="6" class="muted">لا مفاتيح</td></tr>';
    $("allKeysTable").querySelectorAll("[data-krev]").forEach((b) => b.onclick = async () => {
      try { await api("/api/admin/keys/" + b.dataset.krev, { method: "DELETE" }); loadAllKeys(); } catch (e) { toast(e.message, true); }
    });
  } catch (e) { toast(e.message, true); }
}

const SETTING_LABELS = {
  app_name: "اسم الموقع", assistant_name: "اسم المساعد", currency: "رمز العملة",
  price_per_minute: "سعر الدقيقة الإضافية", free_minutes_signup: "دقائق مجانية عند التسجيل",
  allow_register: "بدّل التسجيل دخول  (1 يدعم / 0 يمنع)", warm_models: "تحميل النماذج عند الإقلاع (1/0)",
  system_prompt_voice: "برومبت الشخصية الصوتية", system_prompt_text: "برومبت الشخصية النصية",
  llm_max_new_tokens_voice: "أقصى طول رد صوتي (توكن)", llm_max_new_tokens_text: "أقصى طول رد نصي (توكن)",
  llm_temperature: "درجة الحرارة", llm_top_p: "top p", llm_top_k: "top k",
  reasoning_effort_voice: "مستوى تفكير الصوتي (high|medium|low)", reasoning_effort_text: "مستوى تفكير النصي",
  min_billing_seconds: "أقل ثوانٍ للفوترة", tts_speed: "سرعة الاصطياع", vad_silence_ms: "صمت نهاية الكلام (مث)",
  vad_energy: "عتبة الطاقة", vad_min_speech_ms: "أقل كلام (مث)",
};
async function loadSettings() {
  try {
    const r = await api("/api/admin/settings");
    $("settingsForm").innerHTML = Object.entries(r.settings).map(([k, v]) => {
      const label = SETTING_LABELS[k] || k;
      if (k.startsWith("system_prompt")) {
        return `<div class="field full"><label>${label}</label><textarea data-k="${k}" dir="rtl">${esc(v)}</textarea></div>`;
      }
      if (v.length > 60) {
        return `<div class="field full"><label>${label}</label><input data-k="${k}" value="${esc(v)}"></div>`;
      }
      return `<div class="field"><label>${label}</label><input data-k="${k}" value="${esc(v)}"></div>`;
    }).join("");
  } catch (e) { toast(e.message, true); }
}
$("saveSettingsBtn").onclick = async () => {
  const payload = {};
  $("settingsForm").querySelectorAll("[data-k]").forEach((el) => payload[el.dataset.k] = el.value);
  try { await api("/api/admin/settings", { method: "PUT", json: payload }); $("settingsSaved").classList.remove("hidden"); setTimeout(() => $("settingsSaved").classList.add("hidden"), 2000); toast("حُفظت الإعدادات ✓"); }
  catch (e) { toast(e.message, true); }
};

async function loadAudit() {
  try {
    const r = await api("/api/admin/audit?limit=150");
    $("auditTable").querySelector("tbody").innerHTML = (r.entries || []).map((a) => `
      <tr><td>${a.id}</td><td dir="ltr" class="muted">${esc(a.actor_email || "system")}</td>
      <td><code>${esc(a.action)}</code></td><td>${esc(a.target)}</td><td>${fmtDate(a.created_at)}</td></tr>`).join("");
  } catch (e) { toast(e.message, true); }
}

/* ═══════════════ بدء ═══════════════ */
go((location.hash || "#/chat").replace("#/", ""));
boot();
})();
