// Terminal sungguhan di panel kanan: sesi zsh di PTY (ptyterm.py) dirender dengan xterm.js.
// Output: long-poll GET /api/pty/read; input: POST /api/pty/write. Banyak sesi (tab), dan
// sesi tetap hidup saat halaman di-refresh (output lama diputar ulang).

const TERM_THEME = {
  background: "#0b0e14", foreground: "#d6deeb", cursor: "#80a4c2", selectionBackground: "#264f78",
  black: "#1d2330", red: "#ef5350", green: "#22da6e", yellow: "#c5e478", blue: "#82aaff", magenta: "#c792ea",
  cyan: "#21c7a8", white: "#d6deeb", brightBlack: "#637777", brightRed: "#ef5350", brightGreen: "#22da6e",
  brightYellow: "#ffeb95", brightBlue: "#82aaff", brightMagenta: "#c792ea", brightCyan: "#7fdbca", brightWhite: "#ffffff",
};
const terms = {};      // id -> { id, title, term, fit, el, offset, alive, queue }
let termActive = null;

function termTabs() {
  const list = Object.values(terms);
  $("termTabs").innerHTML = list.map((t) => `<button class="term-tab ${t.id === termActive ? "active" : ""}" data-term="${t.id}">
      <span class="dot ${t.alive ? "on" : ""}"></span>${esc(t.title)}<span class="term-x" data-term-close="${t.id}" title="${esc(window.t("term.closeTip"))}">×</span></button>`).join("")
    + `<button class="term-tab term-new" id="termNew" title="${esc(t("term.newTip"))}">＋</button>`;
}

function termShow(id) {
  termActive = id;
  for (const t of Object.values(terms)) t.el.hidden = t.id !== id;
  termTabs();
  const t = terms[id];
  if (t) requestAnimationFrame(() => { try { t.fit.fit(); } catch {} t.term.focus(); });
}

function termAttach(id, title, alive = true) {
  const el = document.createElement("div");
  el.className = "term-pane";
  $("termHost").append(el);
  const term = new Terminal({
    fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace', fontSize: 13, lineHeight: 1.15,
    cursorBlink: true, allowProposedApi: true, scrollback: 10000, macOptionIsMeta: true, theme: TERM_THEME,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon((e, url) => window.open(url, "_blank", "noopener")));
  term.open(el);
  // Ctrl+` dipakai untuk buka/tutup panel, jangan dikirim ke shell
  term.attachCustomKeyEventHandler((e) => !(e.ctrlKey && e.key === "`"));
  const t = terms[id] = { id, title, term, fit, el, offset: 0, alive, queue: "", sending: false };
  term.onData((d) => { t.queue += d; termFlush(t); });
  term.onResize(({ cols, rows }) => { if (t.alive) api("/api/pty/resize", { id, cols, rows }).catch(() => {}); });
  term.onTitleChange((s) => { if (s) { t.title = s.replace(/^.*?:\s*/, "").slice(0, 28); termTabs(); } });
  termPoll(t);
  return t;
}

// kirim ketikan berurutan; ketikan cepat digabung jadi satu request
async function termFlush(t) {
  if (t.sending || !t.queue || !t.alive) return;
  t.sending = true;
  const data = t.queue;
  t.queue = "";
  try { await api("/api/pty/write", { id: t.id, data }); } catch { /* sesi berakhir */ }
  t.sending = false;
  if (t.queue) termFlush(t);
}

async function termPoll(t) {
  while (terms[t.id] === t) {
    let d;
    try { d = await api(`/api/pty/read?id=${t.id}&offset=${t.offset}`); }
    catch { t.alive = false; break; }
    if (d.data) {
      const bin = atob(d.data), bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      t.term.write(bytes);
    }
    t.offset = d.offset;
    if (!d.alive) {
      t.alive = false;
      t.term.write(`\r\n\x1b[90m[${window.t("term.ended")}${d.code != null ? `, exit ${d.code}` : ""} — ${window.t("term.pressNew")}]\x1b[0m\r\n`);
      termTabs();
      break;
    }
  }
}

async function termNew(command = "", cwd = "~") {
  const host = $("termHost");
  // perkiraan ukuran awal agar prompt pertama tidak terpotong
  const cols = Math.max(40, Math.floor((host.clientWidth - 16) / 7.8)), rows = Math.max(10, Math.floor((host.clientHeight - 8) / 17));
  const r = await api("/api/pty/new", { command, cwd, cols, rows });
  const t = termAttach(r.id, r.title);
  termShow(r.id);
  setTimeout(() => { try { t.fit.fit(); } catch {} }, 60);
  return t;
}

async function termClose(id) {
  const t = terms[id];
  if (!t) return;
  if (t.alive && !confirm(window.t("term.closeConfirm", { title: t.title }))) return;
  delete terms[id];
  api("/api/pty/kill", { id }).catch(() => {});
  t.term.dispose();
  t.el.remove();
  const rest = Object.keys(terms);
  if (rest.length) termShow(rest.at(-1)); else termTabs();
}

// dipanggil panelView("term"): pastikan ada sesi, lalu fokus
let termInit = null;
function terminalShown() {
  termInit ??= api("/api/pty/list").then(({ sessions }) => {
    for (const s of sessions.filter((s) => s.alive)) termAttach(s.id, s.title);
  }).catch(() => {});
  termInit.then(() => {
    const ids = Object.keys(terms);
    if (!ids.length) termNew().catch((e) => toast(e.message, true));
    else termShow(termActive && terms[termActive] ? termActive : ids.at(-1));
  });
}

$("termTabs").onclick = (e) => {
  const x = e.target.closest("[data-term-close]");
  if (x) { e.stopPropagation(); return termClose(x.dataset.termClose); }
  if (e.target.closest("#termNew")) return termNew().catch((err) => toast(err.message, true));
  const b = e.target.closest("[data-term]");
  if (b) termShow(b.dataset.term);
};
new ResizeObserver(() => { const t = terms[termActive]; if (t && !t.el.hidden) try { t.fit.fit(); } catch {} }).observe($("termHost"));

// ↗ buka di aplikasi terminal (Terminal / iTerm / Warp) di folder sesi aktif
api("/api/terminal/apps").then(({ apps }) => {
  const sel = $("termApp");
  sel.innerHTML = apps.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  try { const saved = localStorage.getItem("termApp"); if (apps.some((a) => a.id === saved)) sel.value = saved; } catch {}
  sel.onchange = () => { try { localStorage.setItem("termApp", sel.value); } catch {} };
}).catch(() => {});
$("termExt").onclick = async () => {
  try {
    const r = await api("/api/terminal/open", { command: "", cwd: "~", app: $("termApp").value });
    toast(t("term.opened", { app: r.app }));
  } catch (err) { toast(err.message, true); }
};

// Dipakai halaman lain: buka panel & jalankan perintah di sesi terminal baru
window.runInTerminal = async (command, cwd) => {
  panelOpen("term");
  await (termInit ?? Promise.resolve());
  return termNew(command, cwd);
};

// Открыть панель терминала на конкретной сессии (в т.ч. запущенной сервером для задачи агента).
window.focusSession = async (id) => {
  panelOpen("term");
  await (termInit ?? Promise.resolve());
  if (!terms[id]) {
    const { sessions } = await api("/api/pty/list");
    const s = sessions.find((x) => String(x.id) === String(id) && x.alive);
    if (!s) return toast(t("tasks.sessionGone"), true);
    termAttach(s.id, s.title);
  }
  termShow(String(id));
};
