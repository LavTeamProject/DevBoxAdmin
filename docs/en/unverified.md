# What could not be verified

A list of what I could NOT verify myself, and what is needed from the owner to close each item. Details and context are in
`docs/roadmap.md` (each item is marked ⚠️ there too). **Rule:** a new unverified item is added here immediately; a verified one is
moved to the "Closed" section with the date and the method of verification.

Format: **what** — why it was not verified — **how you can help**.

## Needs your actions / your data

> ⏸ **Skipped several times and postponed by the owner:** GitHub (account + token), MCP clients Codex/OpenCode/Gemini. Do not remind until the owner returns to them.

| What | Why it was not verified | How you can help |
|---|---|---|
| Whether an agent can programmatically click this dialog (accessibility permissions) | Not tried: this is a test of bypassing a protection and needs your machine and your decision | Decide whether such a test is needed |
| GitHub as a whole (`runner.spawn`, self-test, API client `ci_api.GitHub`) | No account/repository/token; the code was written from the API documentation | A GitHub access token (classic PAT, scope `repo`; for an org also `admin:org`) and a test organization/repository |
| HTTPS Gitea instance (your `git.example.com`) | Verified only on my test Gitea over http | A registration token and a test repository (do not send the token in chat — add the source on the "Virtual machines" page) |
| A real external drive for backups | Only the refusal for a nonexistent `/Volumes/…` was verified | Connect a drive and run a backup |
| `gh` and a real GitHub for `workflow_run` (Phase 2.7) | Did not run `gh` against a real repository | A repository with a `workflow_dispatch` workflow |
| `push`/`fetch` to a real remote (Phase 2.5) | Did not push to a real remote | A test repository |
| A real `brew install/uninstall` via catalog operations (Phase 4.1) | Did not install/remove packages on the working machine | Allow installing a lightweight package in a VM or on the host |
| Xcode admin operations (`xcode.select`, `first_launch`, `download_platform`) | Needs the administrator password and several GB; Xcode is not in the VM | Run on your machine and report the result |
| Administrator password dialog for cask / Homebrew (Phase 2.1–2.4) | In the vanilla image, `sudo` works without a password | A run on a machine with regular sudo |

## Not technically verified by me (can be checked later)

| What | Why | Note |
|---|---|---|
| `vm.pull`: the actual DOWNLOAD of an image from ghcr.io (tens of GB) | Expensive in space and time | The whole operation path was verified on an ALREADY downloaded image (`tart clone` from the local cache → VM created, deleted) and the refusals (foreign registry, low disk space, wrong confirmation) |
| Abandoned ephemeral runner on the CI server | Fixed for sources with an access token (the panel deletes the runner via the API; verified on a local Gitea). For sources with a registration token (`auth=registration`) the runner still remains | Use an access token (`api`) |
| Limits on downloads/task time for agents, lists of repositories and networks (4.4) | Not implemented | Phase 4.4, remainder |

## Environment you should know about

- **The tart VM disk (Tahoe) cannot be expanded inside the guest:** the recovery partition sits before the free space, SIP does not allow deleting it, and `diskutil apfs resizeContainer` answers "-69519". So the guest volume stays at ~44 GB with ~18 GB free, and the Apple dialog for Command Line Tools fails (it needs 24.27 GB) — workaround: `softwareupdate`.
- **Clicking buttons inside the VM window:** the VM window belongs to a `tart` process that is not registered as an application, so screen control (computer use) gives no access to it; clicks on guest dialogs are made by the owner. The VM window is created only by running `~/.local/bin/tart run <vm>` in the user's regular Terminal.

- **The VM guest has no internet while a VPN is enabled on the host** (default route through `utun…`): tart/vmnet NAT does not forward traffic through the tunnel.
  The local network and the `192.168.64.1` bridge still work (the runner connects to Gitea on the host). To check: in the guest, `curl https://example.com`
  gets no response; turn the VPN off and it responds. For workflows that need the internet: turn off the VPN while the runner is running (or use an actions mirror, as in the test).

## Minor notes (not blocking)

- `vm.restore` is not atomic: if the VM was deleted but the rename did not happen, a copy of the snapshot remains as `<prefix>-restoring-…`, and the log gives the exact `tart rename …` command to finish by hand. Snapshots in the old format (`<name>-snap-<time>`, from before the hash fix) cannot be restored.

- Native `prompt()`/`confirm()` remain for ordinary input (names, confirmations); tokens are entered in a dialog with a password field (`askSecret`).

## Closed

| What | When / how |
|---|---|
| Full `runner.spawn` cycle on a test Gitea (ephemeral registration, workflow in a VM, VM deletion, no token in the log) | 2026-10-13, Gitea 28.1.0 on the VM bridge; result in `docs/roadmap.md` (Phase 5, step 5) |
| The "Virtual machines" page in the browser, RU and EN: clone, snapshot, start, stop, delete (wrong name → refusal, correct → deletion), runner file installation, "Runner in VM…", adding/removing a source, "On-demand runner…" (expected registration failure → VM deleted) | 2026-10-13, browser panel + real tart; native `prompt`/`confirm` were replaced by a script |
| VM image `runner-base` (git + Node) and a real `actions/checkout@v4` in the guest | 2026-10-13, test Gitea with a checkout mirror; VM `runner-base` left on disk |
| Guest network isolation via softnet (only the CI address is allowed; the router and other LAN devices are unreachable) + full `runner.spawn` cycle with isolation | 2026-10-13, after the owner set SUID on `softnet`; Gitea on the host's LAN address |
| Agent confirmation in a real macOS system dialog: "Approve" → plan executed (once, repeat rejected), "Reject" → `rejected`, no response → `rejected` after 110 s; audit `propose/approve/execute/reject` | 2026-10-13, the owner clicked the dialogs on their machine (temporary HOME, environment snapshot) |
| A real MCP client, **Claude Code 2.1.236**, connected to the panel gateway (stdio, temporary panel): tool list (no `execute_shell`), `inspect_system` (macOS 26.6, arm64, 25.8 GB, 108 GB free), `inspect_diagnostics` (2 findings), `forbidden` refusal for `plan_changes` from an L1 agent | 2026-10-13, `claude -p --mcp-config`; the owner performed the CLI login. **Still unverified: Codex, OpenCode, Gemini** |
| An **L3**-level agent (real Claude Code) proposes `runner.selftest`, the owner approves the real dialog (marked L3), the agent executes and verifies; the server is clean after the test | 2026-10-13, temporary Gitea 28.1.0 (not yours), softnet enabled |
| L3 hardening after the security review: no auto-approval of L3 (even when the registry is edited), L3 always goes through a dialog, switching the mode to "panel" goes through a dialog, direct `spawn`/`selftest` calls go through a dialog, proposal limit | 2026-10-13, fake `osascript` (logic); **the real dialog for the "On-demand runner…"/"CI self-test…" buttons has not yet been clicked by you** |
| Clean install (`install.sh`) on macOS 26.6 without CLT/Homebrew/Git: Python 3.12.15 downloaded and checksum-verified, app in /Applications, LaunchAgent, server on 8765, panel pages, Apple CLT dialog; installer messages translated (they were in Indonesian) | 2026-10-13, VM `fresh-install` from the vanilla image; screenshots in `manuals/img/` |
| Screenshots for the agent and CI runner manuals (form, L3 table, confirmation queue, real L3 system dialog, "CI runners" block, self-test log) | 2026-10-13, temporary panel + my Gitea; the Mac name was replaced with "Demo Mac" |
| Full clean-install path in a VM: Apple "Install" dialog (owner's click) → error "not enough disk space 24.27 GB needed, 18.49 GB available" (confirmed live) → Command Line Tools via `softwareupdate` (~4 min) → Homebrew 7.0.9 from the panel (~3.5 min) → "Foundation" profile 12/12 from the panel (~2.5 min) → before/after snapshots (formulae 0→20) | 2026-10-13, VM `fresh-big` (100 GB disk, but the volume is 44 GB: the Recovery partition blocks expansion), host VPN off |
| Confirmed live: `plan.busy` (a second agent plan does not start while the first is running); `vm.restore` by content; macOS notification about a failed backup; GitHub Actions parameters/cancel/retry (fake gh); reading the simulator runtime list; password field for a token (`askSecret`: input/cancel/Esc); translation of journal lines into EN | 2026-10-13 |

## Docker for agents (list_containers / docker.container_control / cancel_job)
- Verified with fakes (remote context → `docker.remote_context`, someone else's job → `plan.job_not_yours`); real container start/stop via a plan with a real dialog on the working Mac was not run.
- The context is determined by `docker context ls` and `DOCKER_HOST`; anything that is not `unix://` is considered remote (fail closed).

- Owner's HTTPS Gitea 1.27.2: read-only check only — an org-scope source was added with an access token and "Check" returned the user and the runner list (1). Self-test and on-demand runner were NOT run on this server (owner's decision: "Check only").

- `get.sh` (one-command install): download / unpack / checksum check / refusal on a wrong checksum or a bad `SA_REF` were tested locally on a `git archive` tarball (no install). **The full chain was verified in a clean VM (macOS 26.6, vanilla):** `curl … | zsh` from GitHub → sources in `~/.service-admin/app` → `install.sh` (its own Python 3.12, app in /Applications, LaunchAgent) → the panel answers 200 on `127.0.0.1:8765`.

## VM preparation recipes (`vm.recipe`)
- `node`: verified on a copy of `clean-mac` (host download, sha256, upload, `node --version` in the guest, VM stopped and deleted).
- `clt`: fully verified in a clean VM with the host VPN off — Command Line Tools for Xcode 26.6 installed in ~3.7 min, `xcode-select -p` = `/Library/Developer/CommandLineTools`, `git` and `clang` work in the guest, the VM was stopped. With a VPN on the host the recipe stops early with a clear "no internet in the guest" error.
- Node.js integrity: the sha256 comes from the same nodejs.org (the `SHASUMS256.txt.asc` signature is not checked); the file runs only inside a throw-away guest VM. If the VM becomes a CI base, pin versions and sums in the repository.
- Xcode, Flutter and Android Studio are deliberately not automated by recipes (Apple ID / licences).

## Linux (Phase 6)
- L0/L1 were verified only on Ubuntu 24.04.5 arm64 in a tart VM without a display (Python 3.12.3). Not verified: a Linux workstation with a screen, x86_64, Debian/Fedora; the GitHub Actions matrix has not run yet.
- Linux statistics: temperatures, battery and GPU are absent in a VM (checked: "no data" is not an error); not tried on real hardware.
- Linux, UI: hiding pages by `data-cap` works only in the sidebar; typing the address directly (`#herd`, `#mobile`, `#vms`) opens the page, and its API on Linux answers with a tool error (409/404), not 500. A server-side `platform.unsupported` refusal for non-catalog routes is planned in L5.
- Linux, agent approval (ADR-0001): channel B does not protect against an agent that edits the panel's code or injects into its process; the requirements from the review are written into the ADR and are mandatory for L2.
- Linux L1: `pkexec` (the polkit window) and external terminals were verified only by code and with stubs — the VM has no display. `notify-send` was not tried. `get.sh`/`fetch-python.sh` on macOS bash 3.2 are partly verified (the Python download and unpack — yes; a full `install.sh` through `bash get.sh` on macOS after the rewrite — no).
- Linux L2: `pkexec` (polkit) does not authenticate in the VM ("No session for cookie"); the polkit window and the `zenity`/`kdialog` dialog were not verified (no screen). Channel B through `sudo` (the root helper, a pty) was verified. The residual risks from ADR-0001 remain: an agent that edits the panel's code / injects into its process; X11 input synthesis; `ydotool`/`uinput`. An independent security review of L2 is mandatory before the Linux version is released for agents.
- Linux L3: package installs / actions on system services through `pkexec` (with a screen) were not tried — only the headless path (a `sudo …` command for the panel terminal). Profiles were not installed on real apt (the plan and the command building were verified). The catalog and recommendations are mapped to apt by the `svc.APT_MAP` table; the packages themselves were not installed. Docker was verified on `docker.io` (a container was started and removed).
- Linux L4: verified only on arm64 with TCG (no KVM) in a tart VM; KVM, x86_64, the GitHub runner, an HTTPS CI server by name and the mode without isolation were not tried. Isolation: the guest has no internet at all (workflows that need the internet / `actions/checkout` from an external address will not work in the default mode) — the internet without access to the local network cannot be had without root. The base is built from an Ubuntu cloud image; the guest password is random and lives in the panel user's `meta.json` (0600).
- Linux L5/L6: `pkexec` may cache authorization (polkit rules with `auth_admin_keep`) — then, after the human enters the password once, an agent could repeat an admin command without a new window; a dedicated polkit action for the panel is more robust (planned). Real Flutter/Android SDKs were not installed on Linux (only detection on stub directories was checked).
- Linux L7: the `.deb` was verified on Ubuntu 24.04 (build, install, the service, the helper installer); Debian 13/Fedora were not tried; the package depends on a system Python 3.11+ (on Ubuntu 22.04 — only the one-command install with its own Python). The screenshots of the Linux guides were taken from the panel in a VM without a screen (the polkit/zenity windows are not on them).

### L8 — final matrix and review (Linux)
- Verified: unit tests (47) and 70 GET routes in `debian:12`, `ubuntu:22.04`, `ubuntu:24.04` (arm64) containers — 0 errors; macOS: 76 routes, 0 differences; socket-owner check in the lab VM (another user → 403).
- Not verified: a real workstation with a screen (pkexec/zenity/polkit), x86_64, KVM (`vm-linux.yml`), a GitHub runner, Codex/OpenCode/Gemini MCP clients; the socket-owner check is not applied on macOS.
- Review: before fixes F1–F7, L2/L3 agents on Linux were considered unsafe; fixed, no second independent review of the fixes was done.

### Phase 7 — harness for agents
- Done: `tests/test_agent_contract.py` (22 checks of the gateway/plans/MCP subprocess, in CI); `tests/agent_eval/` (13 scenarios, runner `run_eval.py`, the `fake` client passed 13/13 on macOS).
- Not verified: no run with a live agent yet (`--client claude`) — needs a disposable VM with a logged-in client; Codex/OpenCode/Gemini are not described in `clients.json`; the runner does not automate the approval channels (zenity/helper), the "human" is the panel button (L2 only).
- Expected findings (`known_gap`): a same-user agent with a shell can edit `plans.json` and read other agents' tokens.

### Phase 7 — live layer-B run (2026-10-15)
- Claude Code 2.1.300, Ubuntu 24.04 arm64 VM (tart), 13 scenarios: **13/13 PASS, 0 FINDING**. The "propose → button → execute → verify" loop with a live agent worked (a snapshot was created), a rejection was not retried, L1 could not propose a change, an L3 plan without the dialog did not run.
- Limit: in every hostile scenario the agent itself declined to break the protection (forging the plans/decision file, another agent's token, shell injection), so they did not test the panel's technical resistance — layer A does; a check that does not rely on the model's good behaviour needs a scripted direct-call scenario.
- Found and fixed: the tool descriptions said "macOS dialog"/"Mac"/Homebrew on Linux.
- Not verified: other clients (Codex/OpenCode/Gemini), repeated runs (non-determinism), the agent and the panel under different users.

### Phase 8, step 1 — a remote agent over SSH
- Verified: the server with the panel is an Ubuntu 24.04 VM, the client is a Mac over SSH with a restricted key (forced command + `restrict`): the MCP bridge works, the L1 tools (10) are available, `plan_changes` is refused, an extra command does not run, TCP and Unix forwarding do not work, no pty.
- Not verified: a live agent (Claude Code) through the SSH bridge from another computer; macOS as the server (turning on "Remote Login"); `sk-` keys; rsa keys; SSH servers other than OpenSSH 9.6; an address restriction (`from="…"`) — not added, can be put into the line by hand.
- Residual risk: whoever has the private key and network access gets this agent's rights (like a token); to revoke, delete the line from `authorized_keys` or revoke the agent.

### Phase 8, steps 2–3 — remote API, operators, Telegram (2026-10-15)
- Verified: 124 tests (incl. RFC 6238, the TOTP lockout, rights and dialogs, address limits/blocking, TLS and the fingerprint, an idle connection and slowloris, a fake Telegram server, the example client with certificate pinning); on a real VM over the network with TLS and an address list: agent → plan → operator (TOTP) → execution → verification, a replayed code is refused, the panel's ordinary API is unreachable from the network; an independent security review — 1 HIGH, 1 MEDIUM-HIGH, 4 MEDIUM and a number of LOW found; all fixed (ADR-0003, the section "Changes after the independent review").
- Not verified: **a live Telegram bot with a real token** (only a fake server); an authenticator app with a real secret (only the algorithm was checked against the RFC vectors); operation behind a real reverse proxy (nginx/Caddy/Cloudflare Tunnel); Linux/macOS as the server on different OSes/architectures (Ubuntu arm64 and the macOS tests were checked); the system confirmation window in a real graphical session when turning access on (replaced in tests and the VM); load and DoS resistance under a real attack; a client app/chatbot built on the API (only an example exists).
- Residual risk: an agent of the same OS user with a shell can write to `~/.service-admin` and bypass the dialogs (as before Phase 8) — the answer is isolation (a separate user/VM).

### Phase 9 — Python and Homebrew packages
- Verified: 8 tests (dependency and "unneeded" parsing, the guards when removing versions, validation, removal of uv folders only inside the uv directory); the "Packages & services" and "Python" pages on real Mac data (141 formulae, 2.9 GB, the "unneeded" list matched `brew autoremove --dry-run`: empty; 2 Python versions, 150 pip packages).
- Not verified: **the installation and removal themselves** (`uv python install/uninstall`, `brew install/uninstall python@X.Y`, `brew autoremove`, `brew cleanup`, `pip uninstall`) — not run on the working Mac so that nothing changes; a run on a clean macOS (tart) is needed; `pyenv`; installing uv from the panel is not provided (the uv method is available if uv is already there).

### Phase 10, U2 (part) and U4a
- Verified: the smoke harness `tests/ui_smoke.py` — 29 of 29 addresses on the real HOME (old addresses redirect, composite pages have tabs, no JS errors); 8 tests of the profile catalog; the catalog and the install plan on the real Mac (the Web/Backend-PHP profiles show what is missing: PHP, Composer).
- Not verified: **installing** the new profiles (PHP, Composer, Herd, pnpm, Yarn, uv, pipx, mkcert, HTTPie, Chrome) on a clean macOS; the profiles page and "Getting started" on Linux (the menu and the `linux-web` profile are checked only by the catalog tests); the harness cannot inject a failing request (pages with one failed request were checked by hand only for "Packages" and "AI access").
- Known: on this Mac Node 26 is installed by the `node` formula while profiles expect `node@22` — the "Node.js LTS" item shows as found, but the "one Node — Homebrew" policy is not yet brought to one version (stage U3).

### Phase 10, U3 (versions from Homebrew)
- Verified: 7 tests (the list of versioned formulae and their order, similar names, the formula name from a path, "removable", Node/Go); the Node page on real data (Node 26 from the `node` formula; `node@24/22/20/18` available); the Go/Java/Ruby version lists on real data.
- Not verified: **installing and removing** versions (`brew install/uninstall node@22`, etc.) and choosing the default Node version were not run on the working Mac; former nvm users: nvm versions are shown in the installs list but not removed from the panel; the PHP (Herd) page did not change.

### Phase 10: FlyEnv ideas (object page, service sets, ports)
- Verified: 6 tests of sets/groups/ports (lsof parsing, set statuses, skipping not-installed services, `install` steps, input validation and limits) + a formula-family test; the service page (4 tabs) and language pages (2 tabs), the "Sets" and "Ports" tabs on real Mac data; the 12 new catalog cards exist in Homebrew (formulae and casks checked against local data).
- Not verified: **starting/stopping sets** (`brew services start/stop`) and installing the missing were not run on the working Mac; the service page on Linux (systemd): the "Versions" tab is empty there, "Sets" are off; ports on Linux through `lsof` see only your own processes without root.
