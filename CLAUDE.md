# CLAUDE.md

Panduan untuk Claude saat bekerja di repo ini.

**Bahasa — aturan keras:**

- **UI hanya punya DUA bahasa: Rusia (default) dan Inggris.** Kamusnya ada di `static/i18n.js`
  (`I18N.ru` dan `I18N.en`). **Jangan menambahkan bahasa ketiga**, dan jangan mengembalikan kamus `id`
  yang sudah dihapus. Kedua kamus harus selalu lengkap sama (jumlah kuncinya identik).
- **Teks UI baru wajib lewat `t("kunci")`**, bukan string langsung. Kalau kuncinya belum ada,
  tambahkan ke **kedua** kamus sekaligus.
- **Komentar kode: Bahasa Indonesia** (warisan repo, belum dimigrasi). Ini keputusan yang belum
  diambil — jangan mengubah bahasa komentar secara massal tanpa diminta.
- **Pesan yang dicetak skrip shell (`install.sh`, `uninstall.sh`, `fetch-python.sh`) juga hanya Rusia (default) / Inggris:** pakai `msg "ru" "en"` (bahasa Inggris jika `SA_LANG=en` atau `LANG=en*`). Dilarang pesan berbahasa Indonesia untuk pengguna.
- **Pesan error backend: `ApiError(pesan_Rusia, status, code="modul.slug", **params)`.** `pesan` = teks Rusia
  (default + cadangan); `code`+`params` diterjemahkan frontend lewat kunci `err.<code>` (kamus `ru` dan `en`,
  `{param}` sebagai pengganti). Jangan menulis `ApiError` tanpa `code`. **Jangan beri `code` pada pesan yang
  hanya berupa cadangan dari stderr alat** — pakai `code=None if err.strip() else "x.y"` supaya teks asli
  tidak tertimpa. Jangan mencocokkan `e.message` di JS: pakai `e.code`.
- **Kamus tambahan:** selain `static/i18n.js`, ada `static/i18n-ext-<area>.js` (`Object.assign(I18N.ru, {...})` dan
  `Object.assign(I18N.en, {...})`) — satu berkas per area supaya pekerjaan paralel tidak bentrok. Cek paritas
  dan kunci kosong dengan **`node check-i18n.js`** (wajib lulus: jumlah kunci `ru` = `en`).
- **Galat alat yang tidak ada** (brew, docker, …) → `FileNotFoundError` jadi `tool_missing` (kartu "Tidak
  ditemukan alat" dengan tautan ke Persiapan Sistem); keluaran JSON kosong/rusak dari alat → pakai
  `core.loads_or(teks, default)`, bukan `json.loads` langsung (jatuh jadi `bad_output`, bukan "Internal error").
- Katalog paket (`svc.py`) berbahasa Rusia di sumbernya; terjemahan EN-nya per teks di `static/i18n-ext-catalog.js`
  (kunci `cd.<teks Rusia>`; `catTr()` di `packages.js`). Tambah entri katalog baru → tambah juga terjemahannya.


## Keputusan arsitektur — FINAL, jangan diragukan lagi

Ini sudah diputuskan pemilik project. Jangan mengusulkan ulang alternatif yang sudah ditolak di sini.

1. **Panel harus bisa dipasang di macOS yang BARU diinstal, tanpa apa pun sebelumnya.**
   Itu tujuan produknya: satu panel yang menyiapkan dan mengendalikan seluruh Mac. Kalau ada langkah
   yang tidak bisa dilakukan dari dalam panel, langkah itu wajib dicatat sebagai **pengecualian yang
   disengaja** beserta alasannya (mis. dialog Apple untuk Command Line Tools, Apple ID untuk Xcode).
2. **Runtime Python DI-BUNDEL, bukan diambil dari sistem.** Panel tidak boleh bergantung pada Python
   bawaan macOS (di macOS bersih tidak ada Python sama sekali; Command Line Tools hanya memberi 3.9).
   `install.sh` mengunduh CPython standalone dari `python-build-standalone` (~25 MB, sudah terbukti
   tersedia: `cpython-3.12.x+<tanggal>-aarch64-apple-darwin-install_only.tar.gz`) ke
   `~/.service-admin/runtime/python/`. **Jangan menambah ketergantungan baru pada alat sistem.**
3. **Launcher tidak boleh membutuhkan Command Line Tools.** Pakai `/usr/bin/osacompile` (bagian dari
   macOS), **bukan `swiftc`** — `swiftc` berasal dari CLT dan itu justru prasyarat yang mau dihilangkan.
   Yang boleh diasumsikan ada di macOS bersih hanya: `curl`, `tar`, `osacompile`, `open`, `osascript`.
4. **"Tanpa kostum" lebih penting daripada cepat.** Kerjakan langsung ke bentuk yang benar; jangan
   menambah jembatan sementara (mis. menggantungkan diri pada Python 3.9 bawaan Apple) yang nanti harus
   dibongkar lagi.
5. **`tomllib` DIIZINKAN punya jalur cadangan.** Pemilik project memberi izin eksplisit: tulis
   `tomllib` → `tomli` → nonaktifkan validasi TOML dengan pesan yang jelas. Ini murni pertahanan untuk
   kasus seseorang menjalankan `python3 server.py` dengan interpreter lama; jalur utama tetap Python
   yang dibundel. Jangan menghapus validasi TOML-nya, cukup mundur dengan pesan yang jujur.
   Saat ini hanya `files.py` (3 baris: `import tomllib`, `tomllib.loads`, `tomllib.TOMLDecodeError`)
   yang membutuhkan 3.11 — tidak ada fitur 3.11+ lain di seluruh repo.
6. **Verifikasi instalasi/first-run dilakukan di VM macOS bersih (tart), bukan di mesin kerja** (keputusan
   pemilik project, diperbarui). Rinciannya di `docs/roadmap.md` bagian "Verifikasi di macOS bersih".

## Apa ini

**Mac Service Admin**: dashboard web lokal untuk mengelola dev environment macOS (Apple Silicon):
Homebrew (paket + `brew services`), Docker/OrbStack, Laravel Herd, versi bahasa (PHP, Node, Python, Go,
Rust, Java, Ruby, …), file konfigurasi (zsh, `/etc/hosts`, SSH, Git, php.ini, `.env`), dan statistik
sistem (CPU, RAM, suhu, GPU, baterai).

```bash
python3 server.py            # http://127.0.0.1:8765  (--port untuk ganti)
```

## Aturan utama

- **Stdlib saja, tanpa dependensi.** Backend Python murni (http.server, subprocess, ctypes); frontend
  vanilla JS/CSS tanpa build step, tanpa CDN (ikon disimpan lokal di `static/icons.js`).
- **Keamanan (jangan dilonggarkan):**
  - Server hanya bind `127.0.0.1`; header `Host` wajib `localhost`/`127.0.0.1` (anti DNS rebinding).
  - Semua POST wajib header `X-Requested-With: service-admin` (anti CSRF). `api()` di `app.js` sudah
    mengirimnya.
  - Perintah dijalankan sebagai **list argumen, tanpa shell**. Validasi setiap input (nama paket,
    versi, id container, hostname, port) dengan regex sebelum dipakai.
  - File hanya boleh dibaca/ditulis lewat **registry** (`files.py`, `svc.service_spec`, compose dari
    `docker compose ls`), jangan pernah path bebas dari browser.
  - Jangan kirim rahasia ke browser tanpa perlu: `herd sites --json` berisi isi `.env`, jadi field
    `env` dibuang di `herd_info()`. Env container disamarkan di UI (`SECRET_RE` di `dockerx.py`).
  - File milik root (`/etc/hosts`, `/etc/resolver/*`) ditulis lewat
    `osascript ... with administrator privileges` (dialog password macOS), bukan sudo.
- **Sebelum menimpa file user: validasi + backup.** Pola yang dipakai: validasi dulu (atau tulis →
  validasi → rollback kalau gagal), backup ke `~/.service-admin/backups/...`, simpan 20 versi.
- Aksi yang merusak (uninstall, hapus volume, prune, down) wajib `data-confirm` di tombolnya.
- **FASE 1 = hanya baca** (pengecualian sempit: `projects.py` boleh menulis `~/.service-admin/projects.json` — registry & preset — lewat `registry_add/registry_remove/preset_set`; git tetap hanya baca). `profiles.py`, `mobile.py`, `projects.py`, dan `agents.py` **tidak boleh**
  memasang, mengunduh, mengubah, atau menghentikan apa pun. Kalau nanti ditambah tombol aksi
  (mis. `brew install`, `xcode-select -s`, `git worktree add`, menjalankan agen), aksi itu wajib:
  lewat `start_job`/`start_steps`, punya `data-confirm` di UI, dan tidak boleh menyentuh sistem tanpa
  permintaan eksplisit user. Jangan pernah menaikkan `--no-rename`/timeout diam-diam untuk "mempercepat".
- **Jangan menambah dependensi.** Fase 1 sengaja tidak memakai satu pun paket baru.
- **Panduan untuk manusia (instruksi + screenshot) disimpan di `manuals/`** (lihat `manuals/README.md`); screenshot hanya dari sistem asli (VM tart/Mac), tanpa data pribadi, format JPEG yang sudah dipangkas. Jangan memasukkan jendela/aplikasi pengguna lain ke screenshot.
- **Rencana kerja ada di `docs/roadmap.md`.** Sebelum mengerjakan fitur baru, periksa dokumen itu:
  kalau itemnya belum ada di sana, jangan dikerjakan — usulkan dulu perubahan dokumennya.
  Urutan Fase 2 mengikat: **2.0 Bootstrap mandiri → 2.1 Halaman Persiapan Sistem → 2.2 Jejak audit**,
  dan baru setelah ketiganya selesai boleh ada aksi yang mengubah sistem (2.3 dan seterusnya).
  Audit bukan pelengkap: panel akan memasang Homebrew dan meminta sandi admin, jadi tanpa jejak audit
  tidak ada cara menjawab "apa yang tadi dijalankan?".

## Aturan dari pengujian di macOS bersih (VM tart)

- **Menyalin repo ke VM: JANGAN lewat `tar` dari folder bersama** (`/Volumes/My Shared Files`) — diam-diam terpotong dan VM
  menerima salinan tidak lengkap. Pakai aliran SSH (`tar -cf - . | ssh … tar -xf -`) lalu **bandingkan `shasum` semua berkas**.

- **`/usr/bin/git`, `python3`, `make`, `xcrun`, dll. tanpa CLT = stub yang membuka dialog Apple.**
  Jangan pernah memanggilnya langsung. `core.run()` sudah menolak menjalankannya (lihat `CLT_SHIMS`,
  `clt_stub()`); `Popen` langsung di job tidak terlindungi, jadi cek `has_clt()` sendiri.
  `install.sh` juga hanya memanggil `git` kalau `xcode-select -p` berhasil.
- **LaunchAgent memicu dialog izin macOS** (Documents, Desktop) pada pemakaian pertama; request yang
  menyentuh folder itu menggantung sampai user menekan Izinkan. Itu bukan bug panel.
- Pengujian instalasi dilakukan di VM `clean-mac` (tart), bukan di mesin kerja — lihat roadmap
  "Verifikasi di macOS bersih". Disk VM 50 GB tidak cukup untuk dialog CLT Apple (butuh ~24 GB bebas).

## Yang sudah terbukti di mesin nyata (jangan diulang salah)

Empat hal ini ditemukan lewat pengukuran di Mac asli, dan semuanya mudah terulang:

1. **`python3` bisa 3.9.** `files.py` mengimpor `tomllib` (≥ 3.11). Di Mac yang Python 3.11+ hanya ada
   di Homebrew, `python3 server.py` gagal dengan `ModuleNotFoundError: tomllib`. Uji dulu `python3 -V`;
   interpreteter eksplisit: `/opt/homebrew/opt/python@3.12/bin/python3.12 server.py`.
   **Arah perbaikannya sudah diputuskan** (lihat "Keputusan arsitektur"): runtime Python di-bundel,
   jadi masalah ini hilang di jalur utama; jalur cadangan `tomllib → tomli` tetap ditulis sebagai
   pertahanan. Jangan menambah ketergantungan baru pada Python sistem untuk "menyelesaikan" ini.
2. **`git` paralel saling mengunci.** `git status`/`git diff` biasanya mengambil `.git/index.lock`.
   Kalau beberapa perintah baca dijalankan bersamaan di repo yang sama (dan `project_detail` memang
   menjalankan 9 sekaligus), satu perintah bisa menggantung **30 detik**. Karena itu `projects.git()`
   selalu memakai `GIT_OPTIONAL_LOCKS=0` (dan `GIT_PAGER=cat`, `GIT_TERMINAL_PROMPT=0`).
3. **`git diff` tanpa `--no-renames` itu mahal.** Deteksi rename memaksa git membaca isi setiap berkas
   yang berubah: diukur **10–25 detik** vs **0,03 detik** dengan `--no-renames`. Semua diff di
   `projects.py` memakai `--no-renames`. Efek sampingnya hanya: rename tampil sebagai hapus+tambah.
4. **`--stat`/`--numstat` tetap lambat walau tanpa rename**, karena tetap menghitung baris. Karena itu
   daftar berkas di halaman detail memakai `--name-status` (0,06 dtk), dan statistik baris (+/-) hanya
   dihitung saat user menekan tombolnya (`/api/projects/diffstat`, timeout 90 dtk).

Selain itu:

- **`flutter --version` menulis ke cache SDK.** Panel **tidak pernah** menjalankannya; versi dibaca dari
  `bin/cache/flutter.version.json`. Kalau butuh versi Flutter di kode baru, pakai jalur berkas itu.
- **Kartu daftar project sengaja tidak memuat ringkasan git di server.** Satu repo besar bisa menahan
  seluruh halaman. `/api/projects` hanya mengembalikan path (0,01 dtk), lalu browser memanggil
  `/api/projects/summary?path=…` per kartu secara paralel dan mengisinya sendiri. Jangan menyatukan lagi.
- **`xcrun simctl` menyalakan CoreSimulatorService** kalau belum jalan. Itu layanan bawaan Apple, bukan
  perubahan setelan — tapi tetap bukan "nol efek samping", jadi jangan panggil di loop ketat.
- **`ps` bisa diblokir** (sandbox, kebijakan MDM). `core.ps_snapshot()` dan `agents._read_ps()`
  mengembalikan kosong kalau `ps` gagal; halaman AI Sessions menampilkan peringatan, bukan error.

## i18n

**Dua bahasa saja: `ru` (default) dan `en`.** Kamusnya di `static/i18n.js`, tanpa build step.
Kedua kamus harus **lengkap sama** (jumlah kuncinya identik). Uji dengan:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('static/i18n.js','utf8');
const i=s.indexOf('const I18N = {')+13;const I=eval('('+s.slice(i,s.indexOf('\n};',i)+2)+')');
const k=Object.keys(I.ru);for(const [l,d] of Object.entries(I))console.log(l,k.filter(x=>!(x in d)));"
```

- HTML statis: `data-i18n` (innerHTML), `data-i18n-title`, `data-i18n-ph`, `data-i18n-aria`, `data-i18n-label`.
- JS: `t("kunci")`, dengan pengganti `t("kunci", {n: 3})` → `{n}` di kamus.
- Fallback: kamus aktif → `I18N.ru` → kunci itu sendiri. Tidak ada bahasa ketiga sebagai cadangan.
- Judul halaman: `tabs.<key>.titleKey` (mis. `"nav.projects"`), bukan `title` yang berisi prosa.
- Setelah `setLang()`, halaman aktif dirender ulang otomatis dan `updatePageTitle()` dipanggil ulang.
- Semua halaman (termasuk packages/config/docker/langs/dashboard/app) sudah memakai `t()`; teks yang dihitung
  di modul harus dicari saat render (di dalam fungsi), bukan disimpan di konstanta tingkat-modul.

## Struktur

| File | Isi |
|---|---|
| `server.py` | HANYA HTTP handler + routing (`GET_ROUTES` / `POST_ROUTES` di bawah file); logika domain ada di modul (`brewsvc`, `herdphp`, `uihelpers`, `dockerx`, `files`, …). Jangan menaruh logika baru di server.py |
| `brewsvc.py` | Службы (`brew services`) и пакеты Homebrew: список, поиск, действия (изменения пакетов исполняет `operations.run_package`). Вынесено из server.py |
| `herdphp.py` | Herd, версии PHP, Node/nvm, создание Laravel-проекта, `EDITORS`. Вынесено из server.py; изменяющие функции вызывает и каталог операций |
| `uihelpers.py` | Боковая панель (`nav_info`), чтение файла для диагностики, открыть Terminal/Activity Monitor, детали проекта |
| `ops_system.py` | Каталог операций над системой (службы, PHP/Herd/Node, языки, Docker, файлы) — регистрируется в `operations.OPS`; исполняет те же функции, что страница; агентам НЕ открыто |
| `core.py` | Helper bersama: `run`/`output`, `ApiError`, state (`~/.service-admin/state.json`), **job** background (`start_job`, `start_steps` multi-langkah, `list_jobs`), backup & blok `.zshrc`, `set_shims`/`set_env`, `shell_probe` |
| `stats.py` | Statistik sistem tanpa sudo: CPU per core (Mach `host_processor_info`), suhu (IOKit HID via ctypes), GPU/baterai (`ioreg`), RAM (`vm_stat`), sampler background |
| `runtimes.py` | Deteksi bahasa (`LANGS`) + manajemen Python/Go/Rust/Java/Ruby |
| `svc.py` | Detail service (config file + validator per service), katalog & 100 rekomendasi paket, panel cloudflared |
| `files.py` | Editor file konfigurasi: registry `STATIC` + resolver, php.ini, `.env` project; validator per jenis |
| `dockerx.py` | Docker: overview, stats, disk, inspect, logs, exec console, `docker run`, compose (baca/validasi/simpan), context remote |
| `ptyterm.py` | Terminal sungguhan: sesi `zsh -l -i` di PTY (`pty.fork`), output long-poll (`/api/pty/read`, base64), input/resize/kill lewat POST, plus `peek` (pratinjau tanpa menggeser offset) |
| `setup.py` | **Persiapan Sistem** (`#setup`): status CLT/Homebrew/Git/Python bawaan + instalasi CLT (dialog Apple, panel menunggu) dan Homebrew (installer resmi, `SUDO_ASKPASS` → dialog password macOS). Lewat `start_steps`, tercatat di audit |
| `snapshots.py` | Snapshot lingkungan (`#snapshots`): `~/.service-admin/snapshots/*.json` (brew + Brewfile, runtime, Xcode, Flutter/Android, profil) + perbandingan dua snapshot / "sekarang". Tidak mengubah sistem |
| `audit.py` | Jejak audit JSONL `~/.service-admin/audit.log` (0600, rotasi). Setiap entri punya `by` (`panel`/`agent:<nama>`/`system:<apa>`) dari `audit.INITIATOR` (ContextVar) — thread baru harus meneruskannya (job menyimpan `by` saat start). Semua POST + akhir job; rahasia disamarkan, input terminal TIDAK dicatat. Halaman Audit: `static/audit.js` (`#audit`, `GET /api/audit`: filter aksi/hasil/tanggal) |
| `profiles.py` | Katalog profil instalasi (Fondasi/AI/Flutter/iOS/Backend) + satu detektor per alat. Deteksi hanya baca; `plan()` menyusun rencana tanpa mengubah apa pun, `install()` menjalankannya lewat `start_steps` (satu job `profile-install` sekaligus, snapshot sebelum/sesudah). Tipe di katalog harus cocok dengan Homebrew (`flutter`, `codex` = cask) — uji dengan `brew info --json=v2` |
| `mobile.py` | Xcode & simulator (`xcrun simctl`), Flutter/FVM, Android SDK, CocoaPods, fastlane. **Hanya baca** |
| `mobile_ops.py` | Aksi atas toolchain mobile (`POST /api/mobile/op`): Xcode select/first-launch, simulator boot/shutdown/erase/screenshot, Flutter/FVM/pod, Android sdkmanager. `build()` murni (tidak menjalankan); eksekusi lewat `start_steps`; aksi admin lewat dialog password macOS. Browser hanya menyebut id dari registry server |
| `projects.py` | Repo git: pemindaian folder, status/branch/worktree/log/diff, `gh` untuk PR/issue/CI, registry & preset. **Git: hanya baca** |
| `gitops.py` | Aksi tulis Git (`POST /api/git/op`): fetch/pull(--ff-only)/push(tanpa --force), branch, stash, add/commit, worktree (hanya di `~/Worktrees`), discard/clean (wajib ketik nama project di SERVER). Id & file divalidasi terhadap keadaan repo; `build()` murni |
| `agents.py` | Pemantauan sesi AI: memetakan proses agen ke sesi PTY (butuh `pid` dari `ptyterm.list_sessions`) + CPU/RAM per pohon proses. **Hanya pantau** |
| `operations.py` | **Katalog operasi tunggal** (Fase 4.1): 86 operasi — level L1–L4 + eskalasi, skema parameter, syarat (`REQUIREMENTS`), idempoten, verifikasi, rollback; `plan/verify/execute`. Operasi paket Homebrew dijalankan HANYA lewat `run_package` (server.py hanya membungkus). Operasi baru → daftarkan di sini; katalog dicek dua arah terhadap `gitops`/`mobile_ops` |
| `opschema.py` | Validator skema parameter bersama (gateway agen + operations) |
| `plans.py` | **Rencana + persetujuan** (Fase 4.2/4.4): `propose → approve (dialog macOS) → execute (sekali, hash dicek ulang → `plan.stale`) → verify`. Agen: 6 operasi L2 (`AGENT_OPS`, termasuk `docker.container_control` — hanya engine Docker LOKAL) dan, hanya untuk agen level L3, `AGENT_OPS_L3` (`runner.spawn`, `runner.selftest`) — dialog macOS WAJIB, `auto_approve` mustahil untuk L3, maks 3/jam; persetujuan default = dialog sistem macOS (default button Reject, timeout 110 dtk = tolak, teks lewat argv). `auto_approve` hanya L2, eksplisit + audit. **Jangan tambah operasi ke `AGENT_OPS` tanpa memperbarui roadmap.** Uji dengan `ask_human` & `osascript` palsu — jangan menampilkan dialog asli di mesin kerja |
| `agent_gateway.py` | Gerbang agen AI (Fase 4.0): registry (`agent-registry.json`, hanya hash SHA-256; rahasia di `agents/<id>.token` 0600), tool L1 baca-saja, validasi skema, rate limit 60/mnt, audit dengan identitas agen. **Tidak ada `execute_shell`.** |
| `agent_socket.py` | Unix socket `~/.service-admin/agent.sock` (0600): hanya gerbang agen, bukan HTTP API; path ≤100 byte |
| `mcp_server.py` | MCP stdio (JSON-RPC) — jembatan tipis ke socket; TIDAK menjalankan panel. Uji dengan driver sendiri; **belum diuji dengan klien MCP asli** |
| `cli.py`, `service-admin` | CLI для агентов без MCP (Fase 4.3): тонкая обёртка над `mcp_server.panel_call`, без своей логики; вывод JSON, код 2 = панель недоступна |
| `vm.py` | Драйверы ВМ (Fase 5): `Driver`/`TartDriver` — чтение + `build()` (чистая) и `run_op` для vm.clone/pull/start/stop/snapshot/delete через `start_steps`. Агентам НЕ открыто (не добавлять в `plans.AGENT_OPS` без обновления roadmap). Тест: клонируй `clean-mac` и работай только с копией; `TART_HOME` задай явно, если меняешь HOME |
| `runners.py` | CI-раннеры (Fase 5): адаптеры провайдеров `github`/`gitea` (установка ФАЙЛОВ, sha256 из релиза), реестр источников (`runner-sources.json`: провайдер + любой URL + область) и токены в файлах 0600 (`runner-tokens/`, в API/аудит не попадают). Без регистрации/запуска — это L3 + изоляция в ВМ, следующие шаги |
| `ci_api.py` | Клиенты API Gitea/Forgejo и GitHub по токену доступа: регистрационный токен, список/удаление раннеров, репозиторий/файл/запуск для самотеста. Редиректы ЗАПРЕЩЕНЫ (токен не уходит на другой хост), ошибки без тел ответов (нет секретов). GitHub-часть не проверена на настоящем GitHub |
| `runner_spawn.py` | Раннер по требованию (L3): клон ВМ-основы → ephemeral-раннер на ОДНО задание → ВМ всегда удаляется. Токен — только через stdin в файл 0600 гостя, из вывода вырезается. Тест — только на копии `clean-mac` и недоступном сервере/токене-пустышке; реальную регистрацию на Gitea/GitHub ВЛАДЕЛЬЦА не запускать — тестируй на СВОЕЙ временной Gitea (скачать `dl.gitea.com`, sha256, SQLite, слушать только LAN-адрес хоста, удалить после). Агентам уровня L3 — только через план + обязательный диалог |
| `backups.py` | Cadangan (`#backups`): `git bundle --all` per repo (dedupe via fingerprint ref, tanpa worktree), arsip `tar.gz` folder data + data panel (tanpa runtime/tmp/screenshots), simpan N terakhir, verifikasi (**`git bundle verify` TIDAK cukup — lolos bundle terpotong; pakai clone+fsck**), jadwal (thread, tiap 5 mnt), restore HANYA ke folder baru `~/Restored/…` (cek `..` di arsip). Tujuan: folder lokal/`/Volumes`, tanpa cloud |
| `runs.py` | Test/build dari preset project + riwayat (`~/.service-admin/runs.jsonl`, `runs/*.log`) + GitHub Actions (`gh workflow run`, wajib ketik nama project). Perintah HANYA dari preset dan harus lolos `projects.runnable_argv` (allowlist `RUN_TOOLS` + `./skrip` project; tanpa `-c/-e`); timeout 30 menit, process group dibunuh. Uji gh dengan **gh palsu** (`projects.GH`), jangan pernah memanggil gh asli untuk menjalankan workflow |
| `agent_tasks.py` | Tugas agen (`~/.service-admin/agents.json`): "tugas baru" = worktree (`gitops`, `~/Worktrees`) + agen di PTY; stop/start, kirim teks ke sesi (eksplisit), perubahan/diff relatif `base_sha`. Agen hanya dari yang terpasang, tanpa flag "skip permissions"; status busy/idle = HEURISTIK. **Uji dengan agen PALSU** — di stand uji `/opt/homebrew/bin` ada di awal PATH sehingga `claude` asli tertangkap duluan: pakai nama agen yang tidak terpasang (mis. `aider`) |
| `static/index.html` | Shell: sidebar, header (tombol terminal + tema), dialog, panel kanan (tab Terminal / Proses) |
| `static/app.js` | Core UI: `api()`, `btn()`, `toast`, router hash, `handlers` (event delegation), panel (`panelOpen`/`panelView`), job runner (`runJob`), tema, PHP/Node/Herd |
| `static/terminal.js` | Tab Terminal: xterm.js per sesi, polling output, batching input, resize (FitAddon), reattach setelah refresh, `window.runInTerminal(cmd, cwd)` |
| `static/vendor/` | xterm.js + addon fit/web-links (MIT), disimpan lokal, jangan diganti CDN |
| `static/packages.js` | Halaman Paket & Service + detail service (`#service:<nama>`) + cloudflared |
| `static/docker.js` | Semua halaman Docker (`#docker:<sub>`) + pembuat compose + dialog buat container |
| `static/langs.js` | Halaman grup **Bahasa** (`#langs`, kartu 3 kolom + bahasa yang bisa di-install), halaman detail `#lang-<key>` (nav: `langs`), versi/status di sidebar (`applyNav`/`refreshNav`) |
| `static/config.js` | Halaman File konfigurasi (`#config:<id>`) |
| `static/dashboard.js` | Dashboard statistik + `lineChart()` (SVG, dipakai juga oleh docker.js) |
| `macapp/launcher.applescript`, `macapp/AppIcon.icns`, `install.sh`, `fetch-python.sh` | Peluncur `Service Admin.app` (applet AppleScript, dikompilasi `/usr/bin/osacompile` tanpa CLT; nyalakan server via LaunchAgent/fallback lalu buka browser lewat `/usr/bin/open`), installer LaunchAgent `local.service-admin`, dan pengunduh Python bawaan ke `~/.service-admin/runtime/python/`. `macapp/makeicon.swift` hanya untuk membuat ulang ikon (butuh `swift`, tidak dipakai saat instalasi). Server dari launchd butuh izin macOS *Files & Folders → Documents* karena project ada di `~/Documents` |
| `static/icons.js` | Logo Simple Icons (CC0) + `logoSvg()` / `logoFor(formula)` |

## Pola kode

**Backend**
- Endpoint baru: tulis fungsi `(q)` untuk GET (dict query) atau `(body)` untuk POST (dict JSON), lalu
  daftarkan di `GET_ROUTES`/`POST_ROUTES`. Lempar `ApiError(pesan, HTTPStatus.X)` untuk error ke UI.
- Perintah lama (install, compose up, `laravel new`) → `start_job(label, cmd, kind)` atau
  `start_steps(label, [(judul, cmd|callable, opsi)], kind)`, kembalikan `{"job": id}`. Satu `kind`
  hanya boleh satu job berjalan.
- Tool di PATH user (rustup, pipx, nvm, …) bisa tidak ada di PATH server (misalnya saat jalan dari
  LaunchAgent). Resolve lewat `shell_probe` / `runtimes.tools()` (zsh interaktif) dan pakai path absolut.
- Pilih versi default: shim symlink di `~/.service-admin/bin` per bahasa (`set_shims(lang, {...})`)
  atau env di `~/.service-admin/env.zsh` (`set_env`, dipakai JAVA_HOME). Keduanya dimuat oleh satu
  blok di **paling bawah** `~/.zshrc` (`ensure_zshrc_block`).

**Frontend**
- Halaman = `tabs.<key> = { load(silent), interval?, nav?, title?, logo?, leave? }` (`nav` = item sidebar yang disorot, `title` = judul header bila berbeda); route `#key` atau `#key:param`
  (`this.param`). Alias lama: `#services`/`#apps` → `packages`, `#zsh` → `config`.
- **Halaman baru WAJIB memisahkan `load()` (ambil data) dari `render()` (gambar dari data).**
  `load()` menyimpan responsnya ke properti instance (mis. `this.data = await api(...)`) lalu memanggil
  `this.render()`; `render()` menggambar ulang dari properti itu **tanpa satu pun request jaringan**.
  `setLang()` memanggil `current.render()` kalau ada, dan hanya jatuh ke `load()` kalau tidak ada.
  Kalau ini dilanggar, ganti bahasa akan menunggu request — halaman Toolchain Mobile pernah tertahan
  belasan detik karena `xcrun simctl`, padahal datanya tidak berubah. Pola yang sama sudah dipakai
  `tabs.langs` (`load()` → `refreshNav()` → `render()`).
  Data yang diambil bertahap (ringkasan git per repo, project Flutter/FVM, blok GitHub) harus
  **di-cache di properti instance dan digambar ulang dari cache** — jangan di-fetch ulang saat ganti bahasa.
- Tombol: `btn(label, "aksi", {data}, "go|primary|danger")` + `handlers.aksi = async (dataset, el) => …`.
  `data-confirm` otomatis memunculkan konfirmasi.
- Proses panjang: `runJob(api("/api/…", body), onDone)`. Progres tampil di panel kanan, tab **Proses**
  (ikon terminal di header, titik merah saat berjalan). Tab **Terminal** adalah shell PTY sungguhan;
  program interaktif (claude, vim, tinker) harus lewat sini, bukan lewat job (job tidak punya TTY).
- Warna selalu lewat token CSS (`--bg`, `--card`, `--text`, `--series-1..4`, …). Tema: terang/gelap/
  sistem via `html[data-theme]`; token gelap didefinisikan di dua tempat (media query + `[data-theme="dark"]`).
- Selalu `esc()` untuk data dinamis di template string.

## Verifikasi

- Lint Python: `pipx run pyflakes *.py`. Cek syntax JS: `node --check static/*.js`.
- Tes backend: import modul langsung (`python3 -c "import dockerx; print(dockerx.overview({}))"`).
  Untuk fungsi yang menulis `~/.zshrc`/shim/state, **patch konstanta ke HOME sementara**
  (`core.HOME`, `core.DATA_DIR`, `core.SHIM_DIR`, …) supaya file asli user tidak berubah.
- Tes PTY: `import ptyterm`, `new_session` → `write(..."perintah\r")` → `read` (base64) → `kill`. Kalau
  menjalankan `claude` untuk tes, keluar dengan `\x03` lalu `kill` sesi.
- Tes UI: tidak ada Chrome; pakai Firefox headless
  `/Applications/Firefox.app/Contents/MacOS/firefox --headless --profile <dir> --no-remote --window-size=1300,1100 --screenshot out.png file://…`.
  Screenshot diambil saat event `load`, jadi buat halaman harness yang me-*stub* `window.fetch` dengan
  JSON hasil API asli dan jalankan aksi uji langsung di chain `initRuntimes().then(route).then(...)`
  (bukan `setTimeout`). Matikan transisi CSS kalau perlu (`#job{transition:none}`). Untuk konten yang
  dirender async (xterm.js), tahan event `load` dengan `<img>` dari server kecil yang sengaja lambat.
- Setelah mengubah `.py`, restart server (`kill $(lsof -ti tcp:8765)`, lalu jalankan lagi). File statis
  dikirim dengan `Cache-Control: no-cache`, jadi cukup refresh browser.

## Hal yang perlu diingat

- Shell user **zsh**: `$VAR` tidak di-word-split (pakai array `(${=VAR})`), dan `timeout` tidak ada.
- Jangan menjalankan aksi yang mengubah sistem user saat tes (brew install/uninstall, `herd use`,
  `nvm alias`, simpan `/etc/hosts`, dialog Finder/admin) tanpa diminta. Kalau perlu container/project
  uji, buat di scratchpad lalu bersihkan (`docker rm -f`, `compose down -v`, `rmi` image yang baru di-pull).
- Data persisten aplikasi: `~/.service-admin/` (`state.json`, `bin/`, `env.zsh`, `backups/`, `logs/`,
  `php-shims/`).
- Herd gratis tidak punya `services:*` (butuh Herd Pro). CLI Herd ada di
  `~/Library/Application Support/Herd/bin` (`herd`, `php84`, `composer`, `laravel`).
