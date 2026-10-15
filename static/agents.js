// Halaman AI Sessions: pemantauan (agents.py, hanya baca) + Tugas agen (agent_tasks.py: worktree + agen di PTY).

tabs.agents = {
  titleKey: "nav.agents",
  interval: 8000,
  data: null,
  tasks: null,     // /api/agents/tasks
  projects: null,  // реестр проектов для формы «Новая задача»
  async load(silent) {
    try {
      this.data = await api("/api/agents?preview=1");
      this.tasks = await api("/api/agents/tasks");
      if (!this.projects) this.projects = (await api("/api/projects").catch(() => ({ projects: [] }))).projects;
    } catch (e) { if (!silent) return failView(e); return; }
    this.render();
  },

  // Digambar ulang dari data di memori — dipakai saat ganti bahasa (lihat i18n.js).
  render() {
    const d = this.data;
    if (!d) return;
    const s = d.summary;
    $("headline").textContent = `${s.agent_sessions} ${t("agents.agentSessions")} · CPU ${s.cpu}% · ${s.mem_mb} MB`;

    view.innerHTML = `
      <div class="ro-banner"><span>${t("agents.intro")}</span></div>
      ${tasksSection(this.tasks, this.projects, d)}
      ${d.procs_available ? "" : `<div class="warn">${t("agents.noPs")}</div>`}
      <div class="stat">
        <div class="card"><div>${esc(t("agents.sessions"))}</div><div>${s.sessions}</div>
          <div class="muted small">${s.agent_sessions} ${esc(t("agents.kind.agent"))} · ${s.sessions - s.agent_sessions} ${esc(t("agents.kind.terminal"))}</div></div>
        <div class="card"><div>${esc(t("agents.cpu"))}</div><div>${s.cpu}<small>%</small></div>
          <div class="muted small">${esc(t("agents.procs", { n: s.sessions + s.standalone }))}</div></div>
        <div class="card"><div>${esc(t("agents.mem"))}</div><div>${s.mem_mb}<small>MB</small></div>
          <div class="muted small">${esc(t("agents.memHint"))}</div></div>
        <div class="card"><div>${esc(t("agents.standalone"))}</div><div>${s.standalone}</div>
          <div class="muted small">${esc(t("agents.standaloneHint"))}</div></div>
      </div>

      <h2>${esc(t("agents.installed"))}</h2>
      <div class="list">
        ${AGENT_ROWS.map((a) => {
          const hit = d.installed.find((x) => x.key === a.key);
          return `<div class="card item">
            <div><div class="name">${esc(a.label)} ${hit ? `<span class="badge green">${esc(t("common.installed"))}</span>`
                                                          : `<span class="badge gray">${esc(t("agents.notInstalled"))}</span>`}</div>
              <div class="meta">${hit ? monoPath(hit.path) : `<span class="muted small mono">${esc(a.bin)}</span>`}</div></div>
          </div>`;
        }).join("")}
      </div>

      <h2>${esc(t("agents.sessions"))}</h2>
      ${d.sessions.length ? `<div class="list">${d.sessions.map(sessionCard).join("")}</div>`
                          : `<div class="empty">${esc(t("agents.none"))}</div>`}

      <h2>${esc(t("agents.standalone"))}</h2>
      ${d.standalone.length ? `<div class="table-wrap"><table>
          <tr><th>PID</th><th>${esc(t("agents.kind.agent"))}</th><th>CPU</th><th>${esc(t("agents.mem"))}</th><th>${esc(t("agents.started"))}</th><th>shell</th></tr>
          ${d.standalone.map((a) => `<tr>
            <td class="mono">${esc(a.pid)}</td>
            <td><b>${esc(a.agent)}</b><div class="muted small mono">${esc(a.command.slice(0, 90))}</div></td>
            <td>${a.cpu}%</td><td>${a.mem_mb} MB</td><td class="muted small">${esc(a.uptime || "")}</td>
            <td class="mono muted small">${a.shell_pid ? esc(t("agents.shellPid", { pid: a.shell_pid })) : "—"}</td></tr>`).join("")}
        </table></div>` : `<div class="muted small">${esc(t("agents.standaloneEmpty"))}</div>`}
      <p class="muted small">${t("agents.hint")}</p>`;
  },
};

// Label produk (tidak diterjemahkan); `bin` dipakai untuk pencocokan.
const AGENT_ROWS = [
  { key: "claude", bin: "claude", label: "Claude Code" },
  { key: "codex", bin: "codex", label: "Codex CLI" },
  { key: "opencode", bin: "opencode", label: "OpenCode" },
  { key: "gemini", bin: "gemini", label: "Gemini CLI" },
  { key: "aider", bin: "aider", label: "Aider" },
  { key: "cursor-agent", bin: "cursor-agent", label: "Cursor Agent" },
];

// ---- Задачи агентов (agent_tasks.py): «новая задача» = worktree + агент в PTY.
const TASK_STATE = { creating: "blue", busy: "amber", idle: "green", shell: "gray", stopped: "gray", failed: "amber" };

function tasksSection(tk, projects, d) {
  if (!tk) return "";
  const installed = tk.installed || [];
  const form = `<form id="taskNew" class="new-app">
    <div class="field"><label>${esc(t("tasks.project"))}</label>
      <select name="project">${(projects || []).map((p) => `<option value="${esc(p.path)}">${esc(p.name)}</option>`).join("")}</select></div>
    <div class="field"><label>${esc(t("tasks.agent"))}</label>
      <select name="agent">${installed.map((k) => `<option value="${esc(k)}">${esc(AGENT_ROWS.find((a) => a.key === k)?.label || k)}</option>`).join("")}</select></div>
    <div class="field"><label>${esc(t("tasks.title"))}</label><input type="text" name="title" maxlength="80" autocomplete="off"></div>
    <div class="field"><label>${esc(t("tasks.description"))}</label><textarea name="description" rows="2" maxlength="4000"></textarea></div>
    <div class="row"><button type="submit" class="primary" ${installed.length && (projects || []).length ? "" : "disabled"}>${esc(t("tasks.create"))}</button></div>
  </form>`;
  const card = (x) => `<div class="card">
    <div class="sess-head">
      <b>${esc(x.title)}</b>
      <span class="badge ${TASK_STATE[x.state] || "gray"}" ${x.heuristic ? `title="${esc(t("tasks.heuristic"))}"` : ""}>${esc(t("tasks.state." + x.state))}${x.heuristic ? " *" : ""}</span>
      <span class="badge blue">${esc(AGENT_ROWS.find((a) => a.key === x.agent)?.label || x.agent)}</span>
      ${x.merged ? `<span class="badge green">${esc(t("tasks.merged"))}</span>` : ""}
      <span class="spacer"></span><span class="muted small">${x.restarts ? esc(t("tasks.restarts", { n: x.restarts })) : ""}</span>
    </div>
    <div class="meta" style="margin-top:6px"><span class="mono">${esc(x.branch)}</span>${monoPath(x.worktree || "")}</div>
    ${x.description ? `<div class="muted small" style="margin-top:6px;white-space:pre-wrap">${esc(x.description)}</div>` : ""}
    <div class="actions" style="justify-content:flex-start;margin-top:8px">
      ${x.session ? btn(t("tasks.terminal"), "taskTerminal", { session: x.session }, "primary") : ""}
      ${["busy", "idle", "shell"].includes(x.state) ? btn(t("tasks.send"), "taskSend", { id: x.id }) + btn(t("tasks.stop"), "taskCall", { path: "stop", id: x.id, confirm: t("tasks.confirmStop") }, "danger") : ""}
      ${["stopped"].includes(x.state) && x.worktree_exists ? btn(x.restarts ? t("tasks.restart") : t("tasks.start"), "taskCall", { path: "start", id: x.id }) : ""}
      ${x.worktree_exists && x.state !== "creating" && x.state !== "failed" ? btn(t("tasks.changes"), "taskChanges", { id: x.id }) : ""}
      ${["stopped", "shell"].includes(x.state) && x.worktree_exists && !x.merged ? btn(t("tasks.merge"), "taskMerge", { id: x.id }) : ""}
      ${["stopped", "failed", "shell"].includes(x.state) ? btn(t("tasks.removeKeep"), "taskCall", { path: "remove", id: x.id, confirm: t("tasks.confirmRemoveKeep") })
        + (x.worktree_exists ? btn(t("tasks.removeAll"), "taskCall", { path: "remove", id: x.id, remove_worktree: "1", confirm: t("tasks.confirmRemoveAll") }, "danger") : "") : ""}
    </div></div>`;
  return `<h2>${esc(t("tasks.title.section"))}</h2>
    <details ${tk.tasks.length ? "" : "open"} style="margin-bottom:12px"><summary>${esc(t("tasks.new"))}</summary>${form}
      ${installed.length ? "" : `<div class="warn">${esc(t("tasks.noAgents"))}</div>`}
      <div class="muted small" style="margin-top:6px">${esc(t("tasks.newHint"))}</div></details>
    ${tk.tasks.length ? `<div class="list">${tk.tasks.map(card).join("")}</div>` : `<div class="empty">${esc(t("tasks.none"))}</div>`}
    <div class="muted small" style="margin:6px 0 14px">* ${esc(t("tasks.heuristic"))}</div>`;
}

document.addEventListener("submit", async (ev) => {
  if (ev.target.id !== "taskNew") return;
  ev.preventDefault();
  const f = new FormData(ev.target);
  const body = { project: f.get("project"), agent: f.get("agent"), title: String(f.get("title") || "").trim(), description: String(f.get("description") || "").trim() };
  if (!body.title) return toast(t("tasks.needTitle"), true);
  if (!confirm(t("tasks.confirmCreate", { a: body.agent, t: body.title }))) return;
  await runJob(api("/api/agents/task/create", body), () => tabs.agents.load());
});
handlers.taskTerminal = (d) => window.focusSession(d.session);
handlers.taskCall = async (d) => {
  const body = { id: d.id, ...(d.remove_worktree ? { remove_worktree: true } : {}) };
  const r = await api(`/api/agents/task/${d.path}`, body);
  if (r.job) await runJob(Promise.resolve(r), () => tabs.agents.load()); else await tabs.agents.load();
};
handlers.taskSend = async (d) => {
  const text = prompt(t("tasks.sendPrompt"));
  if (!text || !text.trim()) return;
  await api("/api/agents/task/send", { id: d.id, text });
  toast(t("tasks.sent"));
};
const diffHtml = (text) => esc(text).split("\n").map((ln) =>
  ln.startsWith("+") && !ln.startsWith("+++") ? `<span class="add">${ln}</span>` : ln.startsWith("-") && !ln.startsWith("---") ? `<span class="del">${ln}</span>` : ln).join("\n");
handlers.taskChanges = async (d) => {
  const c = await api(`/api/agents/task/changes?id=${encodeURIComponent(d.id)}`);
  const files = c.files.map((f) => `<div class="row" style="gap:8px;margin:2px 0"><span class="mono">${esc(f.status)}</span><span class="mono">${esc(f.path)}</span>
    <button data-act="taskDiff" data-id="${esc(d.id)}" data-file="${esc(f.path)}">diff</button></div>`).join("");
  $("logTitle").textContent = `${t("tasks.changesTitle")}: ${c.branch} (base ${c.base})`;
  $("logBody").innerHTML = `${c.commits.length ? `<b>${esc(t("tasks.commits"))}</b>\n${c.commits.map(esc).join("\n")}\n\n` : ""}`
    + `<b>${esc(t("tasks.files", { n: c.files.length }))}</b>\n${files || esc(t("common.empty"))}\n`
    + (c.untracked.length ? `\n<b>${esc(t("tasks.untracked"))}</b>\n${c.untracked.map(esc).join("\n")}\n` : "")
    + `<div id="taskDiffOut"></div>`;
  logDlg.showModal();
};
handlers.taskDiff = async (d) => {
  const r = await api(`/api/agents/task/diff?id=${encodeURIComponent(d.id)}&file=${encodeURIComponent(d.file)}`);
  $("taskDiffOut").innerHTML = `\n<b>${esc(r.file)}</b>${r.truncated ? ` <span class="badge amber">${esc(t("tasks.truncated"))}</span>` : ""}\n${diffHtml(r.diff)}`;
};

function sessionCard(s) {
  const isAgent = s.kind === "agent";
  const started = s.started ? new Date(s.started * 1000).toLocaleTimeString() : "—";
  const preview = (s.preview || "").split("\n").slice(-14).join("\n");
  return `<div class="card">
    <div class="sess-head">
      <span class="dot ${s.alive ? "on" : "bad"}"></span>
      <b>#${esc(s.id)}</b>
      <span class="badge ${isAgent ? "green" : "gray"}">${esc(isAgent ? t("agents.kind.agent") : t("agents.kind.terminal"))}</span>
      ${s.agent ? `<span class="badge blue">${esc(AGENT_ROWS.find((a) => a.key === s.agent)?.label || s.agent)}</span>` : ""}
      <span class="muted small">${esc(s.alive ? t("agents.alive") : t("agents.dead"))}</span>
      <span class="spacer"></span>
      <span class="chips">
        <span class="badge">CPU ${esc(s.cpu)}%</span>
        <span class="badge">${esc(s.mem_mb)} MB</span>
        <span class="badge">${esc(t("agents.procs", { n: s.procs }))}</span>
        <span class="badge gray">${esc(s.uptime || "")}</span>
      </span>
    </div>
    <div class="meta" style="margin-top:6px">
      <span>${esc(t("agents.cwd"))}: ${monoPath(s.cwd || "—")}</span>
      <span>${esc(t("agents.started"))}: ${esc(started)}</span>
    </div>
    ${s.agents && s.agents.length ? `<div class="table-wrap" style="margin-top:8px"><table>
      <tr><th>PID</th><th>${esc(t("agents.kind.agent"))}</th><th>CPU</th><th>${esc(t("agents.mem"))}</th><th>${esc(t("agents.started"))}</th></tr>
      ${s.agents.map((a) => `<tr><td class="mono">${esc(a.pid)}</td><td><b>${esc(a.agent)}</b>
        <div class="muted small mono">${esc(a.command.slice(0, 80))}</div></td>
        <td>${a.cpu}%</td><td>${a.mem_mb} MB</td><td class="muted small">${esc(a.uptime || "")}</td></tr>`).join("")}
    </table></div>` : ""}
    ${preview ? `<div style="margin-top:8px"><div class="muted small">${esc(t("agents.preview"))}</div>
      <pre class="diff" style="max-height:200px">${esc(preview)}</pre></div>` : ""}
    <div class="actions" style="justify-content:flex-start;margin-top:8px">
      ${s.cwd ? btn(t("projects.openFolder"), "openPath", { path: s.cwd }) : ""}
    </div>
  </div>`;
}

// Слияние ветки задачи: сначала предпросмотр (цель, число коммитов, прогноз конфликта), потом подтверждение и job.
handlers.taskMerge = async (d) => {
  const c = await api(`/api/agents/task/changes?id=${encodeURIComponent(d.id)}`);
  if (!c.target) return toast(t("tasks.mergeNoTarget"), true);
  const conflict = c.conflicts === true ? t("tasks.mergeConflictYes") : c.conflicts === false ? t("tasks.mergeConflictNo") : t("tasks.mergeConflictUnknown");
  if (!confirm(t("tasks.confirmMerge", { b: c.branch, t: c.target, n: c.commits.length, c: conflict }))) return;
  const r = await api("/api/agents/task/merge", { id: d.id });
  await runJob(Promise.resolve(r), () => tabs.agents.load());
};
