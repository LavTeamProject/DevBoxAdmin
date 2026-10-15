# Manuals

Step-by-step instructions for people. All of them were checked on a real system; anything that could not be verified is marked in the text and in `../../docs/en/unverified.md`.

| Manual | What it covers |
|---|---|
| [install-clean-mac.md](install-clean-mac.md) | Installation on a **clean Mac**: the installer, the app, "System preparation", Command Line Tools — with screenshots |
| [connect-ai-agent.md](connect-ai-agent.md) | Connect an AI agent (Claude Code and others) over MCP: levels L1–L3, approval in a system dialog |
| [ci-runners.md](ci-runners.md) | On-demand CI runners in disposable VMs (Gitea/Forgejo, GitHub): access token, self-test, L3 agent |
| [install-linux.md](install-linux.md) | Installation on **Linux** (Ubuntu/Debian): one command or a `.deb`, the systemd service, system setup, profiles, packages and services — with screenshots |
| [connect-ai-agent-linux.md](connect-ai-agent-linux.md) | An AI agent on Linux: how a human approves actions (a window or `service-admin approve`), when the channel is disabled |
| [connect-ai-agent-remote.md](connect-ai-agent-remote.md) | A remote agent over SSH: a restricted key starts only one agent's MCP bridge |
| [remote-api-and-telegram.md](remote-api-and-telegram.md) | The remote API for your own app, operators (TOTP) and the Telegram bot |
| [ci-runners-linux.md](ci-runners-linux.md) | CI runners on Linux: QEMU without root, a base from an Ubuntu image, network isolation, KVM |

Screenshots are in `../img/` (JPEG, cropped and downscaled). **Rule:** a new manual goes into this folder; screenshots only from a real system (a VM or your own Mac), with no personal data.

Plans and status: `../../docs/en/roadmap.md`; checklist of checks for the owner: `../../docs/en/checklist.md`; unverified items: `../../docs/en/unverified.md`.
