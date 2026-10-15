// Удалённый доступ (Фаза 8, ADR-0003): API для клиентов, операторы, Telegram-бот. Часть страницы «Подключение агентов» (connect.js).
// Токены и секрет TOTP показываются ОДИН раз (tab.once) и нигде не сохраняются; всё, что ослабляет защиту, подтверждается системным диалогом на сервере.

async function loadRemoteExtra(tab) {
  tab.rapi = await api("/api/remote").catch(() => null);
  tab.opsList = await api("/api/operators").catch(() => null);
  tab.tg = await api("/api/telegram").catch(() => null);
}

function onceBox(tab) {
  const o = tab.once;
  if (!o) return "";
  return `<div class="card" style="margin:8px 0;border-color:var(--accent)"><div class="name">${esc(o.title)}</div>
    <p class="warn small">${esc(t("rmt.once"))}</p>
    ${o.rows.map(([k, v]) => `<div class="muted small">${esc(k)}</div><pre class="diff" style="white-space:pre-wrap;word-break:break-all">${esc(v)}</pre>`).join("")}
    ${btn(t("rmt.hide"), "rmtHideOnce")}</div>`;
}

function remoteApiCard(tab) {
  const r = tab.rapi;
  if (!r) return "";
  const s = r.settings;
  const badge = r.running ? `<span class="badge green">${esc(t("rmt.running"))}</span>` : r.error ? `<span class="badge amber">${esc(t("rmt.error"))}: ${esc(r.error)}</span>` : `<span class="badge gray">${esc(t("rmt.off"))}</span>`;
  const agents = (tab.data?.agents || []).filter((a) => !a.revoked);
  const base = `${r.scheme}://${(tab.remote?.ssh?.hosts || ["HOST"])[0]}:${s.port}`;
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("gw.remote.type.api"))} ${badge}</div>
    <p class="muted small">${esc(t("rmt.api.intro"))}</p>
    <div class="row" style="gap:12px;flex-wrap:wrap;align-items:center">
      <label class="small"><input type="checkbox" id="rmtEnabled" ${s.enabled ? "checked" : ""}> ${esc(t("rmt.enable"))}</label>
      <label class="small">${esc(t("rmt.bind"))} <input type="text" id="rmtBind" value="${esc(s.bind)}" size="16"></label>
      <label class="small">${esc(t("rmt.port"))} <input type="number" id="rmtPort" value="${esc(s.port)}" style="width:90px"></label>
      <label class="small"><input type="checkbox" id="rmtTls" ${s.tls ? "checked" : ""}> TLS</label>
      <label class="small"><input type="checkbox" id="rmtApproval" ${s.remote_approval ? "checked" : ""}> ${esc(t("rmt.approval"))}</label></div>
    <div class="small" style="margin-top:6px">${esc(t("rmt.allow"))}</div>
    <textarea id="rmtAllow" rows="2" style="width:100%;font-family:monospace" placeholder="192.168.1.0/24">${esc(s.allow.join("\n"))}</textarea>
    <p class="muted small">${esc(t("rmt.bindHelp"))}</p>
    <div class="row" style="gap:8px;margin:6px 0">${btn(t("rmt.save"), "rmtSave", {}, "primary")}</div>
    ${r.running ? `<div class="small">${esc(t("rmt.address"))}: <span class="mono">${esc(base)}</span></div>` : ""}
    ${r.tls_fingerprint ? `<div class="small">${esc(t("rmt.fp"))}: <span class="mono" style="word-break:break-all">${esc(r.tls_fingerprint)}</span></div>` : ""}
    <div class="muted small" style="margin-top:8px">${esc(t("rmt.example"))}</div>
    <pre class="diff" style="white-space:pre-wrap">curl ${r.tls_fingerprint ? "--cacert panel-cert.pem " : ""}-H "Authorization: Bearer &lt;token&gt;" ${esc(base)}/agent/v1/tools</pre>
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px"><label class="small">${esc(t("rmt.issueFor"))}
      <select id="rmtIssueAgent"><option value="">—</option>${agents.map((a) => `<option value="${esc(a.id)}">${esc(a.name)}</option>`).join("")}</select></label>
      ${btn(t("rmt.issue"), "rmtIssue", {})}</div>
    <div class="muted small">${esc(t("rmt.issueNote"))}</div></div>`;
}

function operatorsCard(tab) {
  const d = tab.opsList;
  if (!d) return "";
  const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
  const rows = d.operators.filter((o) => !o.revoked).map((o) => `<tr><td><b>${esc(o.name)}</b><div class="mono muted small">${esc(o.id)}</div></td>
      <td class="small">${o.scopes.map((x) => `<span class="badge">${esc(t("rmt.scope." + x))}</span>`).join(" ")}</td>
      <td class="mono small">${esc(o.telegram_chat_id || "—")}</td><td class="muted small">${esc(when(o.last_seen))}</td>
      <td>${o.totp_locked ? `<span class="badge amber">${esc(t("rmt.locked"))}</span> ${btn(t("rmt.unlock"), "rmtOpUnlock", { id: o.id })} ` : ""}${btn(t("gw.rotate"), "rmtOpRotate", { id: o.id, confirm: t("rmt.confirmRotate", { name: o.name }) }, "go")}
          ${btn(t("gw.revoke"), "rmtOpRevoke", { id: o.id, confirm: t("gw.confirmRevoke", { name: o.name }) }, "danger")}</td></tr>`).join("");
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("rmt.operators"))}</div>
    <p class="muted small">${esc(t("rmt.ops.intro"))}</p>
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
      <input type="text" id="rmtOpName" maxlength="40" placeholder="${esc(t("rmt.opName"))}" autocomplete="off" style="min-width:180px">
      <label class="small"><input type="checkbox" id="rmtOpRead" checked> ${esc(t("rmt.scope.read"))}</label>
      <label class="small"><input type="checkbox" id="rmtOpApprove"> ${esc(t("rmt.scope.approve"))}</label>
      <input type="text" id="rmtOpChat" placeholder="Telegram chat_id" style="width:150px" autocomplete="off">
      ${btn(t("rmt.opCreate"), "rmtOpCreate", {}, "primary")}</div>
    ${onceBox(tab)}
    ${rows ? `<div class="table-wrap"><table><thead><tr><th>${esc(t("rmt.col.operator"))}</th><th>${esc(t("rmt.col.rights"))}</th><th>chat_id</th><th>${esc(t("gw.col.seen"))}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
         : `<div class="muted small">${esc(t("rmt.noOps"))}</div>`}</div>`;
}

function telegramCard(tab) {
  const g = tab.tg;
  if (!g) return "";
  const badge = g.running ? `<span class="badge green">${esc(t("rmt.running"))}</span>` : g.enabled && g.token_set ? `<span class="badge amber">${esc(g.error || t("rmt.starting"))}</span>` : `<span class="badge gray">${esc(t("rmt.off"))}</span>`;
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("gw.remote.type.telegram"))} ${badge}</div>
    <p class="muted small">${esc(t("rmt.tg.intro"))}</p>
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
      <input type="password" id="tgToken" placeholder="${esc(g.token_set ? t("rmt.tg.tokenSet") : t("rmt.tg.tokenPh"))}" autocomplete="off" style="min-width:300px">
      <label class="small"><input type="checkbox" id="tgEnabled" ${g.enabled ? "checked" : ""}> ${esc(t("rmt.enable"))}</label>
      ${btn(t("rmt.save"), "tgSave", {}, "primary")} ${g.token_set ? btn(t("rmt.tg.check"), "tgCheck") : ""}</div>
    ${g.username ? `<div class="small">${esc(t("rmt.tg.bot"))}: @${esc(g.username)}</div>` : ""}
    <p class="muted small">${esc(t("rmt.tg.help"))}</p></div>`;
}

async function rmtReload() { const tab = tabs.connect; await loadRemoteExtra(tab); tab.render(); }

handlers.rmtHideOnce = async () => { tabs.connect.once = null; tabs.connect.render(); };
handlers.rmtSave = async () => {
  const body = { enabled: $("rmtEnabled").checked, bind: $("rmtBind").value.trim(), port: Number($("rmtPort").value), tls: $("rmtTls").checked,
                 remote_approval: $("rmtApproval").checked, allow: $("rmtAllow").value.split(/[\s,]+/).filter(Boolean) };
  try { await api("/api/remote/settings", body); toast(t("rmt.saved")); } catch (e) { toast(e.message, true); }
  await rmtReload();
};
handlers.rmtIssue = async () => {
  const id = $("rmtIssueAgent").value;
  if (!id) return;
  if (!confirm(t("rmt.confirmIssue"))) return;
  try { const r = await api("/api/remote/agent-token", { id }); tabs.connect.once = { title: t("rmt.agentToken"), rows: [[t("rmt.token"), r.token]] }; }
  catch (e) { toast(e.message, true); }
  tabs.connect.render();
};
handlers.rmtOpCreate = async () => {
  const scopes = [$("rmtOpRead").checked && "read", $("rmtOpApprove").checked && "approve"].filter(Boolean);
  const body = { name: $("rmtOpName").value.trim(), scopes };
  if ($("rmtOpChat").value.trim()) body.telegram_chat_id = $("rmtOpChat").value.trim();
  try {
    const r = await api("/api/operators/create", body);
    tabs.connect.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret], [t("rmt.totpUri"), r.totp_uri]] };
  } catch (e) { toast(e.message, true); }
  await rmtReload();
};
handlers.rmtOpRotate = async (d) => {
  try { const r = await api("/api/operators/rotate", { id: d.id }); tabs.connect.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret]] }; }
  catch (e) { toast(e.message, true); }
  await rmtReload();
};
handlers.rmtOpUnlock = async (d) => { try { await api("/api/operators/unlock", { id: d.id }); toast(t("rmt.unlocked")); } catch (e) { toast(e.message, true); } await rmtReload(); };
handlers.rmtOpRevoke = async (d) => { try { await api("/api/operators/revoke", { id: d.id }); toast(t("gw.revoked")); } catch (e) { toast(e.message, true); } await rmtReload(); };
handlers.tgSave = async () => {
  const body = { enabled: $("tgEnabled").checked };
  if ($("tgToken").value.trim()) body.token = $("tgToken").value.trim();
  try { await api("/api/telegram/settings", body); toast(t("rmt.saved")); } catch (e) { toast(e.message, true); }
  await rmtReload();
};
handlers.tgCheck = async () => { try { await api("/api/telegram/check", {}); toast(t("rmt.tg.ok")); } catch (e) { toast(e.message, true); } await rmtReload(); };
