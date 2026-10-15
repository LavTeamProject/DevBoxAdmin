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

- `get.sh` (one-command install): download / unpack / checksum check / refusal on a wrong checksum or a bad `SA_REF` were tested locally on a `git archive` tarball (no install). The full chain through `raw.githubusercontent.com` + `codeload.github.com` followed by `install.sh` from `~/.service-admin/app` has not been run — the script was not on GitHub yet.
