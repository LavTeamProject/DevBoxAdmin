# Руководства (manuals)

Пошаговые инструкции для человека. Все проверены на реальной системе; что проверить не удалось — помечено в тексте и в `docs/unverified.md`.

| Руководство | О чём |
|---|---|
| [install-clean-mac.md](install-clean-mac.md) | Установка на **чистый Mac**: установщик, приложение, «Подготовка системы», Command Line Tools — со скриншотами |
| [connect-ai-agent.md](connect-ai-agent.md) | Подключить ИИ-агента (Claude Code и др.) по MCP: уровни L1–L3, подтверждение в системном диалоге |
| [ci-runners.md](ci-runners.md) | CI-раннеры по требованию в одноразовых ВМ (Gitea/Forgejo, GitHub): токен доступа, самотест, агент L3 |
| [install-linux.md](install-linux.md) | Установка на **Linux** (Ubuntu/Debian): одна команда или `.deb`, служба systemd, подготовка системы, профили, пакеты и службы — со скриншотами |
| [connect-ai-agent-linux.md](connect-ai-agent-linux.md) | ИИ-агент на Linux: как человек подтверждает действия (окно или `service-admin approve`), когда канал отключается |
| [connect-ai-agent-remote.md](connect-ai-agent-remote.md) | Удалённый агент по SSH: ограниченный ключ запускает только мост MCP одного агента |
| [python-and-homebrew.md](python-and-homebrew.md) | Python (версии, по умолчанию без полного пути, pip-пакеты) и пакеты Homebrew (лишние, размер) |
| [connect-agents-wizards.md](connect-agents-wizards.md) | Страница «Подключение агентов»: разделы, мастера и где вы одобряете действия |
| [remote-api-and-telegram.md](remote-api-and-telegram.md) | Удалённый API для своего приложения, операторы (TOTP) и Telegram-бот |
| [ci-runners-linux.md](ci-runners-linux.md) | CI-раннеры на Linux: QEMU без root, основа из образа Ubuntu, изоляция сети, KVM |

Скриншоты лежат в `img/` (JPEG, обрезаны и уменьшены). **Правило:** новое руководство — в эту папку; скриншоты — только с настоящей системы (ВМ или ваш Mac), без персональных данных.

Планы и статус: `docs/roadmap.md`; чек-лист проверок для владельца: `docs/checklist.md`; непроверенное: `docs/unverified.md`.

English: [`en/README.md`](en/README.md)
