// Halaman Toolchain Mobile: keadaan (mobile.py, hanya baca) + aksi (mobile_ops.py, lewat job + audit).
// Xcode/simulator/Flutter/FVM/Android/CocoaPods.


tabs.mobile = {
  titleKey: "nav.mobile",
  force: false,
  interval: 30000,
  data: null,      // respons /api/mobile terakhir
  fvm: null,       // daftar project Flutter/FVM terakhir
  async load(silent) {
    try { this.data = await api(`/api/mobile${this.force ? "?refresh=1" : ""}`); }
    catch (e) { if (!silent) return failView(e); return; }
    this.force = false;
    this.render();
    this.loadFvm();
  },

  // Digambar ulang dari data di memori — dipakai saat ganti bahasa,
  // supaya tidak menunggu request jaringan (lihat setLang di i18n.js).
  render() {
    const d = this.data;
    if (!d) return;
    const s = d.summary;
    $("headline").textContent = `Xcode ${s.xcode ? "✓" : "✗"} · Flutter ${s.flutter ? "✓" : "✗"} · Android ${s.android ? "✓" : "✗"}`;

    view.innerHTML = `
      <div class="ro-banner"><span>${t("mobile.intro")}</span></div>
      <div class="stat">
        <div class="card"><div>${esc(t("mobile.xcode.title"))}</div><div>${esc(d.xcode.active?.version || t("common.notFound"))}</div>
          <div class="muted small">${d.xcode.installs.length} × <code>/Applications/Xcode*.app</code></div></div>
        <div class="card"><div>${esc(t("mobile.flutter.sdk"))}</div><div>${esc(d.flutter.sdk?.version || t("common.notFound"))}</div>
          <div class="muted small">${esc(d.flutter.sdk?.channel || "")} ${d.flutter.sdk?.dart ? "· Dart " + esc(d.flutter.sdk.dart) : ""}</div></div>
        <div class="card"><div>${esc(t("mobile.sim.title"))}</div><div>${esc(t("mobile.sim.runtimes"))}: ${d.xcode.runtimes.length}</div>
          <div class="muted small">${d.summary.simulators} ${esc(t("mobile.sim.devices"))} · ${d.summary.booted} ${esc(t("mobile.sim.booted"))}</div></div>
        <div class="card"><div>${esc(t("mobile.android.title"))}</div><div>${esc(d.android.platforms.length ? d.android.platforms[d.android.platforms.length - 1].replace("android-", "") : t("common.notFound"))}</div>
          <div class="muted small">${d.android.avds.length} AVD · ${d.android.build_tools.length} build-tools</div></div>
      </div>

      <h2>${esc(t("mobile.xcode.title"))}</h2>
      ${xcodeCard(d.xcode)}

      <h2>${esc(t("mobile.sim.title"))}</h2>
      ${simulatorCard(d.xcode)}

      <h2>${esc(t("mobile.flutter.title"))}</h2>
      ${flutterCard(d.flutter)}

      <h2>${esc(t("mobile.android.title"))}</h2>
      ${androidCard(d.android)}

      <p class="muted small">${t("mobile.flutterNote")}</p>`;
    this.renderFvm();
  },

  // Project Flutter/FVM: pemindaian folder bisa lambat, jadi diambil terpisah
  // dan disimpan supaya ganti bahasa tidak memicu pemindaian ulang.
  async loadFvm() {
    const host = $("fvmProjects");
    if (!host) return;
    host.innerHTML = `<h3 class="muted small">${esc(t("mobile.flutter.projects"))}</h3><div class="loading">${esc(t("shell.loading"))}</div>`;
    try { this.fvm = (await api("/api/mobile/flutter/projects")).projects; }
    catch { this.fvm = null; }
    this.renderFvm();
  },
  renderFvm() {
    const host = $("fvmProjects");
    if (!host || !this.fvm) return;
    const rows = this.fvm.map((p) => `<div class="card item">
        <div><div class="name">${esc(p.name)}
          ${p.fvm_pinned ? `<span class="badge blue">${esc(t("mobile.flutter.pinned", { v: p.fvm_pinned }))}</span>`
                         : `<span class="badge gray">${esc(t("mobile.flutter.noPinned"))}</span>`}</div>
          <div class="meta">${monoPath(p.path)}${p.fvm_link ? ` <span class="muted small">→ ${monoPath(p.fvm_link)}</span>` : ""}</div></div>
        <div class="actions">
          ${mobBtn("pub get", "flutter.pub_get", { project: p.path })}
          ${mobBtn("analyze", "flutter.analyze", { project: p.path })}
          ${mobBtn("test", "flutter.test", { project: p.path })}
          ${mobBtn("build apk", "flutter.build_apk", { project: p.path }, "mobile.act.confirmBuild", { name: p.name })}
          ${this.data?.flutter?.cocoapods?.installed ? mobBtn("pod install", "pod.install", { project: p.path }) : ""}
          ${btn(t("projects.openFolder"), "openPath", { path: p.path })}</div>
      </div>`).join("");
    host.innerHTML = `<h3 class="muted small">${esc(t("mobile.flutter.projects"))} · ${this.fvm.length}</h3>`
      + (rows ? `<div class="list">${rows}</div>` : `<div class="empty">${esc(t("common.empty"))}</div>`);
  },
};


// Действие над тулчейном: операция + параметры из реестра сервера (mobile_ops.py). Подтверждение — data-confirm.
const mobBtn = (label, op, params, confirmKey, confirmArgs, cls = "") =>
  btn(label, "mobOp", { op, params: JSON.stringify(params || {}), ...(confirmKey ? { confirm: t(confirmKey, confirmArgs || {}) } : {}) }, cls);

function xcodeCard(x) {
  if (!x.installs.length) return `<div class="warn">${esc(t("mobile.xcode.none"))}</div>`;
  const lic = x.first_launch
    ? (x.first_launch.done
        ? `<span class="badge green">${esc(t("mobile.xcode.licenseOk"))}</span>`
        : `<span class="badge amber">${esc(t("mobile.xcode.licensePending"))}</span>`)
    : `<span class="muted small">—</span>`;
  const rows = x.installs.map((i) => `<div class="card item">
      <div><div class="name">${esc(i.name)} <span class="badge">${esc(i.version || "?")}</span>
        ${x.active && x.active.path === i.path ? `<span class="badge green">${esc(t("mobile.xcode.active"))}</span>` : ""}</div>
        <div class="meta">${monoPath(i.path)}${i.build ? ` <span class="muted small">build ${esc(i.build)}</span>` : ""}</div></div>
      <div class="actions">
        ${x.active && x.active.path === i.path ? "" : mobBtn(t("mobile.act.makeActive"), "xcode.select", { path: i.path }, "mobile.act.confirmSelect", { v: i.version })}
        ${btn(t("projects.openFolder"), "openPath", { path: i.path })}</div>
    </div>`).join("");
  return `
    <div class="card" style="margin-bottom:12px">
      ${kvList([
        [t("mobile.xcode.active"), x.active ? `${esc(x.active.name)} ${esc(x.version || "")}` : `<span class="muted">${esc(t("mobile.xcode.none"))}</span>`],
        [t("mobile.xcode.license"), lic],
        [t("mobile.xcode.clt"), x.clt.installed ? `${monoPath(x.clt.path)}` : `<span class="muted">${esc(t("common.absent"))}</span>`],
        [t("mobile.xcode.xcodes"), x.xcodes_cli ? monoPath(x.xcodes_cli) : `<span class="muted">${esc(t("common.absent"))}</span>`],
      ])}
      ${x.clt.only_clt ? `<div class="note" style="margin-top:8px">${esc(t("mobile.xcode.cltOnly"))}</div>` : ""}
      ${x.first_launch && !x.first_launch.done ? `<div class="actions" style="justify-content:flex-start;margin-top:10px">
        ${mobBtn(t("mobile.act.firstLaunch"), "xcode.first_launch", {}, "mobile.act.confirmFirstLaunch", {}, "primary")}</div>` : ""}
      <div class="muted small" style="margin-top:10px">${t("mobile.xcode.hint")}</div>
    </div>
    <div class="list">${rows}</div>`;
}

function simulatorCard(x) {
  if (!x.simctl) return `<div class="warn">${esc(t("mobile.sim.unavailable"))}</div>`;
  if (!x.runtimes.length) return `<div class="empty">${esc(t("mobile.sim.none"))}</div>`;
  const byRuntime = {};
  for (const dev of x.devices) (byRuntime[dev.runtime] ??= []).push(dev);
  const runtimes = x.runtimes.map((r) => `<div class="card item">
      <div><div class="name">${esc(r.name)} ${r.available ? `<span class="badge green">${esc(t("common.yes"))}</span>` : `<span class="badge amber">${esc(t("common.no"))}</span>`}</div>
        <div class="meta"><span class="mono">${esc(r.identifier)}</span>${r.reason ? ` <span class="muted small">${esc(r.reason)}</span>` : ""}</div></div>
      <div class="actions"><span class="muted small">${(byRuntime[r.name] || []).length} ${esc(t("mobile.sim.devices"))}</span></div>
    </div>`).join("");
  const devs = x.devices.length ? `<div class="table-wrap" style="margin-top:12px"><table>
      <tr><th>${esc(t("mobile.sim.devices"))}</th><th>${esc(t("common.status"))}</th><th>Runtime</th><th>UDID</th><th></th></tr>
      ${x.devices.map((dv) => `<tr>
        <td><b>${esc(dv.name)}</b> <span class="muted small">${esc(dv.type)}</span></td>
        <td class="${dv.state === "Booted" ? "state-booted" : "state-shutdown"}">${esc(dv.state)}</td>
        <td class="small">${esc(dv.runtime || "-")}</td>
        <td class="mono muted">${esc((dv.udid || "").slice(0, 8))}…</td>
        <td><div class="actions">${simActions(dv)}</div></td></tr>`).join("")}
    </table></div>` : "";
  return `<div class="list">${runtimes}</div>
    <div class="actions" style="justify-content:flex-start;margin-top:10px">
      ${mobBtn(t("mobile.act.downloadIos"), "xcode.download_platform", { platform: "iOS" }, "mobile.act.confirmDownload")}
      ${btn(t("mobile.rt.show"), "mobRtShow", {})}</div>
    <div id="mobRtList"></div>
    ${devs}
    <p class="muted small">${t("mobile.sim.hint")}</p>`;
}

function simActions(dv) {
  if (!dv.available) return "";
  const u = { udid: dv.udid };
  if (dv.state === "Booted") {
    return mobBtn(t("mobile.act.screenshot"), "sim.screenshot", u) + mobBtn(t("mobile.act.shutdown"), "sim.shutdown", u);
  }
  if (dv.state === "Shutdown") {
    return mobBtn(t("mobile.act.boot"), "sim.boot", u)
      + mobBtn(t("mobile.act.erase"), "sim.erase", u, "mobile.act.confirmErase", { name: dv.name }, "danger");
  }
  return "";
}

function flutterCard(f) {
  if (!f.sdk) return `<div class="warn">${esc(t("mobile.flutter.none"))}</div>`;
  const s = f.sdk;
  const cache = s.cache_present && s.has_dart_sdk
    ? `<span class="badge green">${esc(t("mobile.flutter.cacheOk"))}</span>`
    : `<span class="badge amber">${esc(t("mobile.flutter.cacheMissing"))}</span>`;
  const others = f.sdks.filter((x) => x.path !== s.path);
  return `
    <div class="card" style="margin-bottom:12px">
      ${kvList([
        [t("mobile.flutter.sdk"), `${esc(s.version || "?")} <span class="badge">${esc(s.channel || "-")}</span>`],
        [t("mobile.flutter.dart"), esc(s.dart || "-")],
        [t("mobile.flutter.engine"), `<span class="mono">${esc((s.engine || "").slice(0, 12))}</span>`],
        [t("mobile.flutter.source"), esc(s.source)],
        [t("mobile.flutter.cache"), cache],
        [t("common.path"), monoPath(s.path)],
        [t("mobile.pods"), f.cocoapods.installed ? `${esc(f.cocoapods.version || "")} ${monoPath(f.cocoapods.path)}` : `<span class="muted">${esc(t("common.absent"))}</span>`],
        [t("mobile.fastlane"), f.fastlane.installed ? monoPath(f.fastlane.path) : `<span class="muted">${esc(t("common.absent"))}</span>`],
        [t("mobile.flutter.fvm"), f.fvm.installed ? `${monoPath(f.fvm.path)}` : `<span class="muted">${esc(t("common.absent"))}</span>`],
        [t("mobile.flutter.fvmVersions"), f.fvm.versions.length ? chipList(f.fvm.versions) : `<span class="muted small">—</span>`],
      ])}
      <div class="actions" style="justify-content:flex-start;margin-top:10px">
        ${btn(t("projects.openFolder"), "openPath", { path: s.path })}
        ${mobBtn("flutter doctor", "flutter.doctor", {})}
      </div>
      <form class="row" id="mobChannel" style="gap:8px;margin-top:10px">
        <select name="channel">${["stable", "beta", "master"].map((c) => `<option ${c === s.channel ? "selected" : ""}>${c}</option>`).join("")}</select>
        <button type="submit">${esc(t("mobile.act.switchChannel"))}</button></form>
      ${f.fvm.installed ? `<form class="row" id="mobFvm" style="gap:8px;margin-top:8px">
        <input type="text" name="version" placeholder="3.24.0 / stable" autocomplete="off" style="width:160px">
        <button type="submit">fvm install</button></form>` : ""}
    </div>
    ${others.length ? `<h3 class="muted small">${esc(t("mobile.flutter.sdks"))}</h3>
      <div class="list">${others.map((o) => `<div class="card item">
        <div><div class="name">${esc(o.version || "?")} <span class="badge">${esc(o.channel || o.source)}</span></div>
          <div class="meta">${monoPath(o.path)}</div></div></div>`).join("")}</div>` : ""}
    <div id="fvmProjects"></div>`;
}

function androidCard(a) {
  if (!a.sdk_path) return `<div class="warn">${esc(t("mobile.android.none"))}</div>`;
  const lic = a.licenses > 0
    ? `<span class="badge green">${esc(t("mobile.android.licensesOk"))} (${a.licenses})</span>`
    : `<span class="badge amber">${esc(t("mobile.android.licensesMissing"))}</span>`;
  return `
    <div class="card" style="margin-bottom:12px">
      ${kvList([
        [t("mobile.android.sdk"), monoPath(a.sdk_path)],
        [t("mobile.android.licenses"), lic],
        [t("mobile.android.adb"), a.adb ? `<span class="mono">${esc(a.adb)}</span>` : `<span class="muted">${esc(t("common.absent"))}</span>`],
        [t("mobile.android.platforms"), a.platforms.length ? chipList(a.platforms) : `<span class="muted small">—</span>`],
        [t("mobile.android.buildTools"), a.build_tools.length ? chipList(a.build_tools) : `<span class="muted small">—</span>`],
        [t("mobile.android.images"), a.system_images.length ? chipList(a.system_images.map((i) => `${i.api} ${i.variant}`)) : `<span class="muted small">—</span>`],
        [t("mobile.android.ndk"), a.ndk.length ? chipList(a.ndk) : `<span class="muted small">—</span>`],
        [t("mobile.jdk"), a.java_homes.length ? chipList(a.java_homes) : `<span class="muted">${esc(t("mobile.jdk.none"))}</span>`],
      ])}
      <div class="actions" style="justify-content:flex-start;margin-top:10px">
        ${btn(t("projects.openFolder"), "openPath", { path: a.sdk_path })}
        ${a.sdkmanager ? mobBtn(t("mobile.act.acceptLicenses"), "android.licenses", {}, "mobile.act.confirmLicenses") : ""}
      </div>
      ${a.sdkmanager ? `<form class="row" id="mobSdk" style="gap:8px;margin-top:10px">
        <input type="text" name="package" placeholder="platforms;android-35" autocomplete="off" style="flex:1;min-width:220px">
        <button type="submit">${esc(t("mobile.act.installPkg"))}</button></form>` : ""}
    </div>
    <h3 class="muted small">${esc(t("mobile.android.avds"))}</h3>
    ${a.avds.length ? `<div class="list">${a.avds.map((v) => `<div class="card item">
        <div><div class="name">${esc(v.name)}</div>
          <div class="meta">${v.target ? `<span>${esc(t("mobile.android.target", { t: v.target }))}</span>` : ""}${v.path ? monoPath(v.path) : ""}</div></div></div>`).join("")}</div>`
      : `<div class="empty">${esc(t("common.empty"))}</div>`}`;
}

handlers.openPath = async (d) => {
  await api("/api/terminal/open", { command: "", cwd: d.path });
  toast(d.path);
};

// Запуск операции: job в панели «Процессы»; после — обновить данные страницы.
async function runMobileOp(op, params) {
  let r;
  try { r = await api("/api/mobile/op", { op, params }); } catch (e) { return toast(e.message, true); }
  await runJob(Promise.resolve(r), async () => {
    tabs.mobile.force = true;
    await tabs.mobile.load();
    if (op === "sim.screenshot") showScreenshot(params.udid);
  });
}
// Удаление рантаймов симуляторов (освободить место): список — только то, что simctl считает удаляемым; подтверждение — ввод названия (проверяет сервер).
handlers.mobRtShow = async () => {
  const host = $("mobRtList");
  try {
    const { runtimes } = await api("/api/mobile/runtimes");
    host.innerHTML = runtimes.length ? `<div class="card" style="margin-top:10px"><b>${esc(t("mobile.rt.title"))}</b><table><tbody>${runtimes.map((r) => `<tr>
      <td class="mono">${esc(r.short)}</td><td class="muted small">${esc(r.kind || "")}</td>
      <td class="num">${r.size_bytes ? (r.size_bytes / 1e9).toFixed(1) + " GB" : "—"}</td>
      <td><div class="actions">${btn(t("mobile.rt.delete"), "mobRtDelete", { runtime: r.uuid, short: r.short }, "danger")}</div></td></tr>`).join("")}</tbody></table></div>`
      : `<div class="muted small">${esc(t("mobile.rt.none"))}</div>`;
  } catch (e) { host.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
};
handlers.mobRtDelete = (d) => {
  const typed = prompt(t("mobile.rt.prompt", { name: d.short }));
  if (typed !== null) return runMobileOp("sim.runtime_delete", { runtime: d.runtime, confirm: typed });
};
handlers.mobOp = (d) => runMobileOp(d.op, JSON.parse(d.params || "{}"));

async function showScreenshot(udid) {
  try {
    const { files } = await api("/api/mobile/screenshot");
    const name = files.find((f) => f.startsWith(udid.slice(0, 8)));
    if (!name) return;
    const { png_base64: b64 } = await api(`/api/mobile/screenshot?name=${encodeURIComponent(name)}`);
    $("logTitle").textContent = name;
    $("logBody").innerHTML = `<img alt="" src="data:image/png;base64,${b64}" style="max-width:100%;max-height:70vh">`;
    logDlg.showModal();
  } catch (e) { toast(e.message, true); }
}

document.addEventListener("submit", (ev) => {
  const id = ev.target.id;
  if (!["mobChannel", "mobFvm", "mobSdk"].includes(id)) return;
  ev.preventDefault();
  const fd = new FormData(ev.target);
  if (id === "mobChannel") {
    const ch = fd.get("channel");
    if (confirm(t("mobile.act.confirmChannel", { ch }))) runMobileOp("flutter.channel", { channel: ch });
  } else if (id === "mobFvm") {
    runMobileOp("fvm.install", { version: String(fd.get("version") || "").trim() });
  } else if (confirm(t("mobile.act.confirmPkg", { p: fd.get("package") }))) {
    runMobileOp("android.install", { package: String(fd.get("package") || "").trim() });
  }
});
