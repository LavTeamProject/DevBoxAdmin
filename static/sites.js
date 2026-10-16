// Страница «Сайты и домены» (Фаза 10, U5): только чтение + установка компонентов кнопками. Конфиги прокси, resolver и /etc/hosts панель не пишет.
tabs.sites = {
  titleKey: "nav.sites",
  data: null,
  async load(silent) {
    try { this.data = await api("/api/sites"); }
    catch (e) { if (!silent) return failView(e); return; }
    this.render();
  },
  render() {
    const d = this.data;
    if (!d) return;
    const step = (ok, label, hint) => `<tr><td>${ok ? `<span class="badge green">${esc(t("sites.ok"))}</span>` : `<span class="badge gray">${esc(t("sites.todo"))}</span>`}</td><td>${label}</td><td class="muted small">${esc(hint || "")}</td></tr>`;
    const part = (p) => {
      const act = p.installed ? "" : btn(t("profiles.install"), "sitesInstall", { formula: p.formula }, "go");
      const state = p.installed ? (p.service ? (p.running ? t("sites.running") : t("sites.stopped")) : t("sites.installed")) : t("sites.notInstalled");
      return `<tr><td>${p.installed ? `<span class="badge green">${esc(t("sites.ok"))}</span>` : `<span class="badge gray">${esc(t("sites.todo"))}</span>`}</td>
        <td><code>${esc(p.formula)}</code></td><td class="muted small">${esc(t("sites.part." + p.id))}</td><td>${esc(state)}</td><td><div class="actions">${act}${p.installed && p.service ? `<a href="#service:${esc(p.formula)}">${esc(t("sites.manage"))}</a>` : ""}</div></td></tr>`;
    };
    const h = d.herd || {};
    const herdBlock = !d.mac ? "" : h.installed
      ? `<h2>${esc(t("sites.herd"))}${h.tld ? ` <span class="muted small">.${esc(h.tld)}</span>` : ""}</h2>
         ${(h.sites || []).length ? `<div class="table-wrap"><table><tr><th>${esc(t("sites.thSite"))}</th><th>URL</th><th>PHP</th><th>HTTPS</th></tr>
           ${h.sites.map((s) => `<tr><td>${esc(s.name)}</td><td class="mono small">${esc(s.url || "")}</td><td>${esc(s.php || "—")}</td><td>${s.secured ? `<span class="badge green">${esc(t("sites.ok"))}</span>` : "—"}</td></tr>`).join("")}</table></div>`
           : `<div class="empty">${esc(t("shell.empty"))}</div>`}
         <p><a href="#herd">${esc(t("sites.openHerd"))}</a></p>`
      : `<h2>${esc(t("sites.herd"))}</h2><p class="muted">${esc(t("sites.noHerd"))}</p>`;
    const hosts = d.hosts.length ? `<div class="table-wrap"><table><tr><th>IP</th><th>${esc(t("sites.thNames"))}</th></tr>
      ${d.hosts.map((r) => `<tr><td class="mono small">${esc(r.ip)}</td><td class="mono small">${esc(r.names.join(" "))}</td></tr>`).join("")}</table></div>` : `<div class="empty">${esc(t("sites.noHosts"))}</div>`;
    view.innerHTML = `${roBanner(t("sites.intro"))}
      ${herdBlock}
      <h2>${esc(t("sites.checklist"))}</h2>
      <p class="muted small">${esc(t("sites.checklistNote"))}</p>
      <div class="table-wrap"><table><tr><th></th><th>${esc(t("sites.thComp"))}</th><th>${esc(t("sites.thWhy"))}</th><th>${esc(t("sites.thState"))}</th><th></th></tr>${d.parts.map(part).join("")}</table></div>
      <div class="table-wrap"><table>
        ${step(d.dnsmasq_rule, t("sites.stepRule"), t("sites.stepRuleHint"))}
        ${d.mac ? step(d.resolver, t("sites.stepResolver"), t("sites.stepResolverHint")) : ""}
        ${step(d.mkcert_ca, t("sites.stepCa"), t("sites.stepCaHint"))}</table></div>
      <h2>${esc(t("sites.tunnels"))}</h2>
      <p>${d.cloudflared ? `<a href="#service:cloudflared">${esc(t("sites.openTunnels"))}</a>` : `<span class="muted">${esc(t("sites.noCf"))}</span> ${btn(t("profiles.install"), "sitesInstall", { formula: "cloudflared" }, "go")}`}</p>
      <h2>/etc/hosts</h2>
      <p class="muted small">${esc(t("sites.hostsNote"))}</p>${hosts}`;
  },
};
handlers.sitesInstall = (d) => runJob(api("/api/services/install", { formula: d.formula }), () => tabs.sites.load());
