# On-demand CI runners: guide

_The screenshots show the Russian interface; switch to English with the RU / EN buttons in the panel header._

What the panel can do: bring up a **disposable virtual machine (VM)**, register a **runner** of your CI system (Gitea/Forgejo or
GitHub) in it, execute **one job** and delete the VM. Code from the workflow runs only in the VM, not on your Mac. Page: **"Virtual machines"** («Виртуальные
машины») (`#vms`). Everything is done through the panel; the only thing you create by hand is **one access token** on the CI server.

> If something does not work, see the section "If something goes wrong" at the end.

---

## 0. What you need on the Mac (once)

| What | Why | How to install |
|---|---|---|
| **tart** | runs the VMs | see `../../docs/en/roadmap.md` ("Verification on a clean macOS"): the official `tart.tar.gz` from GitHub, into `~/.local/opt/tart`, a symlink in `~/.local/bin` (no sudo) |
| **sshpass** | the panel logs into the VM over SSH | `brew install sshpass` |
| base VM image | disposable VMs are cloned from it | on the VMs page: "Download image…" (`ghcr.io/cirruslabs/macos-tahoe-vanilla:latest`, ~25 GB) → "Copy…" → then step 1 |
| **softnet** (recommended) | VM network isolation: it sees the internet and your CI server, but **not** the other devices on your network | see below |

**Installing softnet** (needs the administrator password once):
```bash
# 1) скачать и положить в ~/.local/bin (панель сама ищет там; sha256 берите из страницы релиза)
curl -fsSL -o /tmp/softnet.tar.gz https://github.com/cirruslabs/softnet/releases/download/0.24.1/softnet.tar.gz
echo "8ff8ff099c2b5ac1b1128e7999c4a730ac85f486c8a4cb0239eb98432859a0f7  /tmp/softnet.tar.gz" | shasum -a 256 -c
tar -xzf /tmp/softnet.tar.gz -C /tmp softnet && mkdir -p ~/.local/bin && cp /tmp/softnet ~/.local/bin/softnet && chmod 755 ~/.local/bin/softnet
# 2) права root (SUID) — единственное, что требует пароля
sudo chown root:wheel ~/.local/bin/softnet
sudo chmod u+s ~/.local/bin/softnet
ls -l ~/.local/bin/softnet     # должно быть: -rwsr-xr-x  root  wheel
```
(Comments in the block above, translated: 1) download and put into `~/.local/bin` — the panel looks there itself; take the sha256 from the release page. 2) root ownership (SUID) — the only step that needs a password. Expected `ls` output: `-rwsr-xr-x  root  wheel`.)

Without softnet everything works, but the log will contain the warning "network isolation is OFF — the guest can reach your local network".
Rollback: `sudo chmod u-s ~/.local/bin/softnet` or `rm ~/.local/bin/softnet`.

⚠️ **If a VPN is enabled on the Mac** with a default route, the VM may have no internet (the local network works). For workflows that need
internet, turn the VPN off while the runner is starting.

---

## 1. Base VM with a runner

1. Click **"Install files"** («Установить файлы») for the provider you need (the "CI runners" («CI-раннеры») block): the official runner is downloaded and its sha256 is checked.
   Gitea/Forgejo — `gitea-runner` (~18 MB), GitHub — `actions/runner` (~130 MB).
2. Stop the base VM (if it is running) and click **"Runner into VM…"** («Раннер в ВМ…») on it → provider. The files are copied over SSH and checked by the sha256 of each file.
3. If your workflows use `actions/checkout` or Node actions, the base must have **git** and **Node**. The `vanilla` image has neither; after installing
   Command Line Tools in the VM, git is available, and Node is placed from the official archive into `/usr/local` (this is how the `runner-base` VM was made). Not needed for simple `run:` steps.

Make the base **once**: every runner launch makes a **copy** of it, and the base itself does not change.

---

## 2. Access token on the CI server (the only manual step)

The token gives the panel the right to: obtain runner registration tokens, delete abandoned runners and (for the self-test) create/delete **its own**
test repository. The token is stored in the file `~/.service-admin/runner-tokens/<id>.token` (permissions 0600), is **never shown** back in the interface,
and **does not get** into the audit or logs.

### Gitea / Forgejo
1. Open Gitea → avatar → **Settings → Applications → Generate New Token**.
2. Name: `service-admin`. Permissions (scopes):
   * **organization** scope (recommended): `write:repository`, `write:organization`, `write:user`;
   * **whole server** (instance) scope: the same + `write:admin`, and the token must belong to a Gitea **administrator**.
3. Click "Generate token" and copy it right away (it is not shown later).
4. **Actions** must be enabled in Gitea (`app.ini` → `[actions]` → `ENABLED = true`).

### GitHub (the code is written from the API documentation, **not verified on a real GitHub**)
1. Settings → Developer settings → Personal access tokens (classic) → Generate: scope **`repo`** (for an organization also **`admin:org`**).
2. The whole-server (instance) scope is not supported on GitHub: use an organization or a repository.

Do not send the token in chat and do not paste it into other programs: it is entered **only in the panel**.

---

## 3. Add a source to the panel

The "CI runners" block → **"Add source…"** («Добавить источник…»), following the prompts:

![The "CI runners" block: runner files, a source and its buttons](../img/18-vms-ci-runners.jpg)


| Question | What to enter |
|---|---|
| CI system | `gitea` (Gitea and Forgejo) or `github` |
| server address | `https://git.example.com` — **IP or name**, without login and parameters. `http://` with an access token is allowed only for local addresses (192.168.x.x, `*.local`, a name without a dot) |
| scope | `instance` (whole server), `org` (organization) or `repo` (a single repository) |
| path | empty for `instance`; the organization name for `org`; `owner/repository` for `repo` |
| name | anything, for example `Lab` |
| token type | **`api`** (access token, recommended: the panel obtains registration tokens itself and cleans up after itself) or `registration` (a ready-made registration token — runner launch only, with no self-test and no deletion of an abandoned runner) |
| token | paste the one you copied |

Click **"Check"** («Проверить») on the source: "Connection works: user …, runners on the server: N" means the token was accepted and its permissions are sufficient.
Typical errors: *"token lacks the required scope"* — the token lacks permissions; *"not found"* — wrong address/path/scope; *"server redirected"* — specify the final address
(usually `https://…`).

---

## 4. Self-test — check the whole chain with one button

On a source with an `api` token and an `instance` or `org` scope: **"CI self-test…"** («Самотест CI…») → base VM → type the source name to confirm.

The panel itself:
1. creates a test repository `ci-selftest-xxxxxx` on the server (under your user for instance, in the organization for org);
2. puts a workflow into it that prints `uname`, the `node`/`git` versions and `selftest-ok`;
3. clones the base VM, starts it with network isolation, registers a runner (`--ephemeral`, one job);
4. finds the run **for its own commit specifically** and checks for `success`;
5. deletes the VM, the abandoned runner and the test repository.

Before the start a **macOS system dialog** appears — click "Approve" (this protects against a program on your Mac starting CI without you).
Success — the log ends with the line **`SELFTEST PASSED`**. The log is visible on the panel's "Processes" (Процессы) page (the terminal icon in the header):

![Self-test log: runner registered, job done, VM and repository deleted](../img/19-selftest-job-log.jpg)

The log shows: the test repository was created, the workflow was pushed, **network isolation is on**, the `ci-…` VM clone was started, the runner was registered as ephemeral,
the job was executed, the VM was deleted, the run result is `success`, the test repository was deleted. If the repository was not deleted (no `delete` permission), the log will say `NOTE: … delete it by hand`.

The `repo` scope is not suitable for the self-test: it commits nothing to your real repository. For `repo` use "On-demand runner…".

---

## 5. On-demand runner for real work

On a source, **"On-demand runner…"** («Раннер по требованию…») → base VM → how many minutes to wait for a job (1–240) → source name → **macOS system dialog "Approve"**. Then:

1. the VM is cloned and started, the guest checks that it can see the CI server (otherwise the job fails immediately with a clear error);
2. the runner registers as `ci-xxxxxxxx` with the label **`macos:host`** (Gitea) — write `runs-on: macos` in the workflow;
   for GitHub the labels are the standard ones: `runs-on: [self-hosted, macOS]`;
3. it waits for **one** job (push something — or it is already in the queue);
4. after the job (or when the time runs out) the VM is deleted; the abandoned runner is deleted from the server (`api` source).

One launch = one job = one VM. For continuous work, press the button (or have the agent do it) for each build you need.

---

## 6. Working through an AI agent

The agent (Claude Code, Codex, …) connects to the panel over MCP (the "Agent connection" («AI-доступ») page). For CI operations the agent needs **level L3** — you
grant it in the agents table (the panel asks again). What the agent can do at level L3:

* read: `list_ci_sources` (sources **without tokens**), `list_vms`, `inspect_system`, …;
* **propose** the operations `runner.spawn` and `runner.selftest` through `plan_changes` (parameters: `source` — an id from `list_ci_sources`, `vm` — the base,
  `confirm` — the exact source name, `minutes`, optionally `isolate`).

**The agent cannot execute anything by itself:** after `plan_changes` you click **"Approve"** in the panel ("Agent connection" → request queue) — a
**macOS system dialog** appears with the warning "WARNING, level L3…", the source name, the server address and the VM. Only after your "Approve" does the agent
call `execute_plan`, watch `get_job_status` and check `verify_plan`. "Don't ask" is **impossible** for L3 — even the "button in the panel" mode does not apply to L3. Limits: 6 proposals and 3 CI executions per hour per agent.
The agent **does not see** any tokens (neither access nor registration) and cannot enter them: you add the source and the token.

Example request to the agent: "Run the CI self-test: find the source and a stopped base VM, propose a `runner.selftest` plan and tell me its id".

---

## 7. Security — what is important to understand

* Registering a runner gives the CI server the right to send **code from workflows** to the runner. It runs **inside a disposable VM**; therefore for third-party and
  untrusted repositories use only this mode, not a runner directly on the Mac.
* **Do not connect a public repository that accepts pull requests from strangers** (nor any repository whose code you do not trust): a workflow from such a PR will run on your runner and will see the job's tokens and secrets. The disposable VM and softnet limit the damage to the host and the local network, but not the job's own secrets. GitHub gives the same recommendation for self-hosted runners on public repositories.
* The guest sees the internet and the **allowed addresses of the CI server**; the rest of the local network is unreachable (with softnet enabled). Without softnet it is reachable.
* The access token can do a lot (create repositories, manage runners): give it **minimal** permissions and revoke the token on the CI server if it is no longer needed.
  "Remove" on a source in the panel deletes the stored token from the Mac.
* All actions are written to the audit (`#audit`) without secrets.

---

## 8. If something goes wrong

| Symptom | What to check |
|---|---|
| "Install files" does not download | internet on the **host**; disk space (≥ 5 GB needed) |
| `Runner into VM…`: "the VM did not accept SSH in 2 minutes" | is `sshpass` installed; is SSH enabled in the VM image and is the `admin` account password `admin` (cirruslabs images) |
| "the guest cannot reach the CI server" | the guest does not see the server: check the address; a VPN on the host (turn it off); with softnet the server must be reachable at the address the **host** resolves (with `isolate=false` isolation is turned off) |
| "Check": "token lacks the required scope" | recreate the token with the required permissions (section 2) |
| self-test: `runner.selftest_scope` | choose a source with the `instance` or `org` scope |
| "Runner … cannot register" / registration fails | Actions are disabled on the server; wrong token; for GitHub — no `admin:org` permission |
| the runner stayed "offline" on the server | a source with token type `registration` — delete the runner on the server by hand (with `api` the panel deletes it itself) |
| a `ci-…` VM remained after a failure | VMs page → "Stop", "Delete…" (type the name); normally the panel deletes them itself |
| the log says "network isolation is OFF" | `softnet` is not installed or lacks SUID (section 0) |

Implementation and verification details — `../../docs/en/roadmap.md` (Phase 5), the list of unverified items — `../../docs/en/unverified.md`, the checklist — `../../docs/en/checklist.md`; installation from scratch — `install-clean-mac.md`.
