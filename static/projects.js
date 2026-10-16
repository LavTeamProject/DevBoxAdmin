// Halaman Projects: baca repo, branch, worktree, log, diff (projects.py) + aksi tulis Git (gitops.py, lewat job + audit).


// Добавить проект по пути (запись в реестр, projects.py). Проект должен быть git-репозиторием в домашней папке.
const projAddForm = () => `<form class="row" id="projAdd" style="gap:8px;margin-bottom:12px">
  <input type="text" name="path" placeholder="${esc(t("projects.addPh"))}" style="flex:1;min-width:240px" autocomplete="off">
  <button type="submit">${esc(t("projects.add"))}</button></form>`;
function bindProjAdd() {
  $("projAdd")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const path = new FormData(ev.target).get("path");
    try { await api("/api/projects/add", { path }); toast(t("projects.added")); }
    catch (e) { return toast(e.message, true); }
    tabs.projects.summary = {};
    await tabs.projects.list();
  });
}

tabs.projects = {
  titleKey: "nav.projects",
  force: false,
  items: null,      // daftar repo terakhir (/api/projects)
  summary: {},      // path -> ringkasan git yang sudah diambil
  detail: null,     // respons /api/projects/detail terakhir
  gh: {},           // path -> data GitHub terakhir
  async load(silent) {
    if (this.param) return this.loadDetail(this.param, silent);
    return this.list(silent);
  },

  // Digambar ulang dari data di memori — dipakai saat ganti bahasa (lihat i18n.js).
  // Tidak ada satu pun request jaringan di sini.
  render() {
    if (this.param && this.detail) return this.renderDetail();
    if (!this.param && this.items) return this.renderList();
  },

  async list(silent) {
    // На первом запуске macOS спрашивает доступ к «Документам»/«Рабочему столу»; пока не нажато «Разрешить»,
    // скан молча ждёт. Через 4 с объясняем это, а не оставляем пустой экран.
    const hint = setTimeout(() => {
      const el = view.querySelector(".loading");
      if (el && !el.querySelector(".tcc-hint")) el.insertAdjacentHTML("beforeend", `<div class="tcc-hint muted small" style="margin-top:8px">${esc(t("tcc.hint"))}</div>`);
    }, 4000);
    try { this.items = (await api(`/api/projects${this.force ? "?scan=1" : ""}`)).projects || []; }
    catch (e) { clearTimeout(hint); if (!silent) return failView(e); return; }
    clearTimeout(hint);
    this.force = false;
    this.renderList();
  },

  renderList() {
    const items = this.items || [];
    $("headline").textContent = t("projects.found", { n: items.length });

    if (!items.length) {
      view.innerHTML = `${roBanner(t("projects.readonly"))}
        <div class="empty">${esc(t("projects.none"))}</div>
        <div class="row" style="justify-content:center">${btn(t("projects.scan"), "projScan", {}, "primary")}</div>
        <div id="projScanInfo" class="muted small" style="text-align:center;margin-top:10px"></div>
        <h2>${esc(t("projects.addTitle"))}</h2>${projAddForm()}`;
      bindProjAdd();
      return;
    }

    // Kartu langsung tampil sebagai kerangka; ringkasan git diambil paralel
    // per repo supaya satu repo besar tidak menahan seluruh halaman.
    view.innerHTML = `${roBanner(t("projects.readonly"))}
      <div class="row" style="margin-bottom:12px">
        <span class="muted small">${esc(t("projects.found", { n: items.length }))}</span>
        <span class="spacer"></span>${btn(t("projects.rescan"), "projScan")}
      </div>
      ${projAddForm()}
      <div class="list">${items.map((p) => `<a class="card" id="pc-${hashPath(p.path)}"
          href="#projects:${encodeURIComponent(p.path)}" style="text-decoration:none;color:inherit">
          <div class="row" style="flex-wrap:nowrap;gap:12px">
            <div style="flex:1;min-width:0">
              <div class="name">${esc(p.name)} ${p.worktree ? `<span class="badge blue">${esc(t("projects.worktree"))}</span>` : ""}${p.registered ? `<span class="badge gray">${esc(t("projects.registered"))}</span>` : ""}</div>
              <div class="muted small mono">${esc(p.path.replace(/^\/Users\/[^/]+/, "~"))}</div>
              <div class="meta"></div>
              <div class="proj-body muted small">${esc(t("shell.loading"))}</div>
            </div>
            <span class="muted">→</span>
          </div></a>`).join("")}</div>
      <div id="projScanInfo" class="muted small" style="margin-top:10px"></div>`;
    // Ringkasan yang sudah pernah diambil langsung dipasang (tanpa request),
    // sisanya diambil paralel per kartu.
    bindProjAdd();
    items.forEach((p) => { if (this.summary[p.path]) fillProjectCard(p.path, this.summary[p.path]); });
    this.fillSummaries();
  },

  // Ambil ringkasan tiap repo yang belum ada di cache, lalu isikan ke kartunya.
  async fillSummaries(force) {
    const items = this.items || [];
    await Promise.all(items.map(async (p) => {
      if (!force && this.summary[p.path]) return;
      let s;
      try { s = await api(`/api/projects/summary?path=${encodeURIComponent(p.path)}`); }
      catch (e) { s = { error: e.message }; }
      this.summary[p.path] = s;
      if (current === tabs.projects && !tabs.projects.param) fillProjectCard(p.path, s);
    }));
  },

  async loadDetail(path, silent) {
    try {
      this.detail = await api(`/api/projects/detail?path=${encodeURIComponent(path)}`);
      if (!this.editors) this.editors = (await api("/api/projects/editors").catch(() => ({ editors: [] }))).editors;
    } catch (e) { if (!silent) return failView(e); return; }
    this.renderDetail();
    this.loadGithub(path);
    this.loadRuns(path);
  },

  async loadRuns(path) {
    try { this.runs = (await api(`/api/runs?project=${encodeURIComponent(path)}&limit=8`)).runs; } catch { this.runs = []; }
    renderProjRuns();
  },

  renderDetail() {
    const d = this.detail;
    if (!d) return;
    const st = d.status;
    const rel = (p) => p.replace(/^\/Users\/[^/]+/, "~");
    $("headline").textContent = `${d.name} · ${st.branch}`;

    const fileList = d.files_w || st.files;
    const files = fileList.length ? `<div class="table-wrap" style="margin-top:10px"><table>
        <tr><th>XY</th><th>${esc(t("projects.files"))}</th><th></th></tr>
        ${fileList.map((f) => `<tr>
          <td class="mono ${f.xy.includes("?") ? "muted" : ""}">${esc(f.xy)}</td>
          <td class="mono">${esc(f.path)}</td>
          <td><div class="actions">${btn("diff", "projDiff", { file: f.path, mode: "work" })}${fileActions(d, f)}</div></td>
        </tr>`).join("")}</table></div>` : `<div class="muted small" style="margin-top:8px">${esc(t("projects.diffEmpty"))}</div>`;

    const trees = d.worktrees.map((w) => `<div class="card item">
        <div><div class="name">${esc(w.branch || (w.detached ? "detached" : "-"))}
          ${w.current ? `<span class="badge green">${esc(t("projects.current"))}</span>` : `<span class="badge">${esc(t("projects.mainCheckout"))}</span>`}
          ${w.exists ? "" : `<span class="badge amber">missing</span>`}</div>
          <div class="meta">${monoPath(w.path)}${w.head ? ` <span class="mono">${esc(w.head)}</span>` : ""}</div></div>
        <div class="actions">${w.current ? "" : btn(t("projects.openFolder"), "openPath", { path: w.path })}</div>
      </div>`).join("");

    const branches = d.branches.length ? `<div class="table-wrap"><table>
        <tr><th>${esc(t("projects.branches"))}</th><th>upstream</th><th></th></tr>
        ${d.branches.map((b) => `<tr>
          <td>${b.current ? "<b>" : ""}${esc(b.name)}${b.current ? "</b>" : ""}
            ${b.current ? `<span class="badge green">HEAD</span>` : ""}
            ${b.remote ? `<span class="badge gray">remote</span>` : ""}</td>
          <td class="mono muted small">${esc(b.upstream || "—")}</td>
          <td class="muted small">${esc(b.when || "")}</td></tr>`).join("")}
      </table></div>` : `<div class="empty">${esc(t("common.empty"))}</div>`;

    const commits = d.commits.length ? `<div class="list">${d.commits.map((c) => `<div class="card item">
        <div><div class="name"><span class="mono">${esc(c.hash)}</span> ${esc(c.subject)}</div>
          <div class="meta"><span>${esc(c.author)}</span><span>${esc(c.when)}</span></div></div></div>`).join("")}</div>`
      : `<div class="empty">${esc(t("common.empty"))}</div>`;

    view.innerHTML = `
      <p style="margin:0 0 12px"><a href="#projects">${esc(t("projects.back"))}</a></p>
      ${roBanner(t("projects.readonly"))}
      <div class="stat">
        <div class="card"><div>${esc(t("projects.branch"))}</div><div>${esc(st.branch || "-")}</div>
          <div class="muted small">${esc(d.worktree ? t("projects.worktree") : t("projects.mainCheckout"))}
            ${st.upstream ? "· " + esc(st.upstream) : ""}</div></div>
        <div class="card"><div>${esc(t("common.status"))}</div>
          <div>${st.dirty === null || st.dirty === undefined
            ? `<span class="badge gray">${esc(t("projects.slow"))}</span>`
            : (st.dirty ? esc(t("projects.dirty", { n: st.dirty })) : esc(t("projects.clean")))}</div>
          <div class="muted small">${st.dirty === null || st.dirty === undefined
            ? esc(t("projects.slowHint"))
            : `staged ${st.staged} · modified ${st.modified} · untracked ${st.untracked}`}</div></div>
        <div class="card"><div>ahead / behind</div><div>${esc(t("projects.ahead", { n: st.ahead }))} ${esc(t("projects.behind", { n: st.behind }))}</div>
          <div class="muted small">${esc(t("projects.worktrees"))}: ${d.worktrees.length}</div></div>
        <div class="card"><div>${esc(t("projects.remote"))}</div><div class="mono" style="font-size:13px">${esc(d.remote || "—")}</div>
          <div class="muted small mono">${esc(rel(d.path))}</div></div>
      </div>
      <div class="row" style="margin-bottom:12px">
        ${btn(t("projects.openFolder"), "openPath", { path: d.path })}
        ${btn(t("projects.copyPath"), "projCopy", { path: d.path })}
        ${btn(t("common.refresh"), "projReload")}
      </div>

      ${presetCard(d, this.editors || [])}
      ${gitCard(d)}

      <h2 class="row">${esc(t("projects.diff"))}
        <span class="spacer"></span>
        ${d.changed.length ? btn("diff (work)", "projDiff", { mode: "work" }) : ""}
        ${d.staged_changed.length ? btn("diff (staged)", "projDiff", { mode: "staged" }) : ""}
        ${d.changed.length || d.staged_changed.length
          ? btn(t("projects.lineStats"), "projStat", { mode: "work" }, "", `title="${esc(t("projects.lineStatsHint"))}"`) : ""}</h2>
      ${d.changed.length || d.staged_changed.length
        ? `<div class="muted small">${esc(t("projects.diffFiles", { n: d.changed.length, s: d.staged_changed.length }))}</div>`
        : `<div class="muted small">${esc(t("projects.diffEmpty"))}</div>`}
      <div id="projStatOut"></div>
      ${files}
      <div id="projDiffOut"></div>

      <h2>${esc(t("projects.worktrees"))}</h2>
      <div class="list">${trees}</div>

      <div class="grid two" style="margin-top:14px">
        <div><h2>${esc(t("projects.branches"))}</h2>${branches}</div>
        <div><h2>${esc(t("projects.commits"))}</h2>${commits}</div>
      </div>

      ${d.stashes && d.stashes.length ? `<h2>${esc(t("projects.stashes"))}</h2>
        <pre class="diff">${esc(d.stashes.join("\n"))}</pre>` : ""}

      <div id="projVersions"></div>

      <h2>${esc(t("projects.github"))}</h2>
      <div id="projGh"><div class="loading">${esc(t("shell.loading"))}</div></div>`;
    // Blok GitHub juga harus kembali setelah ganti bahasa. Kalau datanya sudah
    // ada di cache, loadGithub hanya menggambar — tanpa request.
    this.loadGithub(d.path);
    this.loadVersions(d.path);
  },

  // «Версии для проекта»: что просят файлы проекта и подходит ли активная версия (только чтение файлов).
  async loadVersions(path) {
    const host = $("projVersions");
    if (!host) return;
    this.ver = this.ver || {};
    if (!this.ver[path]) {
      try { this.ver[path] = await api(`/api/projects/versions?path=${encodeURIComponent(path)}`); }
      catch (e) { host.innerHTML = ""; return; }
    }
    if (current !== tabs.projects || tabs.projects.param !== path || !$("projVersions")) return;
    const items = this.ver[path].items || [];
    if (!items.length) { host.innerHTML = ""; return; }
    const row = (i) => {
      const badge = i.ok === true ? `<span class="badge green">${esc(t("projects.verOk"))}</span>`
        : i.ok === false ? `<span class="badge amber">${esc(t("projects.verMismatch"))}</span>` : `<span class="badge gray">${esc(t("projects.verUnknown"))}</span>`;
      const fix = i.ok === true ? "" : i.formula
        ? (i.formula_installed ? `<span class="muted">${esc(t("projects.verInstalled", { f: i.formula }))}</span>`
            : `<a class="btn" href="#service:${encodeURIComponent(i.formula)}">${esc(t("projects.verInstall", { f: i.formula }))}</a>`)
        : `<a href="${esc(i.page)}">${esc(t("projects.verOpen"))}</a>`;
      return `<tr><td>${esc(i.name)}</td><td class="mono">${esc(i.wanted)}</td><td class="muted">${esc(i.source)}</td><td class="mono">${esc(i.active || "—")}</td><td>${badge}</td><td>${fix}</td></tr>`;
    };
    host.innerHTML = `<h2>${esc(t("projects.versions"))}</h2>
      <table><thead><tr><th>${esc(t("projects.verTool"))}</th><th>${esc(t("projects.verWanted"))}</th><th>${esc(t("projects.verSource"))}</th><th>${esc(t("projects.verActive"))}</th><th></th><th></th></tr></thead>
      <tbody>${items.map(row).join("")}</tbody></table>
      <p class="muted">${esc(t("projects.verHint"))}</p>`;
  },

  async loadGithub(path) {
    const host = $("projGh");
    if (!host) return;
    if (this.gh[path]) return renderGithub(path, this.gh[path]);
    host.innerHTML = `<div class="loading">${esc(t("shell.loading"))}</div>`;
    try { this.gh[path] = await api(`/api/projects/github?path=${encodeURIComponent(path)}`); }
    catch (e) { host.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    if (current === tabs.projects && tabs.projects.param === path) renderGithub(path, this.gh[path]);
  },
};

// Isi satu kartu repo dengan ringkasannya (dipakai renderList dan fillSummaries).
function fillProjectCard(path, s) {
  const host = $("pc-" + hashPath(path));
  if (!host) return;
  const body = host.querySelector(".proj-body");
  if (!body) return;
  if (s.error) { body.innerHTML = `<span style="color:var(--red)">${esc(s.error)}</span>`; return; }
  const meta = host.querySelector(".meta");
  // dirty === null => `git status` tidak selesai dalam batas waktu; jangan
  // tampilkan "bersih", karena itu menyesatkan.
  const state = (s.dirty === null || s.dirty === undefined)
    ? `<span class="badge gray" title="${esc(t("projects.slowHint"))}">${esc(t("projects.slow"))}</span>`
    : (s.dirty ? `<span class="badge amber">${esc(t("projects.dirty", { n: s.dirty }))}</span>`
               : `<span class="badge green">${esc(t("projects.clean"))}</span>`);
  const name = host.querySelector(".name");
  if (name && !name.dataset.filled) {
    name.insertAdjacentHTML("beforeend",
      `${state}
       ${s.conflicts ? `<span class="badge" style="color:var(--red);border-color:var(--red)">${esc(t("projects.conflicts", { n: s.conflicts }))}</span>` : ""}`);
    name.dataset.filled = "1";
  }
  if (meta) meta.innerHTML = `<span><span class="badge">${esc(s.branch || "-")}</span></span>
    ${s.ahead ? `<span>${esc(t("projects.ahead", { n: s.ahead }))}</span>` : ""}
    ${s.behind ? `<span>${esc(t("projects.behind", { n: s.behind }))}</span>` : ""}
    ${s.remote ? `<span class="mono">${esc(s.remote.replace(/^https?:\/\//, "").replace(/\.git$/, ""))}</span>` : ""}`;
  body.innerHTML = s.last
    ? `${esc(s.last.hash)} · ${esc(s.last.subject)} <span class="muted">— ${esc(s.last.author)}, ${esc(s.last.when)}</span>`
    : "";
}

// Blok GitHub di halaman detail (data sudah diambil; tidak ada request di sini).
function renderGithub(path, g) {
  const host = $("projGh");
  if (!host) return;
  if (!g.available) {
      host.innerHTML = `<div class="muted small">${esc(g.reason === "gh_missing" ? t("projects.ghMissing") : t("projects.notGithub"))}</div>`;
      return;
    }
    const block = (title, rows, render) => `<h3 class="muted small">${esc(title)}</h3>`
      + (rows.length ? `<div class="list">${rows.map(render).join("")}</div>` : `<div class="muted small">${esc(t("projects.ghEmpty"))}</div>`);
    host.innerHTML =
      block(t("projects.prs"), g.prs, (p) => `<div class="card item">
        <div><div class="name">#${esc(p.number)} ${esc(p.title)} ${p.isDraft ? `<span class="badge">draft</span>` : ""}</div>
          <div class="meta"><span>${esc(p.state)}</span><span>${esc(p.headRefName || "")}</span>
            <span>${esc(p.author?.login || "")}</span></div></div></div>`)
      + block(t("projects.runs"), g.runs, (r) => `<div class="card item">
        <div><div class="name">${esc(r.displayTitle || r.databaseId)} <span class="badge ${r.conclusion === "success" ? "green" : r.conclusion === "failure" ? "amber" : ""}">${esc(r.conclusion || r.status)}</span></div>
          <div class="meta"><span>${esc(r.headBranch || "")}</span><span>${esc(r.event || "")}</span></div></div></div>`)
      + `<h3 class="muted small">${esc(t("runs.workflows"))}</h3><div id="projWf">${btn(t("runs.ghLoad"), "ghLoadWorkflows", { project: path, name: (path.split("/").pop() || path) })}</div>`
      + block(t("projects.issues"), g.issues, (i) => `<div class="card item">
        <div><div class="name">#${esc(i.number)} ${esc(i.title)}</div>
          <div class="meta"><span>${esc(i.state)}</span><span>${esc(i.author?.login || "")}</span></div></div></div>`);
}

// Mewarnai diff: baris +/-, header @@, dan metadata diff.
function colorDiff(text) {
  return esc(text).split("\n").map((ln) => {
    if (ln.startsWith("@@")) return `<span class="hunk">${ln}</span>`;
    if (/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity)/.test(ln)) return `<span class="muted">${ln}</span>`;
    if (ln.startsWith("+")) return `<span class="add">${ln}</span>`;
    if (ln.startsWith("-")) return `<span class="del">${ln}</span>`;
    return ln;
  }).join("\n");
}


// ---- Запись в Git (gitops.py): действия над проектом. Подтверждения: обычные — data-confirm, разрушающие — ввод имени проекта.
const gitBtn = (label, op, params, d, confirmKey, confirmArgs, cls = "") =>
  btn(label, "gitOp", { op, params: JSON.stringify({ project: d.path, ...params }), ...(confirmKey ? { confirm: t(confirmKey, confirmArgs || {}) } : {}) }, cls);

function fileActions(d, f) {
  const xy = f.xy, untracked = xy === "??";
  const staged = !untracked && xy[0] !== " ", unstaged = untracked || xy[1] !== " ";
  return (unstaged ? gitBtn(t("git.stage"), "git.add", { files: [f.path] }, d) : "")
    + (staged ? gitBtn(t("git.unstage"), "git.unstage", { files: [f.path] }, d) : "")
    + (!untracked && xy[1] !== " " ? btn(t("git.discard"), "gitDanger", { op: "git.discard", project: d.path, files: JSON.stringify([f.path]), name: d.name, what: t("git.discardWhat", { f: f.path }) }, "danger") : "")
    + (untracked ? btn(t("git.deleteFile"), "gitDanger", { op: "git.clean", project: d.path, files: JSON.stringify([f.path]), name: d.name, what: t("git.cleanWhat", { f: f.path }) }, "danger") : "");
}

function gitCard(d) {
  const st = d.status, files = d.files_w || [];
  const staged = files.filter((f) => f.xy !== "??" && f.xy[0] !== " ");
  const branches = (d.branches || []).filter((b) => !b.current && !b.name.endsWith("/HEAD"));
  const local = (d.branches || []).filter((b) => !b.remote && !b.current);
  const remote = st.upstream ? st.upstream.split("/")[0] : "origin";
  const extraTrees = (d.worktrees || []).filter((w) => !w.current && /\/Worktrees\//.test(w.path));
  const editorName = (tabs.projects.editors || []).find((e) => e.id === (d.preset || {}).editor)?.name;
  return `<div class="card" style="margin-bottom:14px">
    <div class="name" style="margin-bottom:10px">${esc(t("git.title"))}</div>
    <div class="row" style="gap:8px;margin-bottom:12px">
      ${gitBtn("fetch", "git.fetch", {}, d)}
      ${st.upstream ? gitBtn("pull", "git.pull", {}, d) : ""}
      ${gitBtn("push", "git.push", {}, d, "git.confirmPush", { b: st.branch || "?", r: st.upstream || remote, n: st.ahead || 0 })}
      ${editorName ? gitBtn(t("git.openEditor", { e: editorName }), "editor.open", {}, d) : ""}
    </div>

    <form class="row" id="gitSwitch" data-path="${esc(d.path)}" style="gap:8px;margin-bottom:8px">
      <select name="branch">${branches.map((b) => `<option>${esc(b.remote ? b.name.split("/").slice(1).join("/") : b.name)}</option>`).join("")}</select>
      <button type="submit">${esc(t("git.switch"))}</button>
      ${local.length ? `<select name="del">${local.map((b) => `<option>${esc(b.name)}</option>`).join("")}</select>
      <button type="button" data-act="gitDelBranch" data-project="${esc(d.path)}">${esc(t("git.deleteBranch"))}</button>` : ""}
    </form>
    <form class="row" id="gitNewBranch" data-path="${esc(d.path)}" style="gap:8px;margin-bottom:12px">
      <input type="text" name="name" placeholder="feature/name" autocomplete="off" style="width:200px">
      <button type="submit">${esc(t("git.newBranch"))}</button>
      <button type="button" data-act="gitNewWorktree" data-project="${esc(d.path)}">${esc(t("git.newWorktree"))}</button>
    </form>

    <form class="row" id="gitStash" data-path="${esc(d.path)}" style="gap:8px;margin-bottom:8px">
      <input type="text" name="message" placeholder="${esc(t("git.stashMsg"))}" autocomplete="off" style="flex:1;min-width:180px">
      <button type="submit">${esc(t("git.stash"))}</button></form>
    ${(d.stashes || []).map((x, i) => `<div class="row small" style="gap:8px"><span class="mono muted">${esc(x)}</span>
      ${gitBtn("pop", "git.stash_pop", { index: i }, d, "git.confirmPop")}</div>`).join("")}

    <form id="gitCommit" data-path="${esc(d.path)}" style="margin-top:12px">
      <div class="muted small" style="margin-bottom:6px">${esc(t("git.staged", { n: staged.length }))}${staged.length ? ": " + staged.slice(0, 6).map((f) => esc(f.path)).join(", ") + (staged.length > 6 ? "…" : "") : ""}</div>
      <textarea name="message" rows="2" placeholder="${esc(t("git.commitMsg"))}" style="width:100%"></textarea>
      <div class="row" style="margin-top:6px"><button type="submit" class="primary" ${staged.length ? "" : "disabled"}>${esc(t("git.commit"))}</button></div>
    </form>
    ${extraTrees.length ? `<div class="muted small" style="margin-top:12px">${esc(t("git.worktrees"))}</div>
      ${extraTrees.map((w) => `<div class="row small" style="gap:8px">${monoPath(w.path)}
        ${gitBtn(t("git.removeWorktree"), "git.worktree_remove", { worktree: w.path }, d, "git.confirmRemoveWt", { p: w.path }, "danger")}</div>`).join("")}` : ""}
    <div class="muted small" style="margin-top:10px">${esc(t("git.hint"))}</div>
  </div>`;
}

// Запуск операции Git: job в «Процессах»; после — перечитать проект.
async function runGitOp(op, params) {
  let r;
  try { r = await api("/api/git/op", { op, params }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), () => { tabs.projects.summary = {}; tabs.projects.loadDetail(params.project, true); });
}
handlers.gitOp = (d) => runGitOp(d.op, JSON.parse(d.params));
// Разрушающие действия: обычное подтверждение + ввод имени проекта (сервер проверяет его сам).
handlers.gitDanger = async (d) => {
  if (!confirm(d.what + "\n\n" + t("git.irreversible"))) return;
  const typed = prompt(t("git.typeName", { name: d.name }));
  if (typed === null) return;
  await runGitOp(d.op, { project: d.project, files: JSON.parse(d.files), confirm: typed });
};
handlers.gitDelBranch = async (d, el) => {
  const form = el.closest("form"), branch = form.elements.del.value;
  if (confirm(t("git.confirmDeleteBranch", { b: branch }))) await runGitOp("git.branch_delete", { project: d.project, branch });
};
handlers.gitNewWorktree = async (d, el) => {
  const branch = el.closest("form").elements.name.value.trim();
  if (!branch) return toast(t("git.needName"), true);
  if (confirm(t("git.confirmWorktree", { b: branch }))) await runGitOp("git.worktree_add", { project: d.project, branch });
};
document.addEventListener("submit", (ev) => {
  const id = ev.target.id, path = ev.target.dataset?.path;
  if (!["gitSwitch", "gitNewBranch", "gitStash", "gitCommit"].includes(id)) return;
  ev.preventDefault();
  const f = new FormData(ev.target);
  if (id === "gitSwitch") runGitOp("git.switch", { project: path, branch: f.get("branch") });
  else if (id === "gitNewBranch") runGitOp("git.branch_create", { project: path, name: String(f.get("name") || "").trim() });
  else if (id === "gitStash") runGitOp("git.stash_push", { project: path, message: String(f.get("message") || "").trim() });
  else runGitOp("git.commit", { project: path, message: String(f.get("message") || "").trim() });
});

// Пресет проекта: редактор + команды test/build. Команды только СОХРАНЯЮТСЯ (запуск — Фаза 2.8).
function presetCard(d, editors) {
  const p = d.preset || {};
  return `<div class="card" style="margin-bottom:14px">
    <div class="name" style="margin-bottom:8px">${esc(t("projects.preset"))}</div>
    <form id="projPreset" class="new-app" data-path="${esc(d.path)}">
      <div class="field"><label>${esc(t("projects.editor"))}</label>
        <select name="editor"><option value="">—</option>${editors.map((e) =>
          `<option value="${esc(e.id)}" ${e.id === p.editor ? "selected" : ""}>${esc(e.name)}</option>`).join("")}</select></div>
      <div class="field"><label>${esc(t("projects.testCmd"))}</label>
        <input type="text" name="test" value="${esc(p.test || "")}" placeholder="flutter test" autocomplete="off"></div>
      <div class="field"><label>${esc(t("projects.buildCmd"))}</label>
        <input type="text" name="build" value="${esc(p.build || "")}" placeholder="flutter build apk" autocomplete="off"></div>
      <div class="row" style="gap:8px">
        <button type="submit" class="primary">${esc(t("projects.presetSave"))}</button>
        ${d.registered ? btn(t("projects.unregister"), "projUnregister", { path: d.path, confirm: t("projects.unregisterConfirm") }, "danger") : ""}
      </div>
    </form>
    <div class="row" style="gap:8px;margin-top:10px">
      ${p.test ? btn(t("runs.runTest"), "runStart", { project: d.path, kind: "test", confirm: t("runs.confirmRun", { cmd: p.test }) }, "primary") : ""}
      ${p.build ? btn(t("runs.runBuild"), "runStart", { project: d.path, kind: "build", confirm: t("runs.confirmRun", { cmd: p.build }) }) : ""}
      ${!p.test && !p.build ? `<span class="muted small">${esc(t("runs.noPreset"))}</span>` : ""}
    </div>
    <div id="projRuns" data-path="${esc(d.path)}" style="margin-top:10px"></div>
    <div class="muted small" style="margin-top:8px">${esc(t("projects.presetHint"))}</div>
  </div>`;
}
document.addEventListener("submit", async (ev) => {
  if (ev.target.id !== "projPreset") return;
  ev.preventDefault();
  const fd = new FormData(ev.target);
  try {
    const r = await api("/api/projects/preset", { path: ev.target.dataset.path, editor: fd.get("editor"), test: fd.get("test"), build: fd.get("build") });
    if (tabs.projects.detail) tabs.projects.detail.preset = r.preset;
    toast(t("projects.presetSaved"));
    tabs.projects.render();
  } catch (e) { toast(e.message, true); }
});
handlers.projUnregister = async (d) => {
  await api("/api/projects/remove", { path: d.path });
  toast(t("projects.unregistered"));
  tabs.projects.summary = {};
  location.hash = "#projects";
};

handlers.projScan = async (d, el) => {
  const info = $("projScanInfo");
  if (info) info.textContent = t("projects.scanning");
  el.disabled = true;
  try { await api("/api/projects/scan");
    tabs.projects.force = true;
    tabs.projects.summary = {};   // daftar repo berubah -> ringkasan lama tidak valid
    await tabs.projects.list();
    if (tabs.projects.items?.length) toast(t("projects.found", { n: tabs.projects.items.length }));
  } catch (err) { toast(err.message, true); }
  finally { el.disabled = false; }
};
handlers.projReload = () => {
  // "Muat ulang" memang harus mengambil data baru — kebalikan dari ganti bahasa.
  const p = tabs.projects.param;
  delete tabs.projects.gh[p];
  return tabs.projects.loadDetail(p);
};
handlers.projCopy = async (d) => {
  try { await navigator.clipboard.writeText(d.path); toast(t("projects.copied")); }
  catch { toast(d.path); }
};
handlers.projDiff = async (d) => {
  const out = $("projDiffOut");
  if (!out) return;
  const q = new URLSearchParams({ path: tabs.projects.param, mode: d.mode || "work" });
  if (d.file) q.set("file", d.file);
  out.innerHTML = `<div class="loading">${esc(t("shell.loading"))}</div>`;
  let r;
  try { r = await api(`/api/projects/diff?${q}`); }
  catch (e) { out.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  out.innerHTML = `<h2>${esc(d.file || (d.mode === "staged" ? t("projects.staged") : t("projects.diff")))}</h2>
    ${r.diff ? `<pre class="diff">${colorDiff(r.diff)}</pre>` : `<div class="muted small">${esc(t("projects.diffEmpty"))}</div>`}`;
  out.scrollIntoView({ behavior: "smooth", block: "nearest" });
};

// id DOM yang aman untuk path apa pun (path bisa berisi spasi, "!", huruf Sirilik).
function hashPath(p) {
  let h = 0;
  for (let i = 0; i < p.length; i++) h = (h * 31 + p.charCodeAt(i)) | 0;
  return Math.abs(h).toString(36);
}

// Statistik +/- per berkas: lambat di repo besar, jadi hanya saat diminta.
handlers.projStat = async (d) => {
  const out = $("projStatOut");
  if (!out) return;
  out.innerHTML = `<div class="loading">${esc(t("projects.computing"))}</div>`;
  const q = new URLSearchParams({ path: tabs.projects.param, mode: d.mode || "work" });
  let r;
  try { r = await api(`/api/projects/diffstat?${q}`); }
  catch (e) { out.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
  out.innerHTML = r.stat
    ? `<pre class="diff">${esc(r.stat)}</pre>`
    : `<div class="muted small">${esc(t("projects.diffEmpty"))}</div>`;
};

// ---- Запуск test/build из пресета и история (runs.py)
const runBadge = (r) => `<span class="badge ${r.status === "ok" ? "green" : "amber"}">${esc(t("runs.status." + r.status))}</span>`;
const runWhen = (ts) => new Date(ts * 1000).toLocaleString();
function renderProjRuns() {
  const host = $("projRuns");
  if (!host) return;
  const rows = tabs.projects.runs || [];
  host.innerHTML = rows.length ? `<div class="muted small">${esc(t("runs.history"))}</div>
    ${rows.map((r) => `<div class="row small" style="gap:8px">${runBadge(r)}<span class="mono">${esc(r.kind)}</span>
      <span class="mono muted">${esc(r.command)}</span><span class="muted">${esc(r.duration)} s</span>
      <span class="muted">${esc(runWhen(r.started))}</span>${btn(t("runs.log"), "runLog", { id: r.id })}</div>`).join("")}` : "";
}
handlers.runStart = async (d) => {
  const r = await api("/api/runs/start", { project: d.project, kind: d.kind });
  await runJob(Promise.resolve(r), () => tabs.projects.loadRuns(d.project));
};
handlers.runLog = async (d) => {
  const r = await api(`/api/runs/log?id=${encodeURIComponent(d.id)}`);
  $("logTitle").textContent = `${t("runs.log")} ${r.id}`;
  $("logBody").textContent = r.log + (r.truncated ? `\n… ${t("tasks.truncated")}` : "");
  logDlg.showModal();
};

// ---- GitHub Actions: последние запуски с кнопками «Отменить» / «Повторить» (runs.py)
async function ghLoadRuns(path, name) {
  const host = $("ghRunsList");
  if (!host) return;
  try {
    const { runs } = await api(`/api/gh/runs?project=${encodeURIComponent(path)}`);
    host.innerHTML = runs.length ? `<table><tbody>${runs.map((r) => `<tr><td class="mono">${esc(r.databaseId)}</td><td>${esc(r.workflowName)} · ${esc(r.headBranch)}</td>
      <td><span class="badge ${r.status === "completed" ? (r.conclusion === "success" ? "green" : "amber") : "blue"}">${esc(r.status === "completed" ? (r.conclusion || r.status) : r.status)}</span></td>
      <td><div class="actions">${r.status !== "completed" ? btn(t("runs.ghCancel"), "ghRunAct", { project: path, name, run: r.databaseId, act: "cancel" }, "danger")
        : btn(t("runs.ghRerun"), "ghRunAct", { project: path, name, run: r.databaseId, act: "rerun" }) + (r.conclusion === "failure" ? btn(t("runs.ghRerunFailed"), "ghRunAct", { project: path, name, run: r.databaseId, act: "rerun", failed: "1" }) : "")}</div></td></tr>`).join("")}</tbody></table>`
      : esc(t("runs.ghNoRuns"));
  } catch (e) { host.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}
handlers.ghRunAct = async (d) => {
  if (!confirm(t(d.act === "cancel" ? "runs.ghCancelConfirm" : "runs.ghRerunConfirm", { id: d.run }))) return;
  const typed = prompt(t("git.typeName", { name: d.name }));
  if (typed === null) return;
  try {
    const body = { project: d.project, run_id: String(d.run), confirm: typed };
    if (d.failed) body.failed_only = true;
    const r = await api(d.act === "cancel" ? "/api/gh/run_cancel" : "/api/gh/run_rerun", body);
    await runJob(Promise.resolve(r), () => ghLoadRuns(d.project, d.name));
  } catch (e) { toast(e.message, true); }
};

// ---- GitHub Actions: запуск workflow (runs.py). Действие во внешней системе → ввод имени проекта (проверяет сервер).
handlers.ghLoadWorkflows = async (d) => {
  const host = $("projWf");
  try {
    const w = await api(`/api/gh/workflows?project=${encodeURIComponent(d.project)}`);
    host.innerHTML = w.workflows.length ? `<form class="row" id="ghRun" data-path="${esc(d.project)}" data-name="${esc(d.name)}" style="gap:8px">
      <select name="workflow">${w.workflows.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select>
      <select name="ref">${w.branches.map((b) => `<option ${b === w.current ? "selected" : ""}>${esc(b)}</option>`).join("")}</select>
      <input type="text" name="inputs" placeholder="${esc(t("runs.ghInputsPh"))}" autocomplete="off" style="min-width:220px">
      <button type="submit" class="danger">${esc(t("runs.ghRun"))}</button></form>
      <div id="ghRunsList" class="muted small" style="margin-top:8px">${esc(t("common.loading"))}</div>`
      : `<div class="muted small">${esc(t("runs.ghNone"))}</div>`;
    if (w.workflows.length) ghLoadRuns(d.project, d.name);
  } catch (e) { host.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
};
document.addEventListener("submit", async (ev) => {
  if (ev.target.id !== "ghRun") return;
  ev.preventDefault();
  const f = new FormData(ev.target), path = ev.target.dataset.path, name = ev.target.dataset.name;
  const wfName = ev.target.elements.workflow.selectedOptions[0].text;
  if (!confirm(t("runs.ghConfirm", { w: wfName, r: f.get("ref") }))) return;
  const typed = prompt(t("git.typeName", { name }));
  if (typed === null) return;
  try {
    const inputs = {};
    for (const pair of String(f.get("inputs") || "").split(/[,\n]/).map((x) => x.trim()).filter(Boolean)) {
      const i = pair.indexOf("=");
      if (i < 1) return toast(t("runs.ghInputsBad", { p: pair }), true);
      inputs[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
    }
    const r = await api("/api/gh/workflow_run", { project: path, workflow: f.get("workflow"), ref: f.get("ref"), confirm: typed, ...(Object.keys(inputs).length ? { inputs } : {}) });
    await runJob(Promise.resolve(r), () => { delete tabs.projects.gh[path]; tabs.projects.loadGithub(path); });
  } catch (e) { toast(e.message, true); }
});
