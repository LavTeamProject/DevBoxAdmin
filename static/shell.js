// Каркас навигации (Фаза 10, U2): составные страницы («Начало работы», «История и копии»), переадресации старых адресов, общие блоки.
// Подключается после всех страниц и до первого route(): в нём уже должны существовать tabs.setup, tabs.profiles, tabs.snapshots, tabs.backups.

// Старые адреса продолжают работать: route() перепишет их на новые (замена записи в истории, «назад» не зацикливается).
const HASH_ALIASES = { setup: "start:setup", profiles: "start:profiles", snapshots: "history:snapshots", backups: "history:backups" };

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
const objTabs = (base, items, active) => `<div class="row" style="gap:6px;margin-bottom:14px;flex-wrap:wrap">${items.map(([k, label]) =>
  `<a class="pill-link ${k === active ? "active" : ""}" href="#${base}:${k}">${esc(t(label))}</a>`).join("")}</div>`;

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
      <td><div class="actions">${r.installed ? btn(t("lang.uninstall"), "langBrewAct", { formula: r.formula, action: "uninstall", confirm: t("lang.confirmUninstall", { name: r.formula }) }, "danger")
        : btn(t("profiles.install"), "langBrewAct", { formula: r.formula, action: "install" }, "go")}</div></td></tr>`).join("")}</table></div>`
      : `<div class="empty">${esc(t("lang.noVersions"))}</div>`}`;
}
