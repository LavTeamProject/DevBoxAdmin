# Service Admin

[English](README.md) · **Русский**

Локальная веб-панель, которая готовит и обслуживает весь Mac для разработки — начиная с только что установленной macOS —
и позволяет ИИ-агентам (Claude Code, Codex, …) работать с машиной **только через одобренные планы с журналом аудита**.

* **Без зависимостей.** Python stdlib и ванильный JS. Свой Python 3.12 скачивает установщик — на чистом Mac ничего не нужно.
* **Только локально.** Слушает `127.0.0.1`, команды запускаются списком аргументов, без shell.
* **Apple Silicon**, macOS 13+. Язык интерфейса: русский (по умолчанию) и английский.

## Возможности

Подготовка системы (Command Line Tools, Homebrew, Git), профили установки со снимками «до/после», службы и пакеты Homebrew, Docker/OrbStack,
Herd, версии языков, конфиги с проверкой и бэкапом, панель нагрузки, настоящий терминал в браузере, Git-проекты и тесты/сборки,
мобильные тулчейны, резервные копии, виртуальные машины tart и **одноразовые CI-раннеры** (Gitea/Forgejo, GitHub) в изолированной ВМ,
Agent Control API для ИИ-агентов (уровни L1–L3, планы с подтверждением в диалоге macOS, лимиты) и журнал аудита с указанием инициатора.

## Установка

Одной командой (нужны только `curl` и `tar`, они есть в macOS):

```bash
curl -fsSL https://raw.githubusercontent.com/LavTeamProject/DevBoxAdmin/main/get.sh | zsh
```

Скрипт скачает исходники в `~/.service-admin/app` и запустит `install.sh`; повторный запуск обновляет панель (данные в `~/.service-admin` не трогаются).
Чтобы закрепить версию: `SA_REF=<тег или коммит>` (и, по желанию, `SA_SHA256=<сумма архива>`). Скрипт короткий, его можно прочитать заранее: [`get.sh`](get.sh).

Или вручную:

```bash
git clone https://github.com/LavTeamProject/DevBoxAdmin.git ~/service-admin
cd ~/service-admin
./install.sh
```

Панель откроется на **http://127.0.0.1:8765**. Подробно со скриншотами (проверено на чистой macOS в ВМ): [`manuals/install-clean-mac.md`](manuals/install-clean-mac.md).

## Руководства

[`manuals/install-clean-mac.md`](manuals/install-clean-mac.md) · [`manuals/connect-ai-agent.md`](manuals/connect-ai-agent.md) ·
[`manuals/ci-runners.md`](manuals/ci-runners.md) · [`docs/roadmap.md`](docs/roadmap.md) · [`docs/unverified.md`](docs/unverified.md)

## Безопасность

* Не открывайте панель в сеть; для удалённого доступа — SSH-туннель.
* У агентов нет shell: любое изменение — план, который вы одобряете в системном диалоге macOS (по умолчанию «Отклонить», 110 с = отказ).
* **CI-раннер исполняет код из workflow. Не подключайте публичный репозиторий, куда принимают pull request от посторонних.**
  Раннер одноразовый и в изолированной ВМ, но секреты самого задания доступны его коду.

Не проверено на реальных системах: раннеры GitHub, клиенты MCP Codex/OpenCode/Gemini, образ ВМ с Xcode (см. [`docs/unverified.md`](docs/unverified.md)).

## Лицензия

MIT — см. [LICENSE](LICENSE). Об ошибках: кнопка **«Сообщить о проблеме»** в панели (открывает заготовленную заявку на GitHub; само ничего не отправляется) или обычный issue.
