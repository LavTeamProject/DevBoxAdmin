// Bahasa pemrograman: menu sidebar dibuat otomatis dari bahasa yang terdeteksi.
const LANG_ICON = `<svg viewBox="0 0 24 24"><path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/></svg>`;
const fmtSize = (b) => (b == null ? "-" : fmtBytes(b));

// Tulis versi (dan titik status untuk Docker/Herd) di ujung kanan item sidebar.
function setNavVersion(a, version, running) {
  let v = a.querySelector(".nav-ver");
  if (!v) { v = document.createElement("span"); v.className = "nav-ver"; a.append(v); }
  const dot = running == null ? "" : `<i class="nav-dot ${running ? "on" : ""}" title="${esc(running ? t("common.running") : t("common.stopped"))}"></i>`;
  v.innerHTML = dot + esc(version || "");
}

let runtimeInfo = { langs: [], available: [] };
function applyNav(d) {
  runtimeInfo = d;
  const langs = document.querySelector('[data-nav="langs"]');
  if (langs) setNavVersion(langs, `${d.langs.length}`);
  const docker = document.querySelector('[data-nav="docker"]');
  if (docker) setNavVersion(docker, d.docker?.version || "–", d.docker ? d.docker.running : null);
  const herd = document.querySelector('[data-nav="herd"]');
  if (herd) setNavVersion(herd, d.herd?.version || "–", d.herd ? d.herd.running : null);
  if (current === tabs.langs && $("langGrid")) tabs.langs.render();
}

// Flutter/Dart живут в одном месте — «Мобильная разработка» (там FVM и версии SDK); в «Языках» остаётся ссылка
const langHref = (key) => (key === "php" || key === "node" ? `#${key}` : key === "flutter" || key === "dart" ? "#mobile" : `#lang-${key}`);

async function initRuntimes() {
  // возможности платформы (Фаза 6, Л0): страницы без возможностей скрываются; сбой запроса — ничего не скрываем
  try {
    window.PLATFORM = await api("/api/platform");
    document.querySelectorAll("[data-cap]").forEach((a) => { a.hidden = !window.PLATFORM.capabilities[a.dataset.cap]; });
  } catch { /* показываем всё */ }
  // logo untuk item statis (Docker, Herd)
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const logo = logoSvg(a.dataset.nav);
    if (logo) a.querySelector("svg").outerHTML = logo;
  });
  // halaman PHP & Node (app.js) dan halaman bahasa lain berada di bawah menu "Bahasa pemrograman"
  Object.assign(tabs.php, { nav: "langs", title: "PHP", logo: "php" });
  Object.assign(tabs.node, { nav: "langs", title: "Node.js", logo: "node" });
  // panel wajib tetap jalan di interpreter lain, tapi harus jujur menunjukkannya
  api("/api/runtime").then((r) => {
    const note = $("runtimeNote");
    note.hidden = r.bundled || r.packaged;
    note.dataset.py = `${r.python} (${r.version})`;
  }).catch(() => { /* indikator saja, bukan fitur kritis */ });
  let d = { langs: [], available: [] };
  try { d = await api("/api/runtimes"); } catch { /* halaman tetap tampil */ }
  d.langs.filter((l) => !l.builtin).forEach((l) => { tabs[`lang-${l.key}`] = makeLangTab(l.key); });
  applyNav(d);
}

// perbarui versi di sidebar & halaman bahasa (mis. setelah ganti default)
async function refreshNav(force) {
  try { applyNav(await api(`/api/runtimes${force ? "?refresh=1" : ""}`)); } catch { /* abaikan */ }
}

// ------------------------------------------------------------ halaman grup: semua bahasa
tabs.langs = {
  titleKey: "nav.langs",
  async load() {
    view.innerHTML = `<div id="langGrid"><div class="loading">${t("lang.detecting")}</div></div>`;
    await refreshNav();
    this.render();
  },
  render() {
    const { langs, available = [] } = runtimeInfo;
    $("headline").textContent = t("lang.installedCount", { n: langs.length });
    $("langGrid").innerHTML = `
      <div class="grid lang-grid">${langs.map((l) => `
        <a class="card lang-card" href="${langHref(l.key)}">
          <div class="row" style="flex-wrap:nowrap;gap:12px">
            ${logoSvg(l.key, "lang-logo") || `<span class="lang-logo pkg-fallback">${esc(l.name[0])}</span>`}
            <div style="min-width:0"><div class="lang-name">${esc(l.name)}</div>
              <div class="lang-ver">${esc(l.version || "?")}</div></div></div>
          <div class="row" style="gap:6px;margin:12px 0 6px">
            <span class="badge ${l.source === "Homebrew" ? "" : "blue"}">${esc(l.source)}</span>
            ${l.overridden ? `<span class="badge green" title="${esc(t("lang.defaultSetTitle"))}">${esc(t("lang.defaultSet"))}</span>` : ""}
            ${l.managed || l.builtin ? "" : `<span class="badge">${esc(t("lang.infoBadge"))}</span>`}</div>
          <div class="small lang-desc">${esc(t("langdesc." + l.key))}</div>
          <div class="muted small lang-path"><code>${esc(l.path.replace(/^\/Users\/[^/]+/, "~"))}</code></div>
          <div class="lang-foot">${esc(l.managed || l.builtin ? t("lang.manage") : t("lang.details"))}</div>
        </a>`).join("")}</div>
      ${available.length ? `<h2>${esc(t("lang.notInstalled"))} <span class="muted small">${esc(t(window.PLATFORM?.os === "linux" ? "lang.notInstalledHintApt" : "lang.notInstalledHint"))}</span></h2>
        <div class="grid lang-grid small">${available.filter((a) => a.key !== "dart").map((a) => `<div class="card lang-card muted-card">
          <div class="row" style="flex-wrap:nowrap;gap:12px">${logoSvg(a.key, "lang-logo") || `<span class="lang-logo pkg-fallback">${esc(a.name[0])}</span>`}
            <div><div class="lang-name">${esc(a.name)}</div><div class="muted small"><code>${esc(a.formula)}</code>${a.type === "cask" ? ` (${esc(t("lang.appSuffix"))})` : ""}</div></div></div>
          <div class="muted small lang-desc">${esc(t("langdesc." + a.key))}</div>
          <div class="lang-foot">${btn(t("profiles.install"), "langInstall", { formula: a.formula, type: a.type, name: a.name }, "go")}</div></div>`).join("")}</div>` : ""}`;
  },
};
handlers.langInstall = (d) => runJob(api("/api/apps/action", { name: d.formula, type: d.type, action: "install" }),
  () => refreshNav(true).then(() => { for (const l of runtimeInfo.langs) if (!l.builtin) tabs[`lang-${l.key}`] ??= makeLangTab(l.key); }));

function makeLangTab(key) {
  return {
    nav: "langs",
    data: null,
    async load() {
      let d;
      try { d = await api(`/api/lang?key=${key}${this.py ? `&py=${encodeURIComponent(this.py)}` : ""}`); } catch (e) { return failView(e); }
      this.data = d;
      this.render();
    },
    render() {
      const d = this.data;
      if (!d) return;
      $("pageTitle").innerHTML = `${logoSvg(key, "title-logo")}${esc(d.name)}`;
      $("headline").textContent = d.active.version ? t("lang.activeLine", { name: d.name, v: d.active.version }) : "";
      const sel = d.selected;
      const selName = d.installs.find((i) => i.id === sel);
      const installs = d.installs.length ? `
        <h2 class="row">${esc(t("lang.installedVersions"))} <span class="spacer"></span>
          ${sel ? btn(t("lang.clearOverride"), "langAct", { key, action: "select", id: "default" }, "", `title="${esc(t("lang.clearOverrideTitle"))}"`) : ""}</h2>
        <div class="list">${d.installs.map((i) => `<div class="card item">
          <div><div class="name">${esc(d.name)} ${esc(i.version || "?")} <span class="badge ${i.source === "Homebrew" ? "" : "blue"}">${esc(i.source)}</span>
            ${sel === i.id ? `<span class="badge green">${esc(t("lang.defaultBadge"))}</span>` : ""}
            ${i.registered === false ? `<span class="badge amber" title="${esc(t("lang.notRegisteredTitle"))}">${esc(t("lang.notRegistered"))}</span>` : ""}</div>
            <div class="meta"><code>${esc(i.home || i.bin)}</code></div></div>
          <div class="actions">${d.selectable && sel !== i.id ? btn(t("lang.makeDefault"), "langAct", { key, action: "select", id: i.id }, "primary") : ""}
            ${key === "python" && i.removable ? btn(t("lang.uninstall"), "langAct", { key, action: "uninstall", id: i.id, job: 1, confirm: t("lang.confirmUninstallVersion", { v: i.version || "", src: i.source }) }, "danger")
              : key !== "python" && i.removable ? btn(t("lang.uninstall"), "langBrewAct", { formula: i.formula, action: "uninstall", confirm: t("lang.confirmUninstallVersion", { v: i.version || "", src: i.source }) }, "danger")
              : (key === "python" || i.formula) ? `<span class="muted small" title="${esc(sel === i.id ? t("lang.cantRemoveDefault") : ["Homebrew", "uv", "pyenv"].includes(i.source) ? t("lang.cantRemovePanel") : t("lang.cantRemoveSource", { src: i.source }))}">${esc(t("lang.cantRemove"))}</span>` : ""}</div>
        </div>`).join("")}</div>` : "";
      const hasTabs = !!LANG_RENDER[key]?.body;            // у языков с пакетами/инструментами — вкладки «Версии» и «Пакеты и инструменты»
      const sub = hasTabs && this.param === "packages" ? "packages" : "versions";
      const versionsPart = `${(LANG_RENDER[key]?.warn?.(d)) || ""}
        ${installs}
        ${LANG_RENDER[key]?.versions?.(d) || ""}
        ${BREW_VERSION_LANGS.includes(key) ? `<div id="verCard"></div>` : ""}
        ${d.selectable ? `<p class="muted small">${key === "java"
          ? t("lang.javaNote")
          : t("lang.otherNote")}</p>` : ""}`;
      const packagesPart = LANG_RENDER[key]?.body?.(d) || genericBody(d);
      view.innerHTML = `
        <p style="margin:0 0 12px"><a href="#langs">${esc(t("lang.backLink"))}</a></p>
        <div class="stat">
          <div class="card"><div>${esc(t("lang.newTerminalUses"))}</div><div>${esc(d.name)} ${esc(d.active.version || t("lang.notFound"))}</div>
            <div class="muted small"><code>${esc(d.active.path || "-")}</code> · ${esc(d.active.source || "")}</div></div>
          ${d.selectable ? `<div class="card"><div>${esc(t("lang.defaultFromSA"))}</div><div>${selName ? `${esc(selName.version)} <span class="muted small">${esc(selName.source)}</span>` : esc(t("lang.notSet"))}</div>
            <div class="muted small">${esc(key === "java" ? t("lang.viaJavaHome") : sel ? t("lang.viaBin") : t("lang.followsPath"))}</div></div>` : ""}
        </div>
        ${hasTabs ? objTabs(`lang-${key}`, [["versions", "lang.tab.versions"], ["packages", "lang.tab.packages"]], sub) : ""}
        ${hasTabs ? (sub === "packages" ? packagesPart : versionsPart) : versionsPart + packagesPart}`;
      if (!hasTabs || sub === "packages") LANG_RENDER[key]?.bind?.(d);
      if (BREW_VERSION_LANGS.includes(key) && (!hasTabs || sub === "versions")) fillVersions(key);
    },
  };
}

// Версии из Homebrew (в том числе старые): список доступных версионных формул, «Поставить» / «Удалить». Homebrew держит только поддерживаемые версии.
const BREW_VERSION_LANGS = ["node", "go", "java", "ruby"];
const fillVersions = (key) => fillBrewVersions($("verCard"), `/api/lang/versions?key=${key}`);
handlers.langBrewAct = (d) => runJob(api("/api/apps/action", { name: d.formula, type: "formula", action: d.action }), () => current.load());

function genericBody(d) {
  return `<h2>${esc(t("lang.info"))}</h2><div class="card"><dl class="kv">
      <dt>${esc(t("common.version"))}</dt><dd>${esc(d.active.version || "-")}</dd><dt>${esc(t("common.path"))}</dt><dd><code>${esc(d.active.path)}</code></dd>
      <dt>${esc(t("lang.source"))}</dt><dd>${esc(d.active.source)}</dd></dl></div>
    ${d.formula ? `<p class="row">${t("lang.brewInstalled", { f: esc(d.formula) })}
      ${btn(t("lang.upgrade"), "brewUpgrade", { name: d.formula })}</p>`
      : `<p class="muted small">${esc(t("lang.noMgmt", { name: d.name }))}</p>`}`;
}

const tableOf = (head, rows) => rows.length
  ? `<div class="table-wrap"><table><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr>${rows.join("")}</table></div>`
  : `<div class="empty">${esc(t("common.empty"))}</div>`;

function bindForm(id, fn) {
  const f = $(id);
  if (f) f.onsubmit = (e) => { e.preventDefault(); const v = new FormData(f).get("name").trim(); if (v) fn(v); };
}
const langJob = (key, action, name = "") => runJob(api("/api/lang/action", { key, action, name }), () => current.load());

// Python: установка версии, как вызывать без полного пути
function pyInstallCard(d) {
  const o = d.install_options;
  if (!o) return "";
  const have = new Set(d.installs.map((i) => (i.version || "").split(".").slice(0, 2).join(".")));
  return `<h2>${esc(t("lang.pyInstallTitle"))}</h2><div class="card"><p class="muted small">${esc(t("lang.pyInstallText"))}</p>
    <div class="row" style="gap:10px;flex-wrap:wrap;align-items:center">
      <select id="pyVer">${o.versions.map((v) => `<option value="${v}">${v}${have.has(v) ? " ✓" : ""}</option>`).join("")}</select>
      <label class="small"><input type="radio" name="pyVia" value="uv" ${o.uv ? "checked" : "disabled"}> uv ${o.uv ? "" : `(${esc(t("lang.notInstalled"))})`}</label>
      <label class="small"><input type="radio" name="pyVia" value="brew" ${!o.uv && o.brew ? "checked" : ""} ${o.brew ? "" : "disabled"}> Homebrew</label>
      ${btn(t("profiles.install"), "pyInstall", {}, "go")}</div>
    <div class="muted small" style="margin-top:6px">${esc(t("lang.pyInstallHow"))}</div></div>`;
}
function pyPathCard(d) {
  const p = d.path_setup;
  if (!p) return "";
  const ok = d.selected && p.zshrc_block && p.shims.length;
  return `<h2>${esc(t("lang.pathTitle"))}</h2><div class="card">
    <p class="small">${ok ? `✓ ${esc(t("lang.pathOk", { names: p.shims.join(", ") }))}` : esc(t("lang.pathNot", { path: d.active.path || "?", v: d.active.version || "?" }))}</p>
    <ul class="small muted" style="margin:6px 0 0 18px;line-height:1.6">
      <li>${esc(t("lang.pathHow", { dir: p.shim_dir }))}</li>
      <li>${p.zshrc_block ? `✓ ${esc(t("lang.pathBlockYes"))}` : esc(t("lang.pathBlockNo"))}</li>
      <li>${esc(t("lang.pathApply"))}</li></ul></div>`;
}
handlers.pyInstall = async () => {
  const ver = $("pyVer").value, via = document.querySelector('input[name="pyVia"]:checked')?.value;
  if (!via) throw new Error(t("lang.pyNoMethod"));
  return runJob(api("/api/lang/action", { key: "python", action: "install", version: ver, via }), () => current.load());
};
handlers.langPip = async (d) => runJob(api("/api/lang/action", { key: "python", action: "pip-uninstall", name: d.name, id: current.py || "" }), () => current.load());

const LANG_RENDER = {
  python: {
    warn: (d) => (d.cert_fix || []).map((v) => `<div class="warn row">${t("lang.pyCert", { v: esc(v) })}
      <span class="spacer"></span>${btn(t("lang.fixNow"), "langAct", { key: "python", action: "cert-fix", version: v, job: 1 }, "primary")}</div>`).join(""),
    versions: (d) => `${pyInstallCard(d)}${pyPathCard(d)}`,
    body: (d) => `
      <h2 class="row">${esc(t("lang.pipxApps"))} <span class="spacer"></span>
        ${d.pipx?.length ? btn(t("lang.upgradeAll"), "langAct", { key: "python", action: "pipx-upgrade-all", job: 1 }) : ""}</h2>
      ${d.pipx == null ? `<div class="muted small">${t("lang.pipxMissing")}</div>` : `
        ${tableOf([t("lang.thPackage"), t("common.version"), t("lang.thCommand"), ""], d.pipx.map((p) => `<tr><td><b>${esc(p.name)}</b></td><td><code>${esc(p.version)}</code></td>
          <td class="small">${p.apps.map((a) => `<code>${esc(a)}</code>`).join(" ")}</td>
          <td><div class="actions">${btn(t("lang.upgrade"), "langAct", { key: "python", action: "pipx-upgrade", name: p.name, job: 1 })}
            ${btn(t("lang.uninstall"), "langAct", { key: "python", action: "pipx-uninstall", name: p.name, job: 1, confirm: t("lang.confirmUninstall", { name: p.name }) }, "danger")}</div></td></tr>`))}
        <form class="row" id="pipxInstall" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("lang.phPipx"))}" style="flex:1;max-width:320px"><button class="go">pipx install</button></form>`}
      <h2 class="row">${esc(t("lang.pipPackages"))} <span class="spacer"></span>
        <select id="pipPy" title="${esc(t("lang.pipFor"))}"><option value="">${esc(t("lang.pipActive"))}</option>${d.installs.map((i) => `<option value="${esc(i.id)}" ${d.pip_python === i.id ? "selected" : ""}>${esc(i.version || "?")} · ${esc(i.source)}</option>`).join("")}</select>
        <input type="search" id="pipFilter" placeholder="${esc(t("lang.filter"))}"></h2>
      ${d.externally_managed ? `<p class="muted small">${t("lang.pep668")}</p>` : `<form class="row" id="pipInstall" style="margin-bottom:10px"><input type="text" name="name" placeholder="${esc(t("lang.phPip"))}" style="flex:1;max-width:320px"><button class="go">pip install</button></form>`}
      <div id="pipList">${d.packages ? "" : `<div class="muted small">${esc(t("lang.pipReadFail"))}</div>`}</div>
      ${d.tools?.length ? `<h2>${esc(t("lang.pyTools"))}</h2><div class="card"><dl class="kv">${d.tools.map(([n, v, p]) => `<dt>${esc(n)}</dt><dd>${esc(v || "")} <span class="muted small"><code>${esc(p)}</code></span></dd>`).join("")}</dl></div>` : ""}`,
    bind(d) {
      bindForm("pipxInstall", (v) => langJob("python", "pipx-install", v));
      bindForm("pipInstall", (v) => runJob(api("/api/lang/action", { key: "python", action: "pip-install", name: v, id: current.py || "" }), () => current.load()));
      if ($("pipPy")) $("pipPy").onchange = (e) => { current.py = e.target.value; current.load(); };
      const draw = () => {
        if (!d.packages) return;
        const q = ($("pipFilter")?.value || "").toLowerCase();
        $("pipList").innerHTML = tableOf([t("lang.thPackage"), t("common.version"), ""], d.packages.filter((p) => p.name.toLowerCase().includes(q))
          .map((p) => `<tr><td>${esc(p.name)}</td><td><code>${esc(p.version)}</code></td><td>${d.externally_managed || ["pip", "setuptools", "wheel"].includes(p.name.toLowerCase()) ? "" : `<div class="actions">${btn(t("lang.uninstall"), "langPip", { name: p.name, confirm: t("lang.confirmUninstall", { name: p.name }) }, "danger")}</div>`}</td></tr>`));
      };
      if ($("pipFilter")) $("pipFilter").oninput = draw;
      draw();
    },
  },

  go: {
    warn: (d) => d.latest && d.active.version && d.latest !== d.active.version
      ? `<div class="warn">${t("lang.goNew", { v: esc(d.latest), cur: esc(d.active.version) })}
          ${d.active.source === "Homebrew" ? t("lang.goViaBrew") : t("lang.goDownload")}</div>` : "",
    body: (d) => !d.env ? "" : `
      <div class="grid two" style="margin-top:14px">
        <div class="card"><h3>${esc(t("lang.environment"))}</h3><dl class="kv">${Object.entries(d.env).map(([k, v]) =>
          `<dt>${k}</dt><dd><code>${esc(v || "-")}</code></dd>`).join("")}</dl></div>
        <div class="card"><h3>${esc(t("lang.cache"))}</h3><dl class="kv">
            <dt>${esc(t("lang.modCache"))}</dt><dd>${fmtSize(d.caches.modcache)}</dd><dt>${esc(t("lang.buildCache"))}</dt><dd>${fmtSize(d.caches.buildcache)}</dd></dl>
          <div class="row" style="margin-top:12px">
            ${btn(t("lang.cleanModCache"), "langAct", { key: "go", action: "clean-modcache", job: 1, confirm: t("lang.confirmModCache") })}
            ${btn(t("lang.cleanBuildCache"), "langAct", { key: "go", action: "clean-cache", job: 1 })}</div></div>
      </div>
      <h2>${esc(t("lang.toolsInstalled"))} <span class="muted small"><code>${esc(d.bindir)}</code></span></h2>
      ${d.tools.length ? `<div class="list">${d.tools.map((tl) => `<div class="card item"><div class="name"><code>${esc(tl)}</code></div>
        <div class="actions">${btn(t("lang.remove"), "langAct", { key: "go", action: "remove-tool", name: tl, confirm: t("lang.confirmRemove", { name: tl }) }, "danger")}</div></div>`).join("")}</div>`
        : `<div class="muted small">${t("lang.noGoTools")}</div>`}
      <form class="row" id="goInstall" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("lang.phGo"))}" style="flex:1;max-width:420px"><button class="go">go install</button></form>`,
    bind: () => bindForm("goInstall", (v) => langJob("go", "install-tool", v)),
  },

  rust: {
    body: (d) => !d.rustup ? `<div class="warn">${esc(t("lang.notRustup"))}</div>` : `
      <div class="row" style="margin:14px 0">
        ${btn("rustup update", "langAct", { key: "rust", action: "update", job: 1 }, "primary")}
        ${btn(t("lang.checkUpdate"), "langAct", { key: "rust", action: "check", job: 1 })}
        <span class="muted small">rustup ${esc(d.rustup_version || "")}</span></div>
      <h2>Toolchain</h2>
      <div class="list">${d.toolchains.map((tc) => `<div class="card item">
        <div class="name">${esc(tc.name)} ${tc.default ? `<span class="badge green">${esc(t("lang.defaultBadge"))}</span>` : ""}${tc.active ? `<span class="badge blue">${esc(t("lang.activeBadge"))}</span>` : ""}</div>
        <div class="actions">${tc.default ? "" : btn(t("lang.makeDefault"), "langAct", { key: "rust", action: "default", name: tc.name }, "primary")
          + btn(t("lang.uninstall"), "langAct", { key: "rust", action: "toolchain-uninstall", name: tc.name, job: 1, confirm: t("lang.confirmToolchainUninstall", { name: tc.name }) }, "danger")}</div>
      </div>`).join("")}</div>
      <form class="row" id="rustTc" style="margin-top:10px"><input type="text" name="name" placeholder="stable, beta, nightly, 1.85" style="max-width:260px"><button class="go">${esc(t("lang.installToolchain"))}</button></form>
      <div class="grid two" style="margin-top:14px">
        <div class="card"><h3>${esc(t("lang.targets", { tc: d.active_toolchain }))}</h3>
          ${d.targets.map((tg) => `<div class="row issue" style="cursor:default"><code class="spacer">${esc(tg)}</code>
            ${tg.startsWith("aarch64-apple-darwin") ? "" : btn(t("lang.remove"), "langAct", { key: "rust", action: "target-remove", name: tg, job: 1 }, "danger")}</div>`).join("")}
          <form class="row" id="rustTarget" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("lang.phTarget"))}" style="flex:1"><button>${esc(t("lang.add"))}</button></form></div>
        <div class="card"><h3>${esc(t("lang.components"))}</h3>
          <div class="row" style="gap:6px">${d.components.map((c) => `<span class="badge">${esc(c.replace(/-aarch64-apple-darwin$/, ""))}</span>`).join("")}</div>
          <form class="row" id="rustComp" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("lang.phComponent"))}" style="flex:1"><button>${esc(t("lang.add"))}</button></form></div>
      </div>
      <h2>${t("lang.cratesHeading", { size: fmtSize(d.registry_size) })}</h2>
      ${tableOf(["Crate", t("common.version"), ""], (d.crates || []).map((c) => `<tr><td><b>${esc(c.name)}</b></td><td><code>${esc(c.version)}</code></td>
        <td><div class="actions">${btn(t("lang.upgrade"), "langAct", { key: "rust", action: "crate-install", name: c.name, job: 1 })}
          ${btn(t("lang.uninstall"), "langAct", { key: "rust", action: "crate-uninstall", name: c.name, job: 1, confirm: t("lang.confirmUninstall", { name: c.name }) }, "danger")}</div></td></tr>`))}
      <form class="row" id="rustCrate" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("lang.phCrate"))}" style="flex:1;max-width:320px"><button class="go">cargo install</button></form>`,
    bind() {
      bindForm("rustTc", (v) => langJob("rust", "toolchain-install", v));
      bindForm("rustTarget", (v) => langJob("rust", "target-add", v));
      bindForm("rustComp", (v) => langJob("rust", "component-add", v));
      bindForm("rustCrate", (v) => langJob("rust", "crate-install", v));
    },
  },

  java: {
    body: (d) => d.build_tools.length ? `<h2>Build tools</h2><div class="card"><dl class="kv">${d.build_tools.map(([n, v]) =>
      `<dt>${esc(n)}</dt><dd>${esc(v || "-")}</dd>`).join("")}</dl></div>` : "",
  },

  ruby: {
    warn: (d) => d.system_ruby ? `<div class="warn">${t("lang.rubySystem", { v: esc(d.active.version) })}</div>` : "",
    body: (d) => `<h2 class="row">${esc(t("lang.gemsInstalled"))} <span class="spacer"></span><span class="muted small">${(d.gems || []).length} gem</span></h2>
      ${d.system_ruby ? "" : `<form class="row" id="gemInstall" style="margin-bottom:10px"><input type="text" name="name" placeholder="rails" style="flex:1;max-width:320px"><button class="go">gem install</button></form>`}
      ${tableOf(["Gem", t("common.version"), ""], (d.gems || []).map((g) => `<tr><td>${esc(g.name)}</td><td class="small"><code>${esc(g.version)}</code></td>
        <td>${d.system_ruby || g.version.includes("default") ? "" : `<div class="actions">${btn(t("lang.uninstall"), "langAct", { key: "ruby", action: "gem-uninstall", name: g.name, job: 1, confirm: t("lang.confirmUninstall", { name: g.name }) }, "danger")}</div>`}</td></tr>`))}`,
    bind() { bindForm("gemInstall", (v) => langJob("ruby", "gem-install", v)); },
  },

  node: {
    body: (d) => `<h2 class="row">${esc(t("lang.npmGlobal"))} <span class="spacer"></span><span class="muted small">${(d.packages || []).length}</span></h2>
      <p class="muted small">${esc(t("lang.npmGlobalHint", { v: d.active.version || "" }))}</p>
      <form class="row" id="npmInstall" style="margin-bottom:10px"><input type="text" name="name" placeholder="typescript, pnpm, @vue/cli" style="flex:1;max-width:320px"><button class="go">npm install -g</button></form>
      ${d.packages == null ? `<div class="muted small">${esc(t("lang.npmReadFail"))}</div>` : tableOf([t("lang.thPackage"), t("common.version"), ""], d.packages.map((p) => `<tr><td><b>${esc(p.name)}</b></td><td><code>${esc(p.version)}</code></td>
        <td>${["npm", "corepack"].includes(p.name) ? "" : `<div class="actions">${btn(t("lang.uninstall"), "langAct", { key: "node", action: "npm-uninstall", name: p.name, job: 1, confirm: t("lang.confirmUninstall", { name: p.name }) }, "danger")}</div>`}</td></tr>`))}`,
    bind() { bindForm("npmInstall", (v) => langJob("node", "npm-install", v)); },
  },
};

handlers.brewUpgrade = (d) => runJob(api("/api/apps/action", { name: d.name, type: "formula", action: "upgrade" }), () => current.load());
handlers.langAct = async (d) => {
  const body = { key: d.key, action: d.action, id: d.id, name: d.name, version: d.version, via: d.via };
  if (d.job) return runJob(api("/api/lang/action", body), () => current.load());
  const r = await api("/api/lang/action", body);
  toast(r.output || t("lang.done"));
  await current.load();
  refreshNav();
};

// Node.js: версии из Homebrew (node, node@N) и выбор основной — общая страница языка (прежняя страница nvm заменена: единый менеджер — Homebrew)
tabs.node = makeLangTab("node");
