# Verification checklist (for the owner)

What this is: **specific actions for you** — things I cannot verify myself (I don't have your machine, accounts, screen, or
administrator password). For each item: what to do → what should happen → what to send me. The list of unverified items with
reasons is in `docs/unverified.md`; I move closed items there into "Closed".

**General notes before starting**
- Branch with the changes: `feature/roadmap-phases-2-3` (in the `mac-service-admin` repository). Nothing has been pushed.
- Running the panel from source: `cd …/mac-service-admin && python3 server.py` → http://127.0.0.1:8765
  (the system `python3` may be 3.9 — if you get a `tomllib` error, run `/opt/homebrew/opt/python@3.12/bin/python3.12 server.py`).
- Report the result of any check to me in one line: "item N: ok" or "item N: not ok, here is what I saw" (+ screenshot/error text).
  **Do not send tokens, passwords, or secrets in chat.**
- Order: **A (quick, 10–20 min) → B (if possible) → C (optional)**.

---

## A. Most important (no external accounts)

### A1. Confirmation dialog for an AI agent — ✅ done 2026-10-13 (Approve / Reject / timeout)
Why: this is the main protection of Phase 4. In the VM the dialog was shown, but nobody clicked it.
1. Start the panel and open **"Agent connection"** (`#connect`).
2. Register an agent: name `test`, level **L2**. Copy the secret file path/command (the secret is not shown — that's normal).
3. In a terminal (substitute the agent id, visible in the table, like `a1b2c3`):
   `./service-admin --agent <id> plan --op snapshot.create --param label=check1` → the response will contain a `plan_id` (like `p…`).
4. On the **"Agent connection"** page, the plan appeared in the request queue (the pending counter at the top of the menu). Click **"Approve"**
   (the panel will ask again) → a **macOS system dialog** appears with the agent name, the operation, and its parameters (the default button is "Reject").
5. **In the system dialog click "Approve"** → then `./service-admin --agent <id> execute <plan_id>` → expect `done`/a job; a snapshot `check1` appeared on the "Snapshots" page.
6. Repeat steps 3–4 with a new plan (`label=check2`) and **click "Reject" in the system dialog** → `execute` should refuse (`plan.rejected`).
7. Once more, a new plan: click "Approve" in the panel, and in the system dialog **do nothing for 2 minutes** → the plan becomes `rejected` by timeout (110 s).
Send: "A1: ok" or what went wrong (the dialog text, what `execute` answered).

### A2. A real AI client connects over MCP — ✅ Claude Code verified 2026-10-13. ⏸ Codex / OpenCode / Gemini — SKIPPED SEVERAL TIMES, postponed (no clients at hand)
Why: the protocol has been verified only with my own driver.
1. On the **"Agent connection"** page, create an **L1** (read) agent and copy the ready-made `claude mcp add …` command (or the JSON config for Codex/OpenCode/Gemini).
2. Run it and restart the client (Claude Code / Codex / …).
3. Ask the agent: "call the inspect_system tool and tell me what you see".
Expected: the agent sees the `service-admin` tools and returns data about the Mac; it **does not see** `execute_shell` (there is none).
4. Ask: "propose installing the `jq` package via plan_changes" → it should refuse (`forbidden`, level L1).
Send: which client, "ok" or what the agent said, and any errors.

### A3. The "Virtual machines" page, by eye
1. Open `#vms` (tart must be installed — you have it).
2. Make sure the VM list is correct, Russian and English (the **RU/EN** buttons) read well, and nothing is cut off or overlapping.
3. Click "Copy…" on `clean-mac` → name `look-test` → confirm → the VM appeared → "Delete…" → enter `look-test` → it disappeared.
Send: "A3: ok" or a screenshot if the layout is bad.

---

## B. Needs your accounts/repositories

### B1. On-demand runner on **your** Gitea (`https://git.example.com`) ⭐ — now simpler: only an access token is needed
You need to **create one access token once** (the panel creates repositories and workflows itself):
1. In Gitea: avatar → **Settings → Applications → Generate New Token**. Name `service-admin`. Permissions (scopes):
   `write:repository`, `write:organization`, `write:user` and, if you want the whole-server scope (instance), also `write:admin`
   (the token must belong to a Gitea administrator). For the organization scope the first three are enough.
2. Make sure Actions are enabled in Gitea (`[actions] ENABLED = true`).
3. (Details: **`manuals/ci-runners.md`**.) In the panel `#vms` → **CI runners → "Add source…"**: system `gitea`, address `https://git.example.com`, scope `instance` or
   `org` (+ organization name), name `Lab`, token type **`api`**, paste the token. (The token is stored only in a 0600 file on this Mac.)
4. On the source: **"Check"** → "Connection works…", then **"CI self-test…"** → choose the base VM `runner-base` and enter the source name.
Expected: the log ends with `SELFTEST PASSED`; the test repository and the `ci-…` VM are deleted; there are no stray runners in Gitea.
The `repo` scope is not suitable for the self-test (it does not commit to your repository) — the "On-demand runner…" button is available for it.
Send: "B1: ok" or a piece of the log (it should contain no tokens).

### B2. The same on GitHub (if needed) — ⏸ SKIPPED SEVERAL TIMES, postponed (no test account or token)
You need a test repository with a `runs-on: self-hosted` workflow and a token: **Settings → Actions → Runners → New self-hosted runner → macOS ARM64 → the token from the `./config.sh` command**.
Steps are as in B1, but in the panel the provider is `github`, address `https://github.com`, scope `repo`, path `owner/repo`.
Send: "B2: ok/not ok".

### B3. Backups to an external drive
1. Connect an external drive; on the **"Backups"** page specify a folder on the drive (`/Volumes/<drive>/…`) and run a backup.
2. Expected: the backup is created and verified (status "ok").
3. **Disconnect the drive** and run the backup again → expect a clear "destination unavailable" error, and nothing broken.
4. Reconnect the drive → the backup passes again.
Send: "B3: ok" or the error text.

### B4. Git: push/fetch to a real remote
You need a test repository (can be the same `ci-lab`) and your usual git authorization (SSH key or credential helper).
1. On the **Projects** page, add a clone of the test repository to the registry.
2. Make a change → "Add/Commit" → **Push** → check that the commit appeared on the server; then **Fetch/Pull**.
Expected: it works without a password prompt in the panel terminal; if access is missing — a clear error, not a hang.
Send: "B4: ok" or the error.

### B5. GitHub Actions from the panel (workflow_dispatch)
You need a GitHub repository with a workflow that has `on: workflow_dispatch`, and `gh auth login`.
1. On the project page → GitHub block → "Run workflow" → enter the project name to confirm.
Expected: the run is visible in Actions on GitHub. Send: "B5: ok/not ok".

### B6. Real package installation via the panel/agent
1. In the panel (**Packages**) install a **lightweight** package you don't have (for example `jq`), then remove it.
2. Or via an L2 agent (see A1): `plan --op package.install --param name=jq --param type=formula` → approve → `execute`.
Expected: the package appears/disappears in `brew list`, and there is an entry in the audit log (`#audit`).
Send: "B6: ok" or the error.

---

## C. Optional / needs the administrator password

### C1. Xcode admin operations (`#mobile`)
Only if you use them: "Switch Xcode" (`xcode-select -s`), "First launch". A system password dialog should appear.
Send: "C1: ok" or the error text. (**Downloading platforms is several GB — do not run it unless needed.**)

### C2. VM network restriction (softnet) — ✅ done and verified
You set the `softnet` permissions — isolation is on and verified (the guest sees only the CI server; the router and LAN devices are unreachable).
What to keep in mind now: the CI server must be reachable by the guest at the **LAN address of the host/server** (`192.168.64.1` does not work with softnet);
one address (`/32`) from the source URL is allowed. Rollback (if needed): `sudo chmod u-s ~/.local/bin/softnet` or `rm ~/.local/bin/softnet` —
then isolation turns off by itself, and a warning appears in the job log.

### C3. VM image with git and Node — ✅ already made by me
The VM `runner-base` (in the `#vms` list; stopped) contains git, Node 24, and the gitea-runner files; a real `actions/checkout@v4` was verified on it.
Use it as the "base VM" in "On-demand runner…". If your workflows need other tools (Xcode, Flutter, etc.),
tell me which, and I will add them to the base. ⚠️ If a VPN is on on your Mac, the guest has no internet (see `docs/unverified.md`, "Environment").

### C4. Clean install from scratch — ✅ verified in a VM with clean macOS 26.6, illustrated manual: `manuals/install-clean-mac.md`
The installer (Python, app, autostart, server) and the "System preparation" page were verified on an image without Command Line Tools/Homebrew/Git.
Verified together with you: the Apple "Install" dialog (in the VM it failed because of space: 24.27 GB needed, 18.49 GB available — confirmed by screenshot), the `softwareupdate` workaround, Homebrew and the "Foundation" profile from the panel.
What remains for you (on your second Mac): the same steps from the manual; especially the administrator password dialog when installing Homebrew (in the VM `sudo` has no password).

## ⏸ Postponed (skipped several times — return when the means become available)

| Item | What is missing |
|---|---|
| GitHub: self-test, on-demand runner, `ci_api.GitHub` client | a GitHub test account and an access token |
| MCP clients Codex, OpenCode, Gemini | installed and authorized clients |
| The owner's Gitea `git.example.com` | the owner's decision: we do not go into it; verified on my temporary Gitea |

## What I check myself (not yours)
Regression at every step: `python3 -m py_compile *.py`, `node --check static/*.js`, `node check-i18n.js` (RU = EN), smoke test of all GET routes
on a temporary HOME, review by a separate agent, runs on a copy of `clean-mac` in tart. Results are in `docs/roadmap.md` and `docs/unverified.md`.
