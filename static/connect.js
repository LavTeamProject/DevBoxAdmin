// Страница «Подключение агентов»: разделы (Обзор, Агенты, Подтверждения, Операторы, Каналы, Каталог) и мастера (агент, Telegram, API).
// Подтверждения и каталог операций — ниже в этом файле; операторы, каналы и мастера Telegram/API — в remote.js.
// Секреты (токены, TOTP) показываются один раз (tab.once); токен агента в браузер не попадает, кроме явной выдачи для удалённого клиента.

const CONNECT_SECTIONS = ["overview", "agents", "approvals", "operators", "channels", "catalog"];

tabs.connect = {
  titleKey: "nav.connect",
  data: null, ops: null, plans: null, remote: null, rapi: null, opsList: null, tg: null,
  interval: 5000,
  once: null,      // токен/секрет, показываемый один раз
  wiz: null,       // активный мастер {id, step, ...}
  form: {},        // значения полей мастеров: переживают фоновую перерисовку
  remoteAgent: "", remoteKey: "", remoteErr: "",
  get sub() { return CONNECT_SECTIONS.includes(this.param) ? this.param : "overview"; },

  async load(silent) {
    try {   // запросы независимы и идут параллельно (раньше — пять подряд каждые 5 с)
      const [data, ops, plans] = await Promise.all([api("/api/agent-gateway"), api("/api/operations").catch(() => null), api("/api/plans").catch(() => null),
                                                    this.loadRemote(), loadRemoteExtra(this)]);
      this.data = data; this.ops = ops; this.plans = plans;
    } catch (e) { if (!silent) return failView(e); return; }
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
    $("headline").textContent = t("gw.count", { n: activeAgents(this).length });
    view.innerHTML = this.wiz ? wizardView(this) : `${subnav(this)}${onceBox(this)}${sectionBody(this)}`;
  },
};

// ---- общие помощники
const activeAgents = (tab) => (tab.data?.agents || []).filter((a) => !a.revoked);
const activeOps = (tab) => (tab.opsList?.operators || []).filter((o) => !o.revoked);
const approverOps = (tab) => activeOps(tab).filter((o) => o.scopes.includes("approve"));
const pendingPlans = (tab) => (tab.plans?.plans || []).filter((p) => p.status === "pending" || p.status === "awaiting_human").length;
const fv = (id, def = "") => (tabs.connect.form[id] ?? def);
const fld = (id, o = {}) => `<input type="${o.type || "text"}" data-f="${id}" value="${esc(fv(id, o.def || ""))}" placeholder="${esc(o.ph || "")}" autocomplete="off" ${o.max ? `maxlength="${o.max}"` : ""} style="${o.w ? `width:${o.w}` : "min-width:220px"}">`;
const chkf = (id, label, def = false) => `<label class="small"><input type="checkbox" data-f="${id}" ${fv(id, def) ? "checked" : ""}> ${label}</label>`;
const radios = (id, items, def) => items.map(([v, label, desc]) => `<label class="opt"><input type="radio" name="${id}" data-f="${id}" value="${esc(v)}" ${String(fv(id, def)) === String(v) ? "checked" : ""}>
  <span><b>${label}</b>${desc ? `<span class="muted small" style="display:block">${desc}</span>` : ""}</span></label>`).join("");
document.addEventListener("input", (ev) => { const f = ev.target.dataset?.f; if (f && ev.target.type !== "checkbox" && ev.target.type !== "radio") tabs.connect.form[f] = ev.target.value; });
document.addEventListener("change", (ev) => {
  const f = ev.target.dataset?.f;
  if (!f) return;
  tabs.connect.form[f] = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
  if (ev.target.type === "radio") tabs.connect.render();     // выбор варианта меняет содержимое шага
});

function onceBox(tab) {
  const o = tab.once;
  if (!o) return "";
  return `<div class="card" style="margin:8px 0 14px;border-color:var(--accent)"><div class="name">${esc(o.title)}</div>
    <p class="warn small">${esc(t("rmt.once"))}</p>
    ${o.rows.map(([k, v]) => `<div class="muted small">${esc(k)}</div><pre class="diff" style="white-space:pre-wrap;word-break:break-all">${esc(v)}</pre>${btn(t("gw.copy"), "cnCopy", { text: v })}`).join("")}
    <div style="margin-top:8px">${btn(t("rmt.hide"), "rmtHideOnce")}</div></div>`;
}

function subnav(tab) {
  const pend = pendingPlans(tab);
  const labels = { overview: t("cn.sec.overview"), agents: t("cn.sec.agents"), approvals: t("cn.sec.approvals") + (pend ? ` <span class="badge amber">${pend}</span>` : ""),
                   operators: t("cn.sec.operators"), channels: t("cn.sec.channels"), catalog: t("cn.sec.catalog") };
  return `<div class="row" style="gap:6px;margin-bottom:14px;flex-wrap:wrap">${CONNECT_SECTIONS.map((s) => `<a class="pill-link ${tab.sub === s ? "active" : ""}" href="#connect:${s}">${labels[s]}</a>`).join("")}</div>`;
}

function sectionBody(tab) {
  return ({ overview: overviewView, agents: agentsView, approvals: approvalsView, operators: operatorsView, channels: channelsView, catalog: catalogView }[tab.sub])(tab);
}

// ---- обзор: состояние и «что хотите сделать»
function tgState(tab) {
  const g = tab.tg || {};
  if (!g.token_set) return ["gray", t("cn.tg.none")];
  const ap = approverOps(tab).filter((o) => o.telegram_chat_id);
  if (!ap.length) return ["amber", t("cn.tg.needOp", { bot: g.username ? "@" + g.username : "" })];
  return [g.running ? "green" : "amber", t("cn.tg.ready", { bot: g.username ? "@" + g.username : "", op: ap[0].name })];
}

function approvalRoute(tab) {
  const rs = tab.rapi?.settings || {};
  const tg = tgState(tab);
  if (rs.remote_approval && tg[0] === "green") return t("cn.route.tg");
  if (rs.remote_approval && approverOps(tab).length) return t("cn.route.api");
  return t("cn.route.local");
}

function approvalExplainer(tab) {
  return `<div class="card" style="margin-bottom:14px"><div class="name">${esc(t("cn.appr.title"))}</div>
    <div class="small" style="margin:6px 0"><b>${esc(t("cn.appr.now"))}</b> ${esc(approvalRoute(tab))}</div>
    <ul class="small" style="margin:6px 0 0 18px;line-height:1.6">
      <li><b>${esc(t("cn.appr.plans"))}</b> ${esc(t("cn.appr.plansText"))}</li>
      <li><b>${esc(t("cn.appr.l3"))}</b> ${esc(t("cn.appr.l3Text"))}</li>
      <li><b>${esc(t("cn.appr.settings"))}</b> ${esc(t("cn.appr.settingsText"))}</li>
      <li>${esc(t("cn.appr.agent"))}</li></ul></div>`;
}

function overviewView(tab) {
  const ag = activeAgents(tab), pend = pendingPlans(tab), [tcls, ttext] = tgState(tab), api_ = tab.rapi;
  const tile = (title, text, cls, href) => `<a class="card" href="${href}" style="text-decoration:none;color:inherit;display:block"><div class="muted small">${esc(title)}</div>
    <div style="margin-top:4px"><span class="badge ${cls}">${esc(text)}</span></div></a>`;
  const wcard = (id, title, text, hint) => `<div class="card" style="display:flex;flex-direction:column;gap:6px"><div class="name">${esc(title)}</div>
    <div class="muted small" style="flex:1">${esc(text)}</div>${hint ? `<div class="small warn-text">${esc(hint)}</div>` : ""}${btn(t("cn.start"), "cnWiz", { id }, "primary")}</div>`;
  const tgHint = tab.tg?.token_set && !approverOps(tab).filter((o) => o.telegram_chat_id).length ? t("cn.tg.needOpHint") : "";
  return `<div class="ro-banner"><span>${esc(t("gw.intro"))}</span></div>
    <div class="stat" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:14px">
      ${tile(t("cn.tile.agents"), ag.length ? t("cn.tile.agentsN", { n: ag.length }) : t("cn.tile.none"), ag.length ? "green" : "gray", "#connect:agents")}
      ${tile(t("cn.tile.approvals"), pend ? t("cn.tile.pending", { n: pend }) : t("cn.tile.noPending"), pend ? "amber" : "green", "#connect:approvals")}
      ${tile("Telegram", ttext, tcls, "#connect:channels")}
      ${tile(t("cn.tile.api"), api_?.running ? t("rmt.running") : t("rmt.off"), api_?.running ? "green" : "gray", "#connect:channels")}
      ${tile(t("cn.tile.operators"), activeOps(tab).length ? t("cn.tile.opsN", { n: activeOps(tab).length }) : t("cn.tile.none"), activeOps(tab).length ? "green" : "gray", "#connect:operators")}</div>
    <h2>${esc(t("cn.todo"))}</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-bottom:14px">
      ${wcard("agent", t("cn.w.agent"), t("cn.w.agentText"))}
      ${wcard("telegram", t("cn.w.tg"), t("cn.w.tgText"), tgHint)}
      ${wcard("api", t("cn.w.api"), t("cn.w.apiText"))}</div>
    ${approvalExplainer(tab)}`;
}

// ---- агенты
function agentsView(tab) {
  const d = tab.data, now = Date.now() / 1000;
  const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
  const state = (a) => (a.revoked ? ["gray", "gw.state.revoked"] : a.expires && a.expires < now ? ["amber", "gw.state.expired"] : ["green", "gw.state.active"]);
  const rows = d.agents.map((a) => {
    const [cls, key] = state(a);
    return `<tr><td><b>${esc(a.name)}</b><div class="mono muted small">${esc(a.id)}</div></td>
      <td>${a.revoked ? `<span class="badge">${esc(a.level)}</span>` : `<select data-gw-level="${esc(a.id)}" aria-label="${esc(t("gw.col.level"))}">
          ${["L1", "L2", "L3"].map((l) => `<option value="${l}" ${l === a.level ? "selected" : ""}>${l} · ${esc(t("gw.lvl." + l))}</option>`).join("")}</select>
        ${a.level === "L2" || a.level === "L3" ? `<div><label class="small ${a.auto_run ? "warn-text" : "muted"}" title="${esc(t("gw.autoRunTitle"))}"><input type="checkbox" data-gw-run="${esc(a.id)}" ${a.auto_run ? "checked" : ""}> ${esc(t("gw.autoRun"))}</label></div>` : ""}
        ${a.level === "L2" ? `<div><label class="small ${a.auto_approve?.includes("L2") ? "warn-text" : "muted"}"><input type="checkbox" data-gw-auto="${esc(a.id)}" ${a.auto_approve?.includes("L2") ? "checked" : ""}> ${esc(t("gw.autoApprove"))}</label></div>` : ""}`}</td>
      <td><span class="badge ${cls}">${esc(t(key))}</span></td>
      <td class="muted small">${esc(when(a.created))}</td><td class="muted small">${esc(a.expires ? when(a.expires) : t("gw.noExpiry"))}</td>
      <td class="muted small">${esc(when(a.last_seen))}</td><td class="num muted small">${esc(a.calls || 0)}</td>
      <td>${a.revoked ? "" : btn(t("gw.rotate"), "gwRotate", { id: a.id, confirm: t("gw.confirmRotate", { name: a.name }) }, "go") + " " + btn(t("gw.revoke"), "gwRevoke", { id: a.id, confirm: t("gw.confirmRevoke", { name: a.name }) }, "danger")}</td></tr>`;
  }).join("");
  return `<div class="row" style="gap:8px;margin-bottom:12px"><span class="badge ${d.socket_ready ? "green" : "amber"}">${esc(d.socket_ready ? t("gw.socketOk") : t("gw.socketDown"))}</span>
      <span class="muted small">${esc(t("gw.limits", { n: d.rate_per_min }))}</span><span class="spacer"></span>${btn(t("cn.w.agent"), "cnWiz", { id: "agent" }, "primary")}</div>
    ${d.agents.length ? `<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>${esc(t("gw.col.agent"))}</th><th>${esc(t("gw.col.level"))}</th><th>${esc(t("audit.col.result"))}</th><th>${esc(t("gw.col.created"))}</th><th>${esc(t("gw.col.expires"))}</th><th>${esc(t("gw.col.seen"))}</th><th class="num">${esc(t("gw.col.calls"))}</th><th></th></tr></thead>
      <tbody>${rows}</tbody></table></div></div>` : `<div class="empty">${esc(t("gw.none"))}</div>`}
    <div class="warn" style="margin-top:14px">${esc(t("gw.honest"))}</div>`;
}

// ---- подтверждения
function approverCard(tab) {
  const on = !!tab.rapi?.settings?.remote_approval, ops = approverOps(tab), tg = tgState(tab);
  return `<div class="card" style="margin-bottom:14px"><div class="name">${esc(t("cn.who.title"))}</div>
    <p class="muted small">${esc(t("cn.who.text"))}</p>
    <label class="opt"><input type="checkbox" checked disabled><span><b>${esc(t("cn.who.local"))}</b><span class="muted small" style="display:block">${esc(t("cn.who.localText"))}</span></span></label>
    ${tab.plans ? `<div class="row" style="gap:8px;margin:2px 0 8px 26px;flex-wrap:wrap"><label class="small">${esc(t("plans.mode"))} <select id="planMode">
        <option value="dialog" ${tab.plans.policy.approval === "dialog" ? "selected" : ""}>${esc(t("plans.mode.dialog"))}</option>
        <option value="panel" ${tab.plans.policy.approval === "panel" ? "selected" : ""}>${esc(t("plans.mode.panel"))}</option></select></label>
      ${tab.plans.policy.approval === "panel" ? `<span class="warn small">${esc(t("plans.mode.panelWarn"))}</span>` : ""}</div>` : ""}
    <label class="opt"><input type="checkbox" id="apprRemote" ${on ? "checked" : ""}><span><b>${esc(t("cn.who.remote"))}</b>
      <span class="muted small" style="display:block">${esc(t("cn.who.remoteText"))}</span>
      <span class="small" style="display:block;margin-top:4px">${ops.length ? esc(t("cn.who.ops", { list: ops.map((o) => o.name + (o.telegram_chat_id ? " (Telegram)" : "")).join(", ") })) : `<span class="warn-text">${esc(t("cn.who.noOps"))}</span> <a href="#connect:operators">${esc(t("cn.sec.operators"))}</a>`}
        · Telegram: ${esc(tg[1])}</span></span></label>
    <div class="muted small" style="margin-top:6px">${esc(t("cn.who.l3"))}</div></div>`;
}
document.addEventListener("change", async (ev) => {
  if (ev.target.id !== "apprRemote") return;
  try { await api("/api/remote/settings", { remote_approval: ev.target.checked }); toast(t("rmt.saved")); }
  catch (e) { ev.target.checked = !ev.target.checked; toast(e.message, true); }
  await tabs.connect.load();
});

function approvalsView(tab) {
  return `${approverCard(tab)}${plansSection(tab.plans)}${approvalExplainer(tab)}`;
}

function catalogView(tab) {
  return `<div class="muted small">${esc(t("gw.toolsList"))}</div>${opsCatalog(tab.ops)}`;
}

handlers.cnCopy = async (d) => { try { await navigator.clipboard.writeText(d.text || ""); toast(t("gw.copied")); } catch { toast(t("gw.copyFailed"), true); } };
handlers.cnWiz = async (d) => { const tab = tabs.connect; tab.wiz = { id: d.id, step: 0, t0: Date.now() / 1000 }; tab.form = {}; tab.once = null; tab.render(); scrollTo(0, 0); };
handlers.cnWizClose = async () => { const tab = tabs.connect; tab.wiz = null; tab.once = null; await tab.load(); };
handlers.cnWizBack = async () => { const tab = tabs.connect; if (tab.wiz.step > 0) tab.wiz.step--; tab.render(); };
handlers.cnWizNext = async () => {
  const tab = tabs.connect, w = tab.wiz, step = WIZ[w.id].steps[w.step];
  if (step.next) await step.next(tab, w);       // бросает ошибку — мастер остаётся на шаге, ошибку показывает общий обработчик
  if (w.step < WIZ[w.id].steps.length - 1) w.step++; else { tab.wiz = null; await tab.load(); return; }
  await tab.load(); tab.render();
};

function wizardView(tab) {
  const w = tab.wiz, def = WIZ[w.id], steps = def.steps, last = w.step === steps.length - 1, s = steps[w.step];
  const dots = steps.map((x, i) => `<span class="badge ${i === w.step ? "blue" : i < w.step ? "green" : "gray"}">${i + 1}. ${esc(t(x.title))}</span>`).join(" ");
  return `<div class="card" style="max-width:860px"><div class="row" style="margin-bottom:6px"><div class="name">${esc(t(def.title))}</div><span class="spacer"></span>${btn(t("cn.cancel"), "cnWizClose")}</div>
    <div class="row" style="gap:6px;margin-bottom:12px">${dots}</div>
    ${onceBox(tab)}
    <div>${s.render(tab, w)}</div>
    <div class="row" style="gap:8px;margin-top:16px">${w.step > 0 ? btn(t("cn.back"), "cnWizBack") : ""}<span class="spacer"></span>
      ${s.hideNext ? "" : btn(last ? t("cn.finish") : (s.nextLabel ? t(s.nextLabel) : t("cn.next")), "cnWizNext", {}, "primary")}</div></div>`;
}

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
    } else if (el.dataset?.gwRun) {
      if (el.checked && !confirm(t("gw.confirmRun"))) { el.checked = false; return; }
      await api("/api/agent-gateway/settings", { id: el.dataset.gwRun, auto_run: el.checked });
      toast(t("gw.autoSaved")); await tabs.connect.load();
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
handlers.gwRevoke = async (d) => { await api("/api/agent-gateway/revoke", { id: d.id }); toast(t("gw.revoked")); await tabs.connect.load(); };
