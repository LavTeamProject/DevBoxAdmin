# Work Plan (Roadmap)

This document is the **single place** where the project's work plan is described. If a piece of work is not in this
file, it has not been agreed. And if an item is here but the order of phases is violated, that is also an error.

Legend: ⛔ dropped · ✅ done · 🔶 written, partially verified · 🔜 next · ⬜ not started · 🚫 out of scope (deliberately not doing)

---

## Principles binding on all phases

1. **No dependencies.** Backend is pure Python stdlib, frontend is vanilla JS/CSS, no build step, no CDN.
2. **`127.0.0.1` only.** The panel never listens on the network. Access from a MacBook goes through an SSH tunnel:
   `ssh -L 8765:127.0.0.1:8765 mac-mini`.
3. **Paths come only from the server registry.** The browser can never request an arbitrary path.
4. **Actions that change the system must have `data-confirm`** and go through `start_job` /
   `start_steps`, not be executed inside the request handler.
5. **The panel must be able to install itself on a clean macOS.** This is the goal of the product, not a wish:
   one panel that sets up and controls the whole machine. Anything that gets in the way of this is a defect.
6. **Every phase is useful and verifiable on its own** — no phases that merely "prepare" another one.
7. **No hacks.** We build it in the right form straight away; temporary bridges are forbidden, even if
   they speed up the current step.

---

## Phase 1 — Diagnostics (✅ done)

Goal: answer "what is already ready on this machine?", changing nothing.

| Item | Status |
|---|---|
| `profiles.py` — profile catalog (Foundation/AI/Flutter/iOS/Backend) + one detector per tool | ✅ |
| `mobile.py` — Xcode and the active version, license, runtimes and simulators, Flutter/FVM, Android SDK, CocoaPods, fastlane, JDK | ✅ |
| `projects.py` — repository scan, status/branch/worktree/log/diff, `gh` (PR/issue/CI) | ✅ |
| `agents.py` — agent sessions bound to PTY sessions, + CPU/RAM per process tree | ✅ (the PTY binding only started working in 2.7 — see the fix) |
| 4 UI pages + the sidebar group "Development", the *Read-only mode* banner | ✅ |
| i18n **RU (default) + EN**, switch without network requests (`load()` / `render()`) | ✅ |
| `ptyterm.peek()`, `core.ps_snapshot()` / `pid_tree_stats()` | ✅ |

The technical findings that **must be preserved** are listed in `CLAUDE.md` (Python ≥ 3.11,
`GIT_OPTIONAL_LOCKS=0`, `--no-renames`, per-card loading of summaries, `flutter --version` is
never run).

**Remainder of Phase 1 — closed (debts after Phase 2):**

- ✅ **The whole interface is in RU/EN, no Indonesian text.** The old pages (Dashboard, Packages and services, Docker,
  Herd/PHP/Node, Languages, Configuration files, terminal, `index.html`) were moved to `t()` — **≈550 keys** in the
  extension dictionaries `static/i18n-ext-*.js`. Verified: `node check-i18n.js` (ru = en = 1198 keys),
  **all 906 keys used in the code are defined**, and a walk through **24 pages in two languages** in the browser gave
  **0 JavaScript errors and 0 Indonesian words** on screen.
- ✅ **Backend messages:** ≈190 `ApiError`s got a Russian text + `code` + parameters and an EN translation
  (`err.<code>`); the "save anyway?" check now goes by error code, not by text (two such checks
  in `config.js` and `packages.js` would otherwise have broken).
- ✅ **Raw errors instead of understandable ones:** external tool not found → a "Tool not found" card with a link
  to "System setup"; empty/non-text JSON from a tool → `core.loads_or` / `bad_output`. Found
  and fixed a **Phase 1 bug**: `brew services info --all --json` with no services prints empty output, not `[]`,
  and the "Packages" page crashed for any user without services (including right after Homebrew was installed);
  with Docker lacking the `compose` plugin, the main Docker page crashed. **Verified on a clean macOS (VM):** not a single
  "internal error" on any GET route, Docker — "tool not found".
- ✅ **macOS access prompts on first launch** are explained: a hint on the projects page after a 4 s wait
  and a card on the "System setup" page.
- ✅ **Package catalog in EN:** 123 strings (15 categories + 108 descriptions from `svc.py`) translated by text
  (`static/i18n-ext-catalog.js`, key `cd.<Russian text>`; no translation — the original is shown); coverage
  verified by a script (no uncovered strings).
- ✅ **Merging an agent task's branch** (debt from 2.7): `POST /api/agents/task/merge`, the button "Merge into the main branch"
  with a preview (target branch, number of commits, **conflict forecast** via `git merge-tree --write-tree`,
  changes nothing). `git merge --no-ff` only if: the agent session is stopped, the task's worktree and the main
  checkout are clean, the main checkout is on a named branch, the branch has new commits. Conflict → automatic
  `merge --abort`, the main checkout stays as it was, the job fails. No push is done. **Verified (14 checks)
  on throwaway repositories:** successful merge, conflict (predicted in advance and rolled back), all refusals.
- ✅ **Full `install.sh` with opening the browser on a clean macOS (VM):** Safari had not been running before the installation, and afterwards
  it holds connections to `127.0.0.1:8765`, the launcher exited. **The interface on clean-VM data:** 36 renders
  (18 pages × RU/EN) — 0 JS errors, 0 raw errors, 0 Indonesian words.
  ⚠️ I did not see the browser window in the VM visually (with my own eyes) — only by connections; and on the host, screenshots of the
  panel's browser window are unavailable.
- ✅ **VM test-bench bug:** copying the repository into the VM via the shared folder (`tar` from `/Volumes/My Shared Files`)
  silently broke off — an incomplete copy ended up in the VM (some static files were old). Now the copy is
  a stream over SSH (`tar -c … | ssh … tar -x`) and a **mandatory `shasum` check of all files**. The backend checks in the VM
  before that were correct (Python was copied in full); the interface in the VM was not looked at after the migration by the previous check.
- ✅ the internal Indonesian key `Baterai` in `stats.py` was replaced with `Battery` (it is compared in code, not visible
  to the user).

---

## Phase 2 — The panel becomes self-sufficient (🔜 next)

The order within the phase is **mandatory**: 2.0 → 2.1 → 2.2, and only after them 2.3+.

### 2.0 Bootstrap: launching on a clean macOS (✅ verified in the VM, except as noted)

The problem this solves (verified against facts):

- a clean macOS has **no Python at all** (`/System/Library/Frameworks/Python.framework` is absent);
- Command Line Tools provide only `/usr/bin/python3` = **3.9.6**, while the code requires 3.11 because of `tomllib`;
- so **the panel cannot start itself** — there is nowhere to show the "friendly interface".

The solution — **embed our own interpreter**, rather than occupy the system one:

- ✅ `install.sh` downloads a standalone CPython from `python-build-standalone` into
  `~/.service-admin/runtime/python/` (`fetch-python.sh`: release lookup, SHA256 verification, atomic
  installation, idempotency). **Verified on a clean macOS 26.6 in a VM (tart):** Python 3.12.15,
  the panel runs on it (`/api/runtime` → `bundled: true`), a repeat run downloads nothing.
  **Not verified:** the wrong-checksum scenario.
- ✅ The launcher is built via `/usr/bin/osacompile` (`macapp/launcher.applescript`, the icon
  `macapp/AppIcon.icns` is in the repository) instead of `swiftc`. **Verified:** build, signing,
  server start and shutdown in 2 s. **In the VM on a clean macOS both paths were verified:** via LaunchAgent
  and the fallback one (agent stopped → the app starts the server itself with the bundled Python).
  **Not verified:** the "server not responding" dialog; visually — that the page opened in the guest's browser.
- ✅ On a clean macOS it is acceptable to assume only: `curl`, `tar`, `osacompile`, `open`, `osascript`
  (+ `shasum`, `grep`, `sed`, `uname`, `PlistBuddy`, `codesign`, `defaults`, `sips`/`iconutil`).
  **Confirmed in the VM:** all these utilities are present on a clean macOS 26.6.
- ✅ `install.sh` runs to the end without a single prerequisite: download → unpack →
  build the app → start the LaunchAgent (~10 s). **Confirmed in the VM.** The check found and
  fixed a bug: `git rev-parse` in `install.sh` invoked, on a clean system, the Apple stub
  that opened the CLT installation dialog in the middle of the installation; now `git` is called only when
  CLT is present. Opening the browser (without `--no-open`) was not visually verified in the VM.
  ⚠️ The same applies to any `git`/`python3` call from the panel on a clean system — take into account in 2.1.
- ✅ Version check: `/api/runtime` + a note in the sidebar "Running on a non-bundled Python" (RU/EN).
  **Verified:** in the browser on the system interpreter (the note is visible) and in the VM on the bundled one
  (`bundled: true`).
- ✅ `tomllib` gets a fallback path (`tomllib` → `tomli` → TOML validation is disabled with an honest
  message). Verified on Python 3.12 and 3.9.6 (with and without `tomli`). **The project owner's permission
  was obtained** — see `CLAUDE.md`, "Keputusan arsitektur". This is a safeguard, not the main path.

### 2.1 The "System setup" page (🔶 verified in the VM, except as noted)

The first launch on a clean machine shows **not an empty dashboard, but a wizard** (`setup.py`, `static/setup.js`,
route `#setup`, a banner on all pages, auto-redirect on first open).

- ✅ What the panel needs for itself: Command Line Tools, Homebrew, Git, Python (bundled) — status
  "present / absent / first X". Verified in the VM on a clean system.
- ✅ **Homebrew** is installed by a button: the official installer is downloaded to a file, its sha256 is written to
  the log, then it is run (`NONINTERACTIVE=1`, `SUDO_ASKPASS` → the macOS system password dialog). Progress
  in the "Processes" panel. **Verified in the VM:** installation up to `brew 7.0.9`, wizard → `ready=True`.
  ⚠️ **Not verified:** the password dialog itself — the vanilla image has `sudo` without a password, `askpass` was not invoked.
- 🔶 **Command Line Tools:** the button launches the **native Apple dialog** (`xcode-select --install`) and
  waits for CLT to appear (up to 45 min). **Verified in the VM:** the dialog opens; the wait notices
  CLT appearing (installed bypassing the dialog via `softwareupdate`) and finishes with code 0,
  unblocking Homebrew and Git. **Not verified:** successfully completing the Apple dialog itself —
  in the VM it refused: "24.27 GB needed, 18.53 GB available" (a 50 GB image; it cannot be extended — the Recovery
  partition sits before the free space, and SIP forbids deleting it).
- ✅ Disk space warning: if less than 26 GB is free, the wizard says that Apple's download
  may need ~25 GB. This is a warning, not a prohibition: the threshold was measured on one macOS version.
- ⛔ Dropped: "after installing Homebrew, offer Python and restart on it". Decided otherwise:
  the main path is the **bundled** Python (2.0); the system/brew Python is not used for the panel itself.
- ✅ **Protection against CLT stubs** (found in the VM): `/usr/bin/git`, `python3`, `make`, `xcrun` and others without CLT are
  stubs that open an Apple dialog when called. `core.run()` now does not run them (it returns
  "CLT not installed"), the Phase 1 detectors too. **Verified in the VM:** walking all GET endpoints on a clean
  system does not trigger the dialog (before the fix, `git --version` from a detector would have triggered it).
- 🔶 "The rest of the interface does not pretend to work": a "Missing: …" banner on all pages and
  auto-redirect to the wizard are done. **Not done:** the Phase 1 pages, when brew/docker are absent, still
  show raw Python errors (`/api/services` → "Expecting value…", Docker → `[Errno 2] …`).
  Needed: each page gets its own understandable "what is missing" + an "install" button.
- ✅ The wizard's actions are written to the audit log (see 2.2): request, `job_id`, job completion with the code.

**Facts about a clean macOS found during verification (take into account in UX):**

- On first launch **macOS shows access prompts** for "Documents" and "Desktop" for the Python
  from the LaunchAgent. Until the user clicks "Allow", requests to `/api/projects`, `/api/files`,
  `/api/herd/suggest` and others **hang silently** (verified: >90 s, then they respond). Needed: explain this
  in the wizard/on the projects page, rather than leave an empty screen.
- The CLT dialog may refuse because of disk space (see above), and the panel does not learn about it — it only waits.

### 2.2 Audit log (✅)

It becomes mandatory exactly here: the panel starts installing software and asking for the administrator password.
Logging **already works** (it was needed for 2.1), the page does not.

- ✅ Every POST and the completion of every job are written to `~/.service-admin/audit.log` (JSONL: time,
  action, sanitized parameters, result, duration, code, `job`). Permissions `0600`, size-based rotation
  (2 MB × 3). Not written: terminal input (`/api/pty/write`), passwords/tokens/keys/`env`
  (replaced with `***`), file contents (length only), credentials in URLs. **Verified in the VM**
  (CLT and Homebrew records) and by a unit check of the sanitizer.
- ✅ The **Audit** page (`#audit`, `static/audit.js`, `GET /api/audit`): filters by action, result
  (success/error) and dates, "Show more" pagination, Russian and English without requests when switching language.
  **Verified on the working machine** with test data (5 and 455 records): filters, pagination, RU/EN,
  broken lines are skipped. **In the VM**, `GET /api/audit` returns the real records of the CLT and Homebrew installation (5 records, filters by action/result work); the page was not opened visually in the VM.
- ✅ Initiator identity: every audit record has a `by` field — `panel` | `agent:<name>` | `system:<what>` (backup scheduler). The source is `audit.INITIATOR` (ContextVar): set by the POST handler and the agent gateway; a job remembers the initiator at start (`job["by"]`), so the "job end" is also signed. Old records without the field are read as `panel` (or an agent by the `agent` field). The "Audit" page: a "Who" column and an initiator filter. Verified on mocks; a live agent — not.
- Without this it is impossible to answer the question "what did the panel just do to the machine?".
- (Historical note: before this step the log did not distinguish the initiator; now it does — see above.)

### 2.3 Environment snapshots (✅ verified on the working machine and in the VM)

The `#snapshots` page, `snapshots.py`. A snapshot changes nothing in the system: only its own file is written.

- ✅ `~/.service-admin/snapshots/<YYYYMMDD-HHMMSS>.json` (folder `0700`, file `0600`, atomic write):
  Homebrew (`list --formula/--cask --versions`, `tap`, `bundle dump` → Brewfile), versions of all
  languages/runtimes, the active Xcode + installed Xcodes + simulator runtimes, Flutter, Android SDK,
  the status of each profile item, macOS version and arch., panel version. A snapshot does **not** include
  file contents, environment variables, passwords, tokens. A label is ≤ 80 characters, the limit is 200 snapshots.
- ✅ **Comparison:** two snapshots or a snapshot and "Now" → by section added / removed / changed.
  **Verified in the VM on a real "before and after":** snapshot → `brew install jq` → the comparison showed
  `+jq 1.8.2`, `+oniguruma` and the version change of `jq` in the "Foundation" profile (1.7.1 → 1.8.2).
- ✅ Without Homebrew a snapshot is still built (section `brew: {available: false}`); if `brew` did not respond within the
  timeout, the snapshot is marked "incomplete", and the comparison warns about it.
- ✅ Viewing a snapshot's Brewfile; deleting a snapshot (with confirmation; the `id` is checked with a regular
  expression — a `../` bypass is rejected).
- ✅ **The project registry became writable** (`projects.json`, `0600`, atomic write, unknown
  keys are preserved): add a project by path, remove it from the list (the folder is not deleted; ones found
  by the scan cannot be removed). Gates: git repository only, inside the home folder, not hidden folders and
  not `Library`, no symlink pointing outside. **Verified:** rejected `/etc`, `~`, hidden ones, `Library`,
  a symlink to `/tmp`, a non-repository.
- ✅ **Project presets:** an editor + test/build commands. Commands are **only saved**, running them is in
  2.8. This is a command, not a shell expression: `; & | < > \` $` and line breaks are rejected.
- ✅ A path-case bug found and fixed: on case-insensitive APFS `~/code/app` and `~/Code/app` are
  one folder; without canonicalization a project was doubled (scan and manual addition). Now `_canon()`.
- ⚠️ Not verified: a snapshot on a machine with a very large number of packages (brew timeout 90 s); visually, in the
  VM window the pages were not opened (the API was verified there, the interface — on the working machine).
- Creating a snapshot takes ~7 s on the working machine (142 formulae) — a synchronous request, not a job.

### 2.4 Installation profiles run (✅ verified in the VM)

`profiles.py` (`plan()`, `install()`), `GET /api/profiles/plan`, `POST /api/profiles/install`, buttons on the
"Installation profiles" page. Flow: **plan (changes nothing) → confirmation with a package list → job**.

- ✅ `POST /api/profiles/install` → `core.start_steps`. Scope: "required" (`scope=required`), "everything
  missing" (`scope=all`), or specific items. **One `kind` for all profiles** (`profile-install`), rather than
  one per profile as originally written: two `brew install` runs in parallel conflict, so only one
  profile job runs at a time.
- ✅ Steps: `brew install` / `brew install --cask` (`SUDO_ASKPASS` in case a cask has a pkg installer),
  special cases — Rust (`brew install rustup` + `rustup default stable`).
- ✅ **Idempotency via detectors:** the plan is rebuilt with `refresh` at launch time,
  anything already installed gets the `skip` action; a repeated run answers "Nothing to install" (409).
  **Verified in the VM.**
- ✅ Before installing — a preconditions check: no CLT → `needs_clt`, no Homebrew → `needs_homebrew`
  (the UI leads to "System preparation"). Verified with a unit test on the working machine.
- ✅ **Snapshot before and after** (2.3) is taken automatically by the job steps; the job log shows the
  difference, and the final step re-detects what is installed and **fails the job** if anything is not detected
  after installation (it does not silently report success).
- ✅ What cannot be installed from the panel stays as an item with a note: Xcode and Android Studio — "manually",
  CLT/Homebrew — a link to "System preparation", simulator runtimes — "later (2.5)".
- ✅ **Verified in the VM with real installs:** `fzf`+`ripgrep` (formula, with a dependency), `codex` (cask),
  `rustup` + `rustup default stable` (Rust detected afterwards), `openjdk@21` (JDK detected afterwards), `yq`
  by clicking in the UI through an SSH tunnel to the VM (confirm → job → page refreshed).
- ✅ Catalog errors found when checking against Homebrew: `flutter` and `codex` are **casks**, not formulas
  (`brew install flutter` without `--cask` did not match the catalog); `xcodes` is now in homebrew-core,
  the `xcodesorg/made` tap is not needed.
- ✅ Detectors changed so that the installation is visible: JDK from Homebrew (`java_home` does not see it without
  a `sudo` symlink — verified in the VM), Rust (`rustup` puts proxies in `opt/rustup/bin`).
- ✅ The "Python 3.12" item is now an **optional** development tool (`python3.12`), not "Python for the
  panel": the panel runs on the bundled Python (2.0).
- ⚠️ **Not verified:** the administrator password dialog for casks (the vanilla image has passwordless `sudo`); heavy
  profiles in full (Flutter SDK ~1 GB, Docker/OrbStack, PostgreSQL/MySQL as services); a network failure
  in the middle of an installation.
- ⚠️ `docker` in the Backend profile installs OrbStack — the choice between OrbStack and Docker Desktop in the UI is not
  implemented (it remains a hint).

### 2.5 Mobile toolchains (🔶 partially verified)

`mobile_ops.py` (`mobile.py` remains read-only), `POST /api/mobile/op {op, params}`, buttons on the
"Mobile toolchains" page. The browser names an **operation and an identifier from the server registry** (an Xcode from the list of
installed ones, a UDID from `simctl list`, a project from the scan/registry) — not a path or a command. `build()` is a pure
function (assembles commands, runs nothing), execution is `start_steps` (job + audit); admin actions go
through the system password dialog (`osascript … with administrator privileges`).

| Operation | What it does | Verification status |
|---|---|---|
| `sim.screenshot` | PNG of the running simulator in `~/.service-admin/screenshots`, shown in the window | ✅ **on a real simulator** (3 MB PNG) |
| `sim.boot` / `sim.shutdown` | start / stop a simulator (state is checked beforehand) | ✅ **on a real simulator**, state was restored; a repeated `boot` was rejected |
| `sim.erase` | erase simulator data (a `danger` button with confirmation by name) | 🔶 command assembled and validated by dry run, **not executed** (destructive) |
| `flutter.doctor` | Flutter diagnostics | ✅ on a real machine (15 s); it also found unaccepted Android licenses |
| `flutter.pub_get/analyze/test/build_apk` | in a project from the registry; a pinned FVM SDK takes priority | 🔶 commands assembled by dry run (cwd = project), not executed (they modify project files) |
| `flutter.channel` | `flutter channel X` + `flutter upgrade` | 🔶 dry run; not executed (modifies the SDK) |
| `fvm.install` / `fvm.use` | the version is validated by a regular expression | 🔶 validation verified (`; id`, `$(id)`, `../x` rejected); FVM is not on the machine |
| `pod.install` | in the project's `ios/`, if a `Podfile` exists | 🔶 rejections verified; execution — no |
| `android.licenses` / `android.install` | `sdkmanager` with an automatic `y` answer to licenses; the package identifier is checked by a regular expression | 🔶 validation verified; **not executed** (accepting licenses is a legal act by the owner) |
| `xcode.select` | `xcode-select -s` for an Xcode from the installed list + a `-p` check | ⚠️ **not verified**: requires the administrator password and a change to a system setting |
| `xcode.first_launch` | `xcodebuild -runFirstLaunch` (admin) | ⚠️ **not verified** (the owner's Xcode has already done it — the operation refuses) |
| `xcode.download_platform` | `xcodebuild -downloadPlatform iOS` | ⚠️ **not verified** (several GB) |

- ✅ **Rejections verified on a clean macOS (VM):** without Xcode/Flutter/FVM/Android/Podfile every operation gives a
  clear error ("Flutter SDK not found", "FVM is not installed"…), and the CLT dialog does not appear. The guard against
  CLT stubs (`_need_tools`) stands before every operation except Android.
- ✅ Rejected by dry run: a foreign path/`/etc`/`/tmp` instead of a project, a forged UDID and Xcode, an unknown
  channel/platform, shell characters in the version and in the SDK package identifier.
- ✅ **Done (L4):** `sim.runtime_delete` — deleting a simulator runtime (`simctl runtime delete <UUID>`), a list of deletable ones `GET /api/mobile/runtimes` (only `deletable`), confirmation — typing the name (`iOS-27-1`) is checked on the server, refused when a simulator of that runtime is running; a button on the "Mobile toolchains" page. **Verified against the real runtime list (read-only; deletion was NOT performed)**: 3 runtimes, `rt_busy` for 26.5 (a simulator is running on the host), command assembly for the rest, rejections (wrong confirmation, bad/unknown UUID). Previously: ⬜ postponed — deleting simulator runtimes (`simctl runtime delete` takes a UUID from
  `simctl runtime list`, not an identifier from `simctl list` — the syntax cannot be verified, the operation is
  destructive), creating an AVD (`avdmanager create avd` — needs the ABI of a system image, which is not in the data),
  installing an `.app` on a simulator (needs a choice of build from the project — that is 2.8).
- ⚠️ Admin operations (`xcode.select`, `xcode.first_launch`) cannot be verified in the VM in principle: Xcode
  requires an Apple ID (see "Deliberate exceptions"); on the working machine — only with your password and a change to a
  system setting. It is up to you whether to verify them live.

### 2.6 Writing to Git and projects (✅ verified on disposable repositories; without a real remote)

`gitops.py` (`projects.py` remains read-only for git), `POST /api/git/op {op, params}`, the "Git" card on the
project page. A project comes only from the registry; branches, remotes, stashes and files are **checked against the real state of the
repository**; commands are argument lists, paths come after `--`, branch names cannot start with `-`.

| Operation | Safety rules |
|---|---|
| `git.fetch` | `--prune`, remote from `git remote` |
| `git.pull` | only `--ff-only`; on divergence it refuses, no merge commit is created |
| `git.push` | **never `--force`**; without an upstream — `push -u origin <branch>` |
| `git.switch`, `git.branch_create`, `git.branch_delete` | branch name: regular expression + `git check-ref-format`; only `-d` (merged) deletes; `-D` — only with the project name typed |
| `git.stash_push` / `git.stash_pop` | with `--include-untracked`; the stash index is checked |
| `git.add` / `git.unstage` / `git.commit` | the file list is checked against `status`; a commit is **from the index only**, an empty index → refusal |
| `git.discard` / `git.clean` | reverting and deleting untracked files: **the server requires typing the project name** (`confirm`), otherwise 428 — this is a "double confirmation" that cannot be bypassed from the UI or an agent |
| `git.worktree_add` / `_remove` | only inside `~/Worktrees/<repo>/<branch>`; remove — without `--force`, only an additional worktree inside the root |
| `editor.open` | an editor from `EDITORS`, installed; taken from the project preset |

- ✅ **Verified on disposable repositories** (a local `origin.git` + a clone + a "second developer", a temporary
  `HOME`; 38 checks): fetch, pull fast-forward, branches (create/switch/delete `-d` and `-D`), stage/unstage/commit
  (the commit contains only what was staged, the rest stayed modified), push with `-u`, stash/pop, revert and clean
  with confirmation checks (without it 428, with a wrong one 428, with the project name — executed), worktree (created under
  `~/Worktrees`, found by the scan as a project, removed; the main checkout cannot be removed), an editor without a choice refuses.
- ✅ **Rejections and divergence:** with diverged branches `pull --ff-only` finished with code 128 without a merge commit,
  `push` was rejected (non-fast-forward) — `origin` did not change. Substituted `-x`, `a;b`, `../x`, `a..b`, a foreign
  remote, a foreign project, `../../etc/passwd` instead of a file, an unknown operation — rejected.
- ✅ Through the UI: a commit from the card (job → the index was updated); files with spaces and Cyrillic are shown
  correctly (in Phase 1 such paths were parsed incorrectly and the list was truncated to 80 — now it is an exact `status -z`).
- ✅ Installation and scanning: `~/Worktrees` was added to the scan roots, so worktrees are visible as projects.
- ⚠️ **Not verified:** `push`/`fetch` to a **real** remote (GitHub over SSH/HTTPS): `GIT_TERMINAL_PROMPT=0`
  and `GIT_ASKPASS=/usr/bin/false` do not allow a password to be requested, so only what is already configured works
  (a key in the agent, `osxkeychain`) — real sign-in was not verified; repository hooks (`pre-commit`) run as
  in normal work; `editor.open` with a real editor; merge conflicts after `stash pop`;
  the look of the card in a screenshot (the browser panel was hidden).
- The test/build presets (from 2.3) are still only stored — running them is in 2.8.

### 2.7 AI sessions are managed (✅ verified with a stub agent; with real agents — partially)

`agent_tasks.py` (`agents.py` remains monitoring only), the registry `~/.service-admin/agents.json` (`0600`,
atomic write), the "Agent tasks" section on the "AI sessions" page, `window.focusSession()` in the terminal.

- ✅ **"New task" in one action:** a project from the registry → a separate worktree in `~/Worktrees` (via `gitops`)
  on a new branch `agent/<name>-<id>` → the agent in a new PTY session **inside the worktree**; the main checkout is
  not touched (verified). The task's base commit is remembered.
- ✅ **Launch only from installed agents** (`known_agents()`), the command is an absolute path through
  `shlex.quote`, **without "skip confirmations" flags**. The task description is **not inserted into the agent
  automatically** (verified) — only with the explicit "Send to session" button (the text as input + Enter; control
  characters are rejected, only the length is written to the audit).
- ✅ **Stop / restart:** stopping terminates the session's process group; the task stays with its worktree,
  "Start" brings up a new agent in the same worktree (a restart counter). A task cannot be deleted while the
  session is alive; "remove with worktree" is `git worktree remove` **without `--force`**: with unsaved changes git
  refuses and the data stays (verified).
- ✅ **Busy / idle status is a heuristic** (output in the last 3 s or CPU > 5 %) and **is labeled as such in the
  UI** (an asterisk + an explanation), not presented as a status from the agent. There are also states: being created, agent
  exited (the shell remained), stopped, not created.
- ✅ **A task diff limited to its worktree:** changes relative to the base commit (committed and
  uncommitted), untracked files, the agent's commits; a file diff — only for files from this list
  (`../../etc/passwd` → 404), with a 300 KB limit. Verified in the UI too (+/− highlighting).
- ✅ **A Phase 1 bug was fixed:** `ptyterm.list_sessions()` did not return the shell's `pid`, while `agents.sessions_info()`
  uses it to link agent processes to PTY sessions — so the link **never worked** (agents in sessions
  were shown as "outside the panel"). It now returns it; for tasks, monitoring is read without the cache (`fresh=1`).
- ✅ Verified automatically: 28 checks on a disposable repository with a stub agent (creation, worktree and
  branch, the agent in the right folder, the description does not leak, sending text, changes/diff/rejections, stop, repeated
  stop/start, rejections for an uninstalled agent, an empty name, a foreign project, a foreign id).
- ⚠️ **Not verified on the merits with a real agent:** in the test bench a real Claude Code was started twice in a PTY
  (by a test mistake: the panel puts `/opt/homebrew/bin` at the start of `PATH`) — this confirmed that the real binary
  starts in a session and shows its screen (`Welcome to Claude Code`), but in a temporary `HOME` without an account
  sign-in, so the agent's work on a task was not verified. Not verified: the behavior of Codex/OpenCode/Gemini/
  Aider, detecting "agent exited" for their processes, passing the task description (each agent has its own
  input format), sessions after a panel restart (PTYs live in memory — the task becomes "stopped").
- ✅ Merging a task branch into the main one from the panel — added later (see "Phase 1 remainder — closed").

### 2.8 Automation (✅ verified with a fake `gh`; real GitHub was not touched)

`runs.py`, the "Runs" page (`#runs`), buttons on the project page, `GET /api/runs`, `POST /api/runs/start`,
`GET /api/gh/workflows`, `POST /api/gh/workflow_run`.

- ✅ **The test/build buttons** run **only the command from the project preset** (2.3). The preset becomes executable,
  so a **command policy** was added (`projects.runnable_argv`): known tools are allowed (`flutter`, `npm`,
  `cargo`, `make`, `go`, `gradle`, `xcodebuild`, `pytest`, … — the full list is in `RUN_TOOLS`) and `./scripts` inside
  the project (an executable file; a symlink pointing outside is rejected); for interpreters `-c`/`-e`/`--eval`/`-r` are forbidden.
  The check is applied **both on save and on launch** — a hand-edited presets file does not bypass it (verified).
  ⚠️ This is **not protection against arbitrary code**: `npm test` and `make` by definition execute project code. The list
  filters out the foreign and the accidental (`rm`, `curl`, `osascript`, `bash -c`), not a trusted project.
- ✅ Launch: an argument list without a shell, `cwd` = the project, **its own process group and a hard 30-minute timeout**
  (when it expires the whole group is killed — verified, no child processes remain), output to the job log and to a file.
- ✅ **Run history:** `~/.service-admin/runs.jsonl` + `runs/<id>.log` (files `0600`, folder `0700`), at most 300
  latest, log up to 5 MB; success / error (with code) / time limit; filters by project, type and result;
  log viewing (the id is checked — a `../` traversal is rejected). The "Runs" page + "Recent runs" on the project
  page. All runs are also written to the audit log.
- ✅ **GitHub Actions:** a list of active workflows (`gh workflow list`), launch `gh workflow run <id> --ref <branch>`.
  The workflow and branch are checked against the real lists; a launch is an action in an external system (CI, possibly paid
  minutes or a deploy), so it **requires typing the project name on the server**; without `gh` or with a non-GitHub remote — a refusal.
  Verified **with a fake `gh`**: exactly one command arrived in it, `workflow run 123 --ref main`.
- ✅ Verified automatically (42 checks: command policy, success/error/timeout, history and filters, log, file
  permissions, a hand-edited preset, GitHub rejections) and in the browser (buttons, history, log, the "Runs" page, a workflow
  launch via a form with name entry).
- ⚠️ **Not verified:** a real `gh` and a real GitHub repository (authorization, workflows with `inputs` — they are not
  supported), `flutter`/`npm`/`cargo` as real toolchains (`./script` and `make` were verified), launch from the VM.
- ✅ `workflow_dispatch` parameters (inputs, `-f name=value`, up to 10, a value is a single line of up to 200 characters), cancelling a running run (`gh run cancel`), re-running and "re-run failed" (`gh run rerun [--failed]`): `runs.py`, a list of recent runs with buttons on the project page; catalog operations `github.run_cancel` / `github.run_rerun` (L3, not in `AGENT_OPS`). **Verified with a FAKE gh** (arguments `workflow run 1 --ref main -f env=staging -f dry=true -f n=3`, `run cancel 111`, `run rerun 222 --failed`; rejections: bad names/values, 11 parameters, wrong confirmation, an unknown/injected run_id, cancelling a finished run, re-running a running one). ⚠️ The real `gh` and GitHub were not verified.

---

## Verification on a clean macOS (🔶 — the VM is deployed, 2.0 verified; next, run every phase through it)

The project owner's original decision: write it down and do not execute it. **Later the owner decided to verify in
a VM rather than on the working machine — the VM is deployed** (tart, image `clean-mac`, NAT without port forwarding).
Rule: changes touching installation/first launch are verified here, not on the working machine.

Why this is needed: the panel must work on a freshly installed system, and **there is nowhere to verify that on the working machine**
— everything is already installed there. I checked: imitating an empty machine through an empty `PATH`
and a temporary `HOME` does not help, because the detectors look at absolute paths and keep seeing the
real Xcode, CLT and Flutter. Pretending will not work — a genuinely clean system is needed.

**Verified that this is possible on this hardware:**

| What | Value |
|---|---|
| `kern.hv_support` | 1 — the hypervisor is available |
| Hardware | Apple M4 Pro, 24 GB RAM |
| Free disk space | 180 GB |
| Virtualization tools | **none installed** (no `tart`, UTM, VMware, Parallels, QEMU) |

**What needs to be done when we get to it:**

- ✅ Install `tart`. **The tap `openai/tools` does not exist.** Tart is made by Cirrus Labs (`cirruslabs/cli`),
  but on Homebrew 7 the formula does not install (`depends_on macos:` is disabled). A working path: the official
  `tart.tar.gz` from GitHub Releases (2.32.1, SHA256 checked), into `~/.local/opt/tart`, a symlink in
  `~/.local/bin`. Without sudo.
- ✅ Clone a clean image (downloaded, 52 GB on disk): `tart clone ghcr.io/cirruslabs/macos-tahoe-vanilla:latest clean-mac`
  (~25 GB). The `vanilla` variant is macOS **without Xcode and Homebrew**, exactly what is needed.
- ✅ Mount the repository into the guest (`tart run --dir=repo:…:ro`; it is copied into the guest's `~/`, because
  `install.sh` writes to `build/`).
- ✅ Run the full cycle: `install.sh` ✅ → the "System preparation" wizard ✅ → installation profiles ✅ (run in a clean VM, see `../../manuals/install-clean-mac.md`).
- 🔶 Automate the check over SSH (`ssh admin@$(tart ip clean-mac)`, password `admin`),
  **It works** (`sshpass` + `tart ip`). **Screenshots of the guest screen cannot be taken over SSH**
  (`screencapture` does not see the display) — another way is needed (for example, a snapshot of the VM window from the host).
- 🔄 **It used to say: "tart is a verification tool, not part of the product".** The owner's decision has changed: the panel now manages VMs
  (Phase 5, `vm.py`). tart is still NOT included in the distribution and NOT required: the panel works without it, and the VM page shows "tart not found".
- ⚠️ To install and run the VM, the sandbox restriction must be lifted for the duration of these steps: writing goes
  outside the working folder, and `brew install` needs the Homebrew cache.

**Caveat:** Xcode will not appear in the VM (it needs an Apple ID and ~15 GB), so the VM verifies the installation path,
not the "three Xcodes and simulators" scenario — that is covered by the working machine.

---

## Phase 3 — Recovery and backups (✅ verified on the working machine and in the VM)

`backups.py`, the `#backups` page, `GET /api/backups`, `POST /api/backups/{config,run,verify,restore}`.

**The "where to back up" decision (made):** a local folder or an external drive, the path is configurable (default
`~/Backups/Service Admin`); **no cloud** — deliberately, in the first version. The folder must be only inside the home folder or under
`/Volumes/…`, not the home folder itself, not `Library`, not `~/.service-admin`, not inside the folder being copied; it is created `0700`,
files `0600`.

- ✅ **A `git bundle` for every registered repository** (`--all`: full history, branches, tags). Empty repositories
  and linked worktrees (the same repository) are skipped; if the refs did not change, the copy is not duplicated
  ("no changes"). **Verified:** the bundle clones and contains the history, a tag and the branches.
- ✅ **Copying data folders:** folders added by the user (inside home, without hidden ones and `Library`, a 20 GB limit
  per folder) and the panel's own data (without `runtime/`, `tmp/`, `screenshots/`, `worktrees/`) — `tar.gz` archives.
- ✅ **Keeping the N latest copies** of each source (1–30); the extras are deleted.
- ✅ **Every copy is verified immediately.** ⚠️ Found during verification: `git bundle verify` **lets a truncated bundle through**
  (it checks the header, not the whole pack) — so a bundle up to 500 MB is cloned into a temporary bare repository and
  goes through `fsck`; larger ones get a lightweight check, **and the UI states "lightweight check" outright**. A corrupted
  copy is not saved (verified).
- ✅ **Panel: when it last ran, success/error:** a status card (successful / partial / error, time,
  duration, totals "new / unchanged / skipped / errors"), "last successful", a history of 15 runs with
  details, a list of real copies on disk (works without history too), "Verify" and "Restore" buttons.
- ✅ **Schedule:** a thread in the panel (a check every 5 minutes); a copy is made when the interval has passed since the last attempt
  (6 / 12 / 24 / 72 / 168 h); after a failure a retry happens no more than once an hour; anything missed because the Mac slept is caught up.
  **Verified:** the `due()` logic on 6 scenarios and the thread itself with a short period — one copy, a retry does not start
  until the interval ends, the run is marked "scheduled".
- ✅ **Restore does NOT overwrite originals:** a bundle is cloned, an archive is extracted into a new folder
  `~/Restored/<name>-<time>`; before extraction the archive entries are checked for `..` and absolute paths (**verified:**
  a planted archive with `../escaped.txt` was rejected, nothing went outside the boundaries). Copy paths from the browser are checked against the
  real list (`../../etc/passwd`, foreign and nonexistent ones — rejected).
- ✅ **Unavailable disk:** the external drive is not connected → the copy is marked with the error "external drive not connected",
  nothing is created in `/Volumes` (verified).
- ✅ Verified automatically (47 checks) and in the browser in RU/EN (saving settings, a refusal for `/etc` with translation,
  launch, verification, restore); **in the VM on a clean macOS:** a copy of the panel data, verification, restore into a new
  folder, the CLT dialog did not appear.
- ⚠️ **Not verified:** a real external drive (the refusal on disconnect was verified only on a nonexistent `/Volumes/…`),
  very large repositories and folders (limits and timeouts are set but were not measured), restoring panel data
  back "over" the original (by design — only into a new folder, moved manually), encrypting copies, cloud storage.
- ✅ A macOS notification when a SCHEDULED backup fails (and when the destination is unavailable, the drive disconnected): no more than once every 6 hours, RU/EN text by the system language (`core.notify`, the text is passed as osascript arguments). Verified: the texts, the rate limit, the scheduler path, a real `osascript display notification` call (rc=0).
- ⬜ Deliberately not doing: restoring "to the original location" in one click (overwriting originals); restoring only into a new folder `~/Restored/…`.

---

## Phase 4 — Agent Control API: machine control for AI agents (🔶 4.0–4.5 done; Codex/OpenCode/Gemini clients not verified)

**Principle:** do not integrate with each agent separately (Claude Code, Codex, OpenCode, Gemini,
a custom agent). The panel becomes an **operations platform**, and the agent is given restricted access to them.
Changing the model or the provider must not require rewriting the deployment mechanism.

**Dependencies (the phase does not start earlier):** 2.2 audit log, 2.3 snapshots, 2.4 install profiles
are in place, background jobs. An agent without audit and idempotent operations is an unmanaged risk.
The read slice (4.0) depends only on 2.2.

**Scope (owner's decision made):** the agent lives **on the client's Mac** (for example, a Claude Code installed
there) and connects to the panel locally. A local MCP is a sufficient architecture; a cloud
account and external authorization are not needed. Remote management of a fleet of machines is in "Out of scope" below.

**What this phase guarantees — and what it does not (honestly).** An agent on the same Mac usually has its own
Bash and can bypass any API with ordinary commands. Therefore:

- The real security boundary is the **confirmation queue in the panel, which a human approves**.
  The agent's credential does not create it: it sits in the MCP config, and the agent can read that config.
- The value of the API is **audit, idempotency, result verification, a single contract**, not isolation.
  Do not describe or sell this as "the agent is locked in".
- Real isolation (untrusted code, runners) is possible only in a VM — that is Phase 5.

Do not confuse with 2.7: there the panel *launches* agents in a PTY to work on code. Here the agent *controls
the machine itself* through the panel. The roles are separated, and permissions for them are configured separately:
the **developer agent** (code in a repository, allowed project commands) and the **administrator agent**
(software, containers).

### 4.0 Read slice: the first useful MCP (✅ verified with our own MCP client; with real agents — no)

`agent_gateway.py` (registry, permissions, tools, audit), `agent_socket.py` (Unix socket), `mcp_server.py` (MCP over stdio),
the "Agent connection" page (`#connect`), `GET /api/agent-gateway`, `POST /api/agent-gateway/{register,revoke}`.
Useful on its own: the agent sees the machine state, and the whole channel is verified at the safe level L1.

- ✅ **MCP over stdio** (stdlib, no dependencies): `initialize` (version negotiation: 2025-06-18 / 2025-03-26 /
  2024-11-05), `ping`, `tools/list`, `tools/call`; notifications get no response; JSON-RPC errors (`-32700/-32600/-32601/-32602`);
  a call with invalid arguments is a protocol error, an execution failure is `isError`. Only the protocol goes to stdout.
- ✅ **Link to the panel — Unix socket** `~/.service-admin/agent.sock` (`0600`, directory `0700`), no network port;
  through the socket only the **agent gateway** is reachable, not the panel's HTTP API. Request ≤ 64 KB, one request per connection,
  a stale socket is replaced, a second panel instance is rejected, a path that is too long (>100 bytes, the macOS
  limit is 104) is handled without crashing.
- ✅ **L1 tools (read-only):** `inspect_system` (macOS, architecture, CPU/RAM, disk, prerequisites),
  `list_capabilities` (tools and limits, profiles), `inspect_profile` (what is/isn't installed + a preview of "what it would install";
  `executable_by_agent: false`), `inspect_diagnostics` (known problems with a hint), `get_job_status`
  (status and the last 200 lines of a job). Input is validated against a schema: extra fields, enum, types, length.
  There is **no** `execute_shell` and nothing that would change the machine.
- ✅ **Agent registry:** name (validated), expiry, revocation; **the panel stores only the SHA-256 of the secret**, the secret is
  a file `~/.service-admin/agents/<id>.token` (`0600`), it does not reach the browser, logs, or `argv`; constant-time
  comparison; a revoked/expired agent does not pass, the secret file is deleted on revocation; limit of 20 active agents.
- ✅ **Agent identity in the audit:** every call is recorded as `agent:<tool>` with the agent's name and id; the "Audit"
  page shows the label; the secret does not reach the audit or the registry (verified). Rate limit — 60 calls per minute
  per agent.
- ✅ **Panel not running:** the MCP process does **not start** it and returns a clear error (`tools/list` — an error,
  `tools/call` — `isError` "panel is not running"); verified.
- ✅ **Secret in Keychain — cancelled** (see the decision above): a `0600` file + a hash in the panel.
- ✅ Verified: 55 automated checks (registry, permissions, tools, schema, limit, audit, socket, the whole protocol through a
  real `mcp_server.py` subprocess over stdio), the page in a browser in RU/EN, an **end-to-end scenario with a live
  server** (registration in the UI → issued command → calls → audit entry → revocation → denial) and a **clean macOS in a
  VM** (bundled Python, 5 tools, diagnostics, Flutter profile preview; the CLT dialog did not appear).
- ✅ **2026-10-13 verified with a real Claude Code 2.1.236 client** (tool calls, L1 write denial); found and fixed: an L1 agent saw L2 tools in the list (now the list is filtered by level), a `forbidden` denial did not reach the audit (now it is written). The other clients (Codex, OpenCode, Gemini) — not verified. Earlier: ⚠️ connection by a **real client** (Claude Code, Codex, OpenCode, Gemini): the protocol is implemented per the
  specification and verified only by my driver; `structuredContent` is returned without `outputSchema`, and clients may interpret `instructions` and
  tool annotations differently. The `claude mcp add …` command was not run on this machine
  (it changes the user's Claude Code config).
- ⚠️ Honestly: an agent on the same Mac with its own Bash bypasses the gateway; this is stated in the page's interface.

### 4.1 Unified operations layer and capability catalog (✅ catalog and extraction of package operations; the rest — as 4.2+ progresses)

`operations.py` (catalog, requirements, plan/verify/execute), `opschema.py` (shared schema validator), `profiles.describe()`,
`GET /api/operations`, agent tools `list_operations` and `describe_operation`, the catalog on the "Agent connection" page.

- ✅ **Declarative catalog — 43 operations** (L2 — 29, L3 — 11, L4 — 3): Homebrew packages, profiles, snapshots, backups, running
  test/build, GitHub Actions, all git operations (`gitops`), all mobile toolchain operations (`mobile_ops`). Each has:
  type/group, **parameter schema**, **permission level** (L1 read · L2 limited reversible · L3 administrative or
  external · L4 destructive) with **escalations** (for example, `git.branch_delete` with `force` is L4), **requirements**
  (Homebrew, CLT, Xcode, Flutter, FVM, CocoaPods, Android SDK, gh, 10 GB of disk) and their fulfillment **on this machine**,
  idempotency, **result verification**, **rollback**. There is not a single shell/exec/eval-style operation (this is checked).
- ✅ **The catalog does not diverge from the code:** it is automatically verified that every catalog operation is implemented in its
  executor module, and every operation implemented in `gitops`/`mobile_ops` is described in the catalog (in both directions).
- ✅ **Extracted from `server.py` into the layer:** Homebrew package operations (`install/uninstall/upgrade/reinstall/upgrade-all`) —
  `operations.run_package` is now the only place where `brew <action> --<type> <name>` is assembled; the page handler
  became a thin wrapper (same validation, same job, label, and `kind`). The operation gained what it did not have before:
  a **"before" state** (`brew list`), a **plan without execution** (`already installed` → changes nothing),
  an **"after" result verification**.
- ✅ **Unified parameter validation** (`opschema`: string/enum/pattern/length, integer/bounds, boolean, array, extra fields
  forbidden) — used by both the agent gateway and the operations layer.
- ✅ **Profiles are machine-readable** (`profiles.describe`): OS/architecture requirements, prerequisites (CLT, Homebrew), for each
  item — package, method, **dependencies** (JDK → Android SDK), **steps**, **verification**, **rollback**, as well as the **install
  order by dependencies** (verified for all five profiles). The agent does not "know" how a tool is installed — it
  asks the catalog (`inspect_profile` now returns this).
- ✅ **Agents get only the description:** `list_operations` (with filters, availability on this machine, what is missing) and
  `describe_operation` (schema, escalations, requirements, verification, rollback); `executable_by_agent: false` everywhere. Agents have
  **no** execution tools — that is 4.2 together with `plan_id` and the confirmation queue.
- ✅ Verified: 49 automated checks (validator, catalog structure and consistency, levels and escalations, package
  operations with a **mocked `brew`** — the plan runs nothing, execution yields exactly the same command/label/`kind`, "before/after"
  verification, refusal when requirements are unmet; profiles, snapshot, project run, agent tools), the catalog in a
  browser in RU/EN (43 rows, 39 available on this machine) and a **clean macOS in a VM** (24 of 43 available, unavailable ones
  marked with a reason, the CLT dialog did not appear).
- ⚠️ **Not verified:** execution of package operations with a real `brew` (mocked; on the working machine I did not install/remove);
  `execute` for `profile.install`, `git.*`, `mobile.*` through the layer (both modules were verified earlier separately, here only
  their `plan`/description); automatic result verification so far exists for package operations and the profile.
- ✅ **Extraction of operations from `server.py` (2026-10-13):** `server.py` became only HTTP routing (1130 → 331 lines); the code moved to modules:
  `brewsvc.py` (Homebrew services and packages), `herdphp.py` (Herd, PHP, Node/nvm, Laravel project creation), `uihelpers.py` (sidebar, file reading
  for diagnostics, open Terminal/Activity Monitor). The move was done by an AST script (only real names, not strings): **comparison with the pre-move version —
  74 GET routes: identical code and JSON shape; 16 POST cases with invalid data: identical error code and `code`**. Along the way one local variable `herd`
  in `nav_info` was caught (shadowing) and fixed. The mutating operations of these areas were added to the **single catalog** (`ops_system.py`, 28 operations; 85 in total):
  services (`service.start/stop/restart/kill/install/uninstall/config_save`), `php.select`, `herd.php_install/php_update/site/new`, `node.default/install/uninstall`,
  `lang.action`, Docker (`docker.engine_start/engine_stop/container/prune/compose/run/exec/context/compose_save`; `rm/kill/…-rm/down -v` escalate to L4),
  files (`files.save/resolver/ssh_generate`). Each operation is executed by THE SAME functions that the page calls (there is no separate logic for agents);
  verified: all 28 plans are built, invalid parameters are rejected by the schema, execution returns the same module error codes. The **review** (a separate agent) confirmed that the move does not change behavior (pyflakes clean, imports in a fresh interpreter, no shadowing) and found that the `lang.action` schema was too narrow (it did not accept `id`/`name`) and a flat L2 for destructive actions — fixed (schema widened; `pipx-uninstall`, `remove-tool`, `clean-modcache`, `clean-cache`, `cert-fix` → L3). The only path for executing catalog operations is `plans.execute` (agent-driven, under approval); there are no direct HTTP routes bypassing it. Incidentally: a race on the Docker page when switching pages quickly (a console error) — protection added. **These operations are NOT open to agents** (not in `AGENT_OPS`).
  ✅ `verify` for all 15 git operations (`gitops.verify`: a list of checks based on the repository state — fetch is fresh, pull contains the upstream, push "nothing to send", branch created/switched/deleted, files in the index/not, commit with this message and fresh, stash, rollback, clean, worktree created/deleted); **verified on real git** (a local remote, 15 operations: before execution `ok=false`, after — `ok=true`). ✅ `verify` for 16 of 19 mobile operations (`mobile_ops.verify`): active Xcode, first launch, platform runtime, simulator state (Booted/Shutdown), a fresh screenshot PNG, runtime removed, Flutter channel, `pubspec.lock`/`package_config.json`, a fresh `app-release.apk`, version in FVM / pinned in the project, `Podfile.lock` and `Pods`, licenses and an Android SDK package. **Verified on the real system state** (active Xcode and real simulators/runtimes — reading; file checks — on fixtures): everywhere `ok=false` before the result and `ok=true` after. Deliberately WITHOUT verification: `flutter.doctor/analyze/test` (diagnostics: the result is the exit code and the job log); for `sim.erase` only the device state is checked (the erased data itself cannot be verified). ⬜ Only this remains: the agent "plan → execution" contract for these operations — only if the owner decides to open them to agents.

### 4.2 Write tools: plan → execute (✅ with caveats; a short list of safe L2 operations is open)

`plans.py`, gateway tools `plan_changes`, `get_plan`, `execute_plan`, `cancel_plan`, `verify_plan`.
The cycle: `plan_changes` (changes nothing) → **human approval** (4.4) → `execute_plan` → `verify_plan`.

- ✅ **The plan is bound to execution.** `plan_id` + plan hash (operation, parameters, level, plan body, unmet requirements) +
  a lifetime of **15 minutes**. `execute_plan` **rebuilds the plan from scratch** and compares the hash: if the machine or project state
  changed after approval — denial `plan.stale`, no execution, a new plan is needed (verified: a package was installed manually
  between approval and execution → `brew install` was not run).
- ✅ **Once only:** the `executing` status is set BEFORE launch, a repeated `execute_plan` → `plan.already_executed`, the command
  is not executed again (verified). An unapproved, rejected, cancelled, expired, or "change nothing"
  plan cannot be executed.
- ✅ **The human sees before it starts:** what the operation is, the level, the parameters, and "what will happen" (the `brew install …` command, the list of
  profile packages, where the snapshot will be written).
- ✅ **Idempotency:** if there is nothing to change (the package is already installed) — status `noop`, nothing to approve.
- ✅ **`verify_plan`** after the job finishes: result verification (`brew list`, a repeated profile plan).
- ✅ **Only 5 L2 operations are open to agents** (`AGENT_OPS`): `snapshot.create`, `backup.run`, `profile.install`,
  `package.install`, `project.run`. Everything else in the catalog (git, mobile toolchains, software removal, L3/L4) is **not
  open** to agents: `plan.op_not_allowed`. There is **no `execute_shell`**, no `shell=True`, no root.
- ✅ Open to agents: `docker.container_control` (start/stop/restart, L2, dialog, local Docker only), `list_containers` (L1), `cancel_job` (L2, own jobs only). ⬜ The other catalog operations — as the policy becomes ready.
- ⚠️ **Not verified with a real client** (Claude Code, Codex …): the whole cycle was run through our own MCP driver and
  `mcp_server.py`, not through a real agent.

### 4.3 CLI (✅ verified on the working machine with a temporary HOME; with real agents — no)

- ✅ `./service-admin --agent <id> status | tools | operations | describe <op> | plan --profile ID | plan --op ID --param k=v |
  get/execute/cancel/verify <plan_id> | job inspect [id]` — `cli.py` + the `service-admin` wrapper. This is a single gateway tool call
  over the same socket: the same permissions, limits, audit, and human confirmation; it has no installation logic of its own.
  `plan --profile` is read-only (`inspect_profile`), `plan --op` is a change proposal (L2 required).
  Output is JSON; exit code 2 if the panel is not running or there is no secret file.

### 4.4 Policies and permissions (🔶 foundation, rotation, and "one plan at a time" done; download/time limits, L3/L4 — not)

- ✅ **The "Agent connection" page:** registration (name, level, expiry), a ready-made `claude mcp add …` command and a
  JSON config, revocation, a **queue of confirmation requests**, the confirmation mode, the operations catalog, a counter of requests awaiting
  confirmation in the menu (visible on any page) and a notification about a new request.
- ✅ **The agent level (L1 read / L2 proposes changes) is set by a human**, not by the agent; it is changed in the agents table and takes
  effect immediately (verified: L2 → L1 forbids `plan_changes`); an audit entry with "before/after".
- ✅ **Confirmation for ANY change from an agent. By default — a macOS system dialog** (agent name, operation,
  level, parameters, what will happen, expiry; **the default button is "Reject"; timeout 110 s = denial**). Reason: an agent
  with a terminal on this Mac can itself call the "approve" HTTP endpoint, but it cannot click a system dialog without accessibility
  permissions. The text is passed to the dialog as **`argv` arguments**, not by substitution into a script (verified: an injection attempt through a
  parameter remains data). The dialog language follows the macOS language.
  - **Verified on a real macOS in a VM:** the dialog is shown (an `osascript` process, English text, parameters, expiry), with no
    answer after **110.5 s the plan became `rejected` by the `dialog` decision**. ✅ **The "approved by click" branch was passed 2026-10-13 on the owner's machine** (Approve/Reject/110 s timeout — all three outcomes correct). Earlier there was no click in the VM: its outcomes (`approve` / `reject` / timeout / `-128` / no graphical session) were verified only
    on a mocked `osascript`.
  - ⚠️ **Not verified:** whether an agent can click the dialog programmatically (per Apple's documentation this requires accessibility permissions for
    its process — I did not try this on this machine).
- ✅ **Weaker and explicit:** the "button in the panel" mode — enabled by a toggle with a warning and an audit entry (on the
  host I used it only to verify the interface).
- ✅ **"Do not ask" (`auto_approve`)** — L2 only, only as an explicit setting for a specific agent, with a warning and an
  audit entry; for an L1 agent it is forcibly empty; L3/L4 cannot be enabled (verified).
- ✅ **Limits:** no more than 5 open plans and 10 executions per hour per agent, 60 calls per minute (all verified); result
  ≤ 200 KB; an agent sees and cancels **only its own** plans (isolation verified); a revoked agent does not pass.
- ✅ **Audit of the whole lifecycle:** `plan:propose / approve / reject / execute / stale / cancel / policy`,
  `gateway:settings` — with the agent's name and id; secrets do not reach the audit.
- ✅ **Agent secret rotation** ("Rotate secret" button, `POST /api/agent-gateway/rotate`): the new token goes into the same 0600 file,
  the old one is rejected immediately, a `gateway:rotate` entry (verified on a live server).
- ✅ **One executing plan per agent** (`plan.busy`) — there are no parallel jobs from a single agent. ⚠️ Verified only by reading the code.
- 🔶 **Remainder (a decision, not unfinished work):** (a) *an allowlist of repositories* — already exists: the agent works only with projects from the panel's
  registry; (b) *an allowlist of networks* — agents are open only to operations that go to the network via Homebrew/project managers, they have no separate
  network operation; (c) *a time limit* — `project.run` has 30 min; forcibly killing `brew`/a profile midway I do NOT
  add (it risks leaving the system in a half-installed state) — instead there are "one executing plan", 10 executions per
  hour, and escalation on repeated failures; (d) *a download size limit* — we do not implement it (the panel does not know the size before the manager downloads);
  (e) L3/L4 are not open to agents at all. If a different decision is needed — it is a topic for discussion, not missed work.

### 4.5 The "diagnostics → fix" cycle (🔶 boundaries and escalation done)

Diagnostics → plan → approval → execution (jobs) → verification (health checks/tests/build,
comparison with the snapshot from 2.3) → fix.

- ✅ Hard boundaries (server, `plans._escalation`): within an hour 2 failures/rejections of an IDENTICAL plan or 4 consecutive failures of an agent
  → `plan.escalate` ("stop, tell the user"), a `plan:escalate` event in the audit. Plus the already active ones:
  5 open plans, 10 executions/hour, once per plan, `plan.stale`. Verified on synthetic plans (4 cases); a live agent — no.
- ✅ **Cycle time limit** (`plans`): a plan's job (except L3) lives no longer than 30 min — the server stops it (`plan:timeout` in the audit, status `failed`, `error=timeout`); the total job time of an agent per hour is ≤ 45 min, otherwise `plan.cycle_budget` ("stop and tell the user"). The end time is recorded by `_watch`.
- ✅ **Comparison with the snapshot after the fix:** for `package.install` and `profile.install` a "before" snapshot is automatically taken before execution (`snapshot_before`, label `plan <id> before`; no space/failure — we proceed without it, event `plan:snapshot_skipped`), and `verify_plan` returns `snapshot_diff` (what was added/removed/changed). Verified with mocks (timeout, budget, diff); with a live agent and a real brew — no. Limitation: snapshots accumulate (limit 200) — a human deletes the old ones.

---


## Phase 5 — Runners and virtual machines (🔶 VMs, runners, isolation and self-test are done and verified on Gitea; GitHub and an image with Xcode are not)

Depends on the choice of hypervisor and on the VM check on clean macOS (see the section above), so it is kept separate.

- ✅ **Step 3 (universal foundation): `runners.py`** — provider adapters (`github` = actions/runner, `gitea` = gitea/runner, a.k.a.
  act_runner, which also works for Forgejo; a new CI system = a new class), installation of FILES with sha256 verification from the release, a registry
  of **sources** (`runner-sources.json`: provider + ANY URL + scope repo/org/instance), and tokens in 0600 files
  (`runner-tokens/`; they never reach the API, the audit, or job output). The "Virtual machines" page → "CI runners". Operation `runner.install` L2.
  Verified: the real `gitea-runner v5.0.0` starts; the GitHub runner installs (including under Python 3.12 with `filter="data"`);
  a wrong checksum → refusal; the token is found only in the 0600 file, `***` in the audit; input such as `https://u:p@x`, `h:0`, `a..b`, `../` is rejected.
  **Independent review** (a separate agent) found 8 issues (500 on non-string fields, a permanent failure after an interrupted install, weak
  URL validation, two disk thresholds, cancellation at the token request, xz size, `filter=` in tarfile, outdated texts) — **all fixed**.
  ⚠️ Not verified: the buttons in the browser; the decision about http/private addresses is due before the registration step (currently http is allowed, and the token
  is not yet sent there).
- ✅ **Step 4: runner files inside the base VM** (`vm.prepare_runner` L2, the "Runner in VM…" button): a stopped VM is started, the files are copied
  over SSH (the cirruslabs image account `admin`/`admin`, NAT; `sshpass` is required on the host, the password is passed through the environment, not in argv),
  the sha256 of EACH file is verified, then the VM is stopped (the VM is also stopped on any error, including when SSH did not answer within 2 min; a running VM that belongs to someone else is not touched by the job). **It does not register.** Verified on a real VM (a copy of `clean-mac`):
  gitea-runner (1 file) and the GitHub runner (9390 files) — the sums of every file matched; with wrong SSH credentials the VM stopped; `Runner.Listener --version` in the guest → `2.338.0`, `config.sh` works;
  without installed files — a refusal with a code. **Review** (a separate agent): HIGH (the VM stayed running when startup/SSH failed) and 4 MEDIUM (streaming copy instead of loading into memory, a deadline instead of 60 attempts, a stop error does not mask the original one, a VM that belongs to someone else is not stopped) — fixed. ⚠️ Not verified: the button in the browser; an image with Xcode (it is not part of vanilla).
- 🔶 **Step 5: on-demand runner** (`runner_spawn.py`, `runner.spawn` **L3**, the "On-demand runner…" button on a source with a token; not
  open to agents): clone the base VM → start → the source token goes into the guest via stdin into a 0600 file (read and deleted by the command) → registration
  `--ephemeral` + ONE job (Gitea: `register --ephemeral` + `daemon --once`; GitHub: `config.sh --ephemeral` + `run.sh`) with a time
  limit (1–240 min) → the clone is ALWAYS stopped and deleted. The token is cut out of the output (`***`). Requires confirmation by typing the source name.
  **Verified on real VMs:** the real `gitea-runner v5.0.0` in the guest tries to register on an unreachable server →
  an error in the log, the clone is deleted; a 1-minute limit → the clone is deleted after ~77 s; exit with code 137 is not reported as a timeout; a dummy token is not found in
  the job lines or in the audit; refusals (wrong confirmation, a running base, `ci-*`, 0 minutes, bad labels). Along the way we found and
  fixed: a hard VM stop lost fresh files (now `sync` + a graceful guest shutdown), and the first ssh after boot sometimes breaks
  (retry). **Review** (a separate agent): 2 MEDIUM + 1 LOW (the clone outside `try`, a false "timeout" for code 137, killing the process group) — fixed.
  ✅ **End-to-end test on a test Gitea (brought up by me: Gitea 28.1.0, sha256 verified, SQLite, listening only on the VM bridge 192.168.64.1:3300,
  stopped and removed after the test):** the registration token was obtained from Gitea, the source was added to the panel (scope=instance, http), the base VM was
  prepared, `runner.spawn` → the runner `ci-…` registered as **ephemeral** (visible in the Gitea API) → a `runs-on: macos` workflow from a push
  ran **inside the VM** (in the job log: `Darwin Manageds-Virtual-Machine.local … VMAPPLE`, `hello-from-disposable-vm`) →
  the run status `completed/success` → the runner removed its own registration → the VM was deleted (no `ci-*` left) → no token in the job lines.
  ⚠️ **Found:** if the job did not arrive before the time limit, the ephemeral runner stays in Gitea's runner list (after the VM is deleted it
  stays there; `gitea-runner` has no `unregister` command, and it can only be removed through the admin API/the Gitea UI) — remove it manually.
  ⚠️ **NOT verified:** GitHub (an account/repository is needed), an HTTPS instance, a workflow with `actions/checkout` (the vanilla VM has no git/Node),
  the button in the browser.
  ✅ **Image with git and Node (`runner-base`):** a copy of `clean-mac` (it already had Command Line Tools → Apple Git 2.50.1) + Node v24.21.0 LTS
  (the official tarball, sha256 verified on the host, uploaded into the guest over ssh to `/usr/local/lib/nodejs`, symlinks in `/usr/local/bin`) + the
  gitea-runner files; `runner.spawn` adds `/usr/local/bin` to PATH. **Verified on the test Gitea (with a mirror of `actions/checkout@v4`,
  `DEFAULT_ACTIONS_URL=self`):** the real `actions/checkout@v4` ran inside the guest (git + node), the run is `completed/success`.
  ⚠️ Found: **the guest has no internet while a VPN with a default route through `utun` is enabled on the host** (the vmnet NAT does not forward
  traffic through the tunnel; the guest's DNS returns `::`). That is why the image was built without internet (Node was downloaded on the host). For workflows that need
  internet in the guest (downloading dependencies, `actions/checkout` from github.com), the VPN on the host must be turned off while they run.
  Guest network isolation: the `isolate` parameter (`auto`/true/false), `tart run --net-softnet --net-softnet-allow=<CI ip>/32` — ✅ **verified on a real softnet 0.24.1 (the owner set the SUID bit):** the guest reached the CI server (HTTP 200) but not the router
  `192.168.1.1` or another LAN device (timeout); a full `runner.spawn` cycle with `isolate=auto` on a Gitea bound to the host's LAN address:
  the log says "network isolation (softnet): ON", the workflow inside the VM → `ci-server: 200`, `lan-router: 000`, `lan-host: 000`, `node v24`, `git`;
  the run is `completed/success`, the VM is deleted, no token in the log. Without softnet (no SUID) the log carries the warning "isolation is OFF".
  Found and fixed: under softnet `tart ip` does not find the guest via DHCP (the leases are kept by softnet) → `ip()` also tries `--resolver arp`.
  The server address is an **IP or a name** (verified on `git.example.com`: the guest resolves the name and opens HTTPS both in NAT mode and under
  softnet with an allow list): the name is resolved on the host, ALL of its IPv4 addresses are allowed (`/32`); before waiting for a job the guest does a pre-check of
  server availability, and if it is unreachable the job fails immediately with a clear error (verified on a deliberately unreachable address).
  ⚠️ Caveat: IPv4 only; internet from the guest with a VPN enabled on the host
  has not been verified (see "Environment" in `docs/unverified.md`). A CI server on `192.168.64.1` (the tart bridge) is unreachable with softnet — use its
  LAN address. An idle runner may remain "offline" on the CI server after the VM is deleted.
- ✅ **Step 6: everything through the panel via an access token (API token)** — `ci_api.py` (Gitea/Forgejo and GitHub clients). The user creates an access
  token once; the panel itself: obtains a **fresh registration token** for every run (nothing to copy by hand, and it is not stored
  anywhere), **removes an abandoned runner** from the server (verified: "removed the leftover runner"), and runs a **CI self-test**: creates a test
  repository (instance — under the user, org — in the organization), puts a workflow in it, starts an on-demand runner (softnet), finds the run
  for **its own commit**, checks for `success`, and **deletes the test repository**. The "Check" and "CI self-test…" buttons, the operations
  `runner.spawn`/`runner.selftest` (L3, not open to agents). **Verified on a local Gitea 28.1.0** for the instance, org, and repo scopes
  (the registration token is obtained, the runner registers and takes a job; the self-test — instance and org). **Independent review** found
  3 HIGH + 4 MEDIUM, all fixed: the self-test does not commit to a real repository (the repo scope is forbidden), the result is bound to the commit
  (no false PASS from an old run), redirects are forbidden (the token will not go to another host — verified), http with an access token only
  to local addresses, the shape of the server response is validated, the runner list is paginated, the default branch is taken from the response.
  ✅ **L3 agents (owner's decision: "Yes, with a mandatory dialog"):** level L3 is granted by a human (with a warning); an L3 agent may propose
  only `runner.spawn`/`runner.selftest` (plus L2 operations) and read `list_ci_sources` (without tokens); the macOS system dialog is mandatory
  (marked "ATTENTION, level L3", with the source name, the server address, the VM), "do not ask" is impossible for L3 (it is reset), no more than 3
  CI operations per hour, an L2 agent gets `plan.level`. **Verified with the REAL Claude Code acting as an L3 agent and a real dialog on the
  owner's machine** (a temporary Gitea): the agent itself found the source and the VM → `plan_changes` → the owner clicked "Approve" → the agent ran `execute_plan` →
  the self-test `SELFTEST PASSED`, the plan is `done`, no runners or repositories on the server, no `ci-*` VMs, propose/approve/execute in the audit.
  **Security review** (a separate agent) found 2 HIGH + 1 MEDIUM + 1 LOW, all fixed and verified (a fake `osascript`):
  manually editing the registry to `auto_approve: ["L3"]` no longer gives auto-approval (the plan stays `pending`); L3 ALWAYS goes through
  the dialog, even in the "button in the panel" mode; switching to a weak mode requires a dialog (`plan.dialog_denied`); an L3 plan without dialog approval is not
  executed (`l3_without_dialog`); direct HTTP calls to `/api/runners/spawn` and `/api/runners/selftest` (a button in the panel OR
  the agent's terminal) now also require a system dialog; in the dialog the parameters go in a fixed order (source, vm, labels, minutes,
  isolate) and the labels/isolation are shown in "What will happen"; no more than 6 L3 proposals per hour per agent.
  ⚠️ A fundamental limitation remains: an agent with a terminal on this Mac can bypass the gateway, but NOT the dialog — so everything dangerous is covered by the dialog.
  Guide for a human: `manuals/ci-runners.md`.
  ⚠️ **The GitHub part was written from the API documentation and is NOT verified** (no account); the Gitea access token for the instance scope must be
  an administrator's.
- 🔶 Remaining: a check on real GitHub (it has been verified on Gitea), a VM image with Xcode. Guest network restriction (softnet) and the check on a real Gitea are done (see above). Principle: installing a runner is separate from registering it in CI; registration tokens do not reach job output, the audit, or agent responses.
- 🔶 A self-hosted runner executes code from a workflow: the runner is always disposable (`--ephemeral`, one job), in a deleted cloned VM, under softnet by default (the guest sees only the CI server). Not done: an explicit list of repositories/organizations the runner is allowed for (currently the boundary is set by the source and its token).
- ✅ **Step 1: `vm.py`** — the `Driver` interface and the tart driver (`list`/`status`, `GET /api/vms`, the agent tool `list_vms` L1, `service-admin vms`). The limitation of the previous version ("create/start/stop/snapshot/delete are not implemented, there is no page") was lifted by step 2: the `#vms` page and the operations exist.
- ✅ **Step 2: VM management** (`vm.py`, the `#vms` page, `POST /api/vms/op`, operations in the catalog): `vm.clone` L2, `vm.start`/`vm.stop`/
  `vm.snapshot` L2, `vm.pull` L3 (only `ghcr.io/cirruslabs/`, ≥60 GB free, name entry), `vm.delete` L4 (only a stopped VM, entry of
  the exact name). Start is `tart run --no-graphics`, without shared host folders. Everything goes through a job + audit; **not open to agents**
  (not in `AGENT_OPS`). **Verified on the real tart on this machine** with a full cycle on a copy of `clean-mac` (it was not touched):
  clone → start → snapshot refused on a running VM → stop → snapshot → delete refused with a wrong name → delete both. The page was verified in
  the browser (RU). ⚠️ Not verified: `vm.pull` (tens of GB), the English interface of the page, a "snapshot" as a restore
  (restoring from a snapshot is not implemented — in tart it is just a clone).
- ✅ **`vm.restore` (L4):** return a stopped VM to a "snapshot" `<name>-snap-…`: clone the snapshot into a temporary VM → delete the VM → rename (the "Restore to snapshot…" button, confirmation is the exact VM name). **Verified on the real tart by content:** a marker file was created in the VM, rollback to the snapshot → the marker is gone, the temporary `restore-*` is deleted; refusals: someone else's snapshot, wrong confirmation. **Review** found that a VM snapshot with the same name prefix could be substituted for another VM (data loss), and that the snapshot name could exceed 40 characters: fixed — the snapshot is named `<first 12 characters>-snap-<hash of the full name>-<time>` (≤ 40), and the rollback verifies the hash; the delete step re-checks that the VM has not been started and removes the temporary copy on failure; a test on the real tart (two VMs with a shared name prefix, the substitution rejected, cancellation in the middle of a rollback is safe, an ordinary rollback, deletion of all snapshots).
- ✅ VMs go through the driver interface (`Driver`/`TartDriver`: `list`, `status`, `ip`, operations `vm.clone/pull/start/stop/snapshot/delete/restore`), with the panel logic not tied to a single hypervisor; delete/restore are L4. Disk resizing is not done (on a Tahoe image the disk cannot be expanded).
- ✅ A remote Docker host = root on that host: all Docker operations in the catalog refuse when the context is not local (`docker.remote_context`, fail closed; `DOCKER_HOST`/`DOCKER_CONTEXT` are taken into account), `docker.context` is L4, and the engine is pinned with `--host`. Open to agents: `docker.container_control` (start/stop/restart, L2, dialog), `list_containers` (L1), `cancel_job` (L2, own jobs only). Review: a risk remains that an L2 agent (with approval in the dialog) can stop any local container; `unix://` is considered local (an SSH-forwarded socket is not recognized).
- ✅ **VM base recipes** (`vm_recipes.py`, `vm.recipe` L2, button "Install into the VM…"): instead of large ready-made images — an empty image and "install what is needed": `node` (verified), `clt` (fully verified in a clean VM with the host VPN off; git and clang work). Not exposed to agents.
- 🚫 The tools `create_runner` and `manage_vm` are **deliberately not being built**: only `runner.spawn`/`runner.selftest` (through the dialog) are open to L3 agents, and VM management (`vm.*`) is not open to agents — the owner's decision on boundaries; change it only on the owner's new decision.
---

## Phase 6 — Linux (⬜ plan approved by the owner, work not started)

**Owner's decisions:** (1) target systems — both a workstation with a screen and a headless server; (2) first distribution — Ubuntu LTS (24.04, then 22.04), then Debian 12; Fedora — later; arm64 and x86_64 architectures; (3) VMs and CI runners are part of the first Linux version.
**Unchanged principles:** stdlib only, bind to `127.0.0.1`, commands as an argument list without a shell, confirmation of agent actions out of the agent's reach, everything through the operations catalog + audit, RU/EN. Windows and BSD are out of scope.
**Estimate:** minimal version (L0–L3) ≈ 4 weeks; full (L0–L8) ≈ 7–9 weeks. Every stage ends with: a run in a Linux VM → independent review (code + security) → fixes → recording in `docs/unverified.md` of what is not verified → commit.

**Verification stand (created at L0):** `tart` can run Linux VMs on Apple Silicon — Ubuntu 24.04 arm64 (`ghcr.io/cirruslabs/ubuntu`), with a screen (workstation) and without (`--no-graphics`, server). x86_64 and Debian — only in GitHub Actions (test matrix). The owner's real Linux workstation is "later" (`docs/checklist.md`).

### L0. Foundation and decisions (≈ 3–4 days) ⬜
- ⬜ "Platform" layer (`platform_info.py`): detection of OS/distribution/architecture, screen or no screen, systemd, privileges, **set of capabilities** (`capabilities`: `pkg.brew`, `pkg.apt`, `service.systemd`, `vm.tart`, `vm.qemu`, `mobile.xcode`, `ui.gui_dialog` …). `GET /api/platform`.
- ⬜ The interface hides pages without capabilities (Xcode, Herd, OrbStack…); catalog operations get `requires` on capabilities and refuse with a clear code (`platform.unsupported`) rather than an "internal error".
- ⬜ **ADR "Confirmation channel"** (see L2): the choice and the threat model on paper, before any code.
- ⬜ Stand: Ubuntu 24.04 arm64 VM (with a screen and without), CI matrix (unit tests without privileges) on ubuntu-24.04 x86_64 and arm64, Debian 12 in a container.
- ⬜ Rule for CLAUDE.md: new code does not call `brew`/`osascript`/`launchctl` directly, only through the platform layer.
- Acceptance: on macOS nothing has changed (comparison of the 74 GET routes with the previous version, as with the extraction from `server.py`); on Ubuntu the server starts and `GET /api/platform` is honest.

### L1. Core on Linux (≈ 7–10 days) ⬜
- ⬜ Installation: `get.sh`/`install.sh` in POSIX sh (not zsh); own Python 3.12 (python-build-standalone, linux, sha256 check); **systemd user service** + `loginctl enable-linger` for the server; `.desktop` shortcut for the workstation; `uninstall`.
- ⬜ Statistics (`stats.py`): CPU/RAM/swap from `/proc`, temperatures from `/sys/class/hwmon` and `thermal`, battery from `power_supply`, disk, network; GPU — `nvidia-smi`/sysfs, if present; what is missing is "no data", not an error.
- ⬜ Terminal (PTY), processes/agent sessions (`ps`), `open`/"open Terminal" → `xdg-open`/`x-terminal-emulator`, notifications → `notify-send` (if present).
- ⬜ Configuration files: a registry of Linux paths (`/etc/hosts`, `~/.bashrc`/`~/.zshrc`, `~/.ssh/config`, git), writing as root through `pkexec` instead of `osascript … administrator`.
- ⬜ Environment snapshots: `dpkg`/`apt` packages instead of Homebrew; "before/after" comparison.
- ⬜ System setup (the `#setup` page): Linux version — compiler/`git`/`curl` (`build-essential`), package manager; no "Command Line Tools".
- Acceptance: a clean Ubuntu 24.04 (with a screen and headless) — installation with one command, the panel opens, the dashboard, terminal, audit and backups work; a guide with screenshots for Linux.

### L2. Confirming agent actions without the macOS dialog (≈ 3–5 days + security review) ⬜
The principle is the same: an agent with a terminal on this machine must not be able to approve a plan for itself.
- ⬜ **Channel 1 — screen:** `zenity`/`kdialog` (default "Reject", 110 s = rejection) — only if the user has a graphical session.
- ⬜ **Channel 2 — headless:** approval with the command `sudo service-admin approve <plan>` — a helper **root script** that needs the human's password; it signs the decision with a key the agent cannot access (file root:root 0600); the panel accepts only signed decisions. An agent without the sudo password cannot approve.
- ⬜ L3 — only channels 1 or 2; the "button in the panel" mode remains forbidden for L3. If neither channel is available — L2/L3 agent plans are not executed (fail closed).
- ⬜ Tests with `zenity`/`sudo` replaced (as with `osascript`); an independent security review is mandatory before merging.
- Acceptance: on Ubuntu with a screen — a real dialog; on Ubuntu without a screen — approval through the human's ssh session; an agent under the same user could not approve by itself (verified by an attempt).

### L3. Packages, services, languages, Docker (≈ 7–10 days) ⬜
- ⬜ Package manager as a driver (`pkg`): `apt` (search, list, install/remove through `pkexec`, job + audit) and, optionally, Linuxbrew (the same code as for macOS); recommendation catalog and profiles (Foundation, AI, Backend) — a mapping table "Homebrew name → apt package".
- ⬜ Services: `systemctl` (user and system through polkit) instead of `brew services`; `journalctl` logs; unit-file editor only through the registry.
- ⬜ Languages: PHP/Node/Python/Go/Rust/Java/Ruby — through nvm/pyenv/rustup/apt; shims and `env` for bash/zsh/fish.
- ⬜ Docker: `docker` (Engine + compose plugin), without OrbStack; the remote-context guard is already shared.
- Acceptance: the "Foundation" profile installs on a clean Ubuntu from the panel, "before/after" snapshots show the difference, services start/stop.

### L4. VMs and CI runners on Linux (≈ 10–15 days) ⬜
- ⬜ **Hypervisor selection ADR** (2-day spike): Incus (VMs + containers, images, snapshots) or libvirt/QEMU (qcow2 with a backing file). Criteria: a disposable clone in seconds, network isolation, working without root, arm64 and x86_64 support.
- ⬜ VM driver behind the `Driver` interface (list/status/ip/clone/start/stop/snapshot/delete/restore) + recipes (`node`, `build-essential`, runner).
- ⬜ Guest network isolation through nftables (the analogue of softnet: only the CI server), a warning if it is not enabled.
- ⬜ Runners: Linux builds of `gitea-runner` and `actions/runner` (sha256 from the release), `runner.spawn`/`runner.selftest` unchanged for the user.
- Acceptance: CI self-test on a temporary Gitea (as on macOS): an ephemeral runner in a disposable Linux VM, `completed/success`, the VM and the runner are deleted, no token in the logs; isolation: the guest sees only the CI server.

### L5. Operations and agents parity (≈ 3–5 days) ⬜
- ⬜ All catalog operations have an implementation or an explicit refusal based on capabilities; `verify` for the new operations (apt, systemd, VMs).
- ⬜ Agent tools (`list_vms`, `list_containers`, …) work on both systems; limits, time budget and the "snapshot before" are unchanged.
- ⬜ i18n RU = EN, `check-i18n.js` passes; the audit log is the same.

### L6. Developer toolchains (≈ 3–4 days, optional) ⬜
- ⬜ Android SDK and Flutter on Linux (recipes); Xcode/simulators hidden. Android licenses — confirmation by a human.

### L7. Distribution and documents (≈ 3–5 days) ⬜
- ⬜ One-command installation on Linux; a `.deb` package (and/or a Linuxbrew formula) — after stabilization.
- ⬜ Guides `manuals/` and `manuals/en/` for Linux (installation on a clean Ubuntu with screenshots from a VM, connecting a headless agent, runners); README (RU/EN) with a compatibility page.
- ⬜ The "System setup" page and error messages without mentions of macOS where they are not needed.

### L8. Closing (≈ 3–5 days) ⬜
- ⬜ Full matrix: Ubuntu 24.04/22.04 (arm64 in tart, x86_64 in CI), Debian 12; with a screen and headless.
- ⬜ Final independent security review (confirmation channel, root script, nftables, privileges) and a regression on macOS.
- ⬜ Update `docs/unverified.md` and `docs/checklist.md`: what was verified only in a VM, what is needed on a real Linux workstation and on x86_64.

**Risks:** headless confirmation (L2) is the most sensitive place, until its review the Linux version is not released for L2/L3 agents; distribution diversity — we support an explicit list; verification on real x86_64 "hardware" — only in CI; VMs for CI on Linux are the largest part by volume (L0–L3 and L5 can be released earlier, and L4 as a separate release).

---

## Deliberate exceptions (cannot be done from the interface — and why)

The list is mandatory under principle №5: everything that is not done from the panel must be named explicitly.

| What | Why it cannot be done from the panel |
|---|---|
| Installing Command Line Tools | Only through Apple's native dialog (`xcode-select --install`). The panel launches it and shows progress. |
| Installing Xcode | Requires an Apple ID and ~15 GB through the App Store. The panel reports the status and gives a link. |
| Installing Android Studio | A plan decision: the cask can technically be installed through `brew`, but the first launch is a GUI wizard with SDK downloads and licenses; we do not install it from the panel (SDK and licenses are item 2.5). |
| Confirming administrator rights | The macOS system dialog (`osascript ... with administrator privileges`). The panel neither stores nor supplies the password. |

---

## 🚫 Out of scope (deliberately)

- **Exposing the panel to the network.** Only through an SSH tunnel. If the bind is ever widened, that is a separate
  decision requiring authentication and a security analysis.
- **Remote management of clients' machines (control plane).** A server, a client connector with an
  outgoing TLS connection, binding a machine with a one-time code, a key in the Keychain, tenant isolation.
  This is a separate architecture and a separate security model. Decided: the agent lives on the
  client's Mac (Phase 4), so a cloud agent managing a Mac remotely is not being designed. If
  it is ever needed, that is a new decision by the owner, not a continuation of Phase 4.
- **A universal `execute_shell` for agents and running agents with root rights.**
- **Our own CI/CD inside the panel.** Xcode Cloud / GitHub Actions already exist; the panel launches and reads them.
- **Running arbitrary shell commands from a form.** A shell exists only in the "Terminal" tab.

---

## How to use this document

Before starting: ⬜ → 🔜. After verification **on a real machine or in a VM** (not "the code is written") → ✅.
If an item was designed incorrectly, fix this document first, then the code.

