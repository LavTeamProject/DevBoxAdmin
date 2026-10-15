# Remote API, operators and the Telegram bot

Page **Agent connections → Remote connection**. Everything is off by default. Any switching on or widening of access is confirmed by a **system window on the machine with the panel** (on a Linux machine without a screen — `service-admin approve`, see `connect-ai-agent-linux.md`).

## 1. API for your own app
1. The **API for your own app** block: address (127.0.0.1 — for a reverse proxy/SSH tunnel; a LAN/VPN address; outside localhost **TLS** and an **allow-list of addresses** are mandatory), port (8766 by default), “Enable” → **Save** → confirm in the system window.
2. The panel shows the address and the **certificate SHA-256 fingerprint**: pin it in the client (example — `examples/remote_client.py`, description — `docs/openapi-remote.yaml`).
3. An agent token for the client: pick the agent → **Issue a new token** (the previous one stops working). The token is shown once.

## 2. Operators
An operator is an administrator: sees state/log and approves **L2** plans. Create one: a name, rights (read / approve), optionally a Telegram `chat_id`. The token and the TOTP secret are shown **once**: add the secret to an authenticator app. An operator with the approve right is created through the system window. Approval needs: the token, a **single-use TOTP code**, the **plan hash**, and the setting “Operators may approve plans” switched on. An **L3** plan cannot be approved remotely.

## 3. Telegram bot
1. Create a bot with @BotFather, paste its token into the **Telegram bot** block, “Enable” → **Save** (system window) → **Check token**.
2. Message the bot `/start`: it replies with your `chat_id` — enter it for the operator.
3. Commands: `/status`, `/plans`, `/approve <id> <hash> <code>`, `/reject <id>`. The bot announces new plans itself.
The bot polls Telegram itself (no inbound port). Messages pass through Telegram's servers and carry a short plan description without secrets.

Revoking: “Revoke” on the operator; to turn the API off clear “Enable” (no dialog).
