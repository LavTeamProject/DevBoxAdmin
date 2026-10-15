// Konfigurasi: editor semua file config (shell, /etc/hosts, resolver, SSH, Git,
// php.ini, tmux, vim, package manager, .env project) dengan validasi & backup.

tabs.config = {
  files: [],
  item: null,
  dirty: false,
  async load() {
    let list;
    try { list = await api("/api/files"); } catch (e) { return failView(e); }
    this.files = list.files;
    const id = this.param || this.item?.id || "zshrc";
    view.innerHTML = `
      <div class="cfg-layout">
        <aside class="card cfg-list">
          <input type="search" id="cfgQ" placeholder="${esc(t("cfg.search"))}" style="width:100%;margin-bottom:8px">
          <div id="cfgNav"></div>
        </aside>
        <section id="cfgMain"><div class="loading">${esc(t("common.loading"))}</div></section>
      </div>`;
    $("cfgQ").oninput = () => this.renderList();
    this.renderList();
    await this.open(this.files.some((f) => f.id === id) ? id : "zshrc");
  },
  renderList() {
    const q = ($("cfgQ")?.value || "").toLowerCase();
    const groups = {};
    this.files.filter((f) => !q || (f.label + f.path).toLowerCase().includes(q))
      .forEach((f) => (groups[f.group] ??= []).push(f));
    $("cfgNav").innerHTML = Object.entries(groups).map(([g, list]) => `
      <div class="nav-label" style="padding-left:4px">${esc(g)}</div>
      ${list.map((f) => `<a href="#config:${encodeURIComponent(f.id)}" class="cfg-item ${this.item?.id === f.id ? "active" : ""}" title="${esc(f.path)}">
        <span class="cfg-name">${esc(f.label)}</span>
        ${f.admin ? `<span title="${esc(t("cfg.adminTip"))}">🔒</span>` : ""}${f.sensitive ? `<span title="${esc(t("cfg.secretTip"))}">🔑</span>` : ""}
        ${f.exists ? "" : `<span class="badge">${esc(t("cfg.new"))}</span>`}</a>`).join("")}`).join("")
      || `<div class="muted small">${esc(t("cfg.noFiles"))}</div>`;
  },
  async open(id) {
    if (this.item && this.item.id !== id && !this.leaveOk()) return;
    const d = await api(`/api/files/read?id=${encodeURIComponent(id)}`);
    this.item = d;
    this.dirty = false;
    this.renderList();
    $("headline").textContent = d.path;
    $("cfgMain").innerHTML = `
      <div class="row" style="margin-bottom:10px">
        <div><div class="name" style="font-size:15px">${esc(d.label)}
            ${d.admin ? `<span class="badge amber">🔒 ${esc(t("cfg.adminNeeded"))}</span>` : ""}
            ${d.sensitive ? `<span class="badge amber">🔑 ${esc(t("cfg.hasSecrets"))}</span>` : ""}
            ${d.exists ? "" : `<span class="badge">${esc(t("cfg.notYet"))}</span>`}</div>
          <div class="muted small"><code>${esc(d.path)}</code> <span id="cfgState"></span></div></div>
        <span class="spacer"></span>
        ${d.validator ? btn(t("cfg.validate"), "fileValidate") : ""}
        ${btn(t("cfg.reload"), "fileReload")}
        ${btn(t("cfg.save"), "fileSave", {}, "primary")}
      </div>
      ${d.sensitive ? `<div class="warn">${esc(t("cfg.sensitiveWarn"))}</div>` : ""}
      <textarea class="editor" id="fileEd" spellcheck="false" style="min-height:52vh"></textarea>
      <pre class="card" id="fileOut" style="display:none;margin-top:10px"></pre>
      <div class="grid two" style="margin-top:14px">
        <div id="filePanel"></div>
        <div class="card"><h3>${esc(t("cfg.backup"))} <span class="muted small">${esc(t("cfg.backupNote"))}</span></h3>
          ${d.backups.length ? d.backups.map((b) => `<div class="row issue" style="cursor:default">
            <span class="spacer">${esc(b.replace(/^.*\.(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$/, "$3/$2/$1 $4:$5:$6"))}</span>
            ${btn(t("cfg.loadToEditor"), "fileBackup", { backup: b })}</div>`).join("") : `<div class="muted small">${esc(t("cfg.noBackups"))}</div>`}</div>
      </div>`;
    const ed = $("fileEd");
    ed.value = d.content;
    ed.oninput = () => { this.dirty = true; $("cfgState").textContent = "● " + t("cfg.unsaved"); };
    ed.onkeydown = (e) => {
      if (e.key === "Tab") { e.preventDefault(); ed.setRangeText(d.validator === "zsh" ? "    " : "  ", ed.selectionStart, ed.selectionEnd, "end"); ed.oninput(); }
      if ((e.metaKey || e.ctrlKey) && e.key === "s") { e.preventDefault(); handlers.fileSave({}); }
    };
    await this.panel(d);
  },
  // panel tambahan sesuai jenis file
  async panel(d) {
    const el = $("filePanel");
    if (d.validator === "zsh") {
      el.innerHTML = `<div class="card"><h3>${esc(t("cfg.check"))}</h3>${d.issues.length ? d.issues.map((i) =>
        `<div class="issue" data-act="fileGoto" data-line="${i.line}">${esc(t("cfg.line", { n: i.line }))}: ${esc(i.msg)}</div>`).join("")
        : `<div class="muted small">✅ ${esc(t("cfg.noIssues"))}</div>`}
        <p class="muted small">${t("cfg.zshNote", { file: `<code>source ~/${esc(d.label)}</code>` })}</p></div>`;
    } else if (d.id === "hosts" || d.id.startsWith("resolver:")) {
      el.innerHTML = `<div class="card">
        ${d.id === "hosts" ? `<h3>${esc(t("cfg.hostsAdd"))}</h3>
          <form class="row" id="hostsAdd"><input name="ip" value="127.0.0.1" style="width:130px"><input name="host" placeholder="myapp.test" style="flex:1"><button>${esc(t("cfg.addToEditor"))}</button></form>` : ""}
        <h3 style="margin-top:14px">${esc(t("cfg.newResolver"))} <span class="muted small">/etc/resolver</span></h3>
        <form class="row" id="resolverAdd"><input name="domain" placeholder="${esc(t("cfg.domainPh"))}" style="flex:1"><input name="nameserver" value="127.0.0.1" style="width:130px"><button>${esc(t("cfg.create"))}</button></form>
        <p class="muted small">${esc(t("cfg.sysSaveNote"))}</p></div>`;
      if ($("hostsAdd")) $("hostsAdd").onsubmit = (e) => {
        e.preventDefault();
        const f = Object.fromEntries(new FormData(e.target));
        if (!f.host.trim()) return;
        const ed = $("fileEd");
        ed.value = ed.value.replace(/\n*$/, "\n") + `${f.ip.trim()}\t${f.host.trim()}\n`;
        ed.oninput();
        toast(t("cfg.addedToast"));
      };
      $("resolverAdd").onsubmit = async (e) => {
        e.preventDefault();
        try {
          const r = await api("/api/files/resolver", Object.fromEntries(new FormData(e.target)));
          toast(t("cfg.resolverCreated"));
          location.hash = `#config:${encodeURIComponent(r.id)}`;
        } catch (err) { toast(err.message, true); }
      };
    } else if (d.id === "ssh_config") {
      const k = await api("/api/ssh/keys");
      el.innerHTML = `<div class="card"><h3>SSH key</h3>
        ${k.keys.map((key, i) => `<div class="issue" style="cursor:default">
          <div class="row"><b>${esc(key.name)}</b><span class="badge">${esc(key.type)}</span><span class="muted small">${esc(key.comment)}</span>
            <span class="spacer"></span>${btn(t("cfg.copyPub"), "sshCopy", { i })}</div>
          <div class="muted small"><code>${esc(key.fingerprint || "")}</code></div></div>`).join("") || `<div class="muted small">${esc(t("cfg.noKeys"))}</div>`}
        <h3 style="margin-top:14px">${esc(t("cfg.newKey"))}</h3>
        <form class="list" id="sshGen">
          <div class="row"><input name="name" placeholder="id_ed25519_github" style="flex:1"><input name="comment" placeholder="${esc(t("cfg.commentPh"))}" style="flex:1"></div>
          <div class="row"><input name="passphrase" type="password" placeholder="${esc(t("cfg.passphrasePh"))}" style="flex:1"><button class="go">Generate</button></div>
        </form>
        <p class="muted small">${esc(t("cfg.keyNote"))}</p></div>`;
      this.keys = k.keys;
      $("sshGen").onsubmit = async (e) => {
        e.preventDefault();
        try {
          const r = await api("/api/ssh/generate", Object.fromEntries(new FormData(e.target)));
          toast(t("cfg.keyCreated", { name: r.name }));
          await this.panel(d);
        } catch (err) { toast(err.message, true); }
      };
    } else if (d.id === "gitconfig") {
      const g = await api("/api/git/identity");
      el.innerHTML = `<div class="card"><h3>${esc(t("cfg.gitIdentity"))}</h3><dl class="kv">
        <dt>user.name</dt><dd>${esc(g.name || "-")}</dd><dt>user.email</dt><dd>${esc(g.email || "-")}</dd>
        <dt>core.excludesfile</dt><dd><code>${esc(g.excludesfile || "~/.config/git/ignore (default)")}</code></dd></dl>
        <p class="muted small">${t("cfg.gitNote")}</p></div>`;
    } else if (d.validator === "phpini") {
      el.innerHTML = `<div class="card"><h3>php.ini</h3><p class="muted small">${t("cfg.phpNote", { link: d.path.includes("Herd") ? `<a href="#herd">Herd → Restart</a>` : `<a href="#service:php">service php → Restart</a>` })}</p></div>`;
    } else {
      el.innerHTML = "";
    }
  },
  leaveOk() { return !this.dirty || confirm(t("cfg.discardConfirm")); },
};

function fileOut(text, ok = true) {
  const o = $("fileOut");
  o.style.display = "block";
  o.style.color = ok ? "" : "var(--red)";
  o.textContent = text;
}
handlers.fileReload = async () => { if (tabs.config.leaveOk()) { tabs.config.dirty = false; await tabs.config.open(tabs.config.item.id); } };
handlers.fileValidate = async () => {
  const r = await api("/api/files/validate", { id: tabs.config.item.id, content: $("fileEd").value });
  fileOut((r.ok ? "✅ " : "❌ ") + r.output, r.ok);
};
handlers.fileSave = async () => {
  const it = tabs.config.item, body = { id: it.id, content: $("fileEd").value };
  if (it.admin) toast(t("cfg.adminPrompt"));
  let r;
  try {
    r = await api("/api/files/save", body);
  } catch (e) {
    fileOut(e.message, false);
    if (e.code !== "files.invalid_not_saved" || !confirm(e.message + "\n\n" + t("cfg.saveAnyway"))) return;
    r = await api("/api/files/save", { ...body, force: true });
  }
  tabs.config.dirty = false;
  toast(t(r.backup ? "cfg.savedBackup" : "cfg.saved", { label: it.label }));
  await tabs.config.open(it.id);
  fileOut(`✅ ${t("cfg.savedOut")} ${r.validation}`);
};
handlers.fileGoto = (d) => {
  const ed = $("fileEd"), lines = ed.value.split("\n");
  const start = lines.slice(0, d.line - 1).join("\n").length + (d.line > 1 ? 1 : 0);
  ed.focus();
  ed.setSelectionRange(start, start + lines[d.line - 1].length);
  ed.scrollTop = (d.line - 5) * parseFloat(getComputedStyle(ed).lineHeight);
};
handlers.fileBackup = async (d) => {
  if (!tabs.config.leaveOk()) return;
  const { content } = await api(`/api/files/backup?id=${encodeURIComponent(tabs.config.item.id)}&backup=${encodeURIComponent(d.backup)}`);
  $("fileEd").value = content;
  $("fileEd").oninput();
  toast(t("cfg.backupLoaded"));
};
handlers.sshCopy = async (d) => {
  await navigator.clipboard.writeText(tabs.config.keys[d.i].public);
  toast(t("cfg.pubCopied"));
};
window.addEventListener("beforeunload", (e) => { if (current === tabs.config && tabs.config.dirty) e.preventDefault(); });
