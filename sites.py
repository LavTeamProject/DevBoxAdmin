"""Сайты и домены (Фаза 10, U5): только чтение. Собирает в одном месте то, что нужно для локальных доменов вида myapp.test с HTTPS:
сайты Herd, туннели cloudflared, записи /etc/hosts и чек-лист компонентов (dnsmasq → *.test, mkcert → доверенный HTTPS, nginx/Caddy → прокси).
Панель сама НЕ пишет /etc/hosts, resolver и конфиги прокси: установка компонентов — кнопками (brew install), остальные шаги описаны в мануале."""
import os
import shutil
import sys

PART = (("dnsmasq", "dnsmasq", True), ("mkcert", "mkcert", False), ("nginx", "nginx", True), ("caddy", "caddy", True))   # (id, формула/пакет, сервис ли)
HOSTS_SKIP = {"localhost", "broadcasthost", "ip6-localhost", "ip6-loopback", "ip6-localnet", "ip6-mcastprefix", "ip6-allnodes", "ip6-allrouters", "ip6-allhosts"}


def hosts_entries(path="/etc/hosts"):
    """Пользовательские записи /etc/hosts (кроме стандартных): [{ip, names}]."""
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f.read(256 * 1024).splitlines():
                parts = line.split("#")[0].split()
                names = [n for n in parts[1:] if n.lower() not in HOSTS_SKIP]
                if len(parts) >= 2 and names:
                    out.append({"ip": parts[0], "names": names})
    except OSError:
        pass
    return out[:200]


def _mac_state():
    import svc
    cellar = os.path.join(svc.BREW_PREFIX, "Cellar")
    try:
        installed = set(os.listdir(cellar))
    except OSError:
        installed = set()
    running = None
    try:
        import brewsvc
        running = {s["name"]: bool(s.get("running")) for s in brewsvc.list_services()}
    except Exception:  # noqa: BLE001 — статус сервисов необязателен
        pass
    return svc.BREW_PREFIX, installed, running


def dnsmasq_rule(paths):
    """Есть ли в конфигах dnsmasq правило address=/test/… для *.test (только чтение)."""
    for p in paths:
        try:
            with open(p, errors="replace") as f:
                if any(l.strip().startswith("address=/") and ("/test/" in l or l.strip().startswith("address=/.test/")) for l in f):
                    return True
        except OSError:
            continue
    return False


def _dnsmasq_test(prefix):
    """(правило для *.test, resolver-файл macOS)."""
    import glob
    if sys.platform == "darwin":
        paths = [os.path.join(prefix, "etc", "dnsmasq.conf")] + sorted(glob.glob(os.path.join(prefix, "etc", "dnsmasq.d", "*.conf")))
    else:
        paths = ["/etc/dnsmasq.conf"] + sorted(glob.glob("/etc/dnsmasq.d/*.conf"))
    return dnsmasq_rule(paths), os.path.isfile("/etc/resolver/test")


def sites_info(q=None):
    mac = sys.platform == "darwin"
    prefix, installed, running = _mac_state() if mac else ("", set(), None)
    parts = []
    for pid, formula, is_service in PART:
        inst = formula in installed if mac else bool(shutil.which(formula))
        parts.append({"id": pid, "formula": formula, "installed": inst, "service": is_service,
                      "running": (running or {}).get(formula) if (mac and is_service and inst) else None})
    ca = os.path.isfile(os.path.expanduser("~/Library/Application Support/mkcert/rootCA.pem")) if mac else os.path.isfile(os.path.expanduser("~/.local/share/mkcert/rootCA.pem"))
    rule, resolver = _dnsmasq_test(prefix)
    herd = {"installed": False}
    if mac:
        import herdphp
        try:
            h = herdphp.herd_info()
            herd = {"installed": bool(h.get("installed")), "tld": h.get("tld"), "sites": h.get("sites", []), "proxies": h.get("proxies", [])}
        except Exception:  # noqa: BLE001 — Herd не должен ломать страницу
            herd = {"installed": True, "error": True, "sites": []}
    cf = os.path.exists(os.path.join(prefix, "bin", "cloudflared")) if mac else bool(shutil.which("cloudflared"))
    return {"mac": mac, "parts": parts, "mkcert_ca": ca, "dnsmasq_rule": rule, "resolver": resolver, "hosts": hosts_entries(),
            "herd": herd, "cloudflared": cf}
