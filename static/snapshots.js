// Страница «Снимки»: сохранить состояние машины и сравнить два снимка (или снимок и «сейчас»).
// Снимок ничего не меняет в системе — пишется только его файл (snapshots.py).

tabs.snapshots = {
  titleKey: "nav.snapshots",
  list: null,      // /api/snapshots
  diff: null,      // последний результат сравнения
  sel: { a: "", b: "current" },
  busy: false,

  async load(silent) {
    try { this.list = (await api("/api/snapshots")).snapshots; }
    catch (e) { if (!silent) return failView(e); return; }
    const ids = this.list.map((s) => s.id);
    if (!ids.includes(this.sel.a)) this.sel.a = ids[0] || "";
    if (this.sel.b !== "current" && !ids.includes(this.sel.b)) this.sel.b = "current";
    this.render();
  },

  // Перерисовка из памяти — при смене языка запросы не нужны (см. i18n.js).
  render() {
    const list = this.list;
    if (!list) return;
    $("headline").textContent = t("snap.count", { n: list.length });
    const when = (ts) => String(ts || "").replace("T", " ").replace(/[+-]\d{4}$/, "");
    const name = (s) => `${when(s.created)}${s.label ? " · " + s.label : ""}`;

    const row = (s) => `<tr>
      <td class="mono small" style="white-space:nowrap">${esc(when(s.created))}</td>
      <td>${esc(s.label || "")}${s.broken ? `<span class="badge amber">${esc(t("snap.broken"))}</span>` : ""}
          ${s.brew_available === false ? `<span class="badge gray">${esc(t("snap.noBrew"))}</span>` : ""}
          ${s.complete === false ? `<span class="badge amber" title="${esc(t("snap.incompleteTitle"))}">${esc(t("snap.incomplete"))}</span>` : ""}</td>
      <td class="muted small">${esc(t("snap.counts", s.counts || {}))}</td>
      <td><div class="actions">
        ${s.broken ? "" : btn(t("snap.brewfile"), "snapBrewfile", { id: s.id })}
        ${btn(t("snap.delete"), "snapDelete", { id: s.id, confirm: t("snap.confirmDelete") }, "danger")}
      </div></td></tr>`;

    const opts = (cur, withNow) => (withNow ? `<option value="current" ${cur === "current" ? "selected" : ""}>${esc(t("snap.now"))}</option>` : "")
      + list.filter((s) => !s.broken).map((s) => `<option value="${esc(s.id)}" ${s.id === cur ? "selected" : ""}>${esc(name(s))}</option>`).join("");

    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("snap.intro"))}</span></div>
      <form class="row" id="snapCreate" style="gap:8px;margin-bottom:14px">
        <input type="text" name="label" maxlength="80" placeholder="${esc(t("snap.labelPh"))}" style="flex:1;min-width:200px">
        <button type="submit" class="primary" ${this.busy ? "disabled" : ""}>${esc(this.busy ? t("snap.creating") : t("snap.create"))}</button>
      </form>
      ${list.length ? `<div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("snap.col.time"))}</th><th>${esc(t("snap.col.label"))}</th><th>${esc(t("snap.col.contents"))}</th><th></th></tr></thead>
        <tbody>${list.map(row).join("")}</tbody></table></div></div>

        <div class="card" style="margin-top:14px">
          <div class="name" style="margin-bottom:8px">${esc(t("snap.compare"))}</div>
          <form class="row" id="snapCompare" style="gap:8px;flex-wrap:wrap">
            <select name="a" aria-label="A">${opts(this.sel.a, false)}</select>
            <span class="muted">→</span>
            <select name="b" aria-label="B">${opts(this.sel.b, true)}</select>
            <button type="submit" class="primary">${esc(t("snap.doCompare"))}</button>
          </form>
          <div id="snapDiff" style="margin-top:12px"></div>
        </div>`
        : `<div class="card empty">${esc(t("snap.empty"))}</div>`}`;

    $("snapCreate")?.addEventListener("submit", (ev) => { ev.preventDefault(); this.create(new FormData(ev.target).get("label") || ""); });
    $("snapCompare")?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      this.sel = { a: fd.get("a"), b: fd.get("b") };
      this.runDiff();
    });
    this.renderDiff();
  },

  async create(label) {
    this.busy = true; this.render();
    try {
      await api("/api/snapshots/create", { label });
      toast(t("snap.created"));
    } catch (e) { toast(e.message, true); }
    this.busy = false;
    await this.load();
  },

  async runDiff() {
    const box = $("snapDiff");
    if (box) box.innerHTML = `<div class="loading">${esc(t("shell.loading"))}</div>`;
    try { this.diff = await api(`/api/snapshots/diff?a=${encodeURIComponent(this.sel.a)}&b=${encodeURIComponent(this.sel.b)}`); }
    catch (e) { this.diff = null; if (box) box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    this.renderDiff();
  },

  renderDiff() {
    const box = $("snapDiff"), d = this.diff;
    if (!box || !d) return;
    const when = (ts) => String(ts || "").replace("T", " ").replace(/[+-]\d{4}$/, "");
    const title = (id) => {
      if (id.startsWith("profile.")) return `${t("snap.sec.profile")}: ${profileName({ id: id.slice(8) })}`;
      const key = `snap.sec.${id}`;
      const tr = t(key);
      return tr === key ? id : tr;
    };
    const head = `<div class="muted small" style="margin-bottom:8px">${esc(when(d.a.created) || t("snap.now"))} → ${esc(d.b.id === "current" ? t("snap.now") : when(d.b.created))}
      · ${esc(t("snap.changes", { n: d.total }))}</div>
      ${d.note ? `<div class="note">${esc(t("snap.incompleteTitle"))}</div>` : ""}`;
    if (!d.total) { box.innerHTML = head + `<div class="muted">${esc(t("snap.noChanges"))}</div>`; return; }
    const line = (sign, cls, k, extra) => `<div class="check-row"><span class="mark ${cls}">${sign}</span>
      <span class="mono small">${esc(k)}</span><span class="muted small mono">${extra ? esc(extra) : ""}</span></div>`;
    box.innerHTML = head + d.sections.map((s) => `<div style="margin-bottom:12px">
      <div class="name" style="font-size:13px">${esc(title(s.id))}</div>
      <div class="checklist">
        ${s.added.map((x) => line("+", "", x.key, x.to)).join("")}
        ${s.removed.map((x) => line("−", "off", x.key, x.from)).join("")}
        ${s.changed.map((x) => line("~", "", x.key, `${x.from} → ${x.to}`)).join("")}
      </div></div>`).join("");
  },
};

handlers.snapDelete = async (d) => { await api("/api/snapshots/delete", { id: d.id }); tabs.snapshots.diff = null; await tabs.snapshots.load(); };
handlers.snapBrewfile = async (d) => {
  const s = await api(`/api/snapshots/get?id=${encodeURIComponent(d.id)}`);
  $("logTitle").textContent = "Brewfile";
  $("logBody").textContent = (s.brew && s.brew.brewfile) || t("snap.noBrewfile");
  logDlg.showModal();
};
