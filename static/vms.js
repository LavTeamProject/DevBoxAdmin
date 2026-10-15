// Страница «Виртуальные машины» (vm.py, драйвер tart): список и управление. Любое изменение — job + запись в аудит.
// Удаление и скачивание образа требуют ввода имени (проверяется и на сервере). Агентам эти операции не открыты.

tabs.vms = {
  titleKey: "nav.vms",
  data: null,
  runners: null,
  async load(silent) {
    try { this.data = await api("/api/vms"); this.runners = await api("/api/runners"); }
    catch (e) { if (!silent) return failView(e); return; }
    this.render();
  },

  render() {
    const d = this.data;
    if (!d) return;
    const drv = d.drivers[0];
    const vms = drv.vms.filter((v) => v.source === "local");
    const images = drv.vms.filter((v) => v.source !== "local");
    $("headline").textContent = t("vm.count", { n: vms.length });
    if (!drv.available) {
      view.innerHTML = `<div class="card"><div class="name">${esc(t("vm.noTart"))}</div><p class="muted">${esc(t("vm.noTartBody"))}</p></div>`;
      return;
    }
    const row = (v) => `<tr>
      <td class="mono">${esc(v.name)}</td>
      <td><span class="badge ${v.running ? "green" : "gray"}">${esc(t(v.running ? "vm.running" : "vm.stopped"))}</span></td>
      <td class="muted small">${esc(t("vm.disk", { d: v.disk_gb ?? "?", s: v.size_gb ?? "?" }))}</td>
      <td><div class="actions" style="flex-wrap:wrap">
        ${v.running ? btn(t("vm.stop"), "vmOp", { op: "vm.stop", name: v.name, confirm: t("vm.confirmStop", { name: v.name }) })
                    : btn(t("vm.start"), "vmOp", { op: "vm.start", name: v.name, confirm: t("vm.confirmStart", { name: v.name }) }, "primary")}
        ${v.running ? "" : btn(t("vm.snapshot"), "vmOp", { op: "vm.snapshot", name: v.name, confirm: t("vm.confirmSnapshot", { name: v.name }) })}
        ${btn(t("vm.clone"), "vmClone", { name: v.name })}
        ${v.running ? "" : btn(t("vm.prepareRunner"), "vmPrepare", { name: v.name }) + btn(t("vm.recipeBtn"), "vmRecipe", { name: v.name })}
        ${v.running || !vms.some((x) => x.snapshot_of === v.name) ? "" : btn(t("vm.restore"), "vmRestore", { name: v.name }, "danger")}
        ${v.running ? "" : btn(t("vm.delete"), "vmDelete", { name: v.name }, "danger")}
      </div></td></tr>`;
    const img = (v) => `<tr><td class="mono small">${esc(v.name)}</td><td class="muted small">${esc(t("vm.disk", { d: v.disk_gb ?? "?", s: v.size_gb ?? "?" }))}</td></tr>`;
    view.innerHTML = `
      <p class="muted">${esc(t("vm.intro"))}</p>
      <div class="card" style="margin-bottom:14px">
        <div class="row" style="gap:8px;align-items:center"><b>${esc(t("vm.title"))}</b><span class="spacer"></span>
          ${btn(t("vm.pull"), "vmPull", {})}</div>
        ${vms.length ? `<table><tbody>${vms.map(row).join("")}</tbody></table>` : `<p class="muted">${esc(t("vm.none"))}</p>`}
      </div>
      <div class="card" style="margin-bottom:14px">
        <div class="row" style="gap:8px;align-items:center"><b>${esc(t("rn.title"))}</b><span class="spacer"></span>
          ${btn(t("rn.addSource"), "rnAddSource", {})}</div>
        <p class="muted small">${esc(t("rn.note"))}</p>
        ${(this.runners?.providers || []).map((p) => `<div class="row" style="gap:8px;align-items:center;margin:4px 0">
          <span>${esc(p.title)}</span>
          ${p.installed.length ? p.installed.map((i) => `<span class="badge green mono">${esc(i.version)}</span>`).join("") : `<span class="badge gray">${esc(t("rn.notInstalled"))}</span>`}
          <span class="spacer"></span>${btn(t("rn.install"), "rnInstall", { provider: p.id, confirm: t("rn.confirmInstall", { name: p.title }) })}</div>`).join("")}
        <div class="nav-label" style="margin-top:10px">${esc(t("rn.sources"))}</div>
        <div class="muted small" style="margin:4px 0">${esc(t("rn.untrustedWarn"))}</div>
        ${(this.runners?.sources || []).map((s) => `<div class="row" style="gap:8px;align-items:center;margin:4px 0">
          <b>${esc(s.name)}</b><span class="badge gray">${esc(s.provider)}</span>
          <span class="mono small">${esc(s.url)}${s.scope === "instance" ? "" : " · " + esc(s.path)}</span>
          ${s.has_token ? `<span class="badge amber">${esc(t(s.auth === "api" ? "rn.hasApiToken" : "rn.hasToken"))}</span>` : ""}
          <span class="spacer"></span>${s.has_token && s.auth === "api" ? btn(t("rn.test"), "rnTest", { id: s.id }) + btn(t("rn.selftest"), "rnSelftest", { id: s.id, name: s.name }) : ""}${s.has_token ? btn(t("rn.spawn"), "rnSpawn", { id: s.id, name: s.name }) : ""}${btn(t("rn.removeSource"), "rnRemoveSource", { id: s.id, confirm: t("rn.confirmRemove", { name: s.name }) }, "danger")}</div>`).join("")
          || `<p class="muted small">${esc(t("rn.noSources"))}</p>`}
      </div>
      ${images.length ? `<div class="card"><b>${esc(t("vm.images"))}</b><table><tbody>${images.map(img).join("")}</tbody></table></div>` : ""}`;
  },
};

async function vmRun(op, params) {
  let r;
  try { r = await api("/api/vms/op", { op, params }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), () => tabs.vms.load());
}
handlers.vmOp = (d) => vmRun(d.op, { name: d.name });
handlers.vmClone = (d) => {
  const name = prompt(t("vm.clonePrompt", { name: d.name }), d.name + "-copy");
  if (name) return vmRun("vm.clone", { source: d.name, name });
};
handlers.vmPrepare = (d) => {
  const provider = prompt(t("vm.prepareAsk", { name: d.name }), "gitea");
  if (provider) return vmRun("vm.prepare_runner", { name: d.name, provider });
};
handlers.vmRecipe = (d) => {
  const recipe = prompt(t("vm.recipeAsk", { name: d.name }), "node");
  if (recipe) return vmRun("vm.recipe", { name: d.name, recipe: recipe.trim() });
};
handlers.vmRestore = (d) => {
  const snaps = (tabs.vms.data?.drivers?.[0]?.vms || []).filter((x) => x.source === "local" && x.snapshot_of === d.name).map((x) => x.name).sort();
  const snap = prompt(t("vm.restorePick", { name: d.name, list: snaps.join("\n") }), snaps[snaps.length - 1] || "");
  if (!snap) return;
  const typed = prompt(t("vm.restorePrompt", { name: d.name, snap }));
  if (typed !== null) return vmRun("vm.restore", { name: d.name, snapshot: snap, confirm: typed });
};
handlers.vmDelete = (d) => {
  const typed = prompt(t("vm.deletePrompt", { name: d.name }));
  if (typed !== null) return vmRun("vm.delete", { name: d.name, confirm: typed });
};
handlers.vmPull = () => {
  const image = prompt(t("vm.pullImage"), "ghcr.io/cirruslabs/macos-tahoe-vanilla:latest");
  if (!image) return;
  const name = prompt(t("vm.pullName"), "macos-new");
  if (!name) return;
  const typed = prompt(t("vm.pullConfirm", { name }));
  if (typed !== null) return vmRun("vm.pull", { image, name, confirm: typed });
};

handlers.rnInstall = async (d) => {
  let r;
  try { r = await api("/api/runners/install", { provider: d.provider }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), () => tabs.vms.load());
};
handlers.rnSpawn = async (d) => {
  const vm = prompt(t("rn.spawnVm"), (tabs.vms.data?.drivers?.[0]?.vms || []).filter((v) => v.source === "local" && !v.running && !v.name.startsWith("ci-")).map((v) => v.name)[0] || "");
  if (!vm) return;
  const minutes = parseInt(prompt(t("rn.spawnMinutes"), "60"), 10);
  if (!minutes) return;
  const typed = prompt(t("rn.spawnConfirm", { name: d.name }));
  if (typed === null) return;
  let r;
  try { r = await api("/api/runners/spawn", { source: d.id, vm, minutes, confirm: typed }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), () => tabs.vms.load());
};
handlers.rnTest = async (d) => {
  try { const r = await api("/api/runners/source/test", { id: d.id }); toast(t("rn.testOk", { user: r.user || "", n: r.runners ?? 0 })); }
  catch (e) { toast(e.message, true); }
};
handlers.rnSelftest = async (d) => {
  const vm = prompt(t("rn.spawnVm"), (tabs.vms.data?.drivers?.[0]?.vms || []).filter((v) => v.source === "local" && !v.running && !v.name.startsWith("ci-")).map((v) => v.name)[0] || "");
  if (!vm) return;
  const typed = prompt(t("rn.selftestConfirm", { name: d.name }));
  if (typed === null) return;
  let r;
  try { r = await api("/api/runners/selftest", { source: d.id, vm, minutes: 10, confirm: typed }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), () => tabs.vms.load());
};
handlers.rnRemoveSource = async (d) => {
  try { await api("/api/runners/source/remove", { id: d.id }); } catch (e) { return toast(e.message, true); }
  toast(t("rn.removed")); await tabs.vms.load();
};
handlers.rnAddSource = async () => {
  const provider = prompt(t("rn.askProvider"), "gitea");
  if (!provider) return;
  const url = prompt(t("rn.askUrl"), provider === "github" ? "https://github.com" : "https://git.example.com");
  if (!url) return;
  const scope = prompt(t("rn.askScope"), "org");
  if (!scope) return;
  const path = scope === "instance" ? "" : prompt(t("rn.askPath"), scope === "repo" ? "owner/repo" : "organization");
  if (path === null) return;
  const name = prompt(t("rn.askName"), "");
  if (!name) return;
  const auth = prompt(t("rn.askAuth"), "api");
  if (!auth) return;
  const token = await askSecret(t(auth === "api" ? "rn.askApiToken" : "rn.askToken"));
  if (token === null) return;
  try { await api("/api/runners/source/add", { name, provider, url, scope, path, auth, token: token || undefined }); } catch (e) { return toast(e.message, true); }
  toast(t("rn.added")); await tabs.vms.load();
};
