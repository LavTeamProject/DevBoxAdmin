// Halaman Install Profiles: status deteksi + instalasi (Fase 2.4). Alurnya: rencana (/api/profiles/plan,
// tanpa mengubah apa pun) -> konfirmasi daftar paket -> job (/api/profiles/install). Lihat profiles.py.

tabs.profiles = {
  titleKey: "nav.profiles",
  force: false,
  data: null,
  async load(silent) {
    try { this.data = await api(`/api/profiles${this.force ? "?refresh=1" : ""}`); }
    catch (e) { if (!silent) return failView(e); return; }
    this.force = false;
    this.render();
  },

  // Digambar ulang dari data di memori — dipakai saat ganti bahasa (lihat i18n.js).
  render() {
    const d = this.data;
    if (!d) return;
    const ready = d.profiles.filter((p) => p.ready).length;
    $("headline").textContent = `${ready}/${d.profiles.length} ${t("profiles.ready")}`;

    const itemRow = (p, i) => {
      const note = i.note ? t(`profiles.note.${i.note}`) : "";
      const detail = [note, i.note === "server_needs_311" && i.compatible === false ? t("profiles.note.too_old") : ""]
        .filter(Boolean).join(" ");
      return `<div class="check-row">
        <span class="mark ${i.installed ? "" : "off"}">${i.installed ? "✔" : "○"}</span>
        <span>${esc(i.name)}
          ${i.required ? `<span class="badge">${esc(t("common.required"))}</span>` : `<span class="badge gray">${esc(t("common.optional"))}</span>`}
          ${i.version ? `<span class="muted small">${esc(i.version)}</span>` : ""}
          ${detail ? `<div class="note">${detail}</div>` : ""}
          ${i.path ? `<div class="pkg mono">${esc(i.path.replace(/^\/Users\/[^/]+/, "~"))}</div>` : ""}
        </span>
        <span class="actions">${itemAction(p, i)}</span>
        <span class="muted small mono pkgcmd">${esc(i.pkg || "")}</span>
      </div>`;
    };
    // Что можно сделать с пунктом из панели: поставить (brew), открыть мастер, или это вне панели.
    const itemAction = (p, i) => {
      if (i.installed) return "";
      if (i.install === "brew") return btn(t("profiles.install"), "profInstall", { profile: p.id, items: i.id, scope: "all" });
      if (i.install === "setup") return `<a class="badge amber" href="#setup">${esc(t("profiles.kind.setup"))}</a>`;
      if (i.install === "later") return `<span class="badge gray">${esc(t("profiles.kind.later"))}</span>`;
      return `<span class="badge gray">${esc(t("profiles.kind.manual"))}</span>`;
    };

    const profileButtons = (p) => {
      const miss = p.items.filter((i) => !i.installed && i.install === "brew");
      const missReq = miss.filter((i) => i.required);
      if (!miss.length) return "";
      return `<div class="row" style="gap:8px;margin:10px 0 4px">
        ${missReq.length ? btn(t("profiles.installRequired", { n: missReq.length }), "profInstall", { profile: p.id, scope: "required" }, "primary") : ""}
        ${miss.length > missReq.length ? btn(t("profiles.installAll", { n: miss.length }), "profInstall", { profile: p.id, scope: "all" }) : ""}
      </div>`;
    };

    const card = (p) => {
      const pct = p.total ? Math.round((p.have / p.total) * 100) : 0;
      return `<div class="card">
        <div class="prof-head">
          ${iconOr(p.icon, p.id)}
          <div style="flex:1;min-width:0">
            <div class="name">${esc(profileName(p))}
              ${p.ready ? `<span class="badge green">${esc(t("profiles.ready"))}</span>`
                        : `<span class="badge amber">${esc(t("profiles.missing", { n: p.missing_required.length }))}</span>`}</div>
            <div class="meta"><span>${esc(t("profiles.desc." + p.id))}</span></div>
            <div class="muted small" style="margin-top:8px">${esc(t("profiles.have", { have: p.have, total: p.total }))}</div>
            <div class="meter ${p.ready ? "" : "partial"}"><i style="width:${pct}%"></i></div>
          </div>
        </div>
        ${profileButtons(p)}
        <div class="checklist">${p.items.map((i) => itemRow(p, i)).join("")}</div>
      </div>`;
    };

    view.innerHTML = `
      <div class="ro-banner"><span>${t("profiles.intro")}</span></div>
      <div class="row" style="margin-bottom:12px">
        <span class="spacer"></span>
        ${btn(t("profiles.rescan"), "profilesReload")}
      </div>
      <div class="list">${d.profiles.map(card).join("")}</div>
      <p class="muted small">${t("profiles.outside")}</p>`;
  },
};

// Nama profil: produk, bukan prosa — dipetakan di sini supaya tetap satu tempat.
const PROFILE_NAMES = {
  ru: { base: "Фундамент", ai: "AI", flutter: "Flutter", ios: "iOS", backend: "Backend" },
  en: { base: "Foundation", ai: "AI", flutter: "Flutter", ios: "iOS", backend: "Backend" },
};
function profileName(p) {
  return (PROFILE_NAMES[LANG] || PROFILE_NAMES.ru)[p.id] || p.id;
}

handlers.profilesReload = async () => {
  tabs.profiles.force = true;
  await tabs.profiles.load();
  toast(t("profiles.rescan"));
};

// Установка профиля: сначала план (ничего не меняет), потом подтверждение со списком, потом job.
handlers.profInstall = async (d) => {
  const scope = d.scope || "required";
  const q = `profile=${encodeURIComponent(d.profile)}&scope=${scope}${d.items ? `&items=${encodeURIComponent(d.items)}` : ""}`;
  const pl = await api(`/api/profiles/plan?${q}`);
  if (pl.blocked) { toast(t(`profiles.blocked.${pl.blocked}`), true); location.hash = "#setup"; return; }
  const todo = pl.items.filter((e) => e.action === "install");
  if (!todo.length) { toast(t("profiles.nothing")); return; }
  const lines = todo.map((e) => `• ${e.name} — brew install ${e.type === "cask" ? "--cask " : ""}${e.pkg}`).join("\n");
  if (!confirm(`${t("profiles.confirmHead", { n: todo.length })}\n\n${lines}\n\n${t("profiles.confirmTail")}`)) return;
  await runJob(api("/api/profiles/install", { profile: d.profile, scope, items: d.items ? [d.items] : [] }),
    () => { tabs.profiles.force = true; tabs.profiles.load(); });
};
