// Каркас навигации (Фаза 10, U2): составные страницы («Начало работы», «История и копии»), переадресации старых адресов, общие блоки.
// Подключается после всех страниц и до первого route(): в нём уже должны существовать tabs.setup, tabs.profiles, tabs.snapshots, tabs.backups.

// Старые адреса продолжают работать: route() перепишет их на новые (замена записи в истории, «назад» не зацикливается).
const HASH_ALIASES = { setup: "start:setup", profiles: "start:profiles", snapshots: "history:snapshots", backups: "history:backups", runs: "projects:runs" };

// Составная страница: вкладки-«дети» — существующие страницы; полоса вкладок вставляется над содержимым ребёнка и восстанавливается,
// если ребёнок перерисовал страницу (MutationObserver). Один механизм для всех составных страниц.
function makeComposite(key, titleKey, children) {   // children: [[sub, i18nКлючПодписи, tabObject], …]
  let observer = null;
  const comp = {
    titleKey,
    get sub() { const k = String(this.param || "").split(":")[0]; return children.some((c) => c[0] === k) ? k : children[0][0]; },
    child() { return children.find((c) => c[0] === this.sub)[2]; },
    get interval() { return this.child().interval; },
    async load(silent) {
      const c = this.child();
      c.param = String(this.param || "").split(":").slice(1).join(":");
      if (!observer) {
        observer = new MutationObserver(() => { if (current === comp && !view.querySelector("#compNav")) comp.subnav(); });
        observer.observe(view, { childList: true });
      }
      await c.load(silent);
      this.subnav();
    },
    render() { this.child().render?.(); this.subnav(); },
    subnav() {
      if (view.querySelector("#compNav")) return;
      view.insertAdjacentHTML("afterbegin", `<div id="compNav" class="row" style="gap:6px;margin-bottom:14px;flex-wrap:wrap">${children.map(([k, label]) =>
        `<a class="pill-link ${k === this.sub ? "active" : ""}" href="#${key}:${k}">${esc(t(label))}</a>`).join("")}</div>`);
    },
    leave() { observer?.disconnect(); observer = null; this.child().leave?.(); },
  };
  return comp;
}

tabs.start = makeComposite("start", "nav.start", [["setup", "nav.setup", tabs.setup], ["profiles", "nav.profiles", tabs.profiles]]);
tabs.history = makeComposite("history", "nav.history", [["snapshots", "nav.snapshots", tabs.snapshots], ["backups", "nav.backups", tabs.backups]]);

// Общие блоки: ошибка блока с «Повторить» и пустое состояние с понятным следующим шагом (каждый блок страницы показывает свою ошибку сам).
const errBlock = (msg, retryAct = "", data = {}) => `<div class="warn small" style="margin-bottom:10px">${esc(t("shell.blockFailed", { msg }))}
  ${retryAct ? btn(t("shell.retry"), retryAct, data) : ""}</div>`;
const emptyBlock = (text, actionHtml = "") => `<div class="empty">${esc(text || t("shell.empty"))}${actionHtml ? `<div style="margin-top:8px">${actionHtml}</div>` : ""}</div>`;
// Загрузка нескольких запросов независимо: {имя: Promise} → {имя: {ok, value|error}}; сбой одного не роняет остальные.
async function loadBlocks(spec) {
  const names = Object.keys(spec), res = await Promise.allSettled(names.map((n) => spec[n]));
  return Object.fromEntries(names.map((n, i) => [n, res[i].status === "fulfilled" ? { ok: true, value: res[i].value } : { ok: false, error: res[i].reason?.message || String(res[i].reason) }]));
}

// Единая страница объекта (Фаза 10): вкладки «Версии · Настройки · Журнал…» одинаково у языков и сервисов. items: [[sub, i18nКлюч], …]; base — адрес без вкладки.
// Ключ вкладки "" = страница по умолчанию (адрес без вкладки). rawLabels: подписи уже переведены (Docker), иначе это ключи словаря.
const objTabs = (base, items, active, rawLabels = false) => `<div class="row" style="gap:6px;margin-bottom:14px;flex-wrap:wrap">${items.map(([k, label]) =>
  `<a class="pill-link ${k === active ? "active" : ""}" href="#${base}${k ? ":" + k : ""}">${esc(rawLabels ? label : t(label))}</a>`).join("")}</div>`;

// Карточка «Версии из Homebrew» (последняя + версионные формулы; «Поставить» / «Удалить»). url отдаёт {supported, available:[{formula, version, installed, latest}]}.
async function fillBrewVersions(box, url, noteKey = "lang.brewVersionsNote") {
  if (!box) return;
  box.innerHTML = `<h2>${esc(t("lang.brewVersions"))}</h2><div class="loading">${esc(t("shell.loading"))}</div>`;
  let v;
  try { v = await api(url); } catch (e) { box.innerHTML = `<h2>${esc(t("lang.brewVersions"))}</h2>${errBlock(e.message)}`; return; }
  if (!v.supported) { box.innerHTML = ""; return; }
  box.innerHTML = `<h2>${esc(t("lang.brewVersions"))}</h2><p class="muted small">${esc(t(noteKey))}</p>
    ${v.available.length ? `<div class="table-wrap"><table><tr><th>${esc(t("lang.thFormula"))}</th><th>${esc(t("common.version"))}</th><th>${esc(t("pkg.thOrigin"))}</th><th></th></tr>
    ${v.available.map((r) => `<tr><td><code>${esc(r.formula)}</code></td><td>${esc(r.latest ? t("lang.latest") : r.version)}</td>
      <td>${r.installed ? `<span class="badge green">${esc(t("lang.installedBadge"))}</span>` : `<span class="muted small">${esc(t("lang.availableBadge"))}</span>`}</td>
      <td><div class="actions">${r.installed && r.default ? `<span class="badge green">${esc(t("app.badge.default"))}</span>`
        : r.installed ? btn(t("lang.uninstall"), "langBrewAct", { formula: r.formula, action: "uninstall", confirm: t("lang.confirmUninstall", { name: r.formula }) }, "danger")
        : btn(t("profiles.install"), "langBrewAct", { formula: r.formula, action: "install" }, "go")}</div></td></tr>`).join("")}</table></div>`
      : `<div class="empty">${esc(t("lang.noVersions"))}</div>`}`;
}


// Быстрые действия в шапке: наборы сервисов «запустить / остановить все» без перехода на страницу (только macOS; без наборов кнопка скрыта).
const QA = { sets: null };
async function qaLoad() {
  const btn = $("qaBtn");
  if (!btn) return;
  try { QA.sets = await api("/api/service-sets"); } catch (e) { QA.sets = null; }
  const usable = QA.sets && QA.sets.supported && QA.sets.sets.some((s) => s.installed > 0);
  btn.hidden = !usable;
  if (!usable) $("qaPop").hidden = true;
}
function qaRender() {
  const pop = $("qaPop");
  const rows = (QA.sets ? QA.sets.sets : []).filter((s) => s.installed > 0).map((s) => {
    const name = s.kind === "preset" ? t("sets.name." + s.id) : s.name;
    return `<div class="qa-row"><span class="qa-name" title="${esc(name)}">${esc(name)} <span class="muted small">${s.running}/${s.total}</span></span>
      ${btn(t("sets.start"), "qaAct", { id: s.id, action: "start" }, "go")}${btn(t("sets.stop"), "qaAct", { id: s.id, action: "stop", confirm: t("sets.confirmStop") })}</div>`;
  }).join("");
  pop.innerHTML = `<h3 style="margin:0 0 4px">${esc(t("qa.sets"))}</h3>${rows || `<div class="muted small">${esc(t("shell.empty"))}</div>`}
    <div class="qa-row"><a href="#packages" onclick="$('qaPop').hidden=true">${esc(t("qa.all"))}</a></div>`;
}
handlers.qaAct = (d) => { $("qaPop").hidden = true; return runJob(api("/api/service-sets/action", { id: d.id, action: d.action }), () => { qaLoad(); if (current && current.load) current.load(); }); };
if ($("qaBtn")) {
  $("qaBtn").addEventListener("click", async (e) => {
    e.stopPropagation();
    const pop = $("qaPop");
    if (!pop.hidden) { pop.hidden = true; return; }
    qaRender();                               // сразу из того, что уже загружено; brew services бывает медленным — список обновится ниже
    pop.hidden = false;
    $("qaBtn").setAttribute("aria-expanded", "true");
    await qaLoad();
    if (!pop.hidden) qaRender();
  });
  document.addEventListener("click", (e) => { const p = $("qaPop"); if (p && !p.hidden && !p.contains(e.target)) { p.hidden = true; $("qaBtn").setAttribute("aria-expanded", "false"); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("qaPop").hidden = true; });
  qaLoad();
}


// «Проекты» + «Запуски»: вкладка #projects:runs (параметр "runs" не пересекается с абсолютными путями проектов). Полоса вкладок — над списком и над запусками, на странице проекта её нет.
(() => {
  const P = tabs.projects, R = tabs.runs;
  const orig = { load: P.load, render: P.render };
  const isRuns = () => P.param === "runs";
  const strip = () => {
    if (view.querySelector("#compNav") || (P.param && !isRuns())) return;
    view.insertAdjacentHTML("afterbegin", `<div id="compNav" class="row" style="gap:6px;margin-bottom:14px;flex-wrap:wrap">
      <a class="pill-link ${isRuns() ? "" : "active"}" href="#projects">${esc(t("nav.projects"))}</a>
      <a class="pill-link ${isRuns() ? "active" : ""}" href="#projects:runs">${esc(t("nav.runs"))}</a></div>`);
  };
  let obs = null;
  P.load = async function (silent) {
    if (!obs) { obs = new MutationObserver(() => { if (current === P) strip(); }); obs.observe(view, { childList: true }); }
    if (isRuns()) { R.param = ""; await R.load(silent); } else await orig.load.call(P, silent);
    strip();
  };
  P.render = function () { if (isRuns()) R.render(); else orig.render.call(P); strip(); };
  Object.defineProperty(P, "interval", { get() { return isRuns() ? R.interval : undefined; }, configurable: true });
  P.leave = function () { obs?.disconnect(); obs = null; R.leave?.(); };
})();


// Центр внимания: колокольчик в шапке (дешёвые проверки раз в минуту) и карточка на «Обзоре» (с медленными проверками, они кэшируются на сервере).
const ATTN = { data: null };
const attnLine = (i) => `<div class="attn-row"><span class="badge ${i.level === "warn" ? "amber" : "gray"}">${i.count}</span><a href="${esc(i.href)}">${esc(t(i.key, { n: i.count }))}${i.names ? ` <span class="muted small">(${esc(i.names.join(", "))})</span>` : ""}</a></div>`;
async function attnLoad(deep) {
  try { ATTN.data = await api("/api/attention" + (deep ? "?deep=1" : "")); } catch (e) { return null; }
  const b = $("attnBtn"), items = ATTN.data.items;
  if (b) { b.hidden = !items.length; $("attnDot").hidden = !ATTN.data.warn; }
  return ATTN.data;
}
function attnFillCard() {
  const host = $("attnCard");
  if (!host || !ATTN.data) return;
  host.innerHTML = ATTN.data.items.length ? `<h3 style="margin:0 0 6px">${esc(t("attn.title"))}</h3>${ATTN.data.items.map(attnLine).join("")}` : "";
  host.hidden = !ATTN.data.items.length;
}
if ($("attnBtn")) {
  $("attnBtn").addEventListener("click", async (e) => {
    e.stopPropagation();
    const pop = $("attnPop");
    if (!pop.hidden) { pop.hidden = true; return; }
    const d = (await attnLoad(true)) || ATTN.data;
    pop.innerHTML = d && d.items.length ? d.items.map(attnLine).join("") : `<div class="muted small">${esc(t("attn.none"))}</div>`;
    pop.hidden = false;
  });
  document.addEventListener("click", (e) => { const p = $("attnPop"); if (p && !p.hidden && !p.contains(e.target)) p.hidden = true; });
  attnLoad(false);
  setInterval(() => { if (!document.hidden) attnLoad(false); }, 60000);
  const D = tabs.dashboard, dLoad = D.load;
  D.load = async function (silent) {
    await dLoad.call(D, silent);
    if (current === D && !$("attnCard")) view.insertAdjacentHTML("afterbegin", `<div class="card attn-card" id="attnCard" hidden></div>`);
    attnFillCard();
    if (current === D && Date.now() - (ATTN.deepAt || 0) > 60000) { ATTN.deepAt = Date.now(); attnLoad(true).then(() => current === D && attnFillCard()); }
  };
}
