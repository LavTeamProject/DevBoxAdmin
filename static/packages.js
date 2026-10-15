// Paket & Service: gabungan paket Homebrew (CLI + app) dan brew services,
// plus halaman detail service (#service:<nama>) untuk config, info, dan cloudflared.

const pkgIcon = (name, type) => logoSvg(logoFor(name) || "", "pkg-logo") ||
  `<span class="pkg-logo pkg-fallback">${type === "cask" ? "▣" : "›_"}</span>`;

function svcDot(s) {
  if (!s) return "";
  return s.running ? "on" : s.status === "error" ? "bad" : s.status === "none" ? "" : "mid";
}

function svcActions(s, detail = true) {
  const d = { name: s.name };
  const main = s.running
    ? btn(t("pkg.restart"), "svc", { ...d, action: "restart" }) + btn(t("pkg.stop"), "svc", { ...d, action: "stop", confirm: t("pkg.confirmStop", { name: s.name }) }, "danger")
    : btn(t("pkg.start"), "svc", { ...d, action: "start" }, "go", `title="${esc(t("pkg.startTitle"))}"`) +
      btn(t("pkg.run"), "svc", { ...d, action: "run" }, "", `title="${esc(t("pkg.runTitle"))}"`) +
      (s.status === "error" || s.loaded ? btn(t("pkg.stop"), "svc", { ...d, action: "stop" }, "danger") : "");
  return main + btn(t("pkg.log"), "svcLog", d) +
    (detail ? `<a class="btn-link" href="#service:${encodeURIComponent(s.name)}">${esc(t("pkg.detailConfig"))}</a>` : "");
}

function svcStats(s) {
  if (s.running) {
    return `<span>PID <code>${s.pid ?? "–"}</code></span><span>CPU ${s.cpu ?? "-"}%</span><span>RAM ${s.mem_mb ?? "-"} MB</span><span>Uptime ${esc(s.uptime ?? "-")}</span>`;
  }
  return s.exit_code != null ? `<span>Exit code <code>${s.exit_code}</code></span>` : "";
}

// Каталог пакетов приходит с сервера по-русски (svc.py): переводим по тексту, нет перевода — показываем как есть.
const catTr = (text) => (I18N[LANG] || {})["cd." + text] ?? text;

tabs.packages = {
  interval: 5000,
  filter: "service",
  apps: null,
  services: [],
  async load(silent) {
    try {
      if (silent) {
        this.services = (await api("/api/services")).services;
      } else {
        this.skeleton();
        const [svcs, apps] = await Promise.all([api("/api/services"), api("/api/apps").catch(() => null)]);
        this.services = svcs.services;
        this.apps = apps?.apps || [];
        if (!this.catalog) api("/api/services/catalog").then((c) => { this.catalog = c.catalog; this.render(); }).catch(() => {});
      }
    } catch (e) { return silent || failView(e); }
    if ($("pkgList")) this.render();
  },
  skeleton() {
    view.innerHTML = `
      <div class="row" style="margin-bottom:12px">
        <form class="row" id="pkgSearch" style="flex:1;min-width:260px">
          <input type="search" id="pkgQ" placeholder="${esc(t("pkg.searchPh"))}" style="flex:1">
          <button>${esc(t("pkg.searchBtn"))}</button>
        </form>
        ${btn(t("pkg.upgradeAll"), "pkgUpgradeAll", { confirm: t("pkg.confirmUpgradeAll") })}
      </div>
      <div class="row" style="margin-bottom:14px"><div class="seg" id="pkgFilter"></div><span class="spacer"></span><span class="muted small" id="pkgNote"></span></div>
      <div id="pkgResults"></div>
      <div id="pkgList"><div class="loading">${esc(t("pkg.readingBrew"))}</div></div>`;
    $("pkgQ").oninput = () => this.render();
    $("pkgSearch").onsubmit = (e) => { e.preventDefault(); this.search(); };
  },
  rows() {
    const svcBy = Object.fromEntries(this.services.map((s) => [s.name, s]));
    const apps = (this.apps || []).map((a) => ({ ...a, svc: svcBy[a.name] }));
    // service yang formulanya tidak ada di daftar paket (jarang, mis. dari tap)
    for (const s of this.services) {
      if (!apps.some((a) => a.name === s.name)) apps.push({ name: s.name, type: "formula", desc: "", version: "", on_request: true, svc: s });
    }
    return apps;
  },
  render() {
    const all = this.rows(), q = ($("pkgQ")?.value || "").toLowerCase();
    const counts = {
      service: all.filter((a) => a.svc).length, all: all.filter((a) => a.on_request).length,
      cli: all.filter((a) => a.type === "formula" && a.on_request).length, app: all.filter((a) => a.type === "cask").length,
      outdated: all.filter((a) => a.outdated).length, recommend: 100,
    };
    const running = this.services.filter((s) => s.running).length;
    $("headline").textContent = t("pkg.headline", { run: running, total: this.services.length, n: counts.all });
    $("svcCount").innerHTML = `<i class="nav-dot ${running ? "on" : ""}"></i>${running}/${this.services.length}`;
    const labels = { service: t("pkg.fService"), all: t("pkg.fAll"), cli: "CLI", app: t("pkg.fApp"), outdated: t("pkg.fUpdates"), recommend: t("pkg.fRecommend") };
    $("pkgFilter").innerHTML = Object.entries(labels).map(([k, l]) =>
      btn(`${l} <span class="muted">${counts[k]}</span>`, "pkgFilter", { f: k }, this.filter === k ? "active" : "")).join("");
    const match = (a) => !q || a.name.toLowerCase().includes(q) || (a.desc || "").toLowerCase().includes(q);
    if (this.filter === "recommend") return this.renderRecommend(match);
    const pick = {
      service: (a) => a.svc, all: (a) => a.on_request, cli: (a) => a.type === "formula" && a.on_request,
      app: (a) => a.type === "cask", outdated: (a) => a.outdated,
    }[this.filter];
    const list = all.filter((a) => pick(a) && match(a)).sort((a, b) => (b.svc?.running ? 1 : 0) - (a.svc?.running ? 1 : 0) || a.name.localeCompare(b.name));
    $("pkgNote").textContent = this.apps === null ? "" : this.filter === "all" ? t("pkg.depsHidden") : "";

    if (this.filter === "service") {
      const cards = list.map((a) => {
        const s = a.svc;
        return `<div class="card item">
          <div class="row" style="flex-wrap:nowrap;align-items:flex-start;gap:12px">${pkgIcon(a.name, a.type)}
            <div><div class="name"><span class="dot ${svcDot(s)}"></span>${esc(a.name)} <span class="badge">${esc(s.status)}</span>
              ${s.registered ? `<span class="badge blue" title="${esc(t("pkg.autoStartTitle"))}">auto-start</span>` : ""}
              ${a.outdated ? `<span class="badge amber">${esc(t("pkg.updateTo", { v: a.latest || t("pkg.newVer") }))}</span>` : ""}</div>
            <div class="meta">${a.desc ? `<span>${esc(a.desc)}</span>` : ""}${svcStats(s)}</div></div></div>
          <div class="actions">${svcActions(s)}</div></div>`;
      }).join("");
      const installed = new Set(all.map((a) => a.name));
      const cat = (this.catalog || []).filter((c) => !c.installed && !installed.has(c.formula.split("/").pop()) && match({ name: c.formula, desc: c.desc + c.name }));
      $("pkgList").innerHTML = `<div class="list">${cards || `<div class="empty">${esc(t("pkg.noServices"))}</div>`}</div>
        <h2>${esc(t("pkg.installNewSvc"))}</h2>
        ${this.catalog ? `<div class="grid cat-grid">${cat.map((c) => `<div class="card cat">
            <div class="row" style="flex-wrap:nowrap">${pkgIcon(c.formula, "formula")}<div><b>${esc(c.name)}</b>
              <div class="muted small">${esc(catTr(c.category))} · <code>${esc(c.formula.split("/").pop())}</code></div></div></div>
            <div class="muted small" style="margin:8px 0 10px;min-height:36px">${esc(catTr(c.desc))}</div>
            ${btn(t("pkg.install"), "svcInstall", { formula: c.formula }, "go")}</div>`).join("")}</div>`
          : `<div class="loading">${esc(t("pkg.loadingCatalog"))}</div>`}`;
      return;
    }
    $("pkgList").innerHTML = list.length ? `<div class="table-wrap"><table>
      <tr><th>${esc(t("pkg.thPackage"))}</th><th>${esc(t("pkg.thVersion"))}</th><th>${esc(t("pkg.thService"))}</th><th></th></tr>
      ${list.map((a) => {
        const d = { name: a.name, type: a.type };
        return `<tr>
          <td><div class="row" style="flex-wrap:nowrap;gap:10px">${pkgIcon(a.name, a.type)}<div>
            <b>${esc(a.name)}</b> <span class="badge ${a.type === "cask" ? "blue" : ""}">${a.type === "cask" ? "app" : "cli"}</span>
            <div class="muted small">${esc(a.desc)}</div></div></div></td>
          <td class="small"><code>${esc(a.version)}</code>${a.outdated ? `<br><span class="badge amber">→ ${esc(a.latest || t("pkg.newVer"))}</span>` : ""}</td>
          <td class="small">${a.svc ? `<a href="#service:${encodeURIComponent(a.name)}" class="row" style="gap:6px;text-decoration:none;color:inherit">
            <span class="dot ${svcDot(a.svc)}"></span>${esc(a.svc.status)}</a>` : `<span class="muted">–</span>`}</td>
          <td><div class="actions">
            ${a.outdated ? btn(t("pkg.upgrade"), "pkg", { ...d, action: "upgrade" }, "go") : ""}
            ${a.svc ? `<a class="btn-link" href="#service:${encodeURIComponent(a.name)}">${esc(t("pkg.detail"))}</a>` : ""}
            ${btn(t("pkg.uninstall"), a.svc ? "svcUninstall" : "pkg", { ...d, action: "uninstall", confirm: t("pkg.confirmUninstall", { name: a.name }) }, "danger")}
          </div></td></tr>`;
      }).join("")}</table></div>` : `<div class="empty">${esc(this.apps === null ? t("pkg.loadingShort") : t("pkg.noMatch"))}</div>`;
  },
  // 100 paket development yang direkomendasikan, dikelompokkan per kategori
  renderRecommend(match) {
    $("pkgNote").textContent = "";
    if (!this.recommend) {
      $("pkgList").innerHTML = `<div class="loading">${esc(t("pkg.loadingRec"))}</div>`;
      api("/api/recommend").then((r) => { this.recommend = r.items; if (this.filter === "recommend") this.render(); })
        .catch((e) => { $("pkgList").innerHTML = `<div class="err">${esc(e.message)}</div>`; });
      return;
    }
    const cats = [...new Set(this.recommend.map((r) => r.category))];
    const cat = this.recCat || "Semua";
    const items = this.recommend.filter((r) => (cat === "Semua" || r.category === cat) && match(r) && (!this.recHide || !r.installed));
    const done = this.recommend.filter((r) => r.installed).length;
    const groups = {};
    items.forEach((r) => (groups[r.category] ??= []).push(r));
    $("pkgList").innerHTML = `
      <div class="row" style="margin-bottom:12px">
        <div class="pills">${["Semua", ...cats].map((c) => btn(esc(c === "Semua" ? t("pkg.fAll") : catTr(c)), "recCat", { c }, c === cat ? "active" : "")).join("")}</div>
        <span class="spacer"></span>
        <label class="chk"><input type="checkbox" id="recHide" ${this.recHide ? "checked" : ""}> ${esc(t("pkg.hideInstalled"))}</label>
        <span class="muted small">${esc(t("pkg.installedCount", { done }))}</span>
      </div>
      ${Object.entries(groups).map(([g, list]) => `<h2>${esc(catTr(g))} <span class="muted small">${list.length}</span></h2>
        <div class="grid cat-grid">${list.map((r) => `<div class="card cat">
          <div class="row" style="flex-wrap:nowrap">${pkgIcon(r.name, r.type)}<div><b>${esc(r.name)}</b>
            <div class="muted small">${esc(r.type === "cask" ? t("pkg.typeApp") : t("pkg.typeCli"))}</div></div></div>
          <div class="muted small" style="margin:8px 0 10px;min-height:36px">${esc(catTr(r.desc))}</div>
          ${r.installed ? `<span class="badge green" style="align-self:flex-start;margin-top:auto">${esc(t("pkg.installedBadge"))}</span>`
            : btn(t("pkg.install"), "recInstall", { name: r.name, type: r.type }, "go")}</div>`).join("")}</div>`).join("")
      || `<div class="empty">${esc(t("pkg.noMatch"))}</div>`}`;
    $("recHide").onchange = (e) => { this.recHide = e.target.checked; this.render(); };
  },
  async search() {
    const q = $("pkgQ").value.trim();
    if (!q) return;
    $("pkgResults").innerHTML = `<div class="loading">${esc(t("pkg.searching", { q }))}</div>`;
    try {
      const { results } = await api(`/api/apps/search?q=${encodeURIComponent(q)}`);
      $("pkgResults").innerHTML = `<div class="card" style="margin-bottom:16px"><h3>${esc(t("pkg.searchResults"))} <span class="spacer"></span>
          ${btn(t("pkg.close"), "pkgCloseSearch")}</h3>
        <div class="list">${results.map((r) => `<div class="item" style="padding:6px 0;border-bottom:1px solid var(--border)">
          <div class="name">${pkgIcon(r.name, r.type)}${esc(r.name)} <span class="badge ${r.type === "cask" ? "blue" : ""}">${r.type === "cask" ? "app" : "cli"}</span></div>
          <div class="actions">${r.installed ? `<span class="badge green">${esc(t("pkg.installedLower"))}</span>` : btn(t("pkg.install"), "pkg", { name: r.name, type: r.type, action: "install" }, "go")}</div>
        </div>`).join("") || `<div class="muted small">${esc(t("pkg.notFound"))}</div>`}</div></div>`;
    } catch (e) { $("pkgResults").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
  },
};

const reloadPackages = () => { if (current === tabs.packages) tabs.packages.load(); else current?.load?.(); };
handlers.pkgFilter = (d) => { tabs.packages.filter = d.f; tabs.packages.render(); };
handlers.recCat = (d) => { tabs.packages.recCat = d.c; tabs.packages.render(); };
handlers.recInstall = (d) => runJob(api("/api/apps/action", { name: d.name, type: d.type, action: "install" }),
  () => { tabs.packages.recommend = null; reloadPackages(); });
handlers.pkgCloseSearch = () => { $("pkgResults").innerHTML = ""; };
handlers.pkg = (d) => runJob(api("/api/apps/action", { name: d.name, type: d.type, action: d.action }), reloadPackages);
handlers.pkgUpgradeAll = () => runJob(api("/api/apps/action", { action: "upgrade-all" }), reloadPackages);
handlers.svcInstall = (d) => runJob(api("/api/services/install", { formula: d.formula }), () => { tabs.packages.catalog = null; reloadPackages(); });
handlers.svcUninstall = (d) => runJob(api("/api/services/uninstall", { name: d.name }), () => {
  if (current === tabs.service) location.hash = "#packages"; else reloadPackages();
});
handlers.svc = async (d) => {
  const r = await api("/api/action", { name: d.name, action: d.action });
  toast(r.output || `${d.action} ${d.name} OK`);
  await current.load(current === tabs.packages);
};
handlers.svcLog = async (d) => {
  const r = await api(`/api/logs?name=${encodeURIComponent(d.name)}`);
  let txt = "";
  if (r.log != null) txt += `# ${r.log_path}\n${r.log || t("pkg.empty")}\n`;
  if (r.error_log != null) txt += `\n# ${r.error_log_path}\n${r.error_log || t("pkg.empty")}`;
  showLog(t("pkg.logTitle", { name: d.name }), txt || t("pkg.noLogFiles"));
};

// ------------------------------------------------------------ detail service
tabs.service = {
  nav: "packages",
  file: null,
  async load() {
    const name = this.param;
    let d, cf = null;
    try {
      d = await api(`/api/services/detail?name=${encodeURIComponent(name)}`);
      if (name === "cloudflared") cf = await api("/api/cloudflared").catch((e) => ({ error: e.message }));
    } catch (e) { return failView(e); }
    const s = d.service, f = d.formula;
    $("pageTitle").innerHTML = `${logoSvg(logoFor(name) || "", "title-logo")}${esc(name)}`;
    $("headline").textContent = f.version ? t("pkg.version", { v: f.version }) : "";
    if (!d.config_files.includes(this.file)) this.file = d.config_files[0] || null;
    const kv = [
      [t("pkg.status"), `<span class="row" style="gap:6px;justify-content:flex-end"><span class="dot ${svcDot(s)}"></span>${esc(s.status)}</span>`],
      [t("pkg.autoStartLogin"), s.registered ? t("pkg.yes") : t("pkg.no")],
      s.pid && ["PID", s.pid],
      d.ports.length && [t("pkg.port"), d.ports.map((p) => `<a href="http://localhost:${p}" target="_blank" rel="noopener"><code>${p}</code></a>`).join(" ")],
      d.data_dir && [t("pkg.dataDir"), `<code>${esc(d.data_dir)}</code>`],
      s.log_path && [t("pkg.log"), `<code>${esc(s.log_path)}</code>`],
      [t("pkg.command"), `<code>${esc(s.command || "-")}</code>`],
      [t("pkg.plistFile"), `<code>${esc(s.file || "-")}</code>`],
    ].filter(Boolean);
    view.innerHTML = `
      <p style="margin:0 0 12px"><a href="#packages">${esc(t("pkg.backToPkgs"))}</a></p>
      <div class="card item" style="margin-bottom:14px">
        <div class="row" style="flex-wrap:nowrap;gap:12px">${pkgIcon(name, "formula")}
          <div><div class="name"><span class="dot ${svcDot(s)}"></span>${esc(name)} <span class="badge">${esc(s.status)}</span></div>
          <div class="meta"><span>${esc(f.desc || "")}</span>${f.homepage ? `<a href="${esc(f.homepage)}" target="_blank" rel="noopener">${esc(f.homepage)}</a>` : ""}</div></div></div>
        <div class="actions">${svcActions(s, false)}
          ${btn(t("pkg.uninstall"), "svcUninstall", { name, confirm: t("pkg.confirmUninstallSvc", { name }) + (d.data_dir ? "\n\n" + t("pkg.dataKept", { dir: d.data_dir }) : "") }, "danger")}</div>
      </div>
      ${cf ? cfPanel(cf) : ""}
      <div class="grid two">
        <div class="card"><h3>${esc(t("pkg.info"))}</h3><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl></div>
        <div class="card"><h3>${esc(t("pkg.brewNotes"))}</h3>
          ${f.caveats ? `<pre style="padding:0;max-height:240px">${esc(f.caveats)}</pre>` : `<div class="muted small">${esc(t("pkg.noNotes"))}</div>`}</div>
      </div>
      <h2 class="row">${esc(t("pkg.config"))} <span class="spacer"></span><span class="muted small">${t("pkg.autoBackup", { dir: esc(d.backup_dir) })}</span></h2>
      ${d.config_files.length ? `
        <div class="row" style="margin-bottom:10px">
          <div class="pills">${d.config_files.map((p) => btn(esc(p.split("/").slice(-2).join("/")), "cfgFile", { path: p }, p === this.file ? "active" : "", `title="${esc(p)}"`)).join("")}</div>
          <span class="spacer"></span>
          ${d.can_validate ? btn(t("pkg.validate"), "cfgValidate") : ""}
          ${btn(t("pkg.save"), "cfgSave")}
          ${btn(t("pkg.saveRestart"), "cfgSave", { restart: 1 }, "primary")}
        </div>
        <textarea class="editor" id="cfgEd" spellcheck="false" style="min-height:48vh"></textarea>
        <pre class="card" id="cfgOut" style="display:none;margin-top:10px"></pre>`
      : `<div class="empty">${esc(t("pkg.noConfig"))}</div>`}`;
    if (this.file) await this.loadFile();
  },
  async loadFile() {
    const r = await api(`/api/services/config?name=${encodeURIComponent(this.param)}&path=${encodeURIComponent(this.file)}`);
    const ed = $("cfgEd");
    ed.value = r.content;
    ed.onkeydown = (e) => {
      if (e.key === "Tab") { e.preventDefault(); ed.setRangeText("  ", ed.selectionStart, ed.selectionEnd, "end"); }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); handlers.cfgSave({}); }
    };
  },
};

function showCfgOut(text, ok = true) {
  const o = $("cfgOut");
  o.style.display = "block";
  o.style.color = ok ? "" : "var(--red)";
  o.textContent = text;
}
handlers.cfgFile = async (d, el) => {
  tabs.service.file = d.path;
  el.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === el));
  await tabs.service.loadFile();
};
handlers.cfgValidate = async () => {
  const r = await api("/api/services/validate", { name: tabs.service.param, path: tabs.service.file });
  showCfgOut((r.ok ? "✅ " : "❌ ") + r.output, r.ok);
};
handlers.cfgSave = async (d) => {
  const body = { name: tabs.service.param, path: tabs.service.file, content: $("cfgEd").value, restart: !!d.restart };
  let r;
  try {
    r = await api("/api/services/config", body);
  } catch (e) {
    showCfgOut(e.message, false);
    if (e.code !== "svc.config_invalid" || !confirm(e.message + "\n\n" + t("pkg.forceSave"))) return;
    r = await api("/api/services/config", { ...body, force: true });
  }
  showCfgOut(t("pkg.savedOut", { backup: r.backup, validation: r.validation }) + (r.restart ? "\n\n" + t("pkg.restartOut", { r: r.restart }) : ""));
  toast(d.restart ? t("pkg.toastSavedRestart") : t("pkg.toastSaved"));
};

// ------------------------------------------------------------ cloudflared
function cfPanel(c) {
  if (c.error && !c.tunnels) return `<div class="warn">cloudflared: ${esc(c.error)}</div>`;
  const tunnels = (c.tunnels || []).map((tn) => {
    const proc = c.processes.find((p) => p.pid === tn.managed_pid) || c.processes.find((p) => p.command.includes(` ${tn.name}`) || p.command.includes(tn.id));
    return `<tr>
      <td><b>${esc(tn.name)}</b> ${tn.in_config ? `<span class="badge blue" title="${esc(t("pkg.cfUsedByConfig"))}">config.yml</span>` : ""}
        <div class="muted small"><code>${esc(tn.id)}</code></div></td>
      <td class="small">${tn.has_credentials ? `<span class="badge green">${esc(t("pkg.cfCredsOk"))}</span>` : `<span class="badge amber" title="${esc(t("pkg.cfNoCredsTitle", { id: tn.id }))}">${esc(t("pkg.cfNoCreds"))}</span>`}</td>
      <td class="small">${proc ? `<span class="row" style="gap:6px"><span class="dot on"></span>${esc(t("pkg.cfRunning", { pid: proc.pid }))}</span>` : `<span class="muted">${esc(t("pkg.cfDown"))}</span>`}
        <div class="muted small">${esc(t("pkg.cfConns", { n: tn.connections }))}</div></td>
      <td><div class="actions">
        ${proc ? btn(t("pkg.stop"), "cf", { action: "stop", name: tn.name, pid: proc.pid }, "danger")
               : tn.has_credentials ? btn(t("pkg.cfRun"), "cf", { action: "run", name: tn.name }, "go") : ""}
        ${btn(t("pkg.log"), "cf", { action: "logs", name: tn.name })}
        ${btn(t("pkg.cfRouteDns"), "cfRoute", { name: tn.name })}
        ${btn(t("pkg.delete"), "cf", { action: "delete", name: tn.name, job: 1, confirm: t("pkg.cfConfirmDelete", { name: tn.name }) }, "danger")}
      </div></td></tr>`;
  }).join("");
  const cfgTunnel = (c.tunnels || []).find((tn) => tn.in_config)?.name || c.config_tunnel;
  const ingress = c.ingress.map((r) => `<tr><td>${r.hostname ? `<a href="https://${esc(r.hostname)}" target="_blank" rel="noopener">${esc(r.hostname)}</a>` : `<span class="muted">${esc(t("pkg.cfOther"))}</span>`}</td>
      <td><code>${esc(r.service)}</code></td>
      <td><div class="actions">${r.hostname && cfgTunnel ? btn(t("pkg.cfRouteDnsShort"), "cf", { action: "route", name: cfgTunnel, hostname: r.hostname, job: 1 }) : ""}</div></td></tr>`).join("");
  return `
    <div class="card" style="margin-bottom:14px">
      <h3>☁️ Cloudflare Tunnel <span class="muted small">${esc(c.version || "")}</span><span class="spacer"></span>
        ${c.logged_in ? `<span class="badge green">${esc(t("pkg.cfLoggedIn"))}</span>
          ${btn(t("pkg.cfRelogin"), "cf", { action: "login", relogin: 1, job: 1, confirm: t("pkg.cfConfirmRelogin") })}`
        : btn(t("pkg.cfLogin"), "cf", { action: "login", job: 1 }, "primary")}</h3>
      ${c.logged_in ? "" : `<div class="warn">${t("pkg.cfNotLoggedIn")}</div>`}
      ${c.error ? `<div class="warn">${esc(c.error)}</div>` : ""}
      <h3 style="margin-top:6px">${esc(t("pkg.cfTunnels"))}</h3>
      ${tunnels ? `<div class="table-wrap"><table><tr><th>${esc(t("pkg.cfThName"))}</th><th>${esc(t("pkg.cfThCreds"))}</th><th>${esc(t("pkg.cfThStatus"))}</th><th></th></tr>${tunnels}</table></div>` : `<div class="muted small">${esc(t("pkg.cfNoTunnels"))}</div>`}
      <form class="row" id="cfCreate" style="margin-top:10px"><input type="text" name="name" placeholder="${esc(t("pkg.cfNewName"))}" style="max-width:240px"><button class="go">${esc(t("pkg.cfCreate"))}</button>
        <span class="muted small">${esc(t("pkg.cfBgNote"))}</span></form>
      <h3 style="margin-top:18px">Ingress <span class="muted small">${c.config_file ? `<code>${esc(c.config_file)}</code>` : t("pkg.cfNoConfig")}</span></h3>
      ${ingress ? `<div class="table-wrap"><table><tr><th>${esc(t("pkg.cfThHost"))}</th><th>${esc(t("pkg.cfThTarget"))}</th><th></th></tr>${ingress}</table></div>` : ""}
      ${c.config_file ? `<form class="row" id="cfIngress" data-tunnel="${esc(cfgTunnel || "")}" style="margin-top:10px">
        <input type="text" name="hostname" placeholder="app.example.com" style="flex:1;min-width:180px">
        <input type="text" name="service" placeholder="http://localhost:8000" style="flex:1;min-width:180px">
        <label class="chk"><input type="checkbox" name="route" checked> ${esc(t("pkg.cfAlsoRoute"))}</label>
        <button class="go">${esc(t("pkg.cfAddRule"))}</button></form>
        <p class="muted small">${esc(t("pkg.cfRuleNote"))}</p>` : ""}
    </div>`;
}

const cfReload = () => tabs.service.load();
handlers.cf = async (d) => {
  const body = { action: d.action, name: d.name, pid: d.pid, hostname: d.hostname, relogin: !!d.relogin };
  if (d.job) return runJob(api("/api/cloudflared", body), cfReload);
  const r = await api("/api/cloudflared", body);
  if (d.action === "logs") return showLog(`cloudflared — ${d.name}`, r.log);
  toast(d.action === "run" ? t("pkg.cfToastRun", { name: d.name, pid: r.pid }) : d.action === "stop" ? t("pkg.cfToastStop") : "OK");
  setTimeout(cfReload, d.action === "run" ? 1500 : 300);
};
handlers.cfRoute = (d) => {
  const host = prompt(t("pkg.cfPrompt", { name: d.name }), "app.example.com");
  if (host) return runJob(api("/api/cloudflared", { action: "route", name: d.name, hostname: host.trim() }), cfReload);
};
document.addEventListener("submit", async (e) => {
  if (e.target.id === "cfCreate") {
    e.preventDefault();
    const name = new FormData(e.target).get("name").trim();
    if (name) runJob(api("/api/cloudflared", { action: "create", name }), cfReload);
  }
  if (e.target.id === "cfIngress") {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      await api("/api/cloudflared", { action: "add-ingress", hostname: f.hostname.trim(), service: f.service.trim() });
      toast(t("pkg.cfToastRule", { host: f.hostname }));
      const tunnel = e.target.dataset.tunnel;
      if (f.route && tunnel) return runJob(api("/api/cloudflared", { action: "route", name: tunnel, hostname: f.hostname.trim() }), cfReload);
      cfReload();
    } catch (err) { toast(err.message, true); }
  }
});
