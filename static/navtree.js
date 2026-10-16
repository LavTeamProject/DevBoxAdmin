// Боковое меню в стиле FlyEnv (Фаза 10): под «Средой» — каждый язык и каждый установленный сервис отдельным пунктом.
// У сервиса справа переключатель «запущен / остановлен» (запуск и остановка без захода на страницу), у языка — активная версия.
// Данные: языки — runtimeInfo (langs.js), сервисы — /api/nav-services (кэш 20 с на сервере). Без сервисов группа не показывается.
const NAV_GROUPS = [["web", "navg.web"], ["db", "navg.db"], ["cache", "navg.cache"], ["other", "navg.other"]];
const NAV_STATE = { svc: null, busy: new Set() };
const navBase = (name) => name.split("/").pop().replace(/@.*$/, "").replace(/-community$/, "").replace(/^httpd$/, "httpd").replace(/-server$/, "");
const navIcon = (key) => logoSvg(key) || `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.2"/></svg>`;

function navLangRow(l) {
  return `<a href="${langHref(l.key)}" data-navkey="${esc(l.key)}">${navIcon(l.key)}<span class="nav-name">${esc(l.name)}</span><span class="nav-ver">${esc(l.version || "")}</span></a>`;
}
function navSvcRow(s) {
  const busy = NAV_STATE.busy.has(s.name);
  const label = s.running ? t("common.running") : t("common.stopped");
  return `<a href="#service:${encodeURIComponent(s.name)}" data-navkey="svc:${esc(s.name)}">${navIcon(navBase(s.name))}<span class="nav-name">${esc(s.name.split("/").pop())}</span>
    <span class="nav-sw ${s.running ? "on" : ""} ${busy ? "busy" : ""}" role="switch" aria-checked="${s.running}" tabindex="0" title="${esc(label)}" data-act="navSvc" data-name="${esc(s.name)}" data-run="${s.running ? 1 : 0}"></span></a>`;
}
function renderNavTree() {
  const langs = (typeof runtimeInfo !== "undefined" && runtimeInfo.langs) || [];
  const host = $("navTech");
  if (!host) return;
  const g = (NAV_STATE.svc && NAV_STATE.svc.groups) || {};
  const langBlock = langs.length ? `<div class="nav-label"><a href="#langs" class="nav-label-link">${esc(t("navg.langs"))}</a></div>${langs.map(navLangRow).join("")}` : "";
  const svcBlocks = NAV_GROUPS.filter(([id]) => (g[id] || []).length).map(([id, key]) => `<div class="nav-label">${esc(t(key))}</div>${g[id].map(navSvcRow).join("")}`).join("");
  host.innerHTML = langBlock + svcBlocks;
  navMarkActive();
}
function navMarkActive() {
  const h = decodeURIComponent(location.hash || "#dashboard");
  document.querySelectorAll("#navTech a").forEach((a) => {
    const href = decodeURIComponent(a.getAttribute("href"));
    // Flutter/Dart ведут на «Мобильную разработку»: у неё свой пункт, второй раз не подсвечиваем
    a.classList.toggle("active", href !== "#mobile" && (h === href || h.startsWith(href + ":")));
  });
  // у страницы сервиса «Пакеты и приложения» тоже подсвечены (nav: packages) — оставляем только пункт самого сервиса
  if (document.querySelector("#navTech a.active")) document.querySelector('#tabs a[href="#packages"]')?.classList.remove("active");
}
async function loadNavTree(refresh) {
  try { NAV_STATE.svc = await api("/api/nav-services" + (refresh ? "?refresh=1" : "")); } catch (e) { /* меню без сервисов */ }
  renderNavTree();
}
handlers.navSvc = async (d) => {
  const name = d.name, action = d.run === "1" ? "stop" : "start";
  if (NAV_STATE.busy.has(name)) return;
  NAV_STATE.busy.add(name);
  renderNavTree();
  try { await api("/api/action", { name, action }); toast(t(action === "start" ? "navg.started" : "navg.stopped", { name })); }
  catch (e) { toast(e.message, true); }
  NAV_STATE.busy.delete(name);
  await loadNavTree(true);
  if (current && current.load && current === tabs.service) current.load(true);
};
document.addEventListener("keydown", (e) => {
  if ((e.key === " " || e.key === "Enter") && e.target.classList?.contains("nav-sw")) { e.preventDefault(); e.target.click(); }
});
window.addEventListener("hashchange", navMarkActive);
if (typeof applyNav === "function") {
  const baseApply = applyNav;
  applyNav = function (d) { baseApply(d); renderNavTree(); };
}
loadNavTree();
setInterval(() => { if (!document.hidden) loadNavTree(); }, 30000);
if (typeof setLang === "function") document.addEventListener("langchange", renderNavTree);
