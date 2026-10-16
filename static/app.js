// Service Admin — frontend. Semua tombol memakai data-act="..." (event delegation).
const $ = (id) => document.getElementById(id);
const view = $("view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const attrs = (o) => Object.entries(o).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ");
const btn = (label, act, data = {}, cls = "", extra = "") =>
  `<button class="${cls}" data-act="${act}" ${attrs(data)} ${extra}>${label}</button>`;

// ---- helper tampilan bersama (dipakai halaman fase 1: Profil/Projects/Mobile/AI) ----
// Logo kalau ada di icons.js, kalau tidak jatuh ke lencana huruf.
function iconOr(key, label) {
  const svg = key ? logoSvg(key, "lang-logo") : "";
  return svg || `<span class="lang-logo pkg-fallback">${esc(String(label || "?").slice(0, 2))}</span>`;
}
// Spanduk "mode baca saja" — fase 1 tidak mengubah apa pun.
function roBanner(html) {
  return `<div class="ro-banner"><span class="ro-tag">${esc(t("common.readonly"))}</span><span>${html}</span></div>`;
}
const roTag = () => `<span class="badge blue">${esc(t("common.readonly"))}</span>`;
const kvList = (pairs) => `<dl class="kv2">${pairs.filter(Boolean)
  .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
const monoPath = (s) => `<span class="mono">${esc(String(s ?? "").replace(/^\/Users\/[^/]+/, "~"))}</span>`;
const chipList = (items) => (items && items.length
  ? `<div class="chips">${items.map((i) => `<span class="badge">${esc(i)}</span>`).join("")}</div>`
  : `<span class="muted small">—</span>`);

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "service-admin" },
    body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  const d = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) {
    // Ошибка с кодом переводится на выбранный язык (err.<код>); нет перевода — текст от сервера как есть.
    const key = d.code ? `err.${d.code}` : null;
    const known = key && ((I18N[LANG] || {})[key] ?? I18N.ru[key]);
    const e = new Error(known ? t(key, d.params || {}) : (d.error || `HTTP ${r.status}`));
    e.code = d.code || null; e.params = d.params || {};
    throw e;
  }
  return d;
}

function toast(msg, bad = false) {
  const t = $("toast");
  t.textContent = msg; t.className = "toast show" + (bad ? " bad" : "");
  clearTimeout(t._h); t._h = setTimeout(() => (t.className = "toast"), 4000);
}

function showLog(title, text) {
  $("logTitle").textContent = title;
  $("logBody").textContent = text;
  $("logDlg").showModal();
  $("logBody").scrollTop = $("logBody").scrollHeight;
}

// ------------------------------------------------------------ panel terminal & proses
// Panel kanan (ikon terminal di header / Ctrl+`) punya 2 tab:
//  - Terminal: shell zsh sungguhan (PTY + xterm.js, lihat terminal.js) — claude, vim, htop jalan normal.
//  - Proses: job background (brew install, laravel new, docker ...). Titik merah = ada yang berjalan.
const jobs = {};          // id -> { id, label, done, code, text, offset }
let jobShown = null;      // job yang ditampilkan di tab Proses

function panelView(v) {
  $("viewTerm").hidden = v !== "term";
  $("viewJobs").hidden = v !== "jobs";
  document.querySelectorAll("#panelTabs button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  if (v === "term") terminalShown?.();
}
function panelOpen(view) {
  $("job").classList.add("show");
  panelView(view || ($("viewJobs").hidden ? "term" : "jobs"));
}
const panelClose = () => $("job").classList.remove("show");
$("panelTabs").onclick = (e) => { const b = e.target.closest("[data-view]"); if (b) panelView(b.dataset.view); };
$("jobBtn").onclick = () => {
  if ($("job").classList.contains("show")) return panelClose();
  panelOpen(Object.values(jobs).some((j) => !j.done) ? "jobs" : "term");
};
$("jobClose").onclick = panelClose;
// Ctrl+` membuka/menutup panel (fase capture supaya tetap jalan saat fokus di xterm)
window.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key === "`") { e.preventDefault(); e.stopPropagation(); $("jobBtn").click(); }
}, true);

// Строки журнала job приходят с сервера по-русски; в EN-интерфейсе переводим стандартные.
function jobLine(l) {
  if (LANG !== "en") return l;
  return l.replace(/^(\n?)✅ Готово\.$/, "$1✅ Done.").replace(/^⏹ {2}Остановлено\.$/, "⏹  Stopped.")
    .replace(/^❌ Сбой на шаге (\d+) \(exit (-?\d+)\)\.$/, "❌ Failed at step $1 (exit $2).")
    .replace(/^⚠️ {2}Этот шаг завершился с ошибкой \(exit (-?\d+)\), пропущен\.$/, "⚠️  This step failed (exit $1) and was skipped.");
}

/** Ввод секрета (токен): поле-пароль вместо prompt(), который показывает текст открытым. → строка или null при отмене. */
function askSecret(label) {
  return new Promise((resolve) => {
    const d = document.createElement("dialog");
    d.className = "secret-dlg";
    d.innerHTML = `<form method="dialog"><p>${esc(label)}</p>
      <input type="password" name="secret" autocomplete="off" spellcheck="false" style="width:100%">
      <div class="row" style="gap:8px;margin-top:12px;justify-content:flex-end">
        <button type="button" data-act="cancel">${esc(t("common.cancel"))}</button><button type="submit" class="primary">OK</button></div></form>`;
    const done = (v) => { d.close(); d.remove(); resolve(v); };
    d.querySelector("form").addEventListener("submit", (e) => { e.preventDefault(); done(d.querySelector("input").value); });
    d.querySelector('[data-act="cancel"]').addEventListener("click", () => done(null));
    d.addEventListener("cancel", (e) => { e.preventDefault(); done(null); });
    document.body.appendChild(d);
    d.showModal();
    d.querySelector("input").focus();
  });
}

function jobIcon(j) { return j.done ? (j.code === 0 ? "✅" : "❌") : "⏳"; }
function jobStatusText(j) {
  if (!j.done) return t("shell.running");
  return j.code === 0 ? t("shell.done") : t("shell.failed", { code: j.code });
}
function renderJobs() {
  const list = Object.values(jobs).sort((a, b) => b.id - a.id);
  const running = list.some((j) => !j.done);
  $("jobDot").hidden = !running;
  $("jobDot2").hidden = !running;
  $("jobBtn").title = running ? t("shell.runningHint") : t("shell.terminal");
  $("jobList").innerHTML = list.map((j) => `<button class="job-item ${j.id === jobShown ? "active" : ""}" data-job="${j.id}">
    ${jobIcon(j)} ${esc(j.label)}</button>`).join("") || `<div class="muted small" style="padding:10px 16px">${esc(t("shell.noJobs"))}</div>`;
  const j = jobs[jobShown];
  $("jobTitle").textContent = j ? `${jobIcon(j)} ${j.label} — ${jobStatusText(j)}` : t("shell.pickJob");
  const out = $("jobOut");
  if (j && out.dataset.job !== String(j.id)) { out.dataset.job = j.id; out.textContent = j.text; out.scrollTop = out.scrollHeight; }
  if (!j) { out.dataset.job = ""; out.textContent = t("shell.jobHint"); }
  $("jobStop").hidden = !j || j.done;
}
function openJobs(id) {
  if (id) jobShown = id;
  panelOpen("jobs");
  renderJobs();
}
$("jobList").onclick = (e) => { const b = e.target.closest("[data-job]"); if (b) { jobShown = +b.dataset.job; $("jobOut").dataset.job = ""; renderJobs(); } };
$("jobStop").onclick = async () => {
  if (jobShown) try { await api("/api/job/cancel", { id: jobShown }); } catch (err) { toast(err.message, true); }
};

async function followJob(id, onDone) {
  const j = jobs[id];
  for (;;) {
    let d;
    try { d = await api(`/api/job?id=${id}&offset=${j.offset}`); } catch (e) { toast(e.message, true); break; }
    j.label = d.label;
    if (d.lines.length) {
      j.text += d.lines.map(jobLine).join("\n") + "\n";
      if (jobShown === id) { const out = $("jobOut"); const end = out.scrollTop + out.clientHeight >= out.scrollHeight - 30;
        out.textContent = j.text; if (end) out.scrollTop = out.scrollHeight; }
    }
    j.offset = d.offset;
    if (d.done) {
      Object.assign(j, { done: true, code: d.code });
      renderJobs();
      toast(d.code === 0 ? `✅ ${d.label} — ${t("shell.done")}`
                         : `❌ ${d.label} — ${t("shell.failed", { code: d.code })}`, d.code !== 0);
      break;
    }
    renderJobs();
    await new Promise((r) => setTimeout(r, 800));
  }
  onDone?.();
}

// Команду с правами администратора НЕ печатаем в терминал панели (он доступен процессам того же пользователя): копируем и показываем — выполнить в своём терминале.
window.showAdminCommand = async (cmd) => {
  try { await navigator.clipboard.writeText(cmd); } catch { /* буфер может быть недоступен */ }
  prompt(t("admin.runInOwnTerminal"), cmd);
};

async function runJob(promise, onDone) {
  let id, r;
  try { r = await promise; id = +r.job; } catch (e) { return toast(e.message, true); }
  if (r && r.terminal) return window.showAdminCommand(r.terminal);  // Linux без экрана: команду выполняет человек в СВОЁМ терминале
  jobs[id] = { id, label: "…", done: false, code: null, text: "", offset: 0 };
  jobShown = id;
  $("jobOut").dataset.job = "";
  renderJobs();
  toast(`⏳ ${t("shell.running")} — ${t("shell.tab.jobs")} · Ctrl+\``);
  return followJob(id, onDone);
}

// setelah refresh halaman: ambil proses yang masih berjalan di server
api("/api/jobs").then(({ jobs: list }) => {
  for (const j of list.reverse()) {
    jobs[+j.id] = { id: +j.id, label: j.label, done: j.done, code: j.code, text: "", offset: 0 };
    followJob(+j.id);
  }
  if (list.length) jobShown = +list[list.length - 1].id;
  renderJobs();
}).catch(() => {});

// Задачи, запущенные НЕ с этой страницы (например, ИИ-агентом через шлюз), тоже должны быть видны человеку:
// раз в несколько секунд подхватываем новые задачи сервера и показываем их во вкладке «Процессы».
let jobSyncBusy = false;
async function syncServerJobs() {
  if (jobSyncBusy || document.hidden) return;
  jobSyncBusy = true;
  try {
    const { jobs: list } = await api("/api/jobs");
    for (const j of list.slice().reverse()) {
      if (jobs[+j.id]) continue;
      jobs[+j.id] = { id: +j.id, label: j.label, done: j.done, code: j.code, text: "", offset: 0 };
      if (!j.done) { jobShown = +j.id; $("jobOut").dataset.job = ""; toast(`⏳ ${j.label} — ${t("shell.tab.jobs")} · Ctrl+\``); }
      followJob(+j.id);
    }
    renderJobs();
  } catch (e) { /* сервер недоступен — повторим в следующий раз */ } finally { jobSyncBusy = false; }
}
setInterval(syncServerJobs, 4000);

// ------------------------------------------------------------ router
const tabs = {};
let current, refreshTimer;
let currentNav = "dashboard";

// Judul header mengikuti item sidebar yang aktif (logo + label), atau
// tab.title/tab.titleKey kalau halamannya punya judul sendiri.
function updatePageTitle() {
  if (current?.titleKey) {
    $("pageTitle").innerHTML = (current.logo ? logoSvg(current.logo, "title-logo") : "") + esc(t(current.titleKey));
    return;
  }
  if (current?.title) {
    $("pageTitle").innerHTML = (current.logo ? logoSvg(current.logo, "title-logo") : "") + esc(current.title);
    return;
  }
  const a = document.querySelector(`#tabs a[href="#${currentNav}"]`);
  if (!a) { $("pageTitle").textContent = t("nav.dashboard"); return; }
  const logo = a.querySelector(".logo-i");
  const label = a.querySelector(".nav-name")?.textContent || "";
  $("pageTitle").innerHTML = (logo ? logo.outerHTML.replace('class="logo-i', 'class="logo-i title-logo') : "") + esc(label);
}

let lastHash = location.hash;
async function route() {
  const leavingEditor = current === tabs.config && !location.hash.startsWith("#config");
  if (leavingEditor && location.hash !== lastHash && !tabs.config.leaveOk()) {
    history.replaceState(null, "", lastHash);
    return;
  }
  lastHash = location.hash;
  // pindah file di dalam halaman Konfigurasi: cukup buka file lain, tanpa render ulang halaman
  if (current === tabs.config && location.hash.startsWith("#config:") && $("cfgMain")) {
    const id = decodeURIComponent(location.hash.slice(8));
    if (tabs.config.leaveOk()) { tabs.config.dirty = false; tabs.config.open(id); }
    return;
  }
  if (leavingEditor) tabs.config.dirty = false;
  // hash: "#key" atau "#key:param" (mis. #service:mysql@9.7); alias lama tetap jalan
  const first = location.hash.slice(1).split(":")[0];
  if (typeof HASH_ALIASES !== "undefined" && HASH_ALIASES[first]) {   // старые адреса (#setup, #snapshots…) → новые (#start:setup, #history:snapshots…), параметры сохраняются
    history.replaceState(null, "", "#" + HASH_ALIASES[first] + location.hash.slice(1 + first.length));
    lastHash = location.hash;
  }
  const [rawKey, ...rest] = location.hash.slice(1).split(":");
  const key = ({ services: "packages", apps: "packages", zsh: "config" })[rawKey] || rawKey;
  const tab = tabs[key] || tabs.dashboard;
  tab.param = decodeURIComponent(rest.join(":"));
  const name = tab.nav || (tabs[key] ? key : "dashboard");
  current?.leave?.();
  current = tab;
  currentNav = name;
  document.querySelectorAll("#tabs a:not(#navTech a)").forEach((a) => a.classList.toggle("active", a.hash === "#" + name));
  if (typeof navMarkActive === "function") navMarkActive();   // пункты языков и сервисов (navtree.js) подсвечивает само меню
  updatePageTitle();
  $("headline").textContent = "";
  document.body.classList.remove("nav-open");
  clearInterval(refreshTimer);
  view.innerHTML = `<div class="loading">${esc(t("shell.loading"))}</div>`;
  await tab.load();
  if (tab.interval) refreshTimer = setInterval(() => current === tab && !document.hidden && tab.load(true), tab.interval);
}
window.addEventListener("hashchange", route);

const handlers = {};
document.addEventListener("click", async (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || !handlers[el.dataset.act]) return;
  e.preventDefault();
  if (el.dataset.confirm && !confirm(el.dataset.confirm)) return;
  el.disabled = true;
  try { await handlers[el.dataset.act](el.dataset, el); }
  catch (err) { toast(err.message, true); }
  finally { el.disabled = false; }
});

const failView = (e) => {
  if (e.code === "tool_missing") {
    view.innerHTML = `<div class="card"><div class="name">${esc(t("err.toolMissing.title", e.params))}</div>
      <p class="muted">${esc(t("err.toolMissing.body", e.params))}</p>
      <div class="row" style="gap:8px"><a href="#setup"><button class="primary">${esc(t("nav.setup"))}</button></a>
        <a href="#profiles"><button>${esc(t("nav.profiles"))}</button></a></div></div>`;
    return;
  }
  view.innerHTML = `<div class="err">${esc(t("shell.loadFailed"))}\n${esc(e.message)}</div>`;
};

// ------------------------------------------------------------ PHP
tabs.php = {
  async load() {
    let d;
    try { d = await api("/api/php"); } catch (e) { return failView(e); }
    $("headline").textContent = t("app.php.active", { v: d.shell.version || "-" });
    const sel = d.selected;
    const warn = sel && !d.shim_active
      ? `<div class="warn">⚠️ ${t("app.php.shimWarn", { path: esc(d.shell.path) })}</div>` : "";
    const rows = d.versions.map((v) => `<div class="card item">
        <div>
          <div class="name">PHP ${esc(v.version)} <span class="badge ${v.source === "Herd" ? "blue" : ""}">${v.source}</span>
            ${sel === v.id ? `<span class="badge green">${esc(t("app.badge.default"))}</span>` : ""}</div>
          <div class="meta"><code>${esc(v.bin)}</code></div>
        </div>
        <div class="actions">${sel === v.id ? "" : btn(t("app.makeDefault"), "phpSel", { id: v.id }, "primary")}</div>
      </div>`).join("");
    const herd = d.herd.length ? `
      <h2>${esc(t("app.php.herdVersions"))}</h2>
      <div class="table-wrap"><table><tr><th>${esc(t("common.version"))}</th><th>${esc(t("common.status"))}</th><th></th></tr>
      ${d.herd.map((h) => `<tr><td><b>${esc(h.version)}</b> ${h.global ? `<span class="badge blue">${esc(t("app.php.herdGlobal"))}</span>` : ""}</td>
        <td>${h.installed ? `<span class="badge green">${esc(t("common.installed"))}</span>` : `<span class="muted small">${esc(t("app.notInstalled"))}</span>`}
            ${h.update ? `<span class="badge amber">${esc(t("app.updateAvail"))}</span>` : ""}</td>
        <td><div class="actions">
          ${!h.installed ? btn(t("app.install"), "herd", { action: "install", version: h.version }, "go") : ""}
          ${h.update ? btn(t("app.update"), "herd", { action: "update", version: h.version }) : ""}
        </div></td></tr>`).join("")}
      </table></div>` : "";
    view.innerHTML = `
      <p style="margin:0 0 12px"><a href="#langs">${esc(t("app.backLangs"))}</a></p>
      <div class="stat">
        <div class="card"><div>${esc(t("app.newTermUses"))}</div><div>PHP ${esc(d.shell.version || t("app.notFoundLower"))}</div>
          <div class="muted small"><code>${esc(d.shell.path || "-")}</code></div></div>
        <div class="card"><div>${esc(t("app.php.adminDefault"))}</div><div>${esc(sel ? d.versions.find((v) => v.id === sel)?.version ?? sel : t("app.notSet"))}</div>
          <div class="muted small">${esc(sel ? t("app.viaShimBin") : t("app.followsPath"))}</div></div>
      </div>
      ${warn}
      <h2 class="row">${esc(t("app.php.pickDefault"))} <span class="spacer"></span>
        ${sel ? btn(t("app.php.removeOverride"), "phpSel", { id: "default" }, "", `title="${esc(t("app.php.removeOverrideTip"))}"`) : ""}</h2>
      <div class="list">${rows}</div>
      <p class="muted small">${t("app.php.note", { pk: `<a href="#packages">${esc(t("nav.packages"))}</a>` })}</p>
      <div id="verCard"></div>
      ${herd}`;
    fillBrewVersions($("verCard"), "/api/lang/versions?key=php");   // php@8.1…8.4 из Homebrew — как у остальных языков
  },
};
handlers.phpSel = async (d) => {
  await api("/api/php/select", { id: d.id });
  toast(d.id === "default" ? t("app.php.overrideRemoved") : t("app.php.defaultChanged"));
  await tabs.php.load();
  refreshNav();
};
handlers.herd = (d) => runJob(api("/api/php/herd", { action: d.action, version: d.version }), () => tabs.php.load());

// ------------------------------------------------------------ Node.js
tabs.node = {
  async load() {
    let d;
    try { d = await api("/api/node"); } catch (e) { return failView(e); }
    $("headline").textContent = t("app.node.active", { v: d.shell.version || "-" });
    if (!d.nvm) {
      view.innerHTML = `<div class="warn">${t("app.node.noNvm", { pk: `<a href="#packages">${esc(t("nav.packages"))}</a>` })}</div>`;
      return;
    }
    const broken = d.default_resolved === "N/A";
    const isDefault = (v) => d.default_alias === v || d.default_resolved === v;
    const row = (v, label, extra = "", removable = true) => `<div class="card item">
        <div><div class="name">${label} ${isDefault(v) ? `<span class="badge green">${esc(t("app.badge.default"))}</span>` : ""}
          ${d.shell.version === (v === "system" ? d.system : v) ? `<span class="badge blue">${esc(t("app.node.usedByTerm"))}</span>` : ""}</div>
          <div class="meta">${extra}</div></div>
        <div class="actions">
          ${isDefault(v) ? "" : btn(t("app.makeDefault"), "nodeDefault", { version: v }, "primary")}
          ${removable && !isDefault(v) ? btn(t("app.uninstall"), "nodeJob", { action: "uninstall", version: v, confirm: t("app.node.confirmUninstall", { v }) }, "danger") : ""}
        </div></div>`;
    view.innerHTML = `
      <p style="margin:0 0 12px"><a href="#langs">${esc(t("app.backLangs"))}</a></p>
      <div class="stat">
        <div class="card"><div>${esc(t("app.newTermUses"))}</div><div>Node ${esc(d.shell.version || t("app.notFoundLower"))}</div>
          <div class="muted small"><code>${esc(d.shell.path || "-")}</code></div></div>
        <div class="card"><div>${esc(t("app.node.nvmDefault"))}</div><div>${esc(d.default_alias || "-")}</div>
          <div class="muted small">→ ${esc(d.default_resolved || "-")}</div></div>
      </div>
      ${broken ? `<div class="warn">⚠️ ${t("app.node.brokenWarn", { alias: esc(d.default_alias), sys: esc(d.system || "-") })}</div>` : ""}
      <h2>${esc(t("app.node.installedH"))}</h2>
      <div class="list">
        ${d.installed.map((v) => row(v, `Node ${esc(v)}`, `<code>~/.nvm/versions/node/${esc(v)}</code>`)).join("")}
        ${d.system ? row("system", `Node ${esc(d.system)} <span class="badge">Homebrew</span>`, `<code>/opt/homebrew/bin/node</code>`, false) : ""}
      </div>
      <h2>${esc(t("app.node.installNew"))}</h2>
      <form class="row" id="nodeInstall">
        <input type="text" id="nodeVer" placeholder="${esc(t("app.node.verPh"))}" style="width:200px">
        <button class="go">${esc(t("app.install"))}</button>
        <span class="spacer"></span>${btn(t("app.node.showLts"), "nodeRemote")}
      </form>
      <div class="list" id="nodeRemote" style="margin-top:10px"></div>
      <p class="muted small">${t("app.node.note")}</p>`;
    $("nodeInstall").onsubmit = (e) => {
      e.preventDefault();
      const v = $("nodeVer").value.trim();
      if (v) handlers.nodeJob({ action: "install", version: v });
    };
  },
};
handlers.nodeDefault = async (d) => {
  await api("/api/node/action", { action: "default", version: d.version });
  toast(t("app.node.defaultSet", { v: d.version }));
  await tabs.node.load();
  refreshNav();
};
handlers.nodeJob = (d) => runJob(api("/api/node/action", { action: d.action, version: d.version }), () => tabs.node.load());
handlers.nodeRemote = async () => {
  $("nodeRemote").innerHTML = `<div class="loading">${esc(t("app.node.fetching"))}</div>`;
  const { lts } = await api("/api/node/remote");
  $("nodeRemote").innerHTML = lts.slice(0, 6).map((r) => `<div class="card item">
      <div class="name">${esc(r.version)} <span class="badge">${esc(r.codename)}</span></div>
      <div class="actions">${btn(t("app.install"), "nodeJob", { action: "install", version: r.version }, "go")}</div>
    </div>`).join("");
};

// ------------------------------------------------------------ Herd
tabs.herd = {
  async load() {
    let d;
    try { d = await api("/api/herd"); } catch (e) { return failView(e); }
    if (!d.installed) { view.innerHTML = `<div class="warn">${t("app.herd.notInstalled", { pk: `<a href="#packages">${esc(t("nav.packages"))}</a>` })}</div>`; return; }
    const p = d.processes, running = p.nginx && p.fpm.length;
    $("headline").textContent = t("app.herd.headline", { v: d.version, n: d.sites.length });
    const phpOpts = (site) => [`<option value="global" ${site.isolated ? "" : "selected"}>${esc(t("app.herd.globalOpt", { v: d.global_php }))}</option>`]
      .concat(d.php_installed.map((v) => `<option value="${esc(v)}" ${site.isolated && site.php === v ? "selected" : ""}>PHP ${esc(v)}</option>`)).join("");
    const proc = (on, label) => `<span class="row"><span class="dot ${on ? "on" : ""}"></span>${label}</span>`;
    const sites = d.sites.map((s) => `<tr>
        <td><b>${esc(s.name)}</b> ${s.linked ? `<span class="badge">link</span>` : `<span class="badge">parked</span>`}
          ${s.has_db ? `<span class="badge" title="${esc(t("app.herd.dbTip"))}">db</span>` : ""}
          <div class="muted small"><code>${esc(s.path)}</code></div></td>
        <td><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url.replace(/^https?:\/\//, ""))}</a>
          ${s.secured ? `<span class="badge green" title="${esc(t("app.herd.httpsTip"))}">🔒 HTTPS</span>` : `<span class="badge">HTTP</span>`}</td>
        <td><select data-herd-php="${esc(s.name)}">${phpOpts(s)}</select></td>
        <td class="small muted">${esc(s.node || "-")}</td>
        <td><div class="actions">
          ${s.secured ? btn(t("app.herd.httpsOff"), "herdSite", { action: "unsecure", name: s.name })
                      : btn(t("app.herd.httpsOn"), "herdSite", { action: "secure", name: s.name }, "go")}
          ${btn(t("app.herd.folder"), "herdQuick", { action: "folder", name: s.name })}
          ${s.linked ? btn("Unlink", "herdSite", { action: "unlink", name: s.name, confirm: t("app.herd.confirmUnlink", { name: s.name }) }, "danger") : ""}
        </div></td></tr>`).join("");
    const proxies = d.proxies.map((x) => `<tr><td><b>${esc(x.Site)}</b></td>
        <td><a href="${esc(x.URL)}" target="_blank" rel="noopener">${esc(x.URL)}</a></td><td><code>${esc(x.Host)}</code></td>
        <td><div class="actions">${btn(t("app.delete"), "herdSite", { action: "unproxy", name: x.Site, confirm: t("app.herd.confirmUnproxy", { name: x.Site }) }, "danger")}</div></td></tr>`).join("");
    const paths = d.paths.map((pa) => `<div class="card item"><div><code>${esc(pa)}</code>
        <div class="muted small">${t("app.herd.parkedHint", { tld: esc(d.tld) })}</div></div>
        <div class="actions">${pa.includes("/config/valet/Sites") ? "" : btn("Forget", "herdSite", { action: "forget", path: pa, confirm: t("app.herd.confirmForget", { path: pa }) }, "danger")}</div></div>`).join("");
    view.innerHTML = `
      <div class="card item" style="margin-bottom:14px">
        <div><div class="name"><span class="dot ${running ? "on" : "bad"}"></span>Laravel Herd ${esc(d.version)}
            <span class="badge">${esc(running ? t("common.running") : t("common.stopped"))}</span></div>
          <div class="meta">${proc(p.app, esc(t("app.herd.appProc")))}${proc(p.nginx, "Nginx")}${proc(p.dnsmasq, "DNS (dnsmasq)")}
            ${proc(p.fpm.length, `PHP-FPM ${p.fpm.join(", ") || ""}`)}<span>TLD <code>.${esc(d.tld)}</code></span>
            <span>${t("app.herd.globalPhp", { v: esc(d.global_php), link: `<a href="#php">${esc(t("app.change"))}</a>` })}</span></div></div>
        <div class="actions">
          ${running ? btn(t("app.restart"), "herdSite", { action: "restart" }) + btn(t("shell.stop"), "herdSite", { action: "stop", confirm: t("app.herd.confirmStop") }, "danger")
                    : btn(t("app.start"), "herdSite", { action: "start" }, "go")}
          ${btn(t("app.herd.newApp"), "newApp", {}, "primary")}
          ${btn(t("app.herd.openApp"), "herdQuick", { action: "open-app" })}
          ${btn(t("app.herd.logNginx"), "herdLog", { file: "nginx-error.log" })}${btn(t("app.herd.logFpm"), "herdLog", { file: "php-fpm.log" })}
        </div>
      </div>
      <h2>${esc(t("app.herd.sites"))}</h2>
      ${sites ? `<div class="table-wrap"><table><tr><th>${esc(t("app.herd.colSite"))}</th><th>URL</th><th>PHP</th><th>Node</th><th></th></tr>${sites}</table></div>` : `<div class="empty">${esc(t("app.herd.noSites"))}</div>`}
      <div class="grid two" style="margin-top:14px">
        <form class="card" id="herdLink">
          <h3>${esc(t("app.herd.addSite"))}</h3>
          <div class="list">
            <div class="row"><input type="text" name="path" id="herdPath" placeholder="${esc(t("app.herd.pathPh"))}" required style="flex:1">
              ${btn(t("app.herd.pickFolder"), "herdPick", {}, "primary")}</div>
            <div class="row"><input type="text" name="name" id="herdName" placeholder="${esc(t("app.herd.siteNamePh"))}" style="flex:1">
              <span class="muted small">.${esc(d.tld)}</span>
              <select name="php" id="herdPhp"><option value="">${esc(t("app.herd.phpGlobalOpt", { v: d.global_php }))}</option>${d.php_installed.map((v) => `<option value="${esc(v)}">PHP ${esc(v)}</option>`).join("")}</select></div>
            <div class="muted small" id="herdPickInfo"></div>
            <div class="row"><label class="chk"><input type="checkbox" name="secure" checked> HTTPS</label><span class="spacer"></span><button class="go">${esc(t("app.herd.link"))}</button></div>
          </div>
        </form>
        <form class="card" id="herdProxy">
          <h3>${esc(t("app.herd.proxyTitle"))} <span class="muted small">(Node, Vite, Docker, Reverb…)</span></h3>
          <div class="list">
            <div class="row"><input type="text" name="name" placeholder="${esc(t("app.herd.proxyNamePh"))}" required style="flex:1">
              <span class="muted small">.${esc(d.tld)}</span></div>
            <input type="text" name="host" placeholder="http://localhost:3000" required>
            <div class="row"><label class="chk"><input type="checkbox" name="secure" checked> HTTPS</label><span class="spacer"></span><button class="go">${esc(t("app.herd.makeProxy"))}</button></div>
          </div>
        </form>
      </div>
      <h2 class="row">${esc(t("app.herd.detected"))} <span class="muted small">${esc(t("app.herd.notLinked"))}</span></h2>
      <div id="herdSuggest"><div class="loading">${esc(t("app.herd.scanning"))}</div></div>
      <h2>Proxy</h2>
      ${proxies ? `<div class="table-wrap"><table><tr><th>${esc(t("app.herd.colName"))}</th><th>URL</th><th>${esc(t("app.herd.colTarget"))}</th><th></th></tr>${proxies}</table></div>` : `<div class="empty">${esc(t("app.herd.noProxies"))}</div>`}
      <h2 class="row">${esc(t("app.herd.parked"))} <span class="spacer"></span></h2>
      <div class="list">${paths}</div>
      <form class="row" id="herdPark" style="margin-top:10px">
        <input type="text" name="path" placeholder="/Users/you/Projects" style="flex:1;min-width:240px"><button>${esc(t("app.herd.parkBtn"))}</button>
      </form>
      <p class="muted small">${t("app.herd.proNote")}</p>`;
    view.querySelectorAll("[data-herd-php]").forEach((sel) => (sel.onchange = () =>
      runJob(api("/api/herd/action", { action: "php", name: sel.dataset.herdPhp, php: sel.value }), () => tabs.herd.load())));
    const form = (id, action) => ($(id).onsubmit = (e) => {
      e.preventDefault();
      const f = Object.fromEntries(new FormData(e.target));
      runJob(api("/api/herd/action", { action, ...f, secure: !!f.secure }), () => tabs.herd.load());
    });
    form("herdLink", "link"); form("herdProxy", "proxy"); form("herdPark", "park");
    this.herd = d;
    this.suggest();
  },
  // versi PHP Herd yang cocok dengan "require.php" di composer.json (mis. ^8.2)
  phpFor(constraint) {
    const m = /(\d+)\.(\d+)/.exec(constraint || "");
    if (!m) return "";
    const ok = (v) => { const [a, b] = v.split(".").map(Number); return a === +m[1] && b >= +m[2]; };
    if (ok(this.herd.global_php)) return "";  // global sudah cocok
    return this.herd.php_installed.filter(ok).sort()[0] || "";
  },
  fillForm(p) {
    $("herdPath").value = p.path;
    $("herdName").value = p.name;
    $("herdPhp").value = this.phpFor(p.php);
    $("herdPickInfo").innerHTML = [p.type && t("app.herd.detectedType", { type: esc(p.type) }), p.php && t("app.herd.needsPhp", { v: esc(p.php) })]
      .filter(Boolean).join(" · ");
  },
  async suggest() {
    let r;
    try { r = await api("/api/herd/suggest"); } catch (e) { $("herdSuggest").innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    this.projects = r.projects;
    $("herdSuggest").innerHTML = r.projects.length ? `<div class="list">${r.projects.map((p, i) => {
      const php = this.phpFor(p.php);
      return `<div class="card item">
        <div><div class="name">${esc(p.name)}<span class="muted small">.${esc(this.herd.tld)}</span>
            <span class="badge blue">${esc(p.type)}</span>${p.php ? `<span class="badge">PHP ${esc(p.php)}</span>` : ""}</div>
          <div class="meta"><code>${esc(p.path)}</code></div></div>
        <div class="actions">${btn(t("app.herd.configure"), "herdFill", { i })}
          ${btn(`Link${php ? ` (PHP ${php})` : ""}`, "herdQuickLink", { i }, "go")}</div></div>`;
    }).join("")}</div>` : `<div class="empty">${esc(t("app.herd.allServed"))}</div>`;
  },
};
handlers.herdSite = (d) => runJob(api("/api/herd/action", { action: d.action, name: d.name || "", path: d.path || "" }), () => { tabs.herd.load(); refreshNav(); });
handlers.herdPick = async () => {
  const start = $("herdPath").value || tabs.herd.projects?.[0]?.path?.replace(/\/[^/]+$/, "") || "~/Documents";
  toast(t("app.herd.finderOpened"));
  const r = await api("/api/pick-folder", { prompt: t("app.herd.pickPrompt"), start });
  if (!r.cancelled) tabs.herd.fillForm(r);
};
handlers.herdFill = (d) => { tabs.herd.fillForm(tabs.herd.projects[d.i]); $("herdPath").scrollIntoView({ behavior: "smooth", block: "center" }); };
handlers.herdQuickLink = (d) => {
  const p = tabs.herd.projects[d.i];
  return runJob(api("/api/herd/action", { action: "link", path: p.path, name: p.name, php: tabs.herd.phpFor(p.php), secure: true }),
    () => { tabs.herd.load(); refreshNav(); });
};
// ---- form aplikasi Laravel baru
handlers.newApp = async () => {
  const o = await api("/api/herd/new-options");
  const f = $("newAppForm");
  const radios = (name, opts, val) => `<div class="choice">${opts.map(([v, l, hint]) => `<label class="choice-item">
      <input type="radio" name="${name}" value="${v}" ${v === val ? "checked" : ""}><span><b>${l}</b>${hint ? `<small>${hint}</small>` : ""}</span></label>`).join("")}</div>`;
  f.innerHTML = `
    <div class="field"><label>${esc(t("app.na.projectName"))}</label>
      <input name="name" required placeholder="${esc(t("app.na.namePh"))}" pattern="[a-z0-9][a-z0-9_\-]*" autocomplete="off">
      <small id="naPreview" class="muted"></small></div>
    <div class="field"><label>${esc(t("app.na.location"))}</label>
      <div class="row"><input name="location" value="${esc(o.default_location)}" style="flex:1">${btn(t("app.na.pick"), "newAppPick")}</div>
      <small class="muted">${t("app.na.locHint")}</small></div>
    <div class="grid two">
      <div class="field"><label>${esc(t("app.na.laravelVer"))}</label><select name="laravel">${o.laravel.map((l) =>
        `<option value="${l.major}" data-php="${l.php_min}">Laravel ${l.major}${l.latest ? ` (${esc(t("app.na.latest"))})` : ""}</option>`).join("")}</select></div>
      <div class="field"><label>${esc(t("app.na.phpVer"))}</label><select name="php"></select><small class="muted" id="naPhpHint"></small></div>
    </div>
    <div id="naKits">
      <div class="field"><label>${esc(t("app.na.starterKit"))}</label>${radios("starter", [["none", t("app.na.kitNone"), t("app.na.kitNoneHint")], ["react", "React", "Inertia + TS"],
        ["vue", "Vue", "Inertia + TS"], ["svelte", "Svelte", "Inertia + TS"], ["livewire", "Livewire", "Blade + Flux"]], "none")}</div>
      <div class="field" id="naAuth" hidden><label>${esc(t("app.na.auth"))}</label>${radios("auth", [["laravel", "Laravel", t("app.na.authBuiltin")],
        ["workos", "WorkOS", "SSO, passkeys"], ["none", t("app.na.authNone"), ""]], "laravel")}
        <div class="row" style="margin-top:6px"><label class="chk"><input type="checkbox" name="teams"> ${esc(t("app.na.teams"))}</label>
          <label class="chk" id="naLwClass" hidden><input type="checkbox" name="livewire_class"> ${esc(t("app.na.lwClass"))}</label></div></div>
      <div class="grid two">
        <div class="field"><label>${esc(t("app.na.testing"))}</label>${radios("testing", [["pest", "Pest"], ["phpunit", "PHPUnit"]], "pest")}</div>
        <div class="field"><label>${esc(t("app.na.frontend"))}</label><select name="js">
          <option value="npm">npm</option><option value="pnpm">pnpm</option><option value="bun">bun</option><option value="yarn">yarn</option><option value="none">${esc(t("app.na.skip"))}</option></select></div>
      </div>
    </div>
    <p class="muted small" id="naOldNote" hidden>${t("app.na.oldNote")}</p>
    <div class="field"><label>${esc(t("app.na.database"))}</label>${radios("database", [["sqlite", "SQLite", t("app.na.noServer")], ["mysql", "MySQL", o.mysql_running ? t("app.na.svcUp") : t("app.na.svcDown")],
        ["mariadb", "MariaDB", ""], ["pgsql", "PostgreSQL", o.postgres_running ? t("app.na.svcUp") : t("app.na.svcDown")]], "sqlite")}
      <div class="row" id="naDbOpts" hidden style="margin-top:6px"><label class="chk"><input type="checkbox" name="create_db" checked> ${esc(t("app.na.createDb"))}</label>
        <label class="chk"><input type="checkbox" name="migrate" checked> ${esc(t("app.na.migrate"))}</label></div></div>
    <div class="field"><label>${esc(t("app.na.other"))}</label><div class="row">
      <label class="chk"><input type="checkbox" name="secure" checked> HTTPS</label>
      <label class="chk"><input type="checkbox" name="git" checked> Git init</label>
      <label class="chk" id="naBoost"><input type="checkbox" name="boost"> ${esc(t("app.na.boost"))}</label>
      <label class="chk"><input type="checkbox" name="open_browser" checked> ${esc(t("app.na.openBrowser"))}</label></div></div>
    <div class="row"><label class="muted small">${esc(t("app.na.openEditor"))}</label><select name="editor"><option value="">${esc(t("common.no"))}</option>
      ${o.editors.map((e) => `<option value="${e.id}" ${e.id === "vscode" ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select>
      <span class="spacer"></span><button class="go">${esc(t("app.na.create"))}</button></div>`;
  const q = (n) => f.elements[n];
  const sync = () => {
    const lv = q("laravel").selectedOptions[0], latest = lv.value === String(o.laravel[0].major), min = lv.dataset.php;
    const ok = (v) => v.localeCompare(min, undefined, { numeric: true }) >= 0;
    const prev = q("php").value;
    q("php").innerHTML = o.php_installed.map((v) => `<option value="${v}" ${ok(v) ? "" : "disabled"}>PHP ${v}${v === o.global_php ? ` (${t("app.na.global")})` : ""}${ok(v) ? "" : ` — ${t("app.na.tooOld")}`}</option>`).join("");
    const pick = [prev, o.global_php, ...o.php_installed].find((v) => v && ok(v) && o.php_installed.includes(v));
    if (pick) q("php").value = pick;
    $("naPhpHint").innerHTML = pick ? t("app.na.phpNeeds", { v: esc(lv.value), min: esc(min) }) : `<span style="color:var(--red)">${t("app.na.phpMissing", { min: esc(min) })}</span>`;
    $("naKits").hidden = !latest; $("naOldNote").hidden = latest; $("naBoost").hidden = !latest;
    const kit = f.querySelector("[name=starter]:checked")?.value;
    $("naAuth").hidden = !latest || kit === "none";
    $("naLwClass").hidden = kit !== "livewire";
    $("naDbOpts").hidden = q("database").value === "sqlite";
    const name = q("name").value || t("app.na.defaultName");
    $("naPreview").innerHTML = `→ <code>${esc(q("location").value.replace(/\/$/, ""))}/${esc(name)}</code> · ${q("secure").checked ? "https" : "http"}://${esc(name)}.${esc(o.tld)}`;
  };
  f.oninput = sync; f.onchange = sync;
  sync();
  f.onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(f));
    for (const k of ["teams", "livewire_class", "create_db", "migrate", "secure", "git", "boost", "open_browser"]) data[k] = !!data[k];
    $("newAppDlg").close();
    runJob(api("/api/herd/new", data), () => { if (current === tabs.herd) tabs.herd.load(); refreshNav(); });
  };
  $("newAppDlg").showModal();
  q("name").focus();
};
handlers.newAppPick = async () => {
  const f = $("newAppForm");
  const r = await api("/api/pick-folder", { prompt: t("app.na.pickPrompt"), start: f.elements.location.value });
  if (!r.cancelled) { f.elements.location.value = r.path; f.oninput(); }
};
handlers.herdQuick = async (d) => { await api("/api/herd/action", { action: d.action, name: d.name || "" }); };
handlers.herdLog = async (d) => { const r = await api(`/api/herd/logs?file=${d.file}`); showLog(`Herd — ${d.file}`, r.log || t("app.herd.logEmpty")); };

// ------------------------------------------------------------ tema
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.dataset.theme = mode;
  else delete document.documentElement.dataset.theme;
  try { mode === "system" ? localStorage.removeItem("theme") : localStorage.setItem("theme", mode); } catch {}
  document.querySelectorAll("[data-theme-set]").forEach((b) => {
    b.classList.toggle("active", b.dataset.themeSet === mode);
    b.setAttribute("aria-checked", b.dataset.themeSet === mode);
  });
}
document.querySelectorAll("[data-theme-set]").forEach((b) => (b.onclick = () => applyTheme(b.dataset.themeSet)));
applyTheme(document.documentElement.dataset.theme || "system");

$("menuBtn").onclick = () => document.body.classList.toggle("nav-open");
$("scrim").onclick = () => document.body.classList.remove("nav-open");

// «Сообщить о проблеме»: открывает новую заявку на GitHub с заготовленным текстом (ничего не отправляется само — вы видите текст и нажимаете Submit).
handlers.reportIssue = async () => {
  let r;
  try { r = await api("/api/report"); } catch (e) { return toast(e.message, true); }
  if (r.repo) { window.open(`${r.repo}/issues/new?title=${encodeURIComponent(r.title)}&body=${encodeURIComponent(r.body)}`, "_blank", "noopener"); return; }
  try { await navigator.clipboard.writeText(r.body); toast(t("report.copied")); } catch (e) { prompt(t("report.copyManual"), r.body); }
};
