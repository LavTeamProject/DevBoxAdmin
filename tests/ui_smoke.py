#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Дымовая проверка интерфейса (Фаза 10, U2): открывает каждую страницу панели в headless-браузере и проверяет, что
  * страница нарисовалась (нет вечной «Загрузки…», нет общей ошибки загрузки);
  * подсвечен нужный пункт меню; у составных страниц есть полоса вкладок; старые адреса переадресуются;
  * в консоли браузера нет необработанных ошибок JS.
Ручной стенд (нужен Chrome/Chromium), в CI не входит:   python3 tests/ui_smoke.py [--only a,b] [--keep]
Панель поднимается ТОЛЬКО ДЛЯ ЧТЕНИЯ (только HTTP-обработчик: без бота, сокета агентов и расписаний). По умолчанию — на вашем HOME (иначе
Homebrew без своего кэша начинает собирать индексы и страницы «зависают»); `--temp-home` — во временной папке."""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# (адрес, ожидаемый пункт меню, нужна ли полоса вкладок составной страницы)
ROUTES = [
    ("#dashboard", "dashboard", False),
    ("#start", "start", True), ("#start:profiles", "start", True), ("#setup", "start", True), ("#profiles", "start", True),
    ("#langs", "langs", False), ("#lang-python", "langs", False), ("#php", "langs", False), ("#node", "langs", False),
    ("#packages", "packages", False), ("#docker", "docker", False), ("#mobile", "mobile", False),
    ("#projects", "projects", False), ("#runs", "runs", False), ("#herd", "herd", False),
    ("#agents", "agents", False),
    ("#connect", "connect", False), ("#connect:agents", "connect", False), ("#connect:approvals", "connect", False), ("#connect:operators", "connect", False),
    ("#connect:channels", "connect", False), ("#connect:catalog", "connect", False),
    ("#vms", "vms", False),
    ("#history", "history", True), ("#history:backups", "history", True), ("#snapshots", "history", True), ("#backups", "history", True),
    ("#config", "config", False), ("#audit", "audit", False),
]
TIMEOUT = 90
BAD_TEXT = ["Внутренняя ошибка панели", "Не удалось загрузить", "Could not load", "Internal panel error"]


def chrome():
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if p and os.path.exists(p):
            return p
    sys.exit("Chrome/Chromium не найден")


def start_panel(temp_home=False):
    home = tempfile.mkdtemp(prefix="sa-smoke-") if temp_home else None
    if home:
        os.environ["HOME"] = home                  # до импорта панели: её данные — во временной папке
    sys.path.insert(0, ROOT)
    from http.server import ThreadingHTTPServer
    import server
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return port, home


def check(browser, port, route, nav, comp):
    url = f"http://127.0.0.1:{port}/?smoke=1{route}"
    try:
        r = subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--virtual-time-budget=20000", "--enable-logging=stderr", "--v=0",
                            "--window-size=1300,1000", "--dump-dom", url], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return [f"страница не завершила загрузку за {TIMEOUT} с (медленный или зависший запрос)"]
    dom, log = r.stdout, r.stderr
    problems = []
    m = re.search(r'<main[^>]*id="view"[^>]*>(.*?)</main>|<div[^>]*id="view"[^>]*>(.*)', dom, re.S)
    body = (m.group(1) or m.group(2) or "") if m else ""
    if len(re.sub(r"<[^>]+>", "", body).strip()) < 20:
        problems.append("пустая страница")
    if 'class="loading"' in body:
        problems.append("осталась «Загрузка…»")
    for bad in BAD_TEXT:
        if bad in body:
            problems.append(f"общая ошибка: «{bad}»")
    active = re.findall(r'<a href="#(\w+)"[^>]*class="[^"]*\bactive\b', dom)
    if nav not in active:
        problems.append(f"меню: подсвечено {active or 'ничего'}, ожидалось {nav}")
    if comp and 'id="compNav"' not in body:
        problems.append("нет полосы вкладок составной страницы")
    errs = [l for l in log.splitlines() if re.search(r"CONSOLE.*(Uncaught|TypeError|ReferenceError|SyntaxError)", l)]
    problems += [f"JS: {e[-160:]}" for e in errs[:2]]
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--temp-home", action="store_true")
    args = ap.parse_args()
    only = {x for x in args.only.split(",") if x}
    browser = chrome()
    port, home = start_panel(args.temp_home)
    bad = 0
    for route, nav, comp in ROUTES:
        if only and route.lstrip("#") not in only:
            continue
        probs = check(browser, port, route, nav, comp)
        bad += bool(probs)
        print(f"{'✔' if not probs else '✘'} {route:22} {'; '.join(probs)}", flush=True)
    if home and not args.keep:
        shutil.rmtree(home, ignore_errors=True)
    print(f"\n{len(ROUTES) - bad if not only else 'выбранные'} OK, {bad} с проблемами")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
