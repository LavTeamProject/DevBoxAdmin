// Страница «Аудит»: журнал действий панели (~/.service-admin/audit.log). Только чтение.
// Запись — audit.py; здесь фильтры по действию, результату и дате.

tabs.audit = {
  titleKey: "nav.audit",
  filters: { action: "", result: "", by: "", date_from: "", date_to: "" },
  data: null,
  entries: [],

  query(offset = 0) {
    const f = { ...this.filters, limit: 200, offset };
    return "?" + Object.entries(f).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  },

  async load(silent) {
    try { this.data = await api(`/api/audit${this.query()}`); }
    catch (e) { if (!silent) return failView(e); return; }
    this.entries = this.data.entries;
    this.render();
  },

  // Перерисовка из памяти — при смене языка запросы не нужны (см. i18n.js).
  render() {
    const d = this.data;
    if (!d) return;
    $("headline").textContent = t("audit.count", { n: d.total });
    const f = this.filters;
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
    const when = (ts) => String(ts || "").replace("T", " ").replace(/[+-]\d{4}$/, "");
    const params = (p) => {
      const s = JSON.stringify(p || {});
      return s === "{}" ? "" : s;
    };
    const who = (by0) => { const by = String(by0); return by === "panel" ? t("audit.by.panel")
      : by.startsWith("user:") ? t("audit.by.dialog")
      : by.startsWith("agent:") ? `${t("audit.agent")}: ${by.slice(6)}` : `${t("audit.by.system")}: ${by.replace(/^system:?/, "") || "—"}`; };
    const row = (e) => `<tr>
      <td class="mono small" style="white-space:nowrap">${esc(when(e.ts))}</td>
      <td class="mono small">${esc(e.action)}${e.job ? ` <span class="muted">#${esc(e.job)}</span>` : ""}</td>
      <td class="small"><span class="badge ${String(e.by).startsWith("agent:") ? "blue" : "gray"}" title="${esc(e.agent_id || "")}">${esc(who(String(e.by || "panel")))}</span></td>
      <td class="mono small" title="${esc(params(e.params))}" style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(params(e.params))}</td>
      <td><span class="badge ${e.failed ? "amber" : "green"}">${esc(e.failed ? t("audit.failed") : t("audit.ok"))}</span>
          ${e.failed && e.result && !["failed", "ok"].includes(e.result) ? `<div class="muted small">${esc(e.result)}</div>` : ""}</td>
      <td class="num muted small">${esc(e.ms >= 1000 ? (e.ms / 1000).toFixed(1) + " s" : e.ms + " ms")}</td>
      <td class="num muted small">${e.code ?? ""}</td>
    </tr>`;
    const more = this.entries.length < d.total
      ? `<div class="row" style="margin-top:10px"><span class="spacer"></span>${btn(t("audit.more", { n: d.total - this.entries.length }), "auditMore")}</div>` : "";

    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("audit.intro"))}</span></div>
      <form class="row" id="auditFilters" style="margin-bottom:12px;gap:8px;flex-wrap:wrap">
        <select name="action" aria-label="${esc(t("audit.f.action"))}">
          ${opt("", t("audit.f.allActions"), f.action)}${d.actions.map((a) => opt(a, a, f.action)).join("")}</select>
        <select name="result" aria-label="${esc(t("audit.f.result"))}">
          ${opt("", t("audit.f.allResults"), f.result)}${opt("ok", t("audit.ok"), f.result)}${opt("error", t("audit.failed"), f.result)}</select>
        <select name="by" aria-label="${esc(t("audit.f.by"))}">
          ${opt("", t("audit.f.allBy"), f.by)}${(d.initiators || []).map((x) => opt(x, who(x), f.by)).join("")}</select>
        <label class="muted small">${esc(t("audit.f.from"))} <input type="date" name="date_from" value="${esc(f.date_from)}"></label>
        <label class="muted small">${esc(t("audit.f.to"))} <input type="date" name="date_to" value="${esc(f.date_to)}"></label>
        <button type="submit" class="primary">${esc(t("audit.f.apply"))}</button>
        <button type="button" data-act="auditReset">${esc(t("audit.f.reset"))}</button>
        <span class="spacer"></span>
        ${btn(t("profiles.rescan"), "auditReload")}
      </form>
      ${this.entries.length ? `<div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("audit.col.time"))}</th><th>${esc(t("audit.col.action"))}</th><th>${esc(t("audit.col.by"))}</th><th>${esc(t("audit.col.params"))}</th>
          <th>${esc(t("audit.col.result"))}</th><th class="num">${esc(t("audit.col.duration"))}</th><th class="num">${esc(t("audit.col.code"))}</th></tr></thead>
        <tbody>${this.entries.map(row).join("")}</tbody></table></div></div>${more}`
        : `<div class="card empty">${esc(t("audit.empty"))}</div>`}`;

    $("auditFilters").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      this.filters = { action: fd.get("action") || "", result: fd.get("result") || "", by: fd.get("by") || "", date_from: fd.get("date_from") || "", date_to: fd.get("date_to") || "" };
      this.load();
    });
  },
};

handlers.auditReload = () => tabs.audit.load();
handlers.auditReset = () => { tabs.audit.filters = { action: "", result: "", by: "", date_from: "", date_to: "" }; return tabs.audit.load(); };
handlers.auditMore = async () => {
  const a = tabs.audit;
  const next = await api(`/api/audit${a.query(a.entries.length)}`);
  a.entries = a.entries.concat(next.entries);
  a.data = { ...a.data, total: next.total, actions: next.actions };
  a.render();
};
