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
