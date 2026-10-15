# Panel UI update plan (Phase 10)

Status: **a plan, waits for the owner's decision.** The menu and pages are not changed until it is approved. Already done (U1): the "who can approve plans" switch moved to "Approvals", and the "on this computer" agent connection wizard explains the steps. The plan went through an independent check (a critic verified the facts against the code); the corrections are included below.

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
- No entry **by role** and no "attention center" (what needs action).
- Already fixed: the "Packages" page failing as a whole (blocks now load independently); agent approvals are now in one section. Remaining: the "Agent connections" page loads five requests in a row every 5 s.

## 2. Principles (as in good web panels: ISPmanager, Plesk, cPanel)
1. **One task — one place.** A setting lives on one page; other pages only link. No copies.
2. **A menu by objects and tasks**, with no one-item groups.
3. **One page template:** title + status chips + a primary action; tabs; "list → card"; one confirmation for danger; **empty states and error blocks are part of the template** ("what to do next", "Retry").
4. **An entry by task and role** — "Getting started" (one flow: system preparation → a stack for your role).
5. **Honest names:** a page is named after what it does (no "rollback" if there is none).
6. **A failure of one part does not break the page.**
7. **Protection-weakening actions are visible and explained.**

## 3. Target menu (5 groups, 15 items, no one-item groups)

```
Overview                      health, "needs attention"
Getting started               system preparation + stacks by role (one first-run flow)
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

## 5. "Getting started" and stacks by role
**This is not just a new layout of "Profiles":** the `profiles.py` catalog must be extended first (stage U4a): a **Web** profile (there is none), PHP, Composer, Herd and Node in **Backend**; a language choice ("PHP/Laravel · Node · Python · Go"); remove duplicates (gh, lazygit, clt, cocoapods, fastlane); **one Node manager** (the owner's decision: nvm or Homebrew); a **"is it running"** check, not only "installed" (the DB service is running, the site is linked); item states: *install · manual · later (a large download) · needs administrator · needs consent* (the Xcode license, `sdkmanager --licenses`, Apple ID — a human does these by hand; the panel never enters a password).
- **Backend:** a language of choice, DB/cache (MySQL, PostgreSQL, Redis) as services with a running check, Docker, git+gh, Cloudflared, curl/jq/httpie; for PHP — a site in "Sites & domains".
- **Flutter / mobile:** Xcode + CLT + license (manual), simulators (a large download, "later"), CocoaPods, Flutter/FVM + Dart, Android SDK + Java, fastlane. Detection is by files: the panel **does not run `flutter --version`/`flutter doctor`** (they write to the SDK cache) — the project rule stays.
- **Web:** Node + a version manager, pnpm/yarn, git, browsers for tests.
- **AI operator:** an agent client, connecting the agent, approvals, Telegram.
- Limits to show: only one profile installation runs at a time; cask apps trigger the administrator password window; the detector does not see GUI programs and manual items.

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
| **U2** | Skeleton: the new menu and groups, the page template (header, chips, tabs, independent block loading, empty states, error blocks), redirects preserving parameters, moving `docker.js`/`connect.js` to one sub-tab mechanism, speeding up `connect.load` | 5–6 days |
| **U3** | "Environment": "Languages & versions" in one layout (versions · default · packages · install/uninstall; Flutter/Dart once), "Packages & services" (tabs: installed · unneeded · updates · services · recommended), "Mobile development" (+ "install"), "Containers" | 6–8 days |
| **U4a** | Extending the profile catalog (Web, Backend with PHP/Node, language choice, no duplicates, one Node manager, "is it running", item states) | 3–4 days |
| **U4** | "Getting started": system preparation + stacks by role on the new catalog | 4–5 days |
| **U5** | "Projects" (+ runs and history) and "Sites & domains" (Herd + cloudflared + hosts) | 4 days |
| **U6** | "Attention center" (a cacheable request) | 2 days |
| **U7** | "Machines & runners"; "History & copies" (honest names; a separate task — "restore from a snapshot": reinstall from a Brewfile, only if the owner decides so) | 3 days |
| **U8** | "AI access" as one whole section (one approval policy, guides per client), in the "AI agents" group | 2 days |
| **U9** | Polish: responsiveness, accessibility, manuals and screenshots, checking the 10 scenarios with the owner | 3–4 days |
Total ≈ 5–6 weeks. The first visible benefit — U2 + U4a/U4.

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

## 10. Questions for the owner
1. Is the menu map (5 groups) right? Especially: "Sites & domains" as a separate item (Herd + cloudflared + hosts), with only PHP versions left in "Languages". Is that how you think of it?
2. Which Node manager stays as the single one: **nvm** (as on the Node page now) or **Homebrew** (as in profiles)?
3. Which roles are needed in "Getting started": Backend (PHP/Laravel, Node, Python, Go), Flutter/mobile, Web, AI operator — enough? Are more needed (Data/ML etc.)?
4. Do you need real "history and rollback" (reinstalling packages from a snapshot), or is "compare and save" enough?
5. Where to start: U2 (the menu skeleton and the template) — recommended.
