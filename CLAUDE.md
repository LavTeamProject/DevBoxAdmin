# CLAUDE.md

Guide for Claude when working in this repo.

**Language — hard rules:**

- **The UI has only TWO languages: Russian (default) and English.** The dictionaries are in `static/i18n.js`
  (`I18N.ru` and `I18N.en`). **Do not add a third language**, and do not bring back the `id` dictionary
  that was removed. Both dictionaries must always be fully identical (identical key counts).
- **New UI text must go through `t("key")`**, not literal strings. If the key does not exist yet,
  add it to **both** dictionaries at once.
- **Code comments: Indonesian** (a repo legacy, not yet migrated). This is a decision that has not
  been made — do not change the comment language in bulk unless asked.
- **Messages printed by shell scripts (`install.sh`, `uninstall.sh`, `fetch-python.sh`) are also only Russian (default) / English:** use `msg "ru" "en"` (English if `SA_LANG=en` or `LANG=en*`). Indonesian-language messages for the user are forbidden.
- **Backend error messages: `ApiError(russian_message, status, code="module.slug", **params)`.** `message` = Russian text
  (default + fallback); `code`+`params` are translated by the frontend via the key `err.<code>` (`ru` and `en` dictionaries,
  `{param}` as the placeholder). Do not write an `ApiError` without a `code`. **Do not give a `code` to messages that
  are only a fallback from a tool's stderr** — use `code=None if err.strip() else "x.y"` so the original text
  is not overwritten. Do not match `e.message` in JS: use `e.code`.
- **Additional dictionaries:** besides `static/i18n.js`, there are `static/i18n-ext-<area>.js` (`Object.assign(I18N.ru, {...})` and
  `Object.assign(I18N.en, {...})`) — one file per area so parallel work does not collide. Check parity
  and empty keys with **`node check-i18n.js`** (must pass: number of `ru` keys = `en`).
- **Missing-tool errors** (brew, docker, …) → `FileNotFoundError` becomes `tool_missing` (a "Tool not
  found" card with a link to System Setup); empty/broken JSON output from a tool → use
  `core.loads_or(text, default)`, not `json.loads` directly (falls back to `bad_output`, not "Internal error").
- The package catalog (`svc.py`) is in Russian at the source; its EN translation is per text in `static/i18n-ext-catalog.js`
  (key `cd.<Russian text>`; `catTr()` in `packages.js`). Adding a new catalog entry → also add its translation.


## Architecture decisions — FINAL, do not doubt them again

These have been decided by the project owner. Do not re-propose alternatives that were rejected here.

1. **The panel must be installable on a FRESHLY installed macOS, with nothing beforehand.**
   That is the product goal: one panel that prepares and controls the whole Mac. If there is a step
   that cannot be done from inside the panel, that step must be recorded as an **intentional exception**
   together with the reason (e.g. the Apple dialog for Command Line Tools, Apple ID for Xcode).
2. **The Python runtime is BUNDLED, not taken from the system.** The panel must not depend on the
   Python bundled with macOS (a clean macOS has no Python at all; Command Line Tools only provide 3.9).
   `install.sh` downloads standalone CPython from `python-build-standalone` (~25 MB, already proven
   available: `cpython-3.12.x+<date>-aarch64-apple-darwin-install_only.tar.gz`) to
   `~/.service-admin/runtime/python/`. **Do not add new dependencies on system tools.**
3. **The launcher must not require Command Line Tools.** Use `/usr/bin/osacompile` (part of
   macOS), **not `swiftc`** — `swiftc` comes from CLT and that is exactly the prerequisite we want to remove.
   The only things that may be assumed to exist on a clean macOS are: `curl`, `tar`, `osacompile`, `open`, `osascript`.
4. **"No workarounds" matters more than speed.** Go straight to the correct form; do not
   add temporary bridges (e.g. relying on Apple's bundled Python 3.9) that will have to be torn down later.
5. **`tomllib` IS ALLOWED to have a fallback path.** The project owner gave explicit permission: write
   `tomllib` → `tomli` → disable TOML validation with a clear message. This is purely a defense for
   the case where someone runs `python3 server.py` with an old interpreter; the main path remains the
   bundled Python. Do not remove the TOML validation, just fall back with an honest message.
   Currently only `files.py` (3 lines: `import tomllib`, `tomllib.loads`, `tomllib.TOMLDecodeError`)
   needs 3.11 — there are no other 3.11+ features in the whole repo.
6. **Install/first-run verification is done in a clean macOS VM (tart), not on the work machine** (the
   project owner's decision, updated). Details are in `docs/roadmap.md` (English: `docs/en/roadmap.md`), section "Проверка на чистой macOS" / "Verification on clean macOS".

## What this is

**Mac Service Admin**: a local web dashboard for managing a macOS (Apple Silicon) dev environment:
Homebrew (packages + `brew services`), Docker/OrbStack, Laravel Herd, language versions (PHP, Node, Python, Go,
Rust, Java, Ruby, …), configuration files (zsh, `/etc/hosts`, SSH, Git, php.ini, `.env`), and system
statistics (CPU, RAM, temperature, GPU, battery).

```bash
python3 server.py            # http://127.0.0.1:8765  (--port to change)
```

## Main rules

- **Stdlib only, no dependencies.** Pure Python backend (http.server, subprocess, ctypes); vanilla JS/CSS
  frontend with no build step, no CDN (icons are stored locally in `static/icons.js`).
- **Security (do not loosen):**
  - The server binds only to `127.0.0.1`; the `Host` header must be `localhost`/`127.0.0.1` (anti DNS rebinding).
  - All POSTs require the header `X-Requested-With: service-admin` (anti CSRF). `api()` in `app.js` already
    sends it.
  - Commands run as an **argument list, without a shell**. Validate every input (package name,
    version, container id, hostname, port) with a regex before use.
  - Files may only be read/written through a **registry** (`files.py`, `svc.service_spec`, compose from
    `docker compose ls`), never a free path from the browser.
  - Do not send secrets to the browser unless necessary: `herd sites --json` contains the contents of `.env`, so the
    `env` field is dropped in `herd_info()`. Container env is masked in the UI (`SECRET_RE` in `dockerx.py`).
  - Root-owned files (`/etc/hosts`, `/etc/resolver/*`) are written through
    `osascript ... with administrator privileges` (the macOS password dialog), not sudo.
- **Before overwriting a user file: validate + back up.** The pattern used: validate first (or write →
  validate → roll back on failure), back up to `~/.service-admin/backups/...`, keep 20 versions.
- Destructive actions (uninstall, delete volume, prune, down) must have `data-confirm` on their button.
- **PHASE 1 = read-only** (narrow exception: `projects.py` may write `~/.service-admin/projects.json` — registry & presets — via `registry_add/registry_remove/preset_set`; git remains read-only). `profiles.py`, `mobile.py`, `projects.py`, and `agents.py` **must not**
  install, download, change, or stop anything. If action buttons are added later
  (e.g. `brew install`, `xcode-select -s`, `git worktree add`, running agents), those actions must:
  go through `start_job`/`start_steps`, have `data-confirm` in the UI, and must not touch the system without an
  explicit user request. Never silently raise `--no-rename`/timeouts to "speed things up".
- **Do not add dependencies.** Phase 1 deliberately uses not a single new package.
- **Guides for humans (instructions + screenshots) are kept in `manuals/`** (see `manuals/README.md`); screenshots only from a real system (tart VM/Mac), without personal data, in trimmed JPEG format. Do not include other users' windows/applications in screenshots.
- **The work plan is in `docs/roadmap.md`.** Before working on a new feature, check that document:
  if the item is not there, do not work on it — first propose a change to the document.
  The Phase 2 order is binding: **2.0 Standalone Bootstrap → 2.1 System Setup page → 2.2 Audit trail**,
  and only after all three are done may there be actions that change the system (2.3 and onwards).
  Audit is not an add-on: the panel will install Homebrew and ask for the admin password, so without an audit trail
  there is no way to answer "what was just run?".

## Rules from testing on clean macOS (tart VM)

- **Copying the repo to the VM: do NOT use `tar` from the shared folder** (`/Volumes/My Shared Files`) — it silently gets truncated and the VM
  receives an incomplete copy. Use an SSH stream (`tar -cf - . | ssh … tar -xf -`) and then **compare the `shasum` of all files**.

- **`/usr/bin/git`, `python3`, `make`, `xcrun`, etc. without CLT = stubs that open an Apple dialog.**
  Never call them directly. `core.run()` already refuses to run them (see `CLT_SHIMS`,
  `clt_stub()`); a direct `Popen` in a job is not protected, so check `has_clt()` yourself.
  `install.sh` also calls `git` only if `xcode-select -p` succeeds.
- **A LaunchAgent triggers macOS permission dialogs** (Documents, Desktop) on first use; requests
  touching those folders hang until the user presses Allow. That is not a panel bug.
- Install testing is done in the `clean-mac` VM (tart), not on the work machine — see the roadmap
  "Verification on clean macOS". The 50 GB VM disk is not enough for the Apple CLT dialog (needs ~24 GB free).

## What has been proven on a real machine (do not repeat the mistakes)

These four things were found by measuring on a real Mac, and all are easy to repeat:

1. **`python3` may be 3.9.** `files.py` imports `tomllib` (≥ 3.11). On a Mac where Python 3.11+ exists only
   in Homebrew, `python3 server.py` fails with `ModuleNotFoundError: tomllib`. Test `python3 -V` first;
   explicit interpreter: `/opt/homebrew/opt/python@3.12/bin/python3.12 server.py`.
   **The direction of the fix has been decided** (see "Architecture decisions"): the Python runtime is bundled,
   so this problem disappears on the main path; the `tomllib → tomli` fallback path is still written
   as a defense. Do not add new dependencies on system Python to "solve" this.
2. **Parallel `git` processes lock each other.** `git status`/`git diff` usually take `.git/index.lock`.
   If several read commands run at the same time in the same repo (and `project_detail` does run 9
   at once), one command can hang for **30 seconds**. That is why `projects.git()`
   always uses `GIT_OPTIONAL_LOCKS=0` (and `GIT_PAGER=cat`, `GIT_TERMINAL_PROMPT=0`).
3. **`git diff` without `--no-renames` is expensive.** Rename detection forces git to read the contents of every
   changed file: measured at **10–25 seconds** vs **0.03 seconds** with `--no-renames`. All diffs in
   `projects.py` use `--no-renames`. The only side effect: a rename shows up as delete+add.
4. **`--stat`/`--numstat` are still slow even without renames**, because they still count lines. That is why
   the file list on the detail page uses `--name-status` (0.06 s), and line statistics (+/-) are only
   computed when the user presses the button (`/api/projects/diffstat`, 90 s timeout).

In addition:

- **`flutter --version` writes to the SDK cache.** The panel **never** runs it; the version is read from
  `bin/cache/flutter.version.json`. If you need the Flutter version in new code, use that file path.
- **The project list cards deliberately do not include the git summary on the server.** One large repo can hold up
  the whole page. `/api/projects` returns only paths (0.01 s), then the browser calls
  `/api/projects/summary?path=…` per card in parallel and fills them in itself. Do not merge them back together.
- **`xcrun simctl` starts CoreSimulatorService** if it is not running. That is a built-in Apple service, not a
  settings change — but it is still not "zero side effects", so do not call it in a tight loop.
- **`ps` can be blocked** (sandbox, MDM policy). `core.ps_snapshot()` and `agents._read_ps()`
  return empty if `ps` fails; the AI Sessions page shows a warning, not an error.

## i18n

**Two languages only: `ru` (default) and `en`.** The dictionaries are in `static/i18n.js`, no build step.
Both dictionaries must be **fully identical** (identical key counts). Test with:

```bash
node -e "const fs=require('fs');const s=fs.readFileSync('static/i18n.js','utf8');
const i=s.indexOf('const I18N = {')+13;const I=eval('('+s.slice(i,s.indexOf('\n};',i)+2)+')');
const k=Object.keys(I.ru);for(const [l,d] of Object.entries(I))console.log(l,k.filter(x=>!(x in d)));"
```

- Static HTML: `data-i18n` (innerHTML), `data-i18n-title`, `data-i18n-ph`, `data-i18n-aria`, `data-i18n-label`.
- JS: `t("key")`, with placeholders `t("key", {n: 3})` → `{n}` in the dictionary.
- Fallback: active dictionary → `I18N.ru` → the key itself. There is no third language as a fallback.
- Page title: `tabs.<key>.titleKey` (e.g. `"nav.projects"`), not a `title` containing prose.
- After `setLang()`, the active page is re-rendered automatically and `updatePageTitle()` is called again.
- All pages (including packages/config/docker/langs/dashboard/app) already use `t()`; text computed
  in a module must be looked up at render time (inside a function), not stored in module-level constants.

## Structure

| File | Contents |
|---|---|
| `server.py` | ONLY the HTTP handler + routing (`GET_ROUTES` / `POST_ROUTES` at the bottom of the file); domain logic is in modules (`brewsvc`, `herdphp`, `uihelpers`, `dockerx`, `files`, …). Do not put new logic in server.py |
| `brewsvc.py` | Services (`brew services`) and Homebrew packages: list, search, actions (package changes are executed by `operations.run_package`). Extracted from server.py |
| `herdphp.py` | Herd, PHP versions, Node/nvm, creating a Laravel project, `EDITORS`. Extracted from server.py; the operations catalog also calls the mutating functions |
| `uihelpers.py` | Sidebar (`nav_info`), reading a file for diagnostics, opening Terminal/Activity Monitor, project details |
| `ops_system.py` | Catalog of operations on the system (services, PHP/Herd/Node, languages, Docker, files) — registered in `operations.OPS`; executes the same functions as the page; NOT exposed to agents |
| `core.py` | Shared helpers: `run`/`output`, `ApiError`, state (`~/.service-admin/state.json`), background **jobs** (`start_job`, multi-step `start_steps`, `list_jobs`), backups & the `.zshrc` block, `set_shims`/`set_env`, `shell_probe` |
| `stats.py` | System statistics without sudo: per-core CPU (Mach `host_processor_info`), temperature (IOKit HID via ctypes), GPU/battery (`ioreg`), RAM (`vm_stat`), background sampler |
| `runtimes.py` | Language detection (`LANGS`) + management of Python/Go/Rust/Java/Ruby |
| `svc.py` | Service details (config file + validator per service), catalog & 100 package recommendations, cloudflared panel |
| `files.py` | Configuration file editor: `STATIC` registry + resolver, php.ini, project `.env`; validator per type |
| `dockerx.py` | Docker: overview, stats, disk, inspect, logs, exec console, `docker run`, compose (read/validate/save), remote contexts |
| `ptyterm.py` | A real terminal: `zsh -l -i` sessions in a PTY (`pty.fork`), long-poll output (`/api/pty/read`, base64), input/resize/kill via POST, plus `peek` (preview without moving the offset) |
| `setup.py` | **System Setup** (`#setup`): status of CLT/Homebrew/Git/bundled Python + installation of CLT (Apple dialog, the panel waits) and Homebrew (official installer, `SUDO_ASKPASS` → macOS password dialog). Via `start_steps`, recorded in the audit |
| `snapshots.py` | Environment snapshots (`#snapshots`): `~/.service-admin/snapshots/*.json` (brew + Brewfile, runtimes, Xcode, Flutter/Android, profiles) + comparison of two snapshots / "now". Does not change the system |
| `audit.py` | JSONL audit trail `~/.service-admin/audit.log` (0600, rotation). Every entry has `by` (`panel`/`agent:<name>`/`system:<what>`) from `audit.INITIATOR` (ContextVar) — new threads must pass it on (a job stores `by` at start). All POSTs + job completion; secrets are masked, terminal input is NOT logged. Audit page: `static/audit.js` (`#audit`, `GET /api/audit`: filter by action/result/date) |
| `profiles.py` | Catalog of installation profiles (Foundation/AI/Flutter/iOS/Backend) + one detector per tool. Detection is read-only; `plan()` builds a plan without changing anything, `install()` runs it via `start_steps` (one `profile-install` job at a time, snapshot before/after). Types in the catalog must match Homebrew (`flutter`, `codex` = cask) — test with `brew info --json=v2` |
| `mobile.py` | Xcode & simulator (`xcrun simctl`), Flutter/FVM, Android SDK, CocoaPods, fastlane. **Read-only** |
| `mobile_ops.py` | Actions on the mobile toolchain (`POST /api/mobile/op`): Xcode select/first-launch, simulator boot/shutdown/erase/screenshot, Flutter/FVM/pod, Android sdkmanager. `build()` is pure (does not execute); execution via `start_steps`; admin actions via the macOS password dialog. The browser only names ids from the server registry |
| `projects.py` | Git repos: folder scanning, status/branch/worktree/log/diff, `gh` for PR/issue/CI, registry & presets. **Git: read-only** |
| `gitops.py` | Git write actions (`POST /api/git/op`): fetch/pull(--ff-only)/push(no --force), branch, stash, add/commit, worktree (only in `~/Worktrees`), discard/clean (must type the project name on the SERVER). Ids & files are validated against the repo state; `build()` is pure |
| `agents.py` | AI session monitoring: maps agent processes to PTY sessions (needs `pid` from `ptyterm.list_sessions`) + CPU/RAM per process tree. **Monitor only** |
| `operations.py` | **The single operations catalog** (Phase 4.1): 86 operations — levels L1–L4 + escalation, parameter schema, requirements (`REQUIREMENTS`), idempotent, verification, rollback; `plan/verify/execute`. Homebrew package operations are executed ONLY via `run_package` (server.py only wraps it). New operation → register it here; the catalog is checked in both directions against `gitops`/`mobile_ops` |
| `opschema.py` | Shared parameter-schema validator (agent gateway + operations) |
| `plans.py` | **Plan + approval** (Phase 4.2/4.4): `propose → approve (macOS dialog) → execute (once, hash re-checked → `plan.stale`) → verify`. Agents: 6 L2 operations (`AGENT_OPS`, including `docker.container_control` — LOCAL Docker engine only) and, only for L3-level agents, `AGENT_OPS_L3` (`runner.spawn`, `runner.selftest`) — the macOS dialog is REQUIRED, `auto_approve` is impossible for L3, max 3/hour; default approval = the macOS system dialog (default button Reject, timeout 110 s = reject, text via argv). `auto_approve` only for L2, explicit + audited. **Do not add operations to `AGENT_OPS` without updating the roadmap.** Test with a fake `ask_human` & `osascript` — do not show real dialogs on the work machine |
| `agent_gateway.py` | AI agent gateway (Phase 4.0): registry (`agent-registry.json`, only SHA-256 hashes; secrets in `agents/<id>.token` 0600), read-only L1 tools, schema validation, rate limit 60/min, audit with agent identity. **There is no `execute_shell`.** |
| `agent_socket.py` | Unix socket `~/.service-admin/agent.sock` (0600): only the agent gateway, not the HTTP API; path ≤100 bytes |
| `mcp_server.py` | MCP stdio (JSON-RPC) — a thin bridge to the socket; does NOT run the panel. Test with your own driver; **not yet tested with a real MCP client** |
| `cli.py`, `service-admin` | CLI for agents without MCP (Phase 4.3): a thin wrapper over `mcp_server.panel_call`, with no logic of its own; JSON output, exit code 2 = panel unavailable |
| `vm.py` | VM drivers (Phase 5): `Driver`/`TartDriver` — reading + `build()` (pure) and `run_op` for vm.clone/pull/start/stop/snapshot/delete via `start_steps`. NOT exposed to agents (do not add to `plans.AGENT_OPS` without updating the roadmap). Test: clone `clean-mac` and work only with the copy; set `TART_HOME` explicitly if you change HOME |
| `runners.py` | CI runners (Phase 5): provider adapters `github`/`gitea` (installing the FILES, sha256 from the release), source registry (`runner-sources.json`: provider + any URL + scope) and tokens in 0600 files (`runner-tokens/`, they do not reach the API/audit). No registration/launch — that is L3 + VM isolation, the next steps |
| `ci_api.py` | Gitea/Forgejo and GitHub API clients using an access token: registration token, list/delete runners, repo/file/run for the self-test. Redirects are FORBIDDEN (the token does not go to another host), errors without response bodies (no secrets). The GitHub part has not been verified against real GitHub |
| `runner_spawn.py` | On-demand runner (L3): clone a VM base → ephemeral runner for ONE job → the VM is always deleted. The token goes only via stdin into a 0600 file in the guest, and is stripped from the output. Test only on a copy of `clean-mac` and an unreachable server/dummy token; do not run real registration on the OWNER's Gitea/GitHub — test on your OWN temporary Gitea (download `dl.gitea.com`, sha256, SQLite, listen only on the host's LAN address, delete afterwards). For L3-level agents — only via a plan + mandatory dialog |
| `backups.py` | Backups (`#backups`): `git bundle --all` per repo (dedupe via a fingerprint ref, no worktree), `tar.gz` archive of the data folder + panel data (without runtime/tmp/screenshots), keep the last N, verification (**`git bundle verify` is NOT enough — it passes truncated bundles; use clone+fsck**), schedule (thread, every 5 min), restore ONLY to a new folder `~/Restored/…` (check for `..` in the archive). Destination: local folder/`/Volumes`, no cloud |
| `runs.py` | Test/build from project presets + history (`~/.service-admin/runs.jsonl`, `runs/*.log`) + GitHub Actions (`gh workflow run`, must type the project name). Commands ONLY from presets and must pass `projects.runnable_argv` (allowlist `RUN_TOOLS` + the project's `./script`; no `-c/-e`); 30-minute timeout, the process group is killed. Test gh with a **fake gh** (`projects.GH`), never call the real gh to run a workflow |
| `agent_tasks.py` | Agent tasks (`~/.service-admin/agents.json`): "new task" = worktree (`gitops`, `~/Worktrees`) + an agent in a PTY; stop/start, send text to a session (explicit), changes/diff relative to `base_sha`. Agents only from what is installed, no "skip permissions" flag; busy/idle status = HEURISTIC. **Test with a FAKE agent** — on the test stand `/opt/homebrew/bin` is at the start of PATH so the real `claude` gets caught first: use an agent name that is not installed (e.g. `aider`) |
| `static/index.html` | Shell: sidebar, header (terminal button + theme), dialogs, right panel (Terminal / Processes tabs) |
| `static/app.js` | Core UI: `api()`, `btn()`, `toast`, hash router, `handlers` (event delegation), panel (`panelOpen`/`panelView`), job runner (`runJob`), theme, PHP/Node/Herd |
| `static/terminal.js` | Terminal tab: xterm.js per session, output polling, input batching, resize (FitAddon), reattach after refresh, `window.runInTerminal(cmd, cwd)` |
| `static/vendor/` | xterm.js + fit/web-links addons (MIT), stored locally, do not replace with a CDN |
| `static/packages.js` | Packages & Services page + service detail (`#service:<name>`) + cloudflared |
| `static/docker.js` | All Docker pages (`#docker:<sub>`) + compose builder + create-container dialog |
| `static/langs.js` | **Languages** group page (`#langs`, 3-column cards + installable languages), detail page `#lang-<key>` (nav: `langs`), versions/status in the sidebar (`applyNav`/`refreshNav`) |
| `static/config.js` | Configuration Files page (`#config:<id>`) |
| `static/dashboard.js` | Statistics dashboard + `lineChart()` (SVG, also used by docker.js) |
| `macapp/launcher.applescript`, `macapp/AppIcon.icns`, `install.sh`, `fetch-python.sh` | The `Service Admin.app` launcher (an AppleScript applet, compiled by `/usr/bin/osacompile` without CLT; starts the server via LaunchAgent/fallback then opens the browser via `/usr/bin/open`), the `local.service-admin` LaunchAgent installer, and the downloader of the bundled Python into `~/.service-admin/runtime/python/`. `macapp/makeicon.swift` is only for regenerating the icon (needs `swift`, not used during installation). A server started from launchd needs the macOS *Files & Folders → Documents* permission because projects are in `~/Documents` |
| `static/icons.js` | Simple Icons logos (CC0) + `logoSvg()` / `logoFor(formula)` |

## Code patterns

**Backend**
- New endpoint: write a function `(q)` for GET (query dict) or `(body)` for POST (JSON dict), then
  register it in `GET_ROUTES`/`POST_ROUTES`. Raise `ApiError(message, HTTPStatus.X)` for errors to the UI.
- Long-running commands (install, compose up, `laravel new`) → `start_job(label, cmd, kind)` or
  `start_steps(label, [(title, cmd|callable, options)], kind)`, return `{"job": id}`. Only one job per `kind`
  may run at a time.
- Tools on the user's PATH (rustup, pipx, nvm, …) may be missing from the server's PATH (for example when running from
  a LaunchAgent). Resolve via `shell_probe` / `runtimes.tools()` (interactive zsh) and use absolute paths.
- Choosing the default version: symlink shims in `~/.service-admin/bin` per language (`set_shims(lang, {...})`)
  or env in `~/.service-admin/env.zsh` (`set_env`, used for JAVA_HOME). Both are loaded by a single
  block at the **very bottom** of `~/.zshrc` (`ensure_zshrc_block`).

**Frontend**
- A page = `tabs.<key> = { load(silent), interval?, nav?, title?, logo?, leave? }` (`nav` = the sidebar item to highlight, `title` = header title if different); route `#key` or `#key:param`
  (`this.param`). Old aliases: `#services`/`#apps` → `packages`, `#zsh` → `config`.
- **A new page MUST separate `load()` (fetch data) from `render()` (draw from data).**
  `load()` stores its response in an instance property (e.g. `this.data = await api(...)`) and then calls
  `this.render()`; `render()` redraws from that property **without a single network request**.
  `setLang()` calls `current.render()` if it exists, and falls back to `load()` only if it does not.
  If this is violated, switching language will wait on a request — the Mobile Toolchain page was once held up
  for over ten seconds by `xcrun simctl`, even though the data had not changed. The same pattern is already used by
  `tabs.langs` (`load()` → `refreshNav()` → `render()`).
  Data fetched incrementally (git summary per repo, Flutter/FVM projects, the GitHub block) must be
  **cached in an instance property and redrawn from the cache** — do not re-fetch when switching language.
- Buttons: `btn(label, "action", {data}, "go|primary|danger")` + `handlers.action = async (dataset, el) => …`.
  `data-confirm` automatically shows a confirmation.
- Long processes: `runJob(api("/api/…", body), onDone)`. Progress is shown in the right panel, **Processes** tab
  (terminal icon in the header, red dot while running). The **Terminal** tab is a real PTY shell;
  interactive programs (claude, vim, tinker) must go through it, not through a job (jobs have no TTY).
- Colors always via CSS tokens (`--bg`, `--card`, `--text`, `--series-1..4`, …). Theme: light/dark/
  system via `html[data-theme]`; dark tokens are defined in two places (media query + `[data-theme="dark"]`).
- Always `esc()` dynamic data in template strings.

## Verification

- Python lint: `pipx run pyflakes *.py`. JS syntax check: `node --check static/*.js`.
- Backend tests: import the module directly (`python3 -c "import dockerx; print(dockerx.overview({}))"`).
  For functions that write `~/.zshrc`/shims/state, **patch the constants to a temporary HOME**
  (`core.HOME`, `core.DATA_DIR`, `core.SHIM_DIR`, …) so the user's real files are not changed.
- PTY tests: `import ptyterm`, `new_session` → `write(..."command\r")` → `read` (base64) → `kill`. If
  you run `claude` for a test, exit with `\x03` and then `kill` the session.
- UI tests: there is no Chrome; use headless Firefox
  `/Applications/Firefox.app/Contents/MacOS/firefox --headless --profile <dir> --no-remote --window-size=1300,1100 --screenshot out.png file://…`.
  The screenshot is taken on the `load` event, so build a harness page that *stubs* `window.fetch` with
  JSON from the real API results and run the test actions directly in the chain `initRuntimes().then(route).then(...)`
  (not `setTimeout`). Disable CSS transitions if needed (`#job{transition:none}`). For content
  rendered asynchronously (xterm.js), hold the `load` event with an `<img>` from a small server that is deliberately slow.
- After changing a `.py`, restart the server (`kill $(lsof -ti tcp:8765)`, then run it again). Static files
  are served with `Cache-Control: no-cache`, so refreshing the browser is enough.

## Things to remember

- The user's shell is **zsh**: `$VAR` is not word-split (use an array `(${=VAR})`), and `timeout` does not exist.
- Do not run actions that change the user's system during tests (brew install/uninstall, `herd use`,
  `nvm alias`, saving `/etc/hosts`, Finder/admin dialogs) unless asked. If you need a test container/project,
  create it in the scratchpad and then clean up (`docker rm -f`, `compose down -v`, `rmi` the newly pulled images).
- The app's persistent data: `~/.service-admin/` (`state.json`, `bin/`, `env.zsh`, `backups/`, `logs/`,
  `php-shims/`).
- Free Herd has no `services:*` (needs Herd Pro). The Herd CLI is at
  `~/Library/Application Support/Herd/bin` (`herd`, `php84`, `composer`, `laravel`).
