// Удалённый доступ (Фаза 8, ADR-0003): операторы, каналы (SSH, API, Telegram) и мастера «агент», «Telegram», «API». Часть страницы «Подключение агентов» (connect.js).
// Всё, что ослабляет защиту, подтверждается системным окном на машине с панелью — это делает сервер; мастера лишь ведут по шагам.

async function loadRemoteExtra(tab) {
  [tab.rapi, tab.opsList, tab.tg] = await Promise.all([api("/api/remote").catch(() => null), api("/api/operators").catch(() => null), api("/api/telegram").catch(() => null)]);
}

const need = (cond, key) => { if (!cond) throw new Error(t(key)); };
const lanIps = (tab) => (tab.remote?.ssh?.hosts || []).filter((h) => /^\d+\.\d+\.\d+\.\d+$/.test(h));
const botName = (tab) => (tab.tg?.username ? "@" + tab.tg.username : "");
const effChat = (tab) => String((fv("tgChatManual") || "").trim() || fv("tgChat", tab.tg?.unbound_chats?.[0]?.chat_id ?? "")).trim();

// ---- раздел «Операторы»
function operatorsView(tab) {
  const remoteOn = !!tab.rapi?.settings?.remote_approval;
  const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
  const rows = activeOps(tab).map((o) => `<tr><td><b>${esc(o.name)}</b><div class="mono muted small">${esc(o.id)}</div></td>
      <td class="small">${o.scopes.map((x) => `<span class="badge">${esc(t("rmt.scope." + x))}</span>`).join(" ")}</td>
      <td class="mono small">${esc(o.telegram_chat_id || "—")}</td><td class="muted small">${esc(when(o.last_seen))}</td>
      <td>${o.totp_locked ? `<span class="badge amber">${esc(t("rmt.locked"))}</span> ${btn(t("rmt.unlock"), "rmtOpUnlock", { id: o.id })} ` : ""}${btn(t("gw.rotate"), "rmtOpRotate", { id: o.id, confirm: t("rmt.confirmRotate", { name: o.name }) }, "go")}
          ${btn(t("gw.revoke"), "rmtOpRevoke", { id: o.id, confirm: t("gw.confirmRevoke", { name: o.name }) }, "danger")}</td></tr>`).join("");
  const chats = tab.tg?.unbound_chats || [];
  return `<p class="muted small">${esc(t("rmt.ops.intro"))}</p>
    <div class="${remoteOn ? "muted small" : "warn small"}" style="margin-bottom:10px">${esc(t(remoteOn ? "cn.who.opsOn" : "cn.who.opsOff"))} <a href="#connect:approvals">${esc(t("cn.sec.approvals"))}</a></div>
    <div class="card" style="margin-bottom:14px"><div class="name">${esc(t("wz.op.new"))}</div>
      <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px">
        ${fld("opName", { ph: t("rmt.opName"), max: 40, w: "180px" })}
        ${chkf("opRead", t("rmt.scope.read"), true)} ${chkf("opApprove", t("rmt.scope.approve"))}
        <select data-f="opChat"><option value="">${esc(t("wz.op.noChat"))}</option>${chats.map((c) => `<option value="${esc(c.chat_id)}" ${String(fv("opChat")) === String(c.chat_id) ? "selected" : ""}>${esc(c.name || "?")} · ${esc(c.chat_id)}</option>`).join("")}</select>
        ${fld("opChatManual", { ph: "Telegram chat_id", w: "140px" })}
        ${btn(t("rmt.opCreate"), "rmtOpCreate", {}, "primary")}</div>
      <div class="muted small" style="margin-top:6px">${esc(t("wz.op.chatHint", { bot: botName(tab) || "—" }))}</div></div>
    ${rows ? `<div class="card"><div class="table-wrap"><table><thead><tr><th>${esc(t("rmt.col.operator"))}</th><th>${esc(t("rmt.col.rights"))}</th><th>chat_id</th><th>${esc(t("gw.col.seen"))}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`
         : `<div class="empty">${esc(t("rmt.noOps"))}</div>`}`;
}

// ---- раздел «Каналы»: тонкая настройка (простой путь — мастера на «Обзоре»)
function channelsView(tab) {
  return `<p class="muted small">${esc(t("cn.channels.intro"))}</p>${sshCard(tab)}${remoteApiCard(tab)}${telegramCard(tab)}`;
}

function remoteApiCard(tab) {
  const r = tab.rapi;
  if (!r) return "";
  const s = r.settings;
  const badge = r.running ? `<span class="badge green">${esc(t("rmt.running"))}</span>` : r.error ? `<span class="badge amber">${esc(t("rmt.error"))}: ${esc(r.error)}</span>` : `<span class="badge gray">${esc(t("rmt.off"))}</span>`;
  const agents = activeAgents(tab);
  const base = `${r.scheme}://${(tab.remote?.ssh?.hosts || ["HOST"])[0]}:${s.port}`;
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("gw.remote.type.api"))} ${badge}</div>
    <p class="muted small">${esc(t("rmt.api.intro"))}</p>
    <div class="row" style="gap:12px;flex-wrap:wrap;align-items:center">
      <label class="small"><input type="checkbox" id="rmtEnabled" ${s.enabled ? "checked" : ""}> ${esc(t("rmt.enable"))}</label>
      <label class="small">${esc(t("rmt.bind"))} <input type="text" id="rmtBind" value="${esc(s.bind)}" size="16"></label>
      <label class="small">${esc(t("rmt.port"))} <input type="number" id="rmtPort" value="${esc(s.port)}" style="width:90px"></label>
      <label class="small"><input type="checkbox" id="rmtTls" ${s.tls ? "checked" : ""}> TLS</label></div>
    <p class="muted small" style="margin:6px 0 0">${esc(t("cn.who.moved"))} <a href="#connect:approvals">${esc(t("cn.sec.approvals"))}</a></p>
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

function telegramCard(tab) {
  const g = tab.tg;
  if (!g) return "";
  const badge = g.running ? `<span class="badge green">${esc(t("rmt.running"))}</span>` : g.enabled && g.token_set ? `<span class="badge amber">${esc(g.error || t("rmt.starting"))}</span>` : `<span class="badge gray">${esc(t("rmt.off"))}</span>`;
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("gw.remote.type.telegram"))} ${badge}</div>
    <p class="muted small">${esc(t("rmt.tg.intro"))}</p>
    ${g.error ? `<div class="warn small">${esc(g.error)}</div>` : ""}
    <div class="row" style="gap:8px;flex-wrap:wrap;align-items:center">
      <input type="password" id="tgToken" placeholder="${esc(g.token_set ? t("rmt.tg.tokenSet") : t("rmt.tg.tokenPh"))}" autocomplete="off" style="min-width:300px">
      <label class="small"><input type="checkbox" id="tgEnabled" ${g.enabled ? "checked" : ""}> ${esc(t("rmt.enable"))}</label>
      ${btn(t("rmt.save"), "tgSave", {}, "primary")} ${g.token_set ? btn(t("rmt.tg.check"), "tgCheck") : ""}</div>
    ${g.username ? `<div class="small">${esc(t("rmt.tg.bot"))}: @${esc(g.username)}</div>` : ""}</div>`;
}

// ---- SSH (шаг 1 Фазы 8): ключ умеет только запускать мост MCP одного агента
function sshBody(tab, picker) {
  const r = tab.remote;
  if (!r) return "";
  const ssh = r.ssh, agents = activeAgents(tab), st = ssh.steps;
  const pre = (txt, what) => `<pre class="diff" style="white-space:pre-wrap">${esc(txt)}</pre>${btn(t("gw.copy"), "gwRemoteCopy", { what })}`;
  return `${r.types[0].status === "available" ? "" : `<div class="warn small">${esc(t(ssh.os === "macos" ? "gw.remote.ssh.needsMac" : "gw.remote.ssh.needsLinux"))}</div>`}
    ${picker ? `<div class="row" style="gap:8px;flex-wrap:wrap;margin:8px 0"><label class="small">${esc(t("gw.remote.agent"))}
      <select id="gwRemoteAgent"><option value="">—</option>${agents.map((a) => `<option value="${esc(a.id)}" ${a.id === tab.remoteAgent ? "selected" : ""}>${esc(a.name)} (${esc(a.level)})</option>`).join("")}</select></label></div>` : ""}
    ${st ? `<div class="small"><b>1.</b> ${esc(t("gw.remote.step1"))}</div>${pre(st.keygen, "keygen")}
      <div class="small"><b>2.</b> ${esc(t("gw.remote.step2"))}</div>
      <textarea id="gwRemoteKey" rows="2" style="width:100%;font-family:monospace" placeholder="ssh-ed25519 AAAA… comment">${esc(tab.remoteKey)}</textarea>
      <div class="row" style="gap:8px;margin:6px 0">${btn(t("gw.remote.build"), "gwRemoteBuild", {}, "primary")}</div>
      ${tab.remoteErr ? `<div class="warn small">${esc(tab.remoteErr)}</div>` : ""}
      ${ssh.authorized_line ? `<div class="muted small">${esc(t("gw.remote.step2b", { user: ssh.user }))}</div>${pre(ssh.authorized_line, "authline")}` : ""}
      <div class="small"><b>3.</b> ${esc(t("gw.remote.step3"))}</div>${pre(st.claude, "claude")}
      <div class="muted small">${esc(t("gw.remote.jsonCfg"))}</div>${pre(st.json, "json")}
      <p class="muted small">${esc(t("gw.remote.safe"))}</p>` : `<p class="muted small">${esc(t("gw.remote.pick"))}</p>`}`;
}
function sshCard(tab) {
  if (!tab.remote) return "";
  return `<div class="card" style="margin-bottom:8px"><div class="name">${esc(t("gw.remote.type.ssh"))}</div><p class="muted small">${esc(t("gw.remote.ssh.intro"))}</p>${sshBody(tab, true)}</div>`;
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

// Подключение агента на ЭТОМ компьютере: клиент → что выполнить → как проверить → что агент сможет
const AGENT_CLIENTS = {
  claude: { name: "Claude Code", kind: "cmd", verified: true },
  codex: { name: "Codex CLI", kind: "cmd", verified: false },
  cursor: { name: "Cursor", kind: "json", file: "~/.cursor/mcp.json", verified: false },
  desktop: { name: "Claude Desktop", kind: "json", file: "~/Library/Application Support/Claude/claude_desktop_config.json", verified: false },
  gemini: { name: "Gemini CLI", kind: "json", file: "~/.gemini/settings.json", verified: false },
  other: { name: "other", kind: "json", file: "", verified: false },
};
function localConnect(tab, w) {
  const a = w.agent, cl = fv("agClient", "claude"), c = AGENT_CLIENTS[cl], ag = (tab.data?.agents || []).find((x) => x.id === a.id);
  const seen = ag?.last_seen && ag.last_seen >= w.t0;
  const cmd = cl === "codex" ? a.claude_code.replace(/^claude mcp add/, "codex mcp add") : a.claude_code;
  const chips = Object.entries(AGENT_CLIENTS).map(([k, v]) => `<label class="opt" style="display:inline-flex;margin:2px 4px 2px 0;padding:5px 10px"><input type="radio" name="agClient" data-f="agClient" value="${k}" ${cl === k ? "checked" : ""}><span>${esc(k === "other" ? t("wz.agent.cOther") : v.name)}</span></label>`).join("");
  const how = c.kind === "cmd"
    ? `<div class="small"><b>1.</b> ${esc(t("wz.agent.cmdStep", { client: c.name }))}</div><pre class="diff" style="white-space:pre-wrap">${esc(cmd)}</pre>${btn(t("gw.copy"), "cnCopy", { text: cmd })}`
    : `<div class="small"><b>1.</b> ${esc(t("wz.agent.jsonStep", { client: cl === "other" ? t("wz.agent.cOther") : c.name }))}${c.file ? ` <code>${esc(c.file)}</code>` : ""}</div>
       <pre class="diff">${esc(a.json)}</pre>${btn(t("gw.copy"), "cnCopy", { text: a.json })}<div class="muted small">${esc(t("wz.agent.jsonMerge"))}</div>`;
  return `<p class="muted small">${esc(t("wz.agent.localIntro"))}</p>
    <div class="small" style="margin-bottom:4px"><b>${esc(t("wz.agent.cPick"))}</b></div><div>${chips}</div>
    ${c.verified ? "" : `<div class="muted small" style="margin-top:4px">${esc(t("wz.agent.unverified"))}</div>`}
    <div style="margin-top:10px">${how}
      <div class="small" style="margin-top:10px"><b>2.</b> ${esc(t("wz.agent.restart", { client: cl === "other" ? t("wz.agent.cOther") : c.name }))}</div>
      <div class="small" style="margin-top:8px"><b>3.</b> ${esc(t("wz.agent.tryIt"))}</div><pre class="diff" style="white-space:pre-wrap">${esc(t("wz.agent.prompt"))}</pre>${btn(t("gw.copy"), "cnCopy", { text: t("wz.agent.prompt") })}</div>
    <div class="card" style="margin-top:12px;${seen ? "border-color:var(--green)" : ""}">${seen ? `<span class="badge green">✓</span> ${esc(t("wz.agent.seen"))}` : `<span class="muted">⏳ ${esc(t("wz.agent.waitSeen"))}</span>`}</div>
    <h3 style="margin:14px 0 4px">${esc(t("wz.agent.canTitle"))}</h3><div class="small muted">${esc(t("gw.toolsList"))}</div>
    <p class="muted small">${esc(t("gw.tokenNote", { file: a.token_file }))}</p>`;
}

// ---- мастера
const WIZ = {
  agent: {
    title: "wz.agent.title",
    steps: [
      { title: "wz.agent.s1", nextLabel: "wz.agent.register",
        render: () => `<p class="muted small">${esc(t("wz.agent.s1Text"))}</p>
          <div class="row" style="gap:8px;margin-bottom:10px">${fld("agName", { ph: t("gw.namePh"), max: 40 })}
            <select data-f="agExp"><option value="">${esc(t("gw.noExpiry"))}</option>${[30, 90, 365].map((n) => `<option value="${n}" ${String(fv("agExp")) === String(n) ? "selected" : ""}>${n} ${esc(t("gw.days"))}</option>`).join("")}</select></div>
          ${radios("agLevel", [["L1", `L1 · ${esc(t("gw.lvl.L1"))}`, esc(t("wz.agent.l1"))], ["L2", `L2 · ${esc(t("gw.lvl.L2"))}`, esc(t("wz.agent.l2"))], ["L3", `L3 · ${esc(t("gw.lvl.L3"))}`, esc(t("wz.agent.l3"))]], "L1")}`,
        next: async (tab, w) => {
          const body = { name: fv("agName").trim(), level: fv("agLevel", "L1") };
          if (fv("agExp")) body.expires_days = Number(fv("agExp"));
          w.agent = await api("/api/agent-gateway/register", body);
          tab.remoteAgent = w.agent.id; tab.remoteKey = ""; tab.form.agWhere = "local";
        } },
      { title: "wz.agent.s2",
        render: (tab) => `<p class="muted small">${esc(t("wz.agent.s2Text"))}</p>${radios("agWhere", [
          ["local", esc(t("wz.agent.local")), esc(t("wz.agent.localText"))], ["ssh", esc(t("wz.agent.ssh")), esc(t("wz.agent.sshText"))], ["api", esc(t("wz.agent.api")), esc(t("wz.agent.apiText"))]], "local")}`,
        next: async (tab, w) => { w.where = fv("agWhere", "local"); if (w.where === "ssh") { tab.remoteAgent = w.agent.id; tab.remoteKey = ""; await tab.loadRemote(); } } },
      { title: "wz.agent.s3",
        render: (tab, w) => {
          w.t0 ??= Date.now() / 1000;
          const a = w.agent, lvlNote = { L1: t("wz.agent.done1"), L2: t("wz.agent.done2"), L3: t("wz.agent.done3") }[a.level || fv("agLevel", "L1")];
          let body = "";
          if (w.where === "ssh") body = sshBody(tab, false);
          else if (w.where === "api") body = tab.rapi?.running
            ? `<p class="small">${esc(t("wz.agent.apiOn", { url: `${tab.rapi.scheme}://${(tab.remote?.ssh?.hosts || ["HOST"])[0]}:${tab.rapi.settings.port}` }))}</p>${btn(t("rmt.issue"), "cnIssueAgent", { id: a.id }, "primary")}`
            : `<p class="small">${esc(t("wz.agent.apiOff"))}</p>${btn(t("cn.w.api"), "cnWiz", { id: "api" }, "primary")}`;
          else body = localConnect(tab, w);
          return `<div class="small" style="margin-bottom:8px">${esc(t("wz.agent.created", { name: a.name }))}</div>${body}<div class="warn small" style="margin-top:12px">${esc(lvlNote)}</div>`;
        } },
    ],
  },

  telegram: {
    title: "wz.tg.title",
    steps: [
      { title: "wz.tg.s1", nextLabel: "wz.tg.s1next",
        render: (tab) => {
          const g = tab.tg || {};
          if (g.token_set && g.username && g.enabled) return `<p>✓ ${esc(t("wz.tg.botOk", { bot: botName(tab) }))}</p><p class="muted small">${esc(t("wz.tg.botReplace"))}</p>${fld("tgToken", { ph: t("rmt.tg.tokenPh"), type: "password", w: "320px" })}`;
          return `<p class="muted small">${esc(t("wz.tg.s1Text"))}</p>${fld("tgToken", { ph: t("rmt.tg.tokenPh"), type: "password", w: "320px" })}
            <p class="muted small">${esc(t("wz.tg.s1Dialog"))}</p>`;
        },
        next: async (tab) => {
          const g = tab.tg || {}, token = (fv("tgToken") || "").trim();
          need(token || g.token_set, "wz.tg.needToken");
          if (token || !g.enabled) await api("/api/telegram/settings", token ? { token, enabled: true } : { enabled: true });
          tab.form.tgToken = "";
          await api("/api/telegram/check", {});
          await loadRemoteExtra(tab);
        } },
      { title: "wz.tg.s2",
        render: (tab) => {
          const g = tab.tg || {}, ops = activeOps(tab), chats = g.unbound_chats || [], sel = fv("tgOp", approverOps(tab)[0]?.id || "new"), chosen = ops.find((o) => o.id === sel);
          const chatPick = chosen?.telegram_chat_id && !fv("tgChatManual")
            ? `<p class="small">✓ ${esc(t("wz.tg.chatBound", { id: chosen.telegram_chat_id }))}</p>`
            : `<div class="small" style="margin:8px 0 4px"><b>${esc(t("wz.tg.chatTitle"))}</b></div>
               <p class="muted small">${esc(t("wz.tg.chatText", { bot: botName(tab) || "—" }))}</p>
               ${chats.length ? radios("tgChat", chats.map((c) => [String(c.chat_id), `${esc(c.name || "?")} · ${esc(c.chat_id)}`, esc(t("wz.tg.chatSeen"))]), String(chats[0].chat_id)) : `<p class="muted small">⏳ ${esc(t("wz.tg.chatWait"))}</p>`}
               <div class="small" style="margin-top:6px">${esc(t("wz.tg.chatManual"))} ${fld("tgChatManual", { ph: "chat_id", w: "160px" })}</div>`;
          const opItems = ops.map((o) => [o.id, `${esc(o.name)}`, esc(`${o.scopes.map((x) => t("rmt.scope." + x)).join(", ")} · ${o.telegram_chat_id ? t("wz.tg.chatBound", { id: o.telegram_chat_id }) : t("wz.tg.noChat")}`)]);
          opItems.push(["new", esc(t("wz.tg.opNew")), ops.length ? "" : esc(t("wz.tg.opNone"))]);
          return `<p class="muted small">${esc(ops.length ? t("wz.tg.s2Have") : t("wz.tg.s2None"))}</p>${radios("tgOp", opItems, sel)}
            ${sel === "new" ? `<div style="margin:6px 0 0 26px">${fld("tgOpName", { def: "Admin", ph: t("rmt.opName"), max: 40, w: "200px" })}<div class="muted small">${esc(t("wz.tg.opNewRights"))}</div></div>` : ""}
            ${chosen && !chosen.scopes.includes("approve") ? `<div style="margin:6px 0 0 26px">${chkf("tgGrant", esc(t("wz.tg.grant")), true)}</div>` : ""}
            ${chatPick}`;
        },
        next: async (tab, w) => {
          const ops = activeOps(tab), sel = fv("tgOp", approverOps(tab)[0]?.id || "new"), chat = effChat(tab);
          w.secret = w.uri = null;
          if (sel === "new") {
            need(chat, "wz.tg.needChat");
            const r = await api("/api/operators/create", { name: (fv("tgOpName", "Admin") || "").trim(), scopes: ["read", "approve"], telegram_chat_id: chat });
            w.opId = r.operator.id; w.secret = r.totp_secret; w.uri = r.totp_uri;
          } else {
            const o = ops.find((x) => x.id === sel);
            need(o, "wz.tg.needOp");
            if (chat && String(o.telegram_chat_id || "") !== chat) await api("/api/operators/settings", { id: o.id, telegram_chat_id: chat });
            else need(o.telegram_chat_id, "wz.tg.needChat");
            if (!o.scopes.includes("approve") && fv("tgGrant", true)) {
              const r = await api("/api/operators/settings", { id: o.id, scopes: [...new Set([...o.scopes, "approve"])] });
              w.secret = r.totp_secret; w.uri = r.totp_uri;
            }
            w.opId = o.id;
          }
          await loadRemoteExtra(tab);
        } },
      { title: "wz.tg.s3",
        render: (tab, w) => {
          const on = tab.rapi?.settings?.remote_approval;
          return `<p class="muted small">${esc(t("wz.tg.s3Text"))}</p>
            ${w.secret ? `<div class="card" style="margin:8px 0;border-color:var(--accent)"><div class="name">${esc(t("wz.tg.totpTitle"))}</div><p class="warn small">${esc(t("rmt.once"))}</p>
              <div class="muted small">${esc(t("rmt.totpSecret"))}</div><pre class="diff" style="word-break:break-all">${esc(w.secret)}</pre>${btn(t("gw.copy"), "cnCopy", { text: w.secret })}
              <div class="muted small" style="margin-top:8px">${esc(t("rmt.totpUri"))}</div><pre class="diff" style="white-space:pre-wrap;word-break:break-all">${esc(w.uri)}</pre>${btn(t("gw.copy"), "cnCopy", { text: w.uri })}
              <div style="margin-top:8px">${chkf("tgTotpDone", esc(t("wz.tg.totpDone")))}</div></div>`
              : `<p class="muted small">${esc(t("wz.tg.totpExisting"))}</p>`}
            ${on ? `<p>✓ ${esc(t("wz.tg.approvalOn"))}</p>` : chkf("tgApproval", esc(t("wz.tg.approvalLabel")), true)}
            <p class="muted small">${esc(t("wz.tg.s3Dialog"))}</p>`;
        },
        next: async (tab, w) => {
          if (w.secret) need(fv("tgTotpDone"), "wz.tg.needTotp");
          if (!tab.rapi?.settings?.remote_approval && fv("tgApproval", true)) await api("/api/remote/settings", { remote_approval: true });
          w.t0 = Date.now() / 1000;
          await loadRemoteExtra(tab);
        } },
      { title: "wz.tg.s4",
        render: (tab, w) => {
          const op = activeOps(tab).find((o) => o.id === w.opId), ok = op?.last_seen && op.last_seen >= w.t0;
          return `<p class="muted small">${esc(t("wz.tg.s4Text", { bot: botName(tab) || "—" }))}</p>
            ${ok ? `<p>✓ ${esc(t("wz.tg.s4Ok"))}</p>` : `<p class="muted">⏳ ${esc(t("wz.tg.s4Wait"))}</p>`}
            <div class="small" style="margin-top:10px">${esc(t("wz.tg.s4How"))}</div>`;
        } },
    ],
  },

  api: {
    title: "wz.api.title",
    steps: [
      { title: "wz.api.s1", nextLabel: "wz.api.s1next",
        render: (tab) => {
          const mode = fv("apiMode", "local"), ips = lanIps(tab), ip = fv("apiBind", ips[0] || "");
          return `<p class="muted small">${esc(t("wz.api.s1Text"))}</p>${radios("apiMode", [
            ["local", esc(t("wz.api.local")), esc(t("wz.api.localText"))], ["lan", esc(t("wz.api.lan")), esc(t("wz.api.lanText"))], ["custom", esc(t("wz.api.custom")), esc(t("wz.api.customText"))]], "local")}
            ${mode === "lan" ? `<div style="margin:6px 0 0 26px" class="row"><label class="small">${esc(t("rmt.bind"))} <select data-f="apiBind">${ips.map((i) => `<option ${i === ip ? "selected" : ""}>${esc(i)}</option>`).join("") || "<option value=''>—</option>"}</select></label>
              <label class="small">${esc(t("rmt.allow").replace(/:$/, ""))} ${fld("apiAllow", { def: ip ? ip.split(".").slice(0, 3).join(".") + ".0/24" : "", w: "170px" })}</label></div>` : ""}
            ${mode === "custom" ? `<div style="margin:6px 0 0 26px" class="row">${fld("apiBind", { def: "127.0.0.1", w: "150px" })} ${fld("apiPort", { def: "8766", w: "90px" })} ${chkf("apiTls", "TLS", false)} ${fld("apiAllow", { ph: "192.168.1.0/24", w: "190px" })}</div>` : ""}
            <p class="muted small">${esc(t("wz.api.s1Dialog"))}</p>`;
        },
        next: async (tab, w) => {
          const mode = fv("apiMode", "local"), ips = lanIps(tab);
          let body;
          if (mode === "local") body = { enabled: true, bind: "127.0.0.1", port: 8766, tls: false, allow: [] };
          else if (mode === "lan") { need(fv("apiBind", ips[0]), "wz.api.needIp"); body = { enabled: true, bind: fv("apiBind", ips[0]), port: 8766, tls: true, allow: (fv("apiAllow", "") || "").split(/[\s,]+/).filter(Boolean) }; }
          else body = { enabled: true, bind: (fv("apiBind", "127.0.0.1") || "").trim(), port: Number(fv("apiPort", "8766")), tls: !!fv("apiTls"), allow: (fv("apiAllow", "") || "").split(/[\s,]+/).filter(Boolean) };
          await api("/api/remote/settings", body);
          await loadRemoteExtra(tab);
          need(tab.rapi?.running, "wz.api.notRunning");
        } },
      { title: "wz.api.s2", nextLabel: "wz.api.s2next",
        render: (tab) => {
          const who = fv("apiWho", activeOps(tab).length ? "operator" : "agent"), ops = activeOps(tab), ags = activeAgents(tab);
          const opSel = fv("apiOp", ops[0]?.id || "new");
          return `<p class="muted small">${esc(t("wz.api.s2Text"))}</p>${radios("apiWho", [["operator", esc(t("wz.api.whoOp")), esc(t("wz.api.whoOpText"))]], who)}
            ${who === "operator" ? `<div style="margin:6px 0 0 26px">${radios("apiOp", [...ops.map((o) => [o.id, esc(o.name), esc(o.scopes.map((x) => t("rmt.scope." + x)).join(", "))]), ["new", esc(t("wz.tg.opNew")), ""]], opSel)}
              ${opSel === "new" ? `<div style="margin-left:26px" class="row">${fld("apiOpName", { ph: t("rmt.opName"), max: 40, w: "180px" })} ${chkf("apiOpApprove", esc(t("rmt.scope.approve")))}</div>` : `<div class="muted small" style="margin-left:26px">${esc(t("wz.api.rotateNote"))}</div>`}</div>`
            : ""}
            ${radios("apiWho", [["agent", esc(t("wz.api.whoAgent")), esc(t("wz.api.whoAgentText"))]], who)}
            ${who === "agent" ? `<div style="margin:6px 0 0 26px">${ags.length ? radios("apiAgent", ags.map((a) => [a.id, `${esc(a.name)} (${esc(a.level)})`, ""]), ags[0].id) : `<p class="muted small">${esc(t("gw.none"))}</p>`}<div class="muted small">${esc(t("rmt.issueNote"))}</div></div>` : ""}
            <p class="muted small">${esc(t("wz.api.s2Dialog"))}</p>`;
        },
        next: async (tab, w) => {
          const who = fv("apiWho", activeOps(tab).length ? "operator" : "agent");
          if (who === "agent") {
            const id = fv("apiAgent", activeAgents(tab)[0]?.id);
            need(id, "wz.api.needAgent");
            const r = await api("/api/remote/agent-token", { id });
            tab.once = { title: t("rmt.agentToken"), rows: [[t("rmt.token"), r.token]] };
          } else {
            const sel = fv("apiOp", activeOps(tab)[0]?.id || "new");
            if (sel === "new") {
              const name = (fv("apiOpName") || "").trim();
              need(name, "wz.api.needName");
              const r = await api("/api/operators/create", { name, scopes: fv("apiOpApprove") ? ["read", "approve"] : ["read"] });
              tab.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret], [t("rmt.totpUri"), r.totp_uri]] };
            } else {
              const r = await api("/api/operators/rotate", { id: sel });
              tab.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret]] };
            }
          }
          await loadRemoteExtra(tab);
        } },
      { title: "wz.api.s3",
        render: (tab) => {
          const r = tab.rapi, base = `${r.scheme}://${(tab.remote?.ssh?.hosts || ["HOST"])[0]}:${r.settings.port}`, op = fv("apiWho", "operator") === "operator";
          return `<p class="small">${esc(t("rmt.address"))}: <span class="mono">${esc(base)}</span></p>
            ${r.tls_fingerprint ? `<p class="small">${esc(t("rmt.fp"))}: <span class="mono" style="word-break:break-all">${esc(r.tls_fingerprint)}</span></p>` : ""}
            <div class="muted small">${esc(t("rmt.example"))}</div>
            <pre class="diff" style="white-space:pre-wrap">curl ${r.tls_fingerprint ? "--cacert panel-cert.pem " : ""}-H "Authorization: Bearer &lt;token&gt;" ${esc(base)}${op ? "/operator/v1/status" : "/agent/v1/tools"}</pre>
            <p class="muted small">${esc(t("wz.api.docs"))}</p>`;
        } },
    ],
  },
};

// ---- обработчики разделов
handlers.rmtHideOnce = async () => { tabs.connect.once = null; tabs.connect.render(); };
handlers.rmtSave = async () => {
  const body = { enabled: $("rmtEnabled").checked, bind: $("rmtBind").value.trim(), port: Number($("rmtPort").value), tls: $("rmtTls").checked,
                 allow: $("rmtAllow").value.split(/[\s,]+/).filter(Boolean) };
  try { await api("/api/remote/settings", body); toast(t("rmt.saved")); } catch (e) { toast(e.message, true); }
  await rmtReload();
};
async function rmtReload() { const tab = tabs.connect; await loadRemoteExtra(tab); tab.render(); }
handlers.rmtIssue = async () => {
  const id = $("rmtIssueAgent").value;
  if (!id) return;
  if (!confirm(t("rmt.confirmIssue"))) return;
  const r = await api("/api/remote/agent-token", { id });
  tabs.connect.once = { title: t("rmt.agentToken"), rows: [[t("rmt.token"), r.token]] };
  tabs.connect.render();
};
handlers.cnIssueAgent = async (d) => {
  if (!confirm(t("rmt.confirmIssue"))) return;
  const r = await api("/api/remote/agent-token", { id: d.id });
  tabs.connect.once = { title: t("rmt.agentToken"), rows: [[t("rmt.token"), r.token]] };
  tabs.connect.render();
};
handlers.rmtOpCreate = async () => {
  const scopes = [fv("opRead", true) && "read", fv("opApprove") && "approve"].filter(Boolean);
  const body = { name: (fv("opName") || "").trim(), scopes };
  const chat = (fv("opChatManual") || "").trim() || fv("opChat");
  if (chat) body.telegram_chat_id = chat;
  const r = await api("/api/operators/create", body);
  tabs.connect.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret], [t("rmt.totpUri"), r.totp_uri]] };
  tabs.connect.form = {};
  await rmtReload();
};
handlers.rmtOpRotate = async (d) => {
  const r = await api("/api/operators/rotate", { id: d.id });
  tabs.connect.once = { title: t("rmt.opCreated", { name: r.operator.name }), rows: [[t("rmt.token"), r.token], [t("rmt.totpSecret"), r.totp_secret]] };
  await rmtReload();
};
handlers.rmtOpUnlock = async (d) => { await api("/api/operators/unlock", { id: d.id }); toast(t("rmt.unlocked")); await rmtReload(); };
handlers.rmtOpRevoke = async (d) => { await api("/api/operators/revoke", { id: d.id }); toast(t("gw.revoked")); await rmtReload(); };
handlers.tgSave = async () => {
  const body = { enabled: $("tgEnabled").checked };
  if ($("tgToken").value.trim()) body.token = $("tgToken").value.trim();
  await api("/api/telegram/settings", body);
  toast(t("rmt.saved"));
  await rmtReload();
};
handlers.tgCheck = async () => { await api("/api/telegram/check", {}); toast(t("rmt.tg.ok")); await rmtReload(); };
