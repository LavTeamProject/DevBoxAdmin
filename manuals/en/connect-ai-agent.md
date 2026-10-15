# Connecting an AI agent to the panel (MCP)

_The screenshots show the Russian interface; switch to English with the RU / EN buttons in the panel header._

The panel gives the agent (Claude Code, Codex, OpenCode, Gemini or your own) **a small set of operations**, not access to the machine. The connection goes over a Unix socket
`~/.service-admin/agent.sock` (permissions 0600) — there is no network port. A "run a command" tool (`execute_shell`) **does not exist**.

> Verified with a real **Claude Code 2.1.236**. Codex, OpenCode and Gemini should work the same way (MCP stdio), but have **not been verified** —
> see `../../docs/en/unverified.md`.

## Agent levels (you grant them, not the agent)

| Level | What the agent can do |
|---|---|
| **L1 — read only** | `inspect_system`, `inspect_diagnostics`, `inspect_profile`, `list_capabilities`, `list_operations`, `describe_operation`, `list_vms`, `list_ci_sources`, `list_containers` (containers of the local Docker) (no tokens), `get_job_status`. It **does not see** any write tools |
| **L2 — proposes changes** | everything from L1 + `plan_changes`, `get_plan`, `execute_plan`, `cancel_plan`, `verify_plan`, `cancel_job` (stops only a job from the agent's own plan) for 6 operations: environment snapshot, backup, profile installation, package installation, project test/build, start/stop/restart of a Docker container (`docker.container_control`; local Docker only — refused with a remote context) |
| **L3 — CI operations too** | everything from L2 + `runner.spawn`, `runner.selftest` (a runner in a disposable VM). Granted with a warning; **confirmation is always in the system dialog**, "don't ask" is impossible |

**Any change proposed by the agent is executed only after you confirm it in a macOS system dialog** (the default button is "Reject";
no answer within 110 seconds means refusal). The agent cannot click this dialog.

## Step 1. Register the agent

1. Open the panel → **"Agent connection"** («AI-доступ») (`#connect`).
2. Enter a name (for example `claude`), choose a level (start with **L1**), optionally an expiry → **"Register"** («Зарегистрировать»).
3. The panel will show a **ready-made command** and a JSON configuration. The agent's secret is **not shown**: it is stored in the file `~/.service-admin/agents/<id>.token` (permissions 0600),
   and the registry keeps only its SHA-256 hash.

![Agent registration form: name, level, expiry](../img/14-connect-register.jpg)

After registration the agent appears in the table. The level can be changed right there (for L3 the panel asks again); next to it are the "Change secret" and "Revoke" buttons.
Below the table the panel lists what is available to the agent at each level.

![Agents table: level L3 and the list of what is available](../img/16-connect-agents-l3.jpg)

## Step 2. Connect the client

**Claude Code** — run the command shown (the panel fills in the path to Python and `mcp_server.py`):
```bash
claude mcp add service-admin -- <python> <папка>/mcp_server.py --agent <id>
```
Restart Claude Code and ask: "call `inspect_system` and tell me what you see".

**Other clients** (Codex, OpenCode, Gemini): paste the JSON from the panel into their MCP server configuration:
```json
{"mcpServers": {"service-admin": {"command": "<python>", "args": ["<папка>/mcp_server.py", "--agent", "<id>"]}}}
```
The `mcp_server.py` process does nothing to the machine: it reads the agent's secret and forwards calls to the panel. **The panel must be running** (the "Service Admin" app
or autostart at login); otherwise the agent gets a clear "panel is not running" error.

Check without a client (CLI, same permissions and audit):
```bash
./service-admin --agent <id> status          # Mac state and detected problems
./service-admin --agent <id> tools           # what is available to this agent
```

## Step 3. How a change happens (L2/L3)

1. The agent calls `plan_changes` → gets a `plan_id` and an expiry (15 minutes). **Nothing is executed.**
2. In the panel ("Agent connection") the plan appears in the request queue; the menu shows a counter of pending items, and a notification "The agent asks you to confirm…" appears at the top.

   ![Request queue: the agent's plan is waiting for confirmation](../img/15-connect-queue.jpg)

   Click **"Approve…"** («Одобрить…») → macOS shows a **system dialog** with the agent's name, the operation, the parameters and "what will happen" (for L3 — marked "WARNING, level L3").
   The default button is "Reject"; if you did not request this, click it.

   ![macOS system dialog for an L3 plan](../img/17-approval-dialog-l3.jpg)
3. You clicked **"Approve"** → the agent calls `execute_plan` (once; if the machine has changed since the approval, the plan is "stale" and a new one is needed) and watches `get_job_status`.
   **"Reject"** or silence for 110 s → the plan is rejected.
4. `verify_plan` checks the result if the operation has an automatic check.

**Watching what the agent does:** jobs started by the agent (installation, runner, self-test) appear within a few seconds on the panel's "Processes" (Процессы) page (the terminal icon in the header or the Ctrl + backtick shortcut), with a full log — you do not need to ask the agent what is going on. Everything else is in the "Audit" (Аудит).

Per-agent limits: up to 5 open plans, 10 executions and 3 CI operations per hour, 60 calls per minute; no more than one plan running at a time. After repeated failures
of the same plan the panel stops the agent (`plan.escalate`) — a human has to decide.

## Security — what is important to understand

* **An honest limitation:** an agent running on this same Mac usually has its own terminal and can do the same thing bypassing the panel. Confirmation in the
  system dialog protects the operations it performs **through** the panel (and leaves a log), but not its own terminal. For untrusted code
  you need isolation (a virtual machine).
* The secret can be **changed** ("Change secret" in the agents table — the old one stops being accepted immediately) or **revoked** ("Revoke").
* Everything the agent does is written to the **Audit** (`#audit`): who (agent name and id), what, with what result; secrets are not recorded.
* Enable level L3 only if you really run CI: it lets the agent **propose** registering a runner on an external server and running code in a VM
  (each one only with your "Approve").

## If something goes wrong

| Symptom | What to do |
|---|---|
| agent: "panel is not running" / `panel_unavailable` | open "Service Admin" or run `python3 server.py`; the socket `~/.service-admin/agent.sock` appears together with the panel |
| `unauthorized` | the secret was changed/revoked or has expired; register the agent again |
| `forbidden: tool … needs level L2` | the agent's level is lower than required; change the level in the agents table |
| `plan.not_approved` | you have not approved the plan yet (or did not click "Approve" in the dialog) |
| `plan.stale` | the machine changed after approval; the agent must propose the plan again |
| the dialog does not appear | a graphical macOS session is required; check "System Settings → Notifications" and that the app is not in Do Not Disturb mode |
