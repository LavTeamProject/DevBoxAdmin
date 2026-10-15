// Страница «Подключение агентов» (agent_gateway.py): регистрация ИИ-агентов и готовая команда подключения по MCP.
// Секрет агента в браузер не попадает: показывается только id и путь к файлу секрета.

tabs.connect = {
  titleKey: "nav.connect",
  data: null,
  ops: null,     // /api/operations (каталог операций)
  plans: null,   // /api/plans (очередь подтверждений и история)
  interval: 5000,
  remote: null,  // /api/agent-gateway/remote (типы удалённого подключения; Фаза 8)
  rapi: null, opsList: null, tg: null, once: null,   // remote.js: API клиентов, операторы, Telegram; once — токен/секрет, показываемый один раз
  remoteAgent: "", remoteKey: "", remoteErr: "",
  fresh: null,   // результат последней регистрации (команда и конфиг для копирования)
  async load(silent) {
    try { this.data = await api("/api/agent-gateway"); this.ops = await api("/api/operations").catch(() => null); this.plans = await api("/api/plans").catch(() => null); await this.loadRemote(); await loadRemoteExtra(this); }
    catch (e) { if (!silent) return failView(e); return; }
    // фоновое обновление не должно стирать то, что человек сейчас вводит в поля
    if (silent && view.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    this.render();
  },

  async loadRemote() {
    const q = this.remoteAgent ? `?agent=${encodeURIComponent(this.remoteAgent)}${this.remoteKey ? `&key=${encodeURIComponent(this.remoteKey)}` : ""}` : "";
    try { this.remote = await api("/api/agent-gateway/remote" + q); this.remoteErr = ""; }
    catch (e) {
      this.remoteErr = e.message;
      if (this.remoteKey) { this.remoteKey = ""; this.remote = await api("/api/agent-gateway/remote" + (this.remoteAgent ? `?agent=${encodeURIComponent(this.remoteAgent)}` : "")).catch(() => this.remote); }
    }
  },

  render() {
    const d = this.data;
    if (!d) return;
    const now = Date.now() / 1000;
    $("headline").textContent = t("gw.count", { n: d.agents.filter((a) => !a.revoked).length });
    const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
    const state = (a) => (a.revoked ? ["gray", "gw.state.revoked"] : a.expires && a.expires < now ? ["amber", "gw.state.expired"] : ["green", "gw.state.active"]);
    const rows = d.agents.map((a) => {
      const [cls, key] = state(a);
      return `<tr><td><b>${esc(a.name)}</b><div class="mono muted small">${esc(a.id)}</div></td>
        <td>${a.revoked ? `<span class="badge">${esc(a.level)}</span>` : `<select data-gw-level="${esc(a.id)}" aria-label="${esc(t("gw.col.level"))}">
            ${["L1", "L2", "L3"].map((l) => `<option value="${l}" ${l === a.level ? "selected" : ""}>${l} · ${esc(t("gw.lvl." + l))}</option>`).join("")}</select>
          ${a.level === "L2" ? `<div><label class="small ${a.auto_approve?.includes("L2") ? "warn-text" : "muted"}"><input type="checkbox" data-gw-auto="${esc(a.id)}" ${a.auto_approve?.includes("L2") ? "checked" : ""}> ${esc(t("gw.autoApprove"))}</label></div>` : ""}`}</td>
        <td><span class="badge ${cls}">${esc(t(key))}</span></td>
        <td class="muted small">${esc(when(a.created))}</td><td class="muted small">${esc(a.expires ? when(a.expires) : t("gw.noExpiry"))}</td>
        <td class="muted small">${esc(when(a.last_seen))}</td><td class="num muted small">${esc(a.calls || 0)}</td>
        <td>${a.revoked ? "" : btn(t("gw.rotate"), "gwRotate", { id: a.id, confirm: t("gw.confirmRotate", { name: a.name }) }, "go") + " " + btn(t("gw.revoke"), "gwRevoke", { id: a.id, confirm: t("gw.confirmRevoke", { name: a.name }) }, "danger")}</td></tr>`;
    }).join("");
    const f = this.fresh;
    const freshCard = f ? `<div class="card" style="margin-bottom:14px;border-color:var(--accent)">
      <div class="name">${esc(t("gw.registered", { name: f.name }))}</div>
      <p class="muted small">${esc(t("gw.tokenNote", { file: f.token_file }))}</p>
      <div class="muted small" style="margin-top:6px">${esc(t("gw.claudeCmd"))}</div>
      <pre class="diff" style="white-space:pre-wrap">${esc(f.claude_code)}</pre>
      ${btn(t("gw.copy"), "gwCopy", { what: "claude" })}
      <div class="muted small" style="margin-top:10px">${esc(t("gw.jsonCfg"))}</div>
      <pre class="diff">${esc(f.json)}</pre>
      ${btn(t("gw.copy"), "gwCopy", { what: "json" })}</div>` : "";
    view.innerHTML = `
      <div class="ro-banner"><span>${esc(t("gw.intro"))}</span></div>
      ${plansSection(this.plans)}
      <div class="warn" style="margin-bottom:14px">${esc(t("gw.honest"))}</div>
      <div class="row" style="gap:8px;margin-bottom:12px">
        <span class="badge ${d.socket_ready ? "green" : "amber"}">${esc(d.socket_ready ? t("gw.socketOk") : t("gw.socketDown"))}</span>
        <span class="muted small">${esc(t("gw.limits", { n: d.rate_per_min }))}</span></div>
      ${freshCard}
      <h2>${esc(t("gw.connect"))}</h2>
      <form id="gwNew" class="row" style="gap:8px;margin-bottom:14px;flex-wrap:wrap">
        <input type="text" name="name" maxlength="40" placeholder="${esc(t("gw.namePh"))}" autocomplete="off" style="min-width:220px">
        <select name="level"><option value="L1">L1 · ${esc(t("gw.lvl.L1"))}</option><option value="L2">L2 · ${esc(t("gw.lvl.L2"))}</option><option value="L3">L3 · ${esc(t("gw.lvl.L3"))}</option></select>
        <select name="expires"><option value="">${esc(t("gw.noExpiry"))}</option><option value="30">30 ${esc(t("gw.days"))}</option><option value="90">90 ${esc(t("gw.days"))}</option><option value="365">365 ${esc(t("gw.days"))}</option></select>
        <button type="submit" class="primary">${esc(t("gw.register"))}</button></form>
      ${remoteSection(this)}
      <h2>${esc(t("gw.agents"))}</h2>
      ${d.agents.length ? `<div class="card"><div class="table-wrap"><table>
        <thead><tr><th>${esc(t("gw.col.agent"))}</th><th>${esc(t("gw.col.level"))}</th><th>${esc(t("audit.col.result"))}</th><th>${esc(t("gw.col.created"))}</th><th>${esc(t("gw.col.expires"))}</th><th>${esc(t("gw.col.seen"))}</th><th class="num">${esc(t("gw.col.calls"))}</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div></div>` : `<div class="empty">${esc(t("gw.none"))}</div>`}
      <h2>${esc(t("gw.tools"))}</h2>
      <div class="muted small">${esc(t("gw.toolsList"))}</div>
      ${opsCatalog(this.ops)}`;
    $("gwNew").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      const body = { name: String(fd.get("name") || "").trim(), level: fd.get("level") || "L1" };
      if (fd.get("expires")) body.expires_days = Number(fd.get("expires"));
      try { this.fresh = await api("/api/agent-gateway/register", body); toast(t("gw.created")); }
      catch (e) { return toast(e.message, true); }
      await this.load();
    });
  },
};

// ---- Подтверждения (plans.py): агент предлагает — человек решает. По умолчанию решение — в системном диалоге macOS.
const planOp = (p) => { const k = `op.${p.operation}`; const v = t(k); return v === k ? p.title : v; };
const planStatusCls = { pending: "amber", awaiting_human: "amber", approved: "blue", executing: "blue", done: "green", failed: "amber", rejected: "gray", expired: "gray", stale: "amber", cancelled: "gray", noop: "gray", unknown: "gray" };
function planSummary(p) {
  const v = p.view || {};
  return v.would_run || (v.to_install && v.to_install.length ? v.to_install.join(", ") : "") || v.writes || "";
}
function plansSection(pl) {
  if (!pl) return "";
  const open = pl.plans.filter((p) => p.status === "pending" || p.status === "awaiting_human");
  const left = (p) => Math.max(0, Math.round((p.expires * 1000 - Date.now()) / 60000));
  const cards = open.map((p) => `<div class="card" style="margin-bottom:8px;border-color:var(--accent)">
      <div class="row" style="gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(planOp(p))}</b> <span class="badge ${p.level === "L2" ? "blue" : "amber"}">${esc(p.level)}</span>
        <span class="muted small">${esc(t("plans.from", { agent: p.agent_name }))}</span><span class="spacer"></span>
        <span class="muted small">${esc(t("plans.left", { n: left(p) }))}</span></div>
      <div class="mono small" style="margin:6px 0;word-break:break-all">${esc(JSON.stringify(p.params))}</div>
      ${planSummary(p) ? `<div class="small">${esc(t("plans.willDo"))}: <span class="mono">${esc(planSummary(p))}</span></div>` : ""}
      ${p.error === "dialog_unavailable" ? `<div class="warn small">${esc(t("plans.dialogUnavailable"))}</div>` : ""}
      <div class="row" style="gap:8px;margin-top:8px">
        ${p.status === "awaiting_human" ? `<span class="badge amber">${esc(t("plans.awaitingDialog"))}</span>`
          : btn(t("plans.approve"), "planApprove", { id: p.id, confirm: t(pl.policy.approval === "dialog" ? "plans.confirmDialog" : "plans.confirmPanel", { op: planOp(p), agent: p.agent_name }) }, "primary")}
        ${btn(t("plans.reject"), "planReject", { id: p.id }, "danger")}</div></div>`).join("");
  const recent = pl.plans.filter((p) => !open.includes(p)).slice(0, 8);
  const rows = recent.map((p) => `<tr><td class="small"><b>${esc(planOp(p))}</b><div class="mono muted small">${esc(p.id)} · ${esc(p.agent_name)}</div></td>
      <td><span class="badge">${esc(p.level)}</span></td><td><span class="badge ${planStatusCls[p.status] || ""}">${esc(t("plans.st." + p.status))}</span></td>
      <td class="muted small">${esc(new Date(p.created * 1000).toLocaleString())}</td></tr>`).join("");
  return `<h2>${esc(t("plans.title"))} ${pl.pending ? `<span class="badge amber">${pl.pending}</span>` : ""}</h2>
    <div class="muted small" style="margin-bottom:8px">${esc(t("plans.intro"))}</div>
    ${cards || `<div class="muted small" style="margin-bottom:8px">${esc(t("plans.none"))}</div>`}
    <div class="row" style="gap:8px;margin:8px 0 12px;flex-wrap:wrap">
      <label class="small">${esc(t("plans.mode"))} <select id="planMode">
        <option value="dialog" ${pl.policy.approval === "dialog" ? "selected" : ""}>${esc(t("plans.mode.dialog"))}</option>
        <option value="panel" ${pl.policy.approval === "panel" ? "selected" : ""}>${esc(t("plans.mode.panel"))}</option></select></label>
      ${pl.policy.approval === "panel" ? `<span class="warn small">${esc(t("plans.mode.panelWarn"))}</span>` : ""}</div>
    ${rows ? `<div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("ops.col.op"))}</th><th>${esc(t("ops.col.level"))}</th><th>${esc(t("audit.col.result"))}</th><th>${esc(t("audit.col.time"))}</th></tr></thead><tbody>${rows}</tbody></table></div></div>` : ""}`;
}

handlers.planApprove = async (d) => { await api("/api/plans/approve", { id: d.id }); toast(t("plans.askedHuman")); await tabs.connect.load(); };
handlers.planReject = async (d) => { await api("/api/plans/reject", { id: d.id }); await tabs.connect.load(); };
document.addEventListener("change", async (ev) => {
  const el = ev.target;
  try {
    if (el.id === "planMode") {
      if (el.value === "panel" && !confirm(t("plans.confirmWeaker"))) { await tabs.connect.load(); return; }
      await api("/api/plans/policy", { approval: el.value });
      await tabs.connect.load();
    } else if (el.dataset?.gwLevel) {
      if (el.value === "L3" && !confirm(t("gw.confirmL3"))) { await tabs.connect.load(); return; }
      await api("/api/agent-gateway/settings", { id: el.dataset.gwLevel, level: el.value });
      toast(t("gw.levelSaved")); await tabs.connect.load();
    } else if (el.dataset?.gwAuto) {
      if (el.checked && !confirm(t("gw.confirmAuto"))) { el.checked = false; return; }
      await api("/api/agent-gateway/settings", { id: el.dataset.gwAuto, auto_approve: el.checked ? ["L2"] : [] });
      toast(t("gw.autoSaved")); await tabs.connect.load();
    }
  } catch (e) { toast(e.message, true); await tabs.connect.load(); }
});

// Счётчик ожидающих подтверждения в меню (работает на любой странице) + уведомление о новом запросе.
const _seenPlans = new Set();
async function refreshPlansBadge() {
  try {
    const pl = await api("/api/plans");
    const link = document.querySelector('#tabs a[data-nav="connect"]');
    if (link) {
      let b = link.querySelector(".nav-ver");
      if (!b) { b = document.createElement("span"); b.className = "nav-ver"; link.append(b); }
      b.textContent = pl.pending ? String(pl.pending) : "";
    }
    for (const p of pl.plans) if (p.status === "pending" && !_seenPlans.has(p.id)) {
      if (_seenPlans.size || pl.plans.length) toast(t("plans.new", { agent: p.agent_name, op: planOp(p) }));
      _seenPlans.add(p.id);
    }
  } catch { /* панель недоступна — молча */ }
}
setInterval(refreshPlansBadge, 10000);
setTimeout(refreshPlansBadge, 1500);

// Каталог операций (operations.py): уровень, доступность на этой машине, чего не хватает.
function opsCatalog(c) {
  if (!c) return "";
  const lvl = { L1: "green", L2: "blue", L3: "amber", L4: "amber" };
  const opName = (o) => { const k = `op.${o.id}`; const v = t(k); return v === k ? o.title : v; };
  const rows = c.operations.map((o) => `<tr>
      <td><b>${esc(opName(o))}</b><div class="mono muted small">${esc(o.id)}</div></td>
      <td><span class="badge ${lvl[o.level] || ""}" title="${esc(t("ops.level." + o.level))}">${esc(o.level)}</span></td>
      <td class="small">${o.available ? `<span class="badge green">${esc(t("ops.available"))}</span>`
        : `<span class="muted">${esc(t("ops.needs", { list: o.unmet.map((u) => u.id).join(", ") }))}</span>`}</td></tr>`).join("");
  const legend = Object.keys(c.levels).map((k) => `<span class="badge ${lvl[k] || ""}">${esc(k)}</span> ${esc(t("ops.level." + k))}`).join(" · ");
  return `<h2>${esc(t("ops.title"))} <span class="muted small">${esc(t("ops.count", { n: c.count }))}</span></h2>
    <div class="muted small" style="margin-bottom:8px">${esc(t("ops.intro"))}</div>
    <div class="small" style="margin-bottom:8px">${legend}</div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("ops.col.op"))}</th><th>${esc(t("ops.col.level"))}</th><th>${esc(t("ops.col.status"))}</th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>`;
}

handlers.gwRotate = async (d) => { await api("/api/agent-gateway/rotate", { id: d.id }); toast(t("gw.rotated")); await tabs.connect.load(); };
handlers.gwRevoke = async (d) => { await api("/api/agent-gateway/revoke", { id: d.id }); if (tabs.connect.fresh?.id === d.id) tabs.connect.fresh = null; toast(t("gw.revoked")); await tabs.connect.load(); };
handlers.gwCopy = async (d) => {
  const f = tabs.connect.fresh;
  try { await navigator.clipboard.writeText(d.what === "claude" ? f.claude_code : f.json); toast(t("gw.copied")); }
  catch { toast(t("gw.copyFailed"), true); }
};

// ---- Удалённое подключение (Фаза 8, шаг 1: SSH). Панель ничего не открывает в сеть: ключ SSH умеет только запускать мост MCP одного агента.
function remoteSection(tab) {
  const r = tab.remote;
  if (!r) return "";
  const ssh = r.ssh, agents = (tab.data?.agents || []).filter((a) => !a.revoked);
  const card = (id, body, cls = "") => `<div class="card" style="margin-bottom:8px;${cls}"><div class="name">${esc(t("gw.remote.type." + id))}</div>${body}</div>`;
  const pre = (txt, what) => `<pre class="diff" style="white-space:pre-wrap">${esc(txt)}</pre>${btn(t("gw.copy"), "gwRemoteCopy", { what })}`;
  const st = ssh.steps;
  const sshBody = `<p class="muted small">${esc(t("gw.remote.ssh.intro"))}</p>
    ${r.types[0].status === "available" ? "" : `<div class="warn small">${esc(t(ssh.os === "macos" ? "gw.remote.ssh.needsMac" : "gw.remote.ssh.needsLinux"))}</div>`}
    <div class="row" style="gap:8px;flex-wrap:wrap;margin:8px 0"><label class="small">${esc(t("gw.remote.agent"))}
      <select id="gwRemoteAgent"><option value="">—</option>${agents.map((a) => `<option value="${esc(a.id)}" ${a.id === tab.remoteAgent ? "selected" : ""}>${esc(a.name)} (${esc(a.level)})</option>`).join("")}</select></label></div>
    ${st ? `<div class="small"><b>1.</b> ${esc(t("gw.remote.step1"))}</div>${pre(st.keygen, "keygen")}
      <div class="small"><b>2.</b> ${esc(t("gw.remote.step2"))}</div>
      <textarea id="gwRemoteKey" rows="2" style="width:100%;font-family:monospace" placeholder="ssh-ed25519 AAAA… comment">${esc(tab.remoteKey)}</textarea>
      <div class="row" style="gap:8px;margin:6px 0">${btn(t("gw.remote.build"), "gwRemoteBuild", {}, "primary")}</div>
      ${tab.remoteErr ? `<div class="warn small">${esc(tab.remoteErr)}</div>` : ""}
      ${ssh.authorized_line ? `<div class="muted small">${esc(t("gw.remote.step2b", { user: ssh.user }))}</div>${pre(ssh.authorized_line, "authline")}` : ""}
      <div class="small"><b>3.</b> ${esc(t("gw.remote.step3"))}</div>${pre(st.claude, "claude")}
      <div class="muted small">${esc(t("gw.remote.jsonCfg"))}</div>${pre(st.json, "json")}
      <p class="muted small">${esc(t("gw.remote.safe"))}</p>` : `<p class="muted small">${esc(t("gw.remote.pick"))}</p>`}`;
  return `<h2>${esc(t("gw.remote.title"))}</h2>
    <div class="muted small" style="margin-bottom:8px">${esc(t("gw.remote.intro", { hosts: ssh.hosts.join(", ") || "—" }))}</div>
    ${card("ssh", sshBody)}${remoteApiCard(tab)}${operatorsCard(tab)}${telegramCard(tab)}`;
}
handlers.gwRemoteBuild = async () => {
  const tab = tabs.connect;
  tab.remoteKey = ($("gwRemoteKey")?.value || "").trim();
  await tab.loadRemote();
  tab.render();
};
handlers.gwRemoteCopy = async (d) => {
  const ssh = tabs.connect.remote?.ssh, st = ssh?.steps || {};
  const txt = { keygen: st.keygen, claude: st.claude, json: st.json, authline: ssh?.authorized_line }[d.what];
  try { await navigator.clipboard.writeText(txt || ""); toast(t("gw.copied")); } catch { toast(t("gw.copyFailed"), true); }
};
document.addEventListener("change", async (ev) => {
  if (ev.target.id !== "gwRemoteAgent") return;
  const tab = tabs.connect;
  tab.remoteAgent = ev.target.value; tab.remoteKey = ""; tab.remoteErr = "";
  await tab.loadRemote(); tab.render();
});
