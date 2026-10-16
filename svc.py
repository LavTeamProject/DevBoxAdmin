"""Manajemen service Homebrew lanjutan: katalog install, uninstall, info
(port, data, log), editor file konfigurasi + validasi, dan panel cloudflared
(login, tunnel, DNS route, ingress, jalankan tunnel manual)."""
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from http import HTTPStatus

from core import (BREW, BREW_PREFIX, DATA_DIR, ENV, HOME, PKG_RE, ApiError, load_state, output, run,
                  save_state, start_job, tail)

ETC, VAR = f"{BREW_PREFIX}/etc", f"{BREW_PREFIX}/var"
CFG_BACKUP_DIR = os.path.join(DATA_DIR, "backups", "services")
LOG_DIR = os.path.join(DATA_DIR, "logs")
CF_DIR = os.path.join(HOME, ".cloudflared")

CATALOG = [
    # (formula, nama, kategori, deskripsi)
    ("mysql", "MySQL", "Базы данных", "Самая популярная реляционная база данных"),
    ("mariadb", "MariaDB", "Базы данных", "Совместимый форк MySQL"),
    ("postgresql@17", "PostgreSQL 17", "Базы данных", "Надёжная реляционная БД с открытым исходным кодом"),
    ("redis", "Redis", "Базы данных", "Кэш и очереди в памяти (Laravel cache/queue/session)"),
    ("valkey", "Valkey", "Базы данных", "Открытый форк Redis (лицензия BSD)"),
    ("mongodb/brew/mongodb-community", "MongoDB", "Базы данных", "Документоориентированная NoSQL-база"),
    ("neo4j", "Neo4j", "Базы данных", "Графовая база данных"),
    ("memcached", "Memcached", "Базы данных", "Простой кэш в памяти"),
    ("nginx", "Nginx", "Веб-серверы", "Веб-сервер и обратный прокси"),
    ("httpd", "Apache", "Веб-серверы", "Apache HTTP Server"),
    ("caddy", "Caddy", "Веб-серверы", "Веб-сервер с автоматическим HTTPS"),
    ("php", "PHP-FPM", "Веб-серверы", "FastCGI для PHP (Nginx/Apache)"),
    ("dnsmasq", "dnsmasq", "Сеть", "Локальный DNS (напр. *.test → 127.0.0.1)"),
    ("cloudflared", "Cloudflare Tunnel", "Сеть", "Публикация локального приложения в интернет"),
    ("mailpit", "Mailpit", "Инструменты", "Перехват писем при разработке + веб-интерфейс"),
    ("meilisearch", "Meilisearch", "Инструменты", "Быстрый поисковый движок (Laravel Scout)"),
    ("minio", "MinIO", "Инструменты", "Объектное хранилище, совместимое с S3"),
    ("rabbitmq", "RabbitMQ", "Инструменты", "Message broker"),
    ("ollama", "Ollama", "Инструменты", "Локальный запуск LLM"),
    ("grafana", "Grafana", "Мониторинг", "Дашборды мониторинга"),
    ("prometheus", "Prometheus", "Мониторинг", "Сборщик метрик"),
    ("etcd", "etcd", "Инструменты", "Распределённое хранилище ключей и значений"),
    ("tomcat", "Apache Tomcat", "Веб-серверы", "Сервер приложений Java"),
    ("temporal", "Temporal", "Инструменты", "Платформа надёжных рабочих процессов"),
]


# 100 paket development yang direkomendasikan (semua sudah dicek ada di Homebrew).
# (nama, tipe, kategori, deskripsi)
RECOMMENDED = [
    # Database & cache
    ("mysql", "formula", "Базы данных и кэш", "Самая популярная реляционная база данных"),
    ("mariadb", "formula", "Базы данных и кэш", "Совместимый форк MySQL"),
    ("postgresql@17", "formula", "Базы данных и кэш", "Надёжная реляционная БД с открытым исходным кодом"),
    ("redis", "formula", "Базы данных и кэш", "Кэш, очереди и сессии в памяти"),
    ("valkey", "formula", "Базы данных и кэш", "Форк Redis под лицензией BSD"),
    ("memcached", "formula", "Базы данных и кэш", "Простой кэш в памяти"),
    ("sqlite", "formula", "Базы данных и кэш", "БД в одном файле, удобна для тестов"),
    ("duckdb", "formula", "Базы данных и кэш", "Встраиваемая аналитическая БД (CSV/Parquet)"),
    ("pgcli", "formula", "Базы данных и кэш", "Клиент PostgreSQL с автодополнением"),
    ("mycli", "formula", "Базы данных и кэш", "Клиент MySQL с автодополнением"),
    # Web server & jaringan
    ("nginx", "formula", "Веб-серверы и сеть", "Веб-сервер и обратный прокси"),
    ("httpd", "formula", "Веб-серверы и сеть", "Apache HTTP Server"),
    ("caddy", "formula", "Веб-серверы и сеть", "Веб-сервер с автоматическим HTTPS"),
    ("traefik", "formula", "Веб-серверы и сеть", "Современный обратный прокси для контейнеров"),
    ("dnsmasq", "formula", "Веб-серверы и сеть", "Локальный DNS, напр. *.test → 127.0.0.1"),
    ("mkcert", "formula", "Веб-серверы и сеть", "Локальные HTTPS-сертификаты, которым доверяет браузер"),
    ("cloudflared", "formula", "Веб-серверы и сеть", "Cloudflare Tunnel: публикация локального приложения"),
    ("ngrok", "cask", "Веб-серверы и сеть", "Мгновенный публичный туннель к localhost"),
    ("httpie", "formula", "Веб-серверы и сеть", "Удобный curl для тестирования API"),
    ("wget", "formula", "Веб-серверы и сеть", "Загрузка файлов из терминала"),
    # Queue, search & storage
    ("rabbitmq", "formula", "Очереди, поиск и хранилища", "Брокер сообщений AMQP"),
    ("kafka", "formula", "Очереди, поиск и хранилища", "Платформа потоковой передачи событий"),
    ("nats-server", "formula", "Очереди, поиск и хранилища", "Лёгкий и быстрый обмен сообщениями"),
    ("meilisearch", "formula", "Очереди, поиск и хранилища", "Быстрый поисковый движок (Laravel Scout)"),
    ("opensearch", "formula", "Очереди, поиск и хранилища", "Поиск и аналитика (форк Elasticsearch)"),
    ("minio", "formula", "Очереди, поиск и хранилища", "Объектное хранилище, совместимое с S3"),
    ("mailpit", "formula", "Очереди, поиск и хранилища", "Перехват писем при разработке + веб-интерфейс"),
    # AI & monitoring
    ("ollama", "formula", "ИИ и мониторинг", "Локальный запуск LLM (Llama, Qwen и др.)"),
    ("llama.cpp", "formula", "ИИ и мониторинг", "Инференс LLM на CPU/GPU Apple Silicon"),
    ("grafana", "formula", "ИИ и мониторинг", "Дашборды мониторинга"),
    ("prometheus", "formula", "ИИ и мониторинг", "Сборщик метрик"),
    ("btop", "formula", "ИИ и мониторинг", "Красивый монитор ресурсов в терминале"),
    ("htop", "formula", "ИИ и мониторинг", "Интерактивный монитор процессов"),
    # Bahasa & version manager
    ("fnm", "formula", "Языки и менеджеры версий", "Очень быстрый менеджер версий Node (альтернатива nvm)"),
    ("pnpm", "formula", "Языки и менеджеры версий", "Менеджер пакетов Node, экономящий диск"),
    ("yarn", "formula", "Языки и менеджеры версий", "Менеджер пакетов Node"),
    ("deno", "formula", "Языки и менеджеры версий", "Современная и безопасная среда выполнения JS/TS"),
    ("bun", "formula", "Языки и менеджеры версий", "Очень быстрая универсальная среда выполнения JS"),
    ("uv", "formula", "Языки и менеджеры версий", "Очень быстрый менеджер пакетов и проектов Python"),
    ("pyenv", "formula", "Языки и менеджеры версий", "Управление несколькими версиями Python"),
    ("pipx", "formula", "Языки и менеджеры версий", "Установка изолированных CLI-приложений Python"),
    ("go", "formula", "Языки и менеджеры версий", "Язык Go"),
    ("rustup", "formula", "Языки и менеджеры версий", "Установщик и менеджер тулчейнов Rust"),
    ("rbenv", "formula", "Языки и менеджеры версий", "Управление несколькими версиями Ruby"),
    ("openjdk", "formula", "Языки и менеджеры версий", "Java Development Kit"),
    ("maven", "formula", "Языки и менеджеры версий", "Система сборки Java"),
    ("gradle", "formula", "Языки и менеджеры версий", "Система сборки Java/Kotlin/Android"),
    ("composer", "formula", "Языки и менеджеры версий", "Менеджер пакетов PHP"),
    ("php", "formula", "Языки и менеджеры версий", "Последний PHP + PHP-FPM"),
    ("mise", "formula", "Языки и менеджеры версий", "Один менеджер версий для всех языков"),
    ("direnv", "formula", "Языки и менеджеры версий", "Автоматические переменные окружения для каждой папки проекта"),
    # CLI produktivitas
    ("jq", "formula", "CLI для продуктивности", "Обработка JSON в терминале"),
    ("yq", "formula", "CLI для продуктивности", "Обработка YAML/JSON/XML в терминале"),
    ("fzf", "formula", "CLI для продуктивности", "Нечёткий поиск по файлам, истории и т. д."),
    ("ripgrep", "formula", "CLI для продуктивности", "Очень быстрый поиск текста в коде (rg)"),
    ("fd", "formula", "CLI для продуктивности", "Простая и быстрая замена find"),
    ("bat", "formula", "CLI для продуктивности", "cat с подсветкой синтаксиса"),
    ("eza", "formula", "CLI для продуктивности", "Современный ls с иконками и статусом git"),
    ("zoxide", "formula", "CLI для продуктивности", "Умный cd, запоминающий папки"),
    ("tlrc", "formula", "CLI для продуктивности", "tldr: краткие примеры использования команд"),
    ("tree", "formula", "CLI для продуктивности", "Показ структуры папок"),
    ("tmux", "formula", "CLI для продуктивности", "Терминальный мультиплексор (панели и сессии)"),
    ("neovim", "formula", "CLI для продуктивности", "Современный редактор Vim"),
    ("starship", "formula", "CLI для продуктивности", "Быстрое и информативное приглашение shell"),
    ("zsh-autosuggestions", "formula", "CLI для продуктивности", "Подсказки команд из истории в zsh"),
    ("zsh-syntax-highlighting", "formula", "CLI для продуктивности", "Подсветка синтаксиса команд в zsh"),
    ("shellcheck", "formula", "CLI для продуктивности", "Линтер для shell-скриптов"),
    ("just", "formula", "CLI для продуктивности", "Запуск задач (альтернатива Makefile)"),
    ("watchman", "formula", "CLI для продуктивности", "Наблюдатель за файлами (React Native, Jest)"),
    # Git
    ("git", "formula", "Git", "Последняя версия Git"),
    ("gh", "formula", "Git", "GitHub CLI: PR, issues, Actions"),
    ("git-lfs", "formula", "Git", "Хранение больших файлов в Git"),
    ("lazygit", "formula", "Git", "Интерфейс Git в терминале"),
    ("git-delta", "formula", "Git", "Гораздо более удобное отображение git diff"),
    ("pre-commit", "formula", "Git", "Автозапуск линтеров перед коммитом"),
    ("act", "formula", "Git", "Локальный запуск GitHub Actions"),
    # DevOps & cloud
    ("kubernetes-cli", "formula", "DevOps & cloud", "kubectl для Kubernetes"),
    ("helm", "formula", "DevOps & cloud", "Менеджер пакетов Kubernetes"),
    ("k9s", "formula", "DevOps & cloud", "Терминальный интерфейс для Kubernetes"),
    ("kind", "formula", "DevOps & cloud", "Локальный кластер Kubernetes в Docker"),
    ("opentofu", "formula", "DevOps & cloud", "Infrastructure as code (форк Terraform)"),
    ("awscli", "formula", "DevOps & cloud", "CLI для Amazon Web Services"),
    ("flyctl", "formula", "DevOps & cloud", "Деплой приложений на Fly.io"),
    ("ansible", "formula", "DevOps & cloud", "Автоматизация конфигурации серверов"),
    # Keamanan & testing
    ("mitmproxy", "cask", "Безопасность и тестирование", "Просмотр и изменение HTTP(S)-трафика"),
    ("trivy", "formula", "Безопасность и тестирование", "Сканирование уязвимостей образов и зависимостей"),
    ("sops", "formula", "Безопасность и тестирование", "Шифрование файлов с секретами (.env, YAML)"),
    ("age", "formula", "Безопасность и тестирование", "Простое шифрование файлов"),
    ("k6", "formula", "Безопасность и тестирование", "Нагрузочное тестирование API со скриптами на JS"),
    ("cocoapods", "formula", "Безопасность и тестирование", "Менеджер зависимостей iOS (React Native/Flutter)"),
    # Aplikasi GUI
    ("visual-studio-code", "cask", "GUI-приложения", "Самый популярный редактор кода"),
    ("zed", "cask", "GUI-приложения", "Очень быстрый редактор кода"),
    ("orbstack", "cask", "GUI-приложения", "Лёгкие Docker и Linux-VM для Mac"),
    ("tableplus", "cask", "GUI-приложения", "GUI для баз данных (MySQL, Postgres, Redis, ...)"),
    ("dbeaver-community", "cask", "GUI-приложения", "Бесплатный универсальный GUI для баз данных"),
    ("bruno", "cask", "GUI-приложения", "Офлайн API-клиент (альтернатива Postman)"),
    ("postman", "cask", "GUI-приложения", "API-клиент и тестирование"),
    ("proxyman", "cask", "GUI-приложения", "Отладка HTTP(S)-трафика в GUI"),
    ("fork", "cask", "GUI-приложения", "Быстрый графический Git-клиент"),
    ("raycast", "cask", "GUI-приложения", "Продуктивный лаунчер вместо Spotlight"),
    # Database tools & infrastructure
    ("phpmyadmin", "formula", "Инструменты баз данных", "Веб-интерфейс для MySQL и MariaDB"),
    ("pgadmin4", "cask", "Инструменты баз данных", "Приложение для управления PostgreSQL"),
    ("dbgate", "cask", "Инструменты баз данных", "Клиент для SQL и NoSQL баз данных"),
    ("mongosh", "formula", "Инструменты баз данных", "Консоль MongoDB"),
    ("mongodb-compass", "cask", "Инструменты баз данных", "Графический клиент MongoDB"),
    ("etcd", "formula", "Инфраструктура", "Распределённое хранилище ключей и значений"),
    ("consul", "cask", "Инфраструктура", "Обнаружение сервисов (HashiCorp)"),
    ("temporal", "formula", "Инфраструктура", "Платформа надёжных рабочих процессов"),
    ("neo4j", "formula", "Инфраструктура", "Графовая база данных"),
    ("clickhouse", "cask", "Инфраструктура", "Колоночная база данных для аналитики"),
    ("tomcat", "formula", "Инфраструктура", "Сервер приложений Java"),
    ("podman", "formula", "Инфраструктура", "Контейнеры без фонового демона (альтернатива Docker)"),
]


# Linux (apt): имя в Homebrew → пакет apt. Пакет без соответствия берётся по тому же имени, если он есть в индексах apt.
APT_MAP = {"mysql": "mysql-server", "mariadb": "mariadb-server", "postgresql@17": "postgresql", "redis": "redis-server", "valkey": "valkey-server",
           "httpd": "apache2", "rabbitmq": "rabbitmq-server", "sqlite": "sqlite3", "fd": "fd-find", "bat": "bat", "php": "php-cli",
           "mongodb/brew/mongodb-community": None, "openjdk": "default-jdk", "go": "golang-go", "rustup": "rustup", "wget": "wget",
           "nats-server": "nats-server", "kafka": None, "opensearch": None, "llama.cpp": None, "ngrok": None, "tlrc": None, "mise": None,
           "fnm": None, "pyenv": None, "rbenv": "rbenv", "composer": "composer", "maven": "maven", "gradle": "gradle", "mkcert": "mkcert"}


def _apt_pkgs():
    return set(output(["apt-cache", "pkgnames"], timeout=30).split())


def _apt_installed():
    return set(output(["dpkg-query", "-W", "-f", "${Package}\\n"], timeout=30).split())


def _apt_name(brew_name, known):
    if brew_name in APT_MAP:
        return APT_MAP[brew_name] if APT_MAP[brew_name] in known else None
    base = brew_name.split("/")[-1].split("@")[0]
    return base if base in known else None


def recommendations(q):
    if sys.platform != "darwin":
        known, have = _apt_pkgs(), _apt_installed()
        items = []
        for n, t, c, d in RECOMMENDED:
            a = _apt_name(n, known)
            if a and t == "formula":
                items.append({"name": a, "type": "formula", "category": c, "desc": d, "installed": a in have})
        return {"items": items}
    formulae = set(output([BREW, "list", "--formula", "-1"], timeout=30).split())
    casks = set(output([BREW, "list", "--cask", "-1"], timeout=30).split())
    return {"items": [{"name": n, "type": t, "category": c, "desc": d,
                       "installed": n in (casks if t == "cask" else formulae)} for n, t, c, d in RECOMMENDED]}


def brew_versions():
    out = output([BREW, "list", "--formula", "--versions"], timeout=30)
    return {line.split()[0]: line.split()[-1] for line in out.splitlines() if line.strip()}


def catalog(q):
    if sys.platform != "darwin":
        known, have = _apt_pkgs(), _apt_installed()
        out = []
        for f, n, c, d in CATALOG:
            a = _apt_name(f, known)
            if a:
                out.append({"formula": a, "name": n, "category": c, "desc": d, "installed": a in have})
        return {"catalog": out}
    installed = brew_versions()
    return {"catalog": [{"formula": f, "name": n, "category": c, "desc": d,
                         "installed": f.split("/")[-1] in installed} for f, n, c, d in CATALOG]}


# ---------------------------------------------------------------- konfigurasi per service

def php_dir(name):
    """php -> etc/php/8.5, php@8.3 -> etc/php/8.3"""
    m = re.match(r"php@(\d+\.\d+)$", name)
    if m:
        return f"{ETC}/php/{m[1]}"
    ver = re.match(r"\d+\.\d+", brew_versions().get(name, "") or "")
    return f"{ETC}/php/{ver[0]}" if ver else None


def service_spec(name):
    """File config, validator, dan folder data untuk sebuah service."""
    opt = f"{BREW_PREFIX}/opt/{name}"
    files, validate, data = [], None, None
    if re.match(r"(mysql|mariadb)", name):
        files = [f"{ETC}/my.cnf", *sorted(glob.glob(f"{ETC}/my.cnf.d/*.cnf"))]
        validate = lambda f: [f"{opt}/bin/mysqld", f"--defaults-file={f}", "--validate-config"]  # noqa: E731
        data = f"{VAR}/mysql"
    elif name.startswith("postgresql"):
        data = f"{VAR}/{name}"
        files = [f"{data}/postgresql.conf", f"{data}/pg_hba.conf"]
    elif name in ("redis", "valkey"):
        files = [f"{ETC}/{name}.conf"]
        data = f"{VAR}/db/{name}"
    elif name == "nginx":
        files = [f"{ETC}/nginx/nginx.conf", *sorted(glob.glob(f"{ETC}/nginx/servers/*"))]
        validate = lambda f: [f"{opt}/bin/nginx", "-t"]  # noqa: E731
        data = f"{VAR}/www"
    elif name == "httpd":
        files = [f"{ETC}/httpd/httpd.conf", f"{ETC}/httpd/extra/httpd-vhosts.conf"]
        validate = lambda f: [f"{opt}/bin/apachectl", "-t"]  # noqa: E731
    elif name == "caddy":
        files = [f"{ETC}/Caddyfile"]
        validate = lambda f: [f"{opt}/bin/caddy", "validate", "--config", f, "--adapter", "caddyfile"]  # noqa: E731
    elif re.match(r"php(@\d+\.\d+)?$", name):
        d = php_dir(name)
        if d:
            files = [f"{d}/php.ini", f"{d}/php-fpm.conf", *sorted(glob.glob(f"{d}/php-fpm.d/*.conf")),
                     *sorted(glob.glob(f"{d}/conf.d/*.ini"))]
        validate = lambda f: [f"{opt}/sbin/php-fpm", "-t"]  # noqa: E731
    elif name == "dnsmasq":
        files = [f"{ETC}/dnsmasq.conf", *sorted(glob.glob(f"{ETC}/dnsmasq.d/*"))]
        validate = lambda f: [f"{opt}/sbin/dnsmasq", "--test", f"--conf-file={f}"]  # noqa: E731
    elif name == "cloudflared":
        files = [f"{CF_DIR}/config.yml", f"{CF_DIR}/config.yaml"]
        validate = lambda f: [f"{opt}/bin/cloudflared", "tunnel", "--config", f, "ingress", "validate"]  # noqa: E731
    elif name == "mongodb-community":
        files = [f"{ETC}/mongod.conf"]
        data = f"{VAR}/mongodb"
    elif name == "rabbitmq":
        files = [f"{ETC}/rabbitmq/rabbitmq-env.conf", f"{ETC}/rabbitmq/rabbitmq.conf"]
    return {"files": [f for f in files if os.path.isfile(f)], "validate": validate,
            "data": data if data and os.path.isdir(data) else None}


def descendants(pid):
    out = output(["ps", "-A", "-o", "pid=,ppid="])
    children = {}
    for line in out.splitlines():
        p = line.split()
        if len(p) == 2:
            children.setdefault(p[1], []).append(p[0])
    result, stack = [], [str(pid)]
    while stack:
        p = stack.pop()
        result.append(p)
        stack += children.get(p, [])
    return result


def listening_ports(pid):
    if not pid:
        return []
    out = output(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", ",".join(descendants(pid))], timeout=10)
    ports = sorted({m[1] for m in re.finditer(r"TCP \S*:(\d+) \(LISTEN\)", out)}, key=int)
    return ports


def service_detail(q, known_service):
    name = q.get("name", "")
    svc = known_service(name)
    spec = service_spec(name)
    formula_info = {}
    try:
        info = json.loads(output([BREW, "info", "--json=v2", name], timeout=30))["formulae"][0]
        formula_info = {"desc": info.get("desc"), "homepage": info.get("homepage"),
                        "version": (info.get("installed") or [{}])[0].get("version"),
                        "caveats": info.get("caveats")}
    except (ValueError, KeyError, IndexError):
        pass
    return {"service": svc, "formula": formula_info, "config_files": spec["files"],
            "can_validate": bool(spec["validate"]), "data_dir": spec["data"],
            "ports": listening_ports(svc.get("pid")), "backup_dir": CFG_BACKUP_DIR}


def config_path(name, path):
    spec = service_spec(name)
    if path not in spec["files"]:
        raise ApiError("неизвестный файл конфигурации для этого сервиса", HTTPStatus.FORBIDDEN, code="svc.config_unknown")
    return path, spec


def config_read(q):
    path, _ = config_path(q.get("name", ""), q.get("path", ""))
    with open(path, errors="replace") as f:
        return {"path": path, "content": f.read()}


def validate_config(spec, path):
    if not spec["validate"]:
        return True, "У этого сервиса нет встроенного валидатора."
    try:
        code, out, err = run(spec["validate"](path), timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return True, f"Не удалось запустить валидатор: {e}"
    return code == 0, (out + err).strip() or ("OK" if code == 0 else f"exit {code}")


def config_save(body):
    name = body.get("name", "")
    path, spec = config_path(name, body.get("path", ""))
    content = body.get("content")
    if not isinstance(content, str):
        raise ApiError("недопустимое содержимое", code="svc.content_invalid")
    os.makedirs(CFG_BACKUP_DIR, exist_ok=True)
    backup = os.path.join(CFG_BACKUP_DIR, f"{name.replace('/', '_')}__{os.path.basename(path)}.{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    with open(path, "w") as f:
        f.write(content)
    ok, msg = validate_config(spec, path)
    if not ok and not body.get("force"):
        shutil.copy2(backup, path)  # kembalikan: config baru tidak valid
        raise ApiError(f"Конфигурация НЕДЕЙСТВИТЕЛЬНА, изменения отменены:\n{msg}", HTTPStatus.UNPROCESSABLE_ENTITY,
                       code="svc.config_invalid", details=msg)
    result = {"ok": True, "backup": backup, "validation": msg}
    if body.get("restart"):
        code, out, err = run([BREW, "services", "restart", name], timeout=120)
        result["restart"] = (out + err).strip()
    return result


def config_validate(body):
    path, spec = config_path(body.get("name", ""), body.get("path", ""))
    ok, msg = validate_config(spec, path)
    return {"ok": ok, "output": msg}


def service_install(body):
    if sys.platform != "darwin":
        import aptsvc
        return aptsvc.app_action({"name": str(body.get("formula", "")), "action": "install"})
    formula = str(body.get("formula", ""))
    if not PKG_RE.match(formula):
        raise ApiError("недопустимое имя формулы", code="svc.formula_invalid")
    return {"job": start_job(f"brew install {formula}", [BREW, "install", formula], "brew")}


def service_uninstall(body, known_service):
    if sys.platform != "darwin":
        import aptsvc
        return aptsvc.app_action({"name": str(body.get("name", "")), "action": "uninstall"})
    name = body.get("name", "")
    known_service(name)
    run([BREW, "services", "stop", name], timeout=120)  # hentikan dulu agar launchd bersih
    return {"job": start_job(f"brew uninstall {name}", [BREW, "uninstall", name], "brew")}


# ---------------------------------------------------------------- cloudflared

def cf_bin():
    p = f"{BREW_PREFIX}/bin/cloudflared"
    if not os.path.exists(p):
        raise ApiError("cloudflared не установлен", HTTPStatus.NOT_FOUND, code="svc.cf_not_installed")
    return p


def cf_config_file():
    return next((f for f in (f"{CF_DIR}/config.yml", f"{CF_DIR}/config.yaml") if os.path.isfile(f)), None)


def parse_ingress(text):
    """Parser YAML minimal untuk blok ingress cloudflared (hostname/service)."""
    rules, cur = [], None
    for line in text.splitlines():
        m = re.match(r"\s*-\s*(hostname|service):\s*(\S+)", line)
        if m:
            cur = {m[1]: m[2]}
            rules.append(cur)
            continue
        m = re.match(r"\s+(hostname|service|path):\s*(\S+)", line)
        if m and cur is not None:
            cur[m[1]] = m[2]
    return [r for r in rules if "service" in r]


def cf_processes():
    """Proses `cloudflared tunnel run` yang sedang jalan (dari dashboard atau terminal)."""
    procs = []
    for line in output(["ps", "-Ao", "pid=,command="]).splitlines():
        m = re.match(r"\s*(\d+)\s+(.*cloudflared.*\btunnel\b.*\brun\b.*)", line)
        if m and "ps -Ao" not in m[2]:
            procs.append({"pid": int(m[1]), "command": m[2].strip()})
    return procs


def cf_info(q):
    binary = cf_bin()
    cfg = cf_config_file()
    content = open(cfg, errors="replace").read() if cfg else ""
    tunnel_id = re.search(r"^tunnel:\s*(\S+)", content, re.M)
    logged_in = os.path.isfile(f"{CF_DIR}/cert.pem")
    tunnels, err = [], None
    if logged_in:
        code, out, e = run([binary, "tunnel", "list", "--output", "json"], timeout=20)
        try:
            tunnels = json.loads(out) if code == 0 else []
        except ValueError:
            tunnels = []
        err = None if code == 0 else (e.strip() or out.strip())
    creds = {os.path.basename(f)[:-5] for f in glob.glob(f"{CF_DIR}/*.json")}
    managed = load_state().get("cf_runs", {})
    procs = cf_processes()
    running_pids = {p["pid"] for p in procs}
    for t in tunnels:
        t["has_credentials"] = t["id"] in creds
        t["connections"] = len(t.get("connections") or [])
        run_info = managed.get(t["name"])
        t["managed_pid"] = run_info["pid"] if run_info and run_info["pid"] in running_pids else None
        t["in_config"] = bool(tunnel_id and tunnel_id[1] in (t["id"], t["name"]))
    return {"version": output([binary, "--version"]).split(" (")[0], "logged_in": logged_in,
            "config_file": cfg, "config_tunnel": tunnel_id[1] if tunnel_id else None,
            "ingress": parse_ingress(content), "tunnels": tunnels, "error": err, "processes": procs}


TUNNEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")
ORIGIN_RE = re.compile(r"^(https?|tcp|ssh|unix)://[A-Za-z0-9._:/-]+$|^http_status:\d{3}$")


def cf_action(body):
    binary = cf_bin()
    action = body.get("action")
    name = str(body.get("name", "")).strip()
    if action == "login":
        if os.path.isfile(f"{CF_DIR}/cert.pem"):
            if not body.get("relogin"):
                raise ApiError("Вход уже выполнен. Используйте «Войти заново», чтобы сменить аккаунт или зону.", code="svc.already_logged_in")
            os.rename(f"{CF_DIR}/cert.pem", f"{CF_DIR}/cert.pem.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        return {"job": start_job("cloudflared tunnel login", [binary, "tunnel", "login"], "cloudflared")}
    if action in ("create", "delete", "route", "run", "stop", "logs") and not TUNNEL_RE.match(name):
        raise ApiError("недопустимое имя туннеля", code="svc.tunnel_name_invalid")
    if action == "create":
        return {"job": start_job(f"tunnel create {name}", [binary, "tunnel", "create", name], "cloudflared")}
    if action == "delete":
        return {"job": start_job(f"tunnel delete {name}", [binary, "tunnel", "delete", "-f", name], "cloudflared")}
    if action == "route":
        host = str(body.get("hostname", "")).strip().lower()
        if not HOST_RE.match(host):
            raise ApiError("недопустимый hostname (пример: app.yourdomain.com)", code="svc.hostname_invalid")
        return {"job": start_job(f"route dns {name} → {host}", [binary, "tunnel", "route", "dns", name, host], "cloudflared")}
    if action == "run":
        return cf_run(binary, name)
    if action == "stop":
        return cf_stop(name, body.get("pid"))
    if action == "logs":
        return {"log": tail(os.path.join(LOG_DIR, f"cloudflared-{name}.log"), 300) or "(логов от дашборда пока нет)"}
    if action == "add-ingress":
        return cf_add_ingress(body)
    raise ApiError("недопустимое действие", code="svc.action_invalid")


def cf_run(binary, name):
    """Jalankan tunnel di background (bukan lewat launchd), log ke ~/.service-admin/logs."""
    runs = load_state().get("cf_runs", {})
    if name in runs and any(p["pid"] == runs[name]["pid"] for p in cf_processes()):
        raise ApiError(f"Туннель {name} уже запущен", code="svc.tunnel_running", name=name)
    os.makedirs(LOG_DIR, exist_ok=True)
    log = open(os.path.join(LOG_DIR, f"cloudflared-{name}.log"), "a")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} start {name} =====\n")
    log.flush()
    proc = subprocess.Popen([binary, "tunnel", "run", name], stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=ENV, cwd=HOME, start_new_session=True)
    runs[name] = {"pid": proc.pid, "started": time.time()}
    save_state(cf_runs=runs)
    return {"ok": True, "pid": proc.pid}


def cf_stop(name, pid=None):
    """Hentikan tunnel yang dijalankan dashboard, atau PID cloudflared tertentu."""
    runs = load_state().get("cf_runs", {})
    target = int(pid) if pid else (runs.get(name) or {}).get("pid")
    if not target or target not in {p["pid"] for p in cf_processes()}:
        raise ApiError("Процесс туннеля не найден (возможно, уже остановлен)", HTTPStatus.NOT_FOUND, code="svc.tunnel_proc_missing")
    os.kill(target, signal.SIGTERM)
    runs.pop(name, None)
    save_state(cf_runs=runs)
    return {"ok": True}


def cf_add_ingress(body):
    """Tambah aturan hostname -> service sebelum aturan catch-all di config.yml."""
    host = str(body.get("hostname", "")).strip().lower()
    origin = str(body.get("service", "")).strip()
    if not HOST_RE.match(host) or not ORIGIN_RE.match(origin):
        raise ApiError("недопустимый hostname/service (пример: app.domain.com → http://localhost:8000)", code="svc.ingress_invalid")
    cfg = cf_config_file()
    if not cfg:
        raise ApiError("config.yml отсутствует в ~/.cloudflared", code="svc.config_missing")
    text = open(cfg).read()
    rule = f"  - hostname: {host}\n    service: {origin}\n\n"
    m = re.search(r"^(\s*)-\s*service:\s*http_status:\d+\s*$", text, re.M)
    if m:
        # sisipkan SEBELUM komentar yang menempel di atas aturan catch-all
        lines = text[:m.start()].split("\n")
        cut = len(lines) - 1
        while cut > 0 and lines[cut - 1].strip().startswith("#"):
            cut -= 1
        head, tail_part = "\n".join(lines[:cut]), "\n".join(lines[cut:]) + text[m.start():]
        text = head.rstrip("\n") + "\n\n" + rule + tail_part.lstrip("\n")
    elif re.search(r"^ingress:\s*$", text, re.M):
        text = re.sub(r"^ingress:\s*$", "ingress:\n" + rule.rstrip("\n"), text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n\ningress:\n" + rule + "  - service: http_status:404\n"
    return config_save({"name": "cloudflared", "path": cfg, "content": text})
