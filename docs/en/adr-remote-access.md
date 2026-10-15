# ADR-0003. Remote access to the panel: client API, operators, Telegram (Phase 8)

Status: accepted by the owner 2026-10-15 (Telegram acceptable, the user's own bot; the user enables access; operators = administrators, as many as the user creates). Step 1 (SSH, the MCP bridge by a forced command) is done; this covers steps 2–3.

## Two roles
- **Agent** — an AI client: gateway tools by level (as over the socket), an agent token. Proposes plans, does not approve.
- **Operator** — a human administrator: sees state and audit, approves/rejects L2 plans remotely. An operator token is **not accepted** on `/agent/v1`, an agent token is not accepted on `/operator/v1` (separate registries).

## Decisions
1. **A separate listener** (`remote_api.py`), **off by default**. The panel API on `127.0.0.1:8765` and the agent socket do not change and are never exposed.
2. **The address is chosen by the user**: `127.0.0.1` (behind a tunnel/reverse proxy), a LAN/VPN address, or `0.0.0.0`. A non-loopback address **requires TLS** and a non-empty **allow-list of addresses** (CIDR); otherwise the listener does not start (fail closed). TLS: a self-signed certificate made by `openssl` (RSA-2048), the fingerprint is shown in the panel so the client can pin it.
3. **Tokens**: 256 bits of randomness, operator tokens carry the prefix `sao_` (agent tokens keep their format), only SHA-256 in the registry, constant-time compare, shown **once**; revocation and rotation; optional expiry. Attempt limit: 10 failures per address per minute → blocked for 5 minutes; an overall request limit per token.
4. **Operator rights**: `read` (status, plans, audit) and/or `approve`. Remote approval is also a **global setting** (off by default, audited, weakens protection like "button in the panel"). Approval requires: a token with `approve`, the operator's **TOTP code** (RFC 6238, the secret is shown once; a code is single-use), an **echo of the plan hash** (`digest`) and a plan of level L2. **An L3 plan can never be approved remotely** — only by the system dialog on the machine with the panel. The decision is recorded as `by=operator:<name>`.
5. **An agent cannot approve**: its token gives no access to `/operator/v1`; approval needs the operator's token and TOTP, which the agent does not have.
6. **Telegram**: the bot **polls** Telegram itself (outgoing HTTPS, no inbound port); only private chats with a `chat_id` bound to an operator are accepted; approval is a command with a TOTP code (a stolen Telegram account cannot approve without the code); the bot token is a 0600 file; messages carry a short plan description and the id, no secrets. New-plan notifications go to operators with the `approve` right.
7. **What an operator cannot do** (in this version): run operations, change settings, manage agents and operators — only read and approve/reject plans. That is the least right for the job "to supervise".
8. **Audit**: every remote request (address, who, path, response code); failed authentication — with a rate limit on records.
9. **Hard limits**: body ≤ 64 KB, JSON only, a 15 s connection timeout, a bounded number of simultaneous connections, no CORS.

## Threats and answers
| Threat | Answer |
|---|---|
| Guessing/stealing an agent token | 256-bit tokens, hashes, attempt limit, allow-list, TLS; the agent is bound to its level |
| An agent approves its own plan | another registry and scope; TOTP needed; L3 only by dialog; a local agent with a shell is the known residual risk (ADR-0001) |
| Stealing an operator token | approval is impossible without TOTP; reading is by `read`; revocation |
| Stealing a Telegram account | approval needs TOTP; restriction by `chat_id` |
| Replaying an intercepted request | TOTP is single-use; `digest` binds to the plan; plan TTL 15 min |
| MITM on the LAN | TLS is mandatory outside loopback; fingerprint pinning |
| DoS | limits on body, connections, attempts, requests per token |
| Plan swapped between display and approval | the `digest` echo is verified on the server |
| Secrets leaking into audit/Telegram | audit masking; messages without secret parameters |

## Changes after the independent review (2026-10-15)
- **TOTP lockout**: 5 wrong codes in a row → the operator is locked out of approving (API and Telegram); only a human unlocks it in the panel ("Unlock"); failure records in the audit are rate-limited.
- **Any rotation of an operator and any change of rights/chat for an operator who has or will get the `approve` right goes through the dialog**, and the dialog text names the action; granting `approve` issues a NEW token and TOTP secret (shown once). Operator names are ASCII only.
- **Listener**: the address check and the connection limit come BEFORE request parsing; the TLS handshake runs in a worker thread with a timeout (a silent TCP connection no longer freezes accepting); an overall 30 s deadline per request (slowloris); loopback addresses are never blocked (behind a reverse proxy every client is 127.0.0.1) — protection there is token entropy and the TOTP lockout; address lists wider than /8 (IPv4) and /32 (IPv6) are refused; when opening to the network the dialog always shows the final address list.
- **Telegram**: each bot run has its own stop event, a disabled bot handles no messages and its threads end; notifications and `/plans` show the plan parameters; settings are written atomically, re-reading after the dialog.
- **The re-review of the fixes** found more: raising an agent's level and "don't ask" (`/api/agent-gateway/settings`) and issuing an agent token (any level) now go only through the system window (before, a local HTTP client could create a self-approving L2 agent with no window); any Telegram chat binding and unlocking an operator go through the window, and the operator state shown in the window is checked at write time; TLS connections are closed after the response (there was a descriptor leak), the 30 s deadline covers receiving the request only, not the tool's work; `verify_request` cannot kill the listener; a replayed valid TOTP code is not counted as guessing, a locked operator gets a distinct answer; the Telegram offset is kept on disk; `plans.approve/_decide/reject` share one lock.
- Other: `plans.approve` under the lock; issuing an L3 agent token goes through the dialog; `shlex.quote` in the SSH forced command; the audit `limit` no longer causes a 500.

## Residual risks
- **An agent of the same OS user with a shell can write to `~/.service-admin`** (`remote.json`, `operators.json`, `plans.json`, the bot token) and bypass the dialogs: as before Phase 8 it can set a plan's status to "approved" itself. The dialogs protect against an agent limited to the HTTP API/reading files; against an agent with a shell the answer is isolation (a separate user or a VM), see ADR-0001.
- Behind a reverse proxy the address list does not apply (every client is 127.0.0.1): restrict access on the proxy.
- Telegram: the TOTP code is not bound to a plan; Telegram's server, seeing `/approve <id> <hash> <code>`, could swap the command for another pending plan within the code window. An inherent risk of the channel.
- For Telegram the operator token is not needed: the chat binding and a TOTP code are enough; a local agent reading `operators.json` obtains the TOTP secret (but binding a chat needs the dialog).
- The certificate is self-signed: the client must pin the fingerprint; a reverse proxy with a real certificate is preferable for the internet.
- The TOTP secret and hashes live in `~/.service-admin/operators.json` (0600): a local agent of the same user can read them (but not the operator's token).
- Telegram is a third-party server: it sees short plan descriptions and the fact of approval.
