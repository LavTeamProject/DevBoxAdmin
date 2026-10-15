// Страница «Подготовка системы»: что нужно самой панели на этой машине (мастер первого запуска).
// Установка идёт задачей (панель «Процессы»); всё записывается в журнал аудита.

const SETUP_NAME = { clt: "Xcode Command Line Tools", homebrew: "Homebrew", git: "Git", python: "Python", toolchain: "Build tools (gcc, make, git, curl)" };
const setupState = { data: null };

async function refreshSetupBanner() {
  try { setupState.data = await api("/api/setup"); } catch { return; }
  renderSetupBanner();
  if (current === tabs.setup) tabs.setup.render();
}

function renderSetupBanner() {
  const b = $("setupBanner"), d = setupState.data;
  if (!b || !d) return;
  const hide = d.ready || location.hash === "#setup";
  b.hidden = hide;
  if (!hide) {
    const list = d.missing.map((id) => SETUP_NAME[id]).join(", ");
    b.innerHTML = `<span>${esc(t("setup.banner", { list }))}</span> <a href="#setup">${esc(t("setup.open"))}</a>`;
  }
}
window.addEventListener("hashchange", renderSetupBanner);

tabs.setup = {
  titleKey: "nav.setup",
  async load(silent) {
    try { setupState.data = await api("/api/setup"); }
    catch (e) { if (!silent) return failView(e); return; }
    renderSetupBanner();
    this.render();
  },

  // Перерисовка из памяти — при смене языка (см. i18n.js).
  render() {
    const d = setupState.data;
    if (!d) return;
    $("headline").textContent = d.ready ? t("setup.ready") : t("setup.missing", { n: d.missing.length });

    const row = (i) => {
      const mark = i.installed ? `<span class="mark">✔</span>` : `<span class="mark off">○</span>`;
      let action = "";
      if (i.can_install) {
        action = btn(t("setup.install"), "setupInstall", { id: i.id, confirm: t(`setup.confirm.${i.id}`) }, "primary");
      } else if (!i.installed && i.blocked_by) {
        action = `<span class="badge amber">${esc(t("setup.first", { name: SETUP_NAME[i.blocked_by] }))}</span>`;
      }
      const mode = i.id === "python" ? t(`setup.python.${i.packaged ? "packaged" : i.mode}`, { v: i.version }) : (i.id === "git" && i.mode === "with_toolchain" ? t("setup.desc.gitLinux") : t(`setup.desc.${i.id}`));
      return `<div class="check-row">
        ${mark}
        <span>${esc(SETUP_NAME[i.id])} ${i.version && i.id !== "python" ? `<span class="muted small">${esc(i.version)}</span>` : ""}
          <div class="${i.id === "python" && i.mode === "system" && !i.packaged ? "note" : "muted small"}">${esc(mode)}</div>
          ${i.low_disk ? `<div class="note">${esc(t("setup.lowdisk", { free: i.free_gb }))}</div>` : ""}
          ${i.path ? `<div class="pkg mono">${esc(i.path.replace(/^\/Users\/[^/]+/, "~"))}</div>` : ""}
        </span>
        <span class="actions">${action}</span>
      </div>`;
    };

    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("setup.intro"))}</span></div>
      <div class="card"><div class="checklist">${d.items.map(row).join("")}</div></div>
      <div class="row" style="margin-top:12px"><span class="spacer"></span>${btn(t("profiles.rescan"), "setupReload")}</div>
      ${(window.PLATFORM?.os || "macos") === "macos" ? `<div class="card" style="margin-top:14px"><div class="name">${esc(t("tcc.title"))}</div>
        <p class="muted small" style="margin:6px 0 0">${esc(t("tcc.body"))}</p></div>` : ""}
      ${d.ready ? `<p class="muted small">${esc(t("setup.done"))} <a href="#profiles">${esc(t("nav.profiles"))}</a></p>` : ""}`;
  },
};

handlers.setupReload = () => tabs.setup.load();
handlers.setupInstall = async (d) => {
  let r;
  try { r = await api("/api/setup/install", { id: d.id }); } catch (e) { return toast(e.message, true); }
  if (r.terminal) return window.showAdminCommand(r.terminal);  // без экрана пароль вводится в терминале панели
  return runJob(Promise.resolve(r), () => tabs.setup.load());
};

// Первый запуск: если чего-то не хватает и пользователь не выбрал страницу — открыть мастер.
async function initSetup() {
  await refreshSetupBanner();
  const d = setupState.data;
  if (d && !d.ready && (!location.hash || location.hash === "#dashboard")) location.hash = "#setup";
}
