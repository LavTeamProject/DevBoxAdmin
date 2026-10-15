# Agent connections: sections and wizards

The **Agent connections** page is split into parts and the typical tasks are wizards (the “Start” button on the Overview).

## Sections
- **Overview** — the state (agents, approvals, Telegram, API, operators), three wizards and an explanation of **where you approve actions**.
- **Agents** — the agent table, levels, secret rotation and revocation.
- **Approvals** — the plans agents proposed, and the approval mode.
- **Operators** — administrators who see the state and approve plans remotely: rights, the Telegram chat, the TOTP secret.
- **Channels** — fine-tuning of SSH, the API and the Telegram bot.
- **Operations catalog** — what the panel can do at all and what agents can use.

## Wizards
1. **Connect an AI agent** — a name and level (L1 read / L2 proposes changes / L3 + CI) → where the agent runs (this computer, another one over SSH, your own app over the API) → a ready command or instructions.
2. **Control from Telegram** — your bot's token (created with @BotFather) → an **operator** (the bot listens only to operators: the wizard offers to create the first one or pick an existing one; your chat is detected by itself: send the bot any message and the chat appears in the list) → the TOTP secret for an authenticator app and turning on approval from Telegram → a check with `/status`.
3. **Connect your own app (API)** — where it calls from (only this computer / the network or VPN with TLS and an address list / your own) → an operator or agent token → the address, the certificate fingerprint and a sample request.

## Where you approve actions
- **Agent L2 plans.** The agent changes nothing by itself, it proposes a plan. You press “Approve” on the Approvals section — then a system window opens on this computer. If a Telegram operator is set up and “Operators may approve plans” is on, the plan can be approved in Telegram (the `/approve <id> <hash> <code>` command, the code from the authenticator): no window on the computer is needed then.
- **L3 operations (CI).** Only the system window on this computer. They cannot be approved from Telegram or the API.
- **Settings on this page** that weaken protection (connecting a bot, an operator with the approve right, remote access, raising an agent's level, issuing a token): always a system window on this computer. Telegram does not replace it.
- The agent itself can approve nothing.

More on the API, operators and Telegram: `remote-api-and-telegram.md`; on SSH: `connect-ai-agent-remote.md`.
