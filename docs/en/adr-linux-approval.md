# ADR-0001: Approval channel for agent actions on Linux

Status: **accepted (design); implementation is stage L2**. Requires an independent security review before release.

## Context
On macOS a human approves an agent's plan with a **system dialog** (`osascript`, default button "Reject", 110 s = reject). An agent with a terminal on the same machine can bypass the panel's gateway but **cannot click a button in the dialog**. On Linux there may be no dialog at all (a server without a screen), and the Python stdlib has no asymmetric cryptography.

**Threat model:** the agent runs as the same user as the panel and has a shell (it can read the user's files, start processes, call the panel's HTTP API, create PTYs). The agent does **not know** the administrator password and has no passwordless sudo. If the user does have passwordless sudo, protection is impossible by definition (root = everything): channel 2 is then **disabled** (fail closed) and the installer warns.

## Options
- **A. A dialog in the graphical session** (`zenity`/`kdialog`). The analogue of macOS. Needs a screen and the user's session. The agent cannot press the button, but on X11 it could in theory synthesise input into a window of its own user (Wayland blocks this, X11 does not) — we document this residual risk.
- **B. Approval through privilege elevation** (`pkexec` + a polkit action with `auth_admin`; fallback `sudo` with `timestamp_timeout=0`). Works over ssh without a screen and needs the **human's password** for every approval. The decision is written by **root** (directory `/var/lib/service-admin/approvals/`, `root:root`); the panel accepts only files with `st_uid == 0`. No crypto is needed: a root-owned file cannot be forged without root.
- **C. TOTP / a code from a phone.** The secret must live where an agent of the same user cannot read it → root ownership again; more complex than B with no gain.
- **D. A button in the panel.** An agent with access to the HTTP API presses it itself. Forbidden for L3; for L2 only as an explicit mode with audit (already exists).

## Decision
1. A graphical user session and `zenity`/`kdialog` exist → **channel A** (X11 caveat in the docs).
2. Otherwise (or by the user's choice) → **channel B**: `service-admin approve <plan>` shows the plan text (like the dialog) and calls `pkexec /usr/local/libexec/service-admin-approve`; the root script reads the plan request from the user's directory, shows a summary, asks `y/N` on **/dev/tty**, and writes the decision into the root directory (`plan_id`, `digest`, `decision`, expiry). The panel executes a plan only if the decision file is root-owned and the `digest` matches.
3. No channel available, or the user has passwordless sudo → agent L2/L3 plans are not executed (`plan.no_approval_channel`).
4. L3 — only channel A or B; the "button in the panel" mode stays forbidden for L3.

## Consequences
- An install step with administrator rights is needed (the polkit action + the helper script); without it only channel A remains.
- Tests: substitute `zenity`/`pkexec` (as with `osascript`); a check that "an agent of the same user could not approve by itself".
- Residual risks are recorded in `docs/unverified.md` after the review.

## Implementation requirements (from the review; mandatory for L2)
1. **Who verifies the decision.** An approval is meaningful only if the code that verifies it and executes the plan cannot be replaced by the agent. In L2 the executing part (checking the root owner of the decision, comparing the `digest`, running the operation) runs as a **separate service under another user/root**, or is installed in a directory the panel's user cannot write; until that is done, channel B protects against accidental and naive agent actions but **not** against an agent that edits the panel's code or injects into its process (`ptrace`, `kernel.yama.ptrace_scope`). This is recorded under "Residual risks".
2. **Replay.** A decision is bound to a one-time `nonce` that the panel puts into the request and the `digest`; the panel remembers used nonces. A decision's lifetime is short (minutes).
3. **The root script and the user's directory.** The script opens the request once with `O_NOFOLLOW|O_NONBLOCK`, checks it with `fstat` (a regular file, owner = `PKEXEC_UID`, size ≤ 64 KB), reads the bytes once and **displays and hashes the same buffer**; `plan_id` is validated against `^[A-Za-z0-9-]{1,64}$` (no paths from argv); the decision is written atomically (`O_CREAT|O_EXCL` + rename) into a `root:root 0755` directory.
4. **Privilege caching.** The polkit action is strictly `auth_admin` (not `auth_admin_keep`); for the `sudo` fallback, `Defaults:ALL timestamp_timeout=0` for this command. Channel B is **disabled** (`plan.no_approval_channel`) if the user has passwordless sudo, a polkit rule granting `wheel`/`sudo` without a password, or membership in root-equivalent groups (`docker`, `lxd`, `libvirt`, `disk`) — the installer warns and `/api/platform` shows `approval.unsafe`.
5. **Channel A.** `zenity`/`kdialog` are started by **absolute path** from system directories (not from the user's `PATH`). Residual risks: X11 (input synthesis), Wayland with `ydotool`/`uinput` (group `input`).
6. **Residual risks are recorded** in `docs/unverified.md` and in the Linux guide for connecting an agent.

## Additions after the L2 security review (implemented)
- **A confirmation code.** The helper asks for a random code shown only on the human's screen; the input queue is flushed before the request (`tcflush`). The agent can write to the human's tty or push a `y` through TIOCSTI, but it does not know the code. Verified in the VM: "y" without the code → reject.
- **Install source.** `install-approver.sh` refuses to install the helper if any component of its path is writable by the panel's user.
- **Channel A vs B.** If the dialog is spoofable (X11 or the `input` group) and a safe root helper is ready, the helper is chosen.
- **Unsafe conditions** are extended: `sudo` by absolute path with a clean environment (cached for 60 s), the `incus`/`incus-admin` groups, polkit rules with `YES` without a password.
- The helper refuses when both `PKEXEC_UID` and `SUDO_UID` are set; shows the request type (agent plan / direct panel action) and id; the CLI never auto-picks `direct-*` requests; bidi/invisible characters are stripped from the text.
- **Residual risks (added):** the agent can write to the human's tty (hide/replace the screen), so the code, not the text, is the protection; the `service-admin` CLI and the shell belong to the user — it is safer to call `pkexec /usr/local/libexec/service-admin-approve <id>` directly from a trusted terminal; a NOPASSWD rule limited to dangerous programs is equivalent to root and is not detected.

## Addendum (final review, L8)
- The panel **never types** an administrator command into its own PTY (`sudo` is shown/copied for the owner's own terminal): an agent of the same user could observe or inject input. The command is `/usr/bin/sudo -k -- …`, the GUI path is `/usr/bin/pkexec` by absolute path; elevation tools are looked up only in system directories.
- The helper refuses to run if `server.py` is among its ancestors (started from the panel's Terminal tab).
- On Linux the panel API checks the owner of the client socket (`/proc/net/tcp`): another local user gets 403 (`srv.peer_forbidden`). Not applied on macOS.
- `~/.service-admin` is mode 0700; the MCP client hint depends on the agent level.
