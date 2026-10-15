// Страница «Резервные копии» (backups.py): настройки, статус последней копии, история, доступные копии, проверка и восстановление.
// Восстановление всегда в НОВУЮ папку (~/Restored/…) — оригиналы не перезаписываются.

const bkSize = (n) => (n >= 1e9 ? (n / 1e9).toFixed(2) + " GB" : n >= 1e6 ? (n / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1e3)) + " KB");
const bkWhen = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
const bkStatusBadge = (s) => `<span class="badge ${s === "ok" ? "green" : s === "partial" ? "amber" : "amber"}">${esc(t("bk.status." + s))}</span>`;
// Сообщения о проблемах приходят кодами (backups.py): переводим, незнакомое показываем как есть.
function bkMsg(code) {
  if (!code) return "";
  const [k, arg] = String(code).split(":");
  const key = `bk.msg.${k}`;
  return t(key, { n: arg || "" }) === key ? String(code) : t(key, { n: arg || "" });
}

tabs.backups = {
  titleKey: "nav.backups",
  data: null,
  async load(silent) {
    try { this.data = await api("/api/backups"); }
    catch (e) { if (!silent) return failView(e); return; }
    this.render();
  },

  render() {
    const d = this.data;
    if (!d) return;
    const c = d.config, last = d.last;
    $("headline").textContent = last ? `${t("bk.last")}: ${t("bk.status." + last.status)}` : t("bk.never");
    const sum = (e) => {
      const n = (s) => e.items.filter((i) => i.status === s).length;
      return t("bk.summary", { ok: n("ok"), same: n("unchanged"), skip: n("skipped"), bad: n("failed") });
    };
    const statusCard = `<div class="card" style="margin-bottom:14px">
      <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap">
        <b>${esc(t("bk.status.title"))}</b>
        ${last ? bkStatusBadge(last.status) : `<span class="badge gray">${esc(t("bk.never"))}</span>`}
        ${d.dest_exists ? "" : `<span class="badge amber">${esc(t("bk.destMissing"))}</span>`}
        <span class="spacer"></span>
        ${btn(t("bk.runNow"), "bkRun", { confirm: t("bk.confirmRun", { dest: c.dest }) }, "primary")}
      </div>
      ${last ? `<div class="muted small" style="margin-top:8px">${esc(bkWhen(last.started))} · ${esc(last.duration)} s · ${esc(t("bk.trigger." + last.trigger))}
        ${last.items.length ? " · " + esc(sum(last)) : ""}${last.message ? " · " + esc(bkMsg(last.message)) : ""}</div>` : ""}
      ${d.last_ok && last && last.status === "failed" ? `<div class="muted small">${esc(t("bk.lastOk"))}: ${esc(bkWhen(d.last_ok.started))}</div>` : ""}
      <div class="muted small" style="margin-top:4px">${c.enabled ? esc(t("bk.next", { when: bkWhen(d.next_due), h: c.interval_hours })) : esc(t("bk.scheduleOff"))}</div>
    </div>`;

    const settings = `<form id="bkConfig" class="new-app">
      <div class="field"><label>${esc(t("bk.dest"))}</label><input type="text" name="dest" value="${esc(c.dest)}" autocomplete="off"></div>
      <div class="field"><label>${esc(t("bk.folders"))}</label>
        <textarea name="folders" rows="3" placeholder="~/Documents/Important">${esc(c.folders.join("\n"))}</textarea>
        <div class="muted small">${esc(t("bk.foldersHint"))}</div></div>
      <div class="row" style="gap:16px;flex-wrap:wrap">
        <label><input type="checkbox" name="repos" ${c.repos ? "checked" : ""}> ${esc(t("bk.repos"))}</label>
        <label><input type="checkbox" name="panel_data" ${c.panel_data ? "checked" : ""}> ${esc(t("bk.panelData"))}</label>
        <label><input type="checkbox" name="enabled" ${c.enabled ? "checked" : ""}> ${esc(t("bk.enabled"))}</label>
        <label>${esc(t("bk.interval"))} <select name="interval_hours">${d.intervals.map((h) => `<option value="${h}" ${h === c.interval_hours ? "selected" : ""}>${esc(t("bk.every", { h }))}</option>`).join("")}</select></label>
        <label>${esc(t("bk.keep"))} <input type="number" name="keep" min="1" max="30" value="${esc(c.keep)}" style="width:64px"></label>
      </div>
      <div class="row"><button type="submit" class="primary">${esc(t("bk.save"))}</button></div>
    </form>`;

    const hist = d.history.length ? `<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>${esc(t("audit.col.time"))}</th><th>${esc(t("bk.col.trigger"))}</th><th>${esc(t("audit.col.result"))}</th><th class="num">${esc(t("audit.col.duration"))}</th><th>${esc(t("bk.col.items"))}</th><th></th></tr></thead>
      <tbody>${d.history.map((h, i) => `<tr><td class="mono small" style="white-space:nowrap">${esc(bkWhen(h.started))}</td>
        <td class="small">${esc(t("bk.trigger." + h.trigger))}</td><td>${bkStatusBadge(h.status)}</td>
        <td class="num muted small">${esc(h.duration)} s</td><td class="muted small">${h.items.length ? esc(sum(h)) : esc(bkMsg(h.message))}</td>
        <td>${h.items.length ? btn(t("bk.details"), "bkDetails", { i }) : ""}</td></tr>`).join("")}</tbody></table></div></div>`
      : `<div class="muted small">${esc(t("bk.noHistory"))}</div>`;

    const kindName = (k) => t("bk.kind." + k);
    const arts = d.artifacts.length ? d.artifacts.map((a) => `<div class="card" style="margin-bottom:8px">
        <div class="name">${esc(kindName(a.kind))} <span class="mono muted small">${esc(a.key)}</span></div>
        ${a.files.map((f) => `<div class="row small" style="gap:8px;margin-top:4px"><span class="mono">${esc(f.file.split("/").pop())}</span>
          <span class="muted">${esc(bkSize(f.size))}</span><span class="spacer"></span>
          ${btn(t("bk.verify"), "bkVerify", { file: f.file })}
          ${btn(t("bk.restore"), "bkRestore", { file: f.file, confirm: t("bk.confirmRestore", { root: d.restore_root }) })}</div>`).join("")}
      </div>`).join("") : `<div class="muted small">${esc(t("bk.noArtifacts"))}</div>`;

    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("bk.intro"))}</span></div>
      ${statusCard}
      <h2>${esc(t("bk.settings"))}</h2><div class="card">${settings}</div>
      <h2>${esc(t("bk.history"))}</h2>${hist}
      <h2>${esc(t("bk.available"))}</h2>${arts}`;
    $("bkConfig").addEventListener("submit", (ev) => { ev.preventDefault(); this.save(new FormData(ev.target)); });
  },

  async save(f) {
    const body = {
      dest: String(f.get("dest") || "").trim(), enabled: !!f.get("enabled"), repos: !!f.get("repos"), panel_data: !!f.get("panel_data"),
      interval_hours: Number(f.get("interval_hours")), keep: Number(f.get("keep")),
      folders: String(f.get("folders") || "").split("\n").map((x) => x.trim()).filter(Boolean),
    };
    try { await api("/api/backups/config", body); toast(t("bk.saved")); }
    catch (e) { return toast(e.message, true); }
    await this.load();
  },
};

handlers.bkRun = async () => {
  const r = await api("/api/backups/run", {});
  await runJob(Promise.resolve(r), () => tabs.backups.load());
};
handlers.bkDetails = (d) => {
  const h = tabs.backups.data.history[Number(d.i)];
  $("logTitle").textContent = `${t("bk.details")}: ${bkWhen(h.started)}`;
  $("logBody").textContent = h.items.map((i) => `${i.status.padEnd(9)} ${t("bk.kind." + i.kind)}: ${i.name}`
    + (i.size ? `  (${bkSize(i.size)}${i.verify_level === "light" ? ", " + t("bk.lightVerify") : ""})` : "") + (i.message ? `  — ${bkMsg(i.message)}` : "")).join("\n");
  logDlg.showModal();
};
handlers.bkVerify = async (d) => {
  const r = await api("/api/backups/verify", { file: d.file });
  toast(r.ok ? `${t("bk.verifyOk")}${r.level === "light" ? " (" + t("bk.lightVerify") + ")" : ""}` : `${t("bk.verifyBad")}: ${r.message}`, !r.ok);
};
handlers.bkRestore = async (d) => {
  const r = await api("/api/backups/restore", { file: d.file });
  await runJob(Promise.resolve(r), () => toast(t("bk.restoredTo", { path: r.target })));
};
