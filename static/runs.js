// Страница «Запуски»: история test/build по всем проектам (runs.py). Только чтение.

tabs.runs = {
  titleKey: "nav.runs",
  filters: { kind: "", status: "" },
  data: null,
  async load(silent) {
    const q = Object.entries({ ...this.filters, limit: 100 }).filter(([, v]) => v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
    try { this.data = await api(`/api/runs?${q}`); }
    catch (e) { if (!silent) return failView(e); return; }
    this.render();
  },
  render() {
    const d = this.data;
    if (!d) return;
    $("headline").textContent = t("runs.count", { n: d.total });
    const f = this.filters;
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(label)}</option>`;
    const row = (r) => `<tr>
      <td class="mono small" style="white-space:nowrap">${esc(runWhen(r.started))}</td>
      <td><a href="#projects:${encodeURIComponent(r.project)}">${esc(r.name)}</a></td>
      <td class="mono small">${esc(r.kind)}</td>
      <td class="mono small muted" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.command)}">${esc(r.command)}</td>
      <td>${runBadge(r)}</td><td class="num muted small">${esc(r.duration)} s</td>
      <td>${btn(t("runs.log"), "runLog", { id: r.id })}</td></tr>`;
    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("runs.intro"))}</span></div>
      <form class="row" id="runsFilters" style="gap:8px;margin-bottom:12px">
        <select name="kind">${opt("", t("runs.f.allKinds"), f.kind)}${opt("test", "test", f.kind)}${opt("build", "build", f.kind)}</select>
        <select name="status">${opt("", t("runs.f.allStatuses"), f.status)}${["ok", "failed", "timeout", "error"].map((x) => opt(x, t("runs.status." + x), f.status)).join("")}</select>
        <button type="submit" class="primary">${esc(t("audit.f.apply"))}</button></form>
      ${d.runs.length ? `<div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("audit.col.time"))}</th><th>${esc(t("tasks.project"))}</th><th>${esc(t("runs.col.kind"))}</th><th>${esc(t("runs.col.command"))}</th>
          <th>${esc(t("audit.col.result"))}</th><th class="num">${esc(t("audit.col.duration"))}</th><th></th></tr></thead>
        <tbody>${d.runs.map(row).join("")}</tbody></table></div></div>` : `<div class="card empty">${esc(t("runs.empty"))}</div>`}`;
    $("runsFilters").addEventListener("submit", (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      this.filters = { kind: fd.get("kind") || "", status: fd.get("status") || "" };
      this.load();
    });
  },
};
