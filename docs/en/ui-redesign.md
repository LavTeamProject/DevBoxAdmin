# Panel UI update plan (Phase 10)

Status: **a plan, waits for the owner's decision.** The menu and pages are not changed until it is approved. Already done (U1): the "who can approve plans" switch moved to "Approvals", and the "on this computer" agent connection wizard explains the steps. The plan went through an independent check (a critic verified the facts against the code); the corrections are included below.

## 0. The owner's decisions (2026-10-15)
1. The menu map (5 groups) is accepted ("seems fine"); the owner asked to check against similar products (section 11).
2. **Node — through Homebrew only** (a single manager). Consequence: Homebrew gives only **versioned formulae** (`node@20`, `node@22`, …) and drops unsupported ones; exact old versions need another mechanism — see "Old versions" below and question 1.
3. **There will be no roles** ("roles are not needed, there are categories where things are grouped"): categories are the menu groups (Environment, Development, AI agents, Machines & data, System). There is no "who are you" choice; "I want this" and the cards of future roles are cancelled.
4. **Old versions:** the owner expects to install not only the latest but also **old versions** of tools (Python, Node, PHP, Flutter, Go…). This is part of stage U3: each language gets a list of available versions (including old), "install", "make main", "remove".
5. We start with U2 ("probably").

## 1. What is wrong now (verified against the code)

The menu has 17 items in four groups named after "technology", not after tasks:

| Group | Items | Problem |
|---|---|---|
| Monitor | Dashboard, System setup | "Setup" is a first-run step, not monitoring |
| Development | Projects, AI sessions, Mobile toolchains, Install profiles | "Profiles" install tools, "Mobile" manages state (Xcode select, simulators, FVM, sdkmanager), but "Mobile" has no "install" link when something is missing (`mobile.js:181`) |
| Manage | Packages & services, Docker, Herd, Languages | Herd is a **site manager** (linking folders, proxies, HTTPS, PHP per site, logs, "new Laravel app"), not a language; PHP/Node version pages already live as separate pages inside "Languages" |
| Configuration | Files, Agent connections, Backups, VMs, Runs, Snapshots, Audit | A junk drawer: copies, VMs and runs are not "configuration" |

Real duplicates and "one function in different corners":
- **Flutter/Dart** is both in "Languages" (`runtimes.LANGS`) and in "Mobile toolchains".
- **Runs** is a separate page although the project card already has run buttons, history and workflows (`projects.js`).
- **Sites and domains** are scattered: sites in Herd, cloudflared tunnels only inside `#service:cloudflared`, `/etc/hosts` in "Files", the restart after editing php.ini in Herd or on the service page.
- **Snapshots and backups** are two items for one idea, but **neither rolls back**: snapshots are only compared and exported to a Brewfile, backups restore only into a new folder.
- **Logs:** "Audit", the "Processes" panel, the run history, the agents log.
- **The profile catalog duplicates itself:** gh and lazygit in two profiles, clt, CocoaPods/fastlane (Flutter and iOS); the Backend profile has **no** PHP, Composer, Herd or Node; Node in a profile is installed as `brew node@22` while the Node page manages nvm — two version managers conflict (a profile shows ✓, the page says "no nvm"). Profiles are flat lists with no "choose one language".
- Two different sub-tab mechanisms (`docker.js`, `connect.js`), no common page template; no frontend tests (Python only).
- No "attention center" (what needs action).
- Already fixed: the "Packages" page failing as a whole (blocks now load independently); agent approvals are now in one section. Remaining: the "Agent connections" page loads five requests in a row every 5 s.

## 2. Principles (as in good web panels: ISPmanager, Plesk, cPanel)
1. **One task — one place.** A setting lives on one page; other pages only link. No copies.
2. **A menu by objects and tasks**, with no one-item groups.
3. **One page template:** title + status chips + a primary action; tabs; "list → card"; one confirmation for danger; **empty states and error blocks are part of the template** ("what to do next", "Retry").
4. **An entry by task:** "Getting started" (one first run: system preparation → tool sets). No roles — categories define the menu groups.
5. **Honest names:** a page is named after what it does (no "rollback" if there is none).
6. **A failure of one part does not break the page.**
7. **Protection-weakening actions are visible and explained.**

## 3. Target menu (5 groups, 15 items, no one-item groups)

```
Overview                      health, "needs attention"
Getting started               system preparation + tool sets (one first-run flow)
─ Environment ─────────────
  Languages & versions        Python, Node (nvm), PHP (versions), Go, Rust, Java, Ruby, Dart, Flutter…: one layout
  Packages & services         Homebrew/apt: installed, unneeded, updates; services
  Containers                  Docker/OrbStack
  Mobile development          Xcode, simulators, FVM, Android SDK, CocoaPods, fastlane (+ "install" for what is missing)
─ Development ─────────────
  Projects                    git, runs and history (was "Runs"), workflows, worktrees
  Sites & domains             Herd: sites, proxies, HTTPS, PHP per site, logs + cloudflared tunnels + hosts
─ AI agents ───────────────
  AI sessions                 agents in the terminal by project
  AI access                   Overview · Agents · Approvals · Operators · Channels · Catalog
─ Machines & data ─────────
  Machines & runners          virtual machines, CI runners, checks
  History & copies            state snapshots (compare, Brewfile) + backups (restore into a new folder)
─ System ──────────────────
  Config files
  Journal                     audit + job log (tabs; project runs only in "Projects", a filter link here)
  Settings                    language, theme, panel updates, network/proxy, "about"
```
Old → new: Dashboard→Overview · System setup+Profiles→Getting started · Herd→"Sites & domains" (PHP versions stay in "Languages") · Mobile toolchains→Environment/Mobile · Runs→Projects · Snapshots+Backups→History & copies · VMs→Machines & runners · Agent connections→AI access · Audit→Journal. Every old address (`#herd`, `#snapshots`, `#docker:container:…`, `#config:…`, `#service:…`, `#lang-go`, `#projects:…`) keeps working: a redirect that preserves parameters and the highlighted item; links in `manuals/` are updated.

**Postponed (the critic's note — over-engineering at 15 items):** Cmd+K search and an "interface profile" switch. We come back after U6 if the owner still wants them; platform-specific items are already hidden by `data-cap`.

## 4. Page template
- Header: title · status chips · primary action. No more than six tabs, one by default.
- Tables: the same columns ("name · version · origin · size · actions"), filters on top.
- Blocks load independently; a block error is a frame with text and "Retry"; an empty state comes with a next-step button.
- One confirmation window for a dangerous action, listing what is affected.
- Built in vanilla JS (the helpers `roBanner`, `kvList`, `chipList` already exist), keeping the rule "`load()` separate from `render()`" — otherwise changing the language breaks. The sub-tabs of `docker.js` and `connect.js` move to one shared mechanism.

## 5. "Getting started" and tool sets
No roles. "Getting started" is two tabs: **system preparation** (Homebrew, git, the panel's Python) and **tool sets** (was "Install profiles") — a flat list of ready sets: Foundation, AI agents, Flutter, iOS, Backend (common), Backend: PHP/Laravel, Node.js, Python, Go, Web. A set has a "N of M ready" checklist, "Install" on an item and "Install everything missing" (confirmed with the list). The `profiles.py` catalog (stage U4a) is already rewritten: each tool is described once; DB services show "running/stopped"; item states: install · manual · later (a large download) · needs administrator · needs consent (the Android SDK license; the Xcode license and Apple ID are done by a human, the panel never enters a password). Flutter is detected by files: the panel **does not run `flutter --version`/`flutter doctor`**. Limits shown in the UI: one set installs at a time; cask apps may trigger the administrator password window; the detector does not see GUI programs and manual items.

## 6. Cross-cutting
- **Attention center:** a block on "Overview" and an icon in the header: a plan waits for approval, updates exist, a service is down, low disk space, a token expires. The data comes from **a separate cacheable request** (the brew outdated list is slow and needs the network), not from the dashboard's two-second poll.
- **RU/EN glossary:** one word — one concept ("plan", "operator", "agent", "service", "snapshot", "copy").
- **Responsiveness and accessibility:** focus, contrast, keyboard; a narrow screen (the panel is opened from a phone through a tunnel).
- **Linux:** the menu is built by capabilities; macOS-only items are hidden, no Xcode items in checklists.

## 7. Stages
Each ends with: a run on a real system → before/after screenshots → independent review → fixes → a note in `docs/unverified.md` → a commit. **Acceptance criteria for every stage:** `node check-i18n.js` passes; every old address opens; every page renders when one of its requests fails; the number of clicks for the 10 scenarios (section 8) is measured before and after; screenshots through a stubbed harness (a headless browser, as in CLAUDE.md).

| Stage | What | Estimate |
|---|---|---|
| **U0** | Glossary, the "where is what" map (this document), measuring the 10 scenarios "before" | 1 day |
| **U1** ✅ | The "who can approve" switch in "Approvals"; the "on this computer" agent wizard | done |
| **U2** 🔶 | **Done:** the new menu in 5 groups, the composite pages "Getting started" and "History & copies" (a shared `makeComposite` mechanism), redirects of old addresses preserving parameters, independent and parallel loading on "AI access", shared error/empty/parallel-load blocks (`shell.js`), the smoke harness `tests/ui_smoke.py` (29 addresses, on the real HOME: 29/29). **Remaining:** one look of the header/status chips, moving `docker.js` to the shared sub-tab mechanism, applying the error/empty blocks on the other pages. The stage's original content: skeleton: the new menu and groups, the page template (header, chips, tabs, independent block loading, empty states, error blocks), redirects preserving parameters, moving `docker.js`/`connect.js` to one sub-tab mechanism, speeding up `connect.load` | 5–6 days |
| **U3** 🔶 | **Done (the "versions" part):** the "Versions from Homebrew" card on the Node, Go, Java, Ruby pages — the latest version and the versioned formulae (`node@18…24`, `go@1.22…1.26`, `openjdk@8…25`, `ruby@3.1…3.4`), "Install / Remove"; Node moved to the shared language page (Homebrew, the default is chosen through links in `~/.service-admin/bin`; the old nvm page is replaced); removing Homebrew versions on every install (except the default and the one the panel runs on); Go sees `go@1.xx`. **Remaining in U3:** one layout for all languages (PHP/Herd, Dart/Flutter once), the tabs of "Packages & services", "Mobile development" with "install", "Containers"; exact old versions outside Homebrew (the `mise` question). The stage's original content: "Environment": "Languages & versions" in one layout (versions · default · packages · install/uninstall; Flutter/Dart once), "Packages & services" (tabs: installed · unneeded · updates · services · recommended), "Mobile development" (+ "install"), "Containers" | 6–8 days |
| **U4a** ✅ | **Done:** the profile catalog rewritten (each tool described once, profiles reference it; the gh/lazygit/clt/CocoaPods/fastlane/Node/Python duplicates removed); added the **Web**, **Backend: PHP/Laravel** (PHP, Composer, Herd), **Node.js**, **Python** (uv, pipx) and **Go** profiles; DB services show "running/stopped"; an item "needs consent" (the Android SDK licenses); one Node policy — Homebrew (`node@22`); 8 catalog tests. The stage's original content: extending the profile catalog (Web, Backend with PHP/Node, no duplicates, one Node manager, "is it running", item states) | 3–4 days |
| **U4** | "Getting started": the "Preparation" and "Sets" tabs on the new catalog (one checklist, "install what is missing"); no roles | 2–3 days |
| **U5** 🔶 | **Done:** "Runs" as a tab in "Projects" (`#runs` → `#projects:runs`); project version hint (`project_versions.py`: .nvmrc, package.json, .python-version, pyproject, go.mod, .tool-versions…, picks a versioned Homebrew formula); "Sites & domains" page (Herd sites, dnsmasq/mkcert/nginx/Caddy checklist, hosts, tunnels link; read-only + component install). **Not done:** automatic proxy, resolver and /etc/hosts setup (the panel does not write them), merging the Herd page into "Sites". | 4 days |
| **U6** ✅ | **Done:** attention center — bell in the header and a card on Overview (`/api/attention`: plans awaiting approval, low disk, agent tokens, failed services and outdated brew packages — slow checks are cached). Header quick actions: start/stop service sets. | 2 days |
| **U7** ✅ | **Done:** menu names "Machines & runners" and "History & copies"; "Dashboard" → "Overview". The separate task (restore from a snapshot) is not started. | 3 days |
| **U8** ✅ | **Done:** the approval-mode selector moved into the single "Who can approve" card; "AI access" section in the "AI agents" group. | 2 days |
| **U9** | Polish: responsiveness, accessibility, manuals and screenshots, checking the 10 scenarios with the owner | 3–4 days |
Total ≈ 5–6 weeks. The first visible benefit — U2 + U3.

**Old versions (part of U3).** Sources of the lists: Python — `uv python list --all-versions` (any patch version), Node — Homebrew versioned formulae (`node@N`), PHP — versioned formulae (`php@8.x`) and Herd, Flutter — FVM (`fvm releases`), Go/Rust/Java/Ruby — version managers or Homebrew versioned formulae. If the exact old version is not in Homebrew (it is unsupported), the panel honestly shows "not in Homebrew" and offers an additional mechanism (question 1).

## 8. Ten check scenarios (goal — each ≤ 3 clicks from "Overview" without hints)
1. Install Python 3.12 and make it the main one (python3 without a full path).
2. Find and remove unneeded Homebrew packages, free space.
3. Prepare a Mac for Flutter development from scratch.
4. Deploy a Laravel site (PHP, MySQL, Redis) and open it in the browser.
5. Connect Claude Code to the panel and make sure it works.
6. Approve an agent's action from a phone (Telegram).
7. Run a project's tests and see the result.
8. See what changed since the last state snapshot, and make a backup of a repository.
9. Find out what was changed yesterday and by whom (the journal).
10. Find where X is configured (without search — by the menu's logic and "Open in…" links).

## 9. Risks
- **Broken links** → redirects and a test for every address; links in `manuals/`.
- **Size** → stages are independent, each ships separately.
- **No frontend tests** → before U2 add a minimal harness: open every page with stubbed requests, including a failing one, and check that it rendered.
- **Version-manager conflict (Node)** → the owner's decision before U4a.
- **Regressions** → comparing 76+ GET routes with the base plus page screenshots.

## 11a. A FlyEnv breakdown: software sets, functions, design
Sources: [flyenv.com](https://flyenv.com), the [demos](https://flyenv.com/demos), the [repository](https://github.com/xpf0000/flyenv) (the `src/render/components` structure). `mise` is not taken for now (the owner's decision).

**Software sets.** FlyEnv has about 60 modules: languages (PHP, Node, Python, Go, Java, Flutter, Bun, Deno, .NET, Erlang, Ruby, Rust, Zig, Perl), databases (MySQL, MariaDB, PostgreSQL, Redis, MongoDB, ClickHouse, Neo4j, Qdrant, Memcached, Typesense, Meilisearch, Etcd…), web servers (Nginx, Apache, Caddy, FrankenPHP, Tomcat), tools (phpMyAdmin, pgAdmin 4, DbGate, Redis Commander, Mailpit, MinIO, mkcert, Cloudflared, Podman, Git, Gradle, Consul), services (RabbitMQ, Temporal, Cron, n8n), AI (Claude Code, Codex, OpenCode, Kimi, Ollama, an MCP server).
- **We already have** in the services catalog (20): Caddy, Cloudflared, dnsmasq, Grafana, httpd, Mailpit, MariaDB, Meilisearch, Memcached, MinIO, MongoDB, MySQL, nginx, Ollama, PHP, PostgreSQL, Prometheus, RabbitMQ, Redis, Valkey; in the recommendations (100): Bun, Deno, Gradle, mkcert and others.
- **In Homebrew, not in ours** (checked against the local formulae): Neo4j, etcd, Temporal, Tomcat, phpMyAdmin, Podman, .NET, Erlang, Zig, mongosh; cask apps: ClickHouse, Consul, pgAdmin 4, DbGate, MongoDB Compass, TablePlus. **Not in Homebrew** (needs a tap or another way): Elasticsearch, Qdrant, Typesense, FrankenPHP, n8n, Adminer, Redis Commander.
- **Proposal:** add ~12 catalog cards "Database tools" (phpMyAdmin, pgAdmin 4, DbGate, TablePlus, mongosh, Compass) and "Infrastructure" (etcd, Consul, Temporal, Neo4j, ClickHouse, Tomcat, Podman) — catalog data, low cost. And ready **service sets** ("Laravel": nginx + php + MySQL + Redis + Mailpit; "Node": MongoDB/PostgreSQL + Redis; "Python": PostgreSQL + Redis + RabbitMQ) with a "start everything" button.

**Functions (what is worth taking, by value/cost):**
1. **One object page: "Versions · Settings · Log".** Their module = versions + service + config + log in one layout. Ours have languages, services and Docker laid out differently — the main idea for U3/U5 (low–medium cost, high value).
2. **Startup groups ("start everything"):** a set of services that start/stop together, on top of `brew services` (medium cost).
3. **Ports:** a tab "who listens on which port" and conflicts (read-only; no "kill the process") (low cost).
4. **Local domains and HTTPS without editing `/etc/hosts`:** a built-in DNS + mkcert + a reverse proxy: "add a site: a folder or a port → https://name.test". Ours — Herd (PHP only) and manual hosts editing. The basis for U5 "Sites & domains": dnsmasq (already in the catalog) + mkcert + nginx/Caddy (high cost, high value).
5. **A per-project version without a manager:** a hint "the project asks for Node 20 (`.nvmrc`/`.node-version`/`.tool-versions`), 26 is active" + an "install / make main" button (low cost).
6. **Quick actions in the header** (they have a floating button/tray): start/stop a group, open a site (low cost).
- Not taking: tools like regex and hash checkers, a built-in DNS/FTP server of our own.
- Our advantage to protect: the AI-agent gateway with approvals, remote operators (Telegram/API), VMs and runners, Linux. In FlyEnv AI is an MCP server ("tell the AI what to run") with no human approval.

**Design.** The site: alternating "text — screenshot", numbered steps, a logo grid, a language switcher; the app — a sidebar of modules, a version list with "Installed / Install" marks, a "Start all" panel, appearance settings. Conclusions: we are already close (a dark theme, a side menu, product logos); missing are **one object layout**, **a startup group "start everything"** and **a clear "what is installed / what can be installed" page** in one view.

**Status of the FlyEnv ideas (as agreed with the owner):** ✅ item 1 one object page — the tabs "Overview · Versions · Settings · Log" on services (versions of any Homebrew formula, the log inside the page) and "Versions · Packages & tools" on languages; ✅ catalog cards: 12 in "Database tools" and "Infrastructure" (phpMyAdmin, pgAdmin 4, DbGate, mongosh, Compass, etcd, Consul, Temporal, Neo4j, ClickHouse, Tomcat, Podman) and 3 services (etcd, Tomcat, Temporal); ✅ item 2 service sets (Laravel, Node.js, Python) and own startup groups — "start all / stop / restart / install the missing"; ✅ item 3 the "Ports" tab (read-only) and a hint on a service page if its port is taken by another process. ⬜ item 4 local domains (U5), item 5 a project-version hint, item 6 quick actions in the header.

## 11. What a survey of similar products showed
- **FlyEnv** (BSD-2, macOS/Windows/Linux) is the closest analogue: runtime versions, web servers and databases, local domains and HTTPS, project services, in one interface without Docker. **Laravel Herd** is the reference for PHP/Laravel (sites, PHP settings, nginx, dnsmasq, Node), closed source. **DevPod** — environments in containers; **Flox/Devbox/mise** — per-project versions and packages, with no panel. Our difference: **an AI-agent gateway with approvals**, remote operators (Telegram/API), Linux, VMs and CI runners — none of them has these; while "versions + services + domains in one place" is worth borrowing from FlyEnv/Herd.
- **ISPmanager, Cockpit, Coolify** (patterns): after login — an **overview**, then a permanent left menu (it neither hides nor appears — a "jumpy" panel annoys); ISPmanager's menu has levels "all / main / favorites / popular" and a search; Cockpit separated overviews from per-host settings; Coolify builds a hierarchy "server → project → environment → resource" and tabs on an object. Conclusion for us: overview + a stable menu + tabs on an object page; **favorites and popular** is a possible replacement for the postponed search and "interface profile".
- **Versions:** `uv python list --all-versions` / `uv python install 3.12.3`, `nvm ls-remote`, `fvm releases` / `fvm install`, `mise ls-remote node` / `mise install node@20` — version managers have lists of "all" versions; Homebrew has only versioned formulae.

## 10. Open questions
1. **"Old versions" (Node etc.):** Homebrew gives only `node@N` of supported versions. For exact old versions (for example Node 14, Python 3.8.10, PHP 7.4, Flutter 2.x) I suggest adding **one extra mechanism — `mise`** (one version manager for Node/Python/Go/Ruby/Java and more) as an optional choice, keeping Homebrew as the main one. Agreed? (Python is already installed through `uv`, Flutter through FVM.)
