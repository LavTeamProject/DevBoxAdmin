"""Дымовая проверка драйвера QEMU на настоящей ВМ (Linux): основа → клон → изоляция сети → удаление.
Запуск: python3 tests/vm_smoke.py [имя-основы]   (нужны qemu-system-*, qemu-utils, sshpass; с KVM — быстро, без — очень медленно).
Проверяет: клон стартует; гость достучался до «сервера CI» (локальный HTTP на хосте) по 10.0.2.100; гость НЕ видит интернет и хост (10.0.2.2);
клон удалён; основа не тронута."""
import http.server
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import core  # noqa: E402
import vm  # noqa: E402
import vm_qemu  # noqa: E402


def run_job(op, params, timeout=7200):
    j = vm.run_op({"op": op, "params": params})["job"]
    t0, seen = time.time(), 0
    while not core.JOBS[j]["done"] and time.time() - t0 < timeout:
        for line in core.JOBS[j]["lines"][seen:]:
            print("   |", line, flush=True)
        seen = len(core.JOBS[j]["lines"])
        time.sleep(5)
    for line in core.JOBS[j]["lines"][seen:]:
        print("   |", line, flush=True)
    return core.JOBS[j]["code"] == 0


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "smoke-base"
    d = vm.driver()
    assert d.name == "qemu" and d.available(), "QEMU is not available"
    if not any(v["name"] == base for v in d.list()):
        print(f"creating the base '{base}' …")
        assert run_job("vm.create_base", {"name": base, "size_gb": 10, "mem_mb": 1024}), "create_base failed"

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ci-server-ok")

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    clone = "ci-smoke"
    d.clone(base, clone)
    try:
        extra = d.isolation({"url": f"http://127.0.0.1:{port}"})
        d.start_step(clone, extra)(print)
        ip = d.ip(clone)
        for _ in range(180):
            try:
                if vm._guest(ip, "true", timeout=90)[0] == 0:  # без KVM рукопожатие SSH медленное
                    break
            except Exception:  # noqa: BLE001 - гость ещё грузится
                pass
            time.sleep(10)
        else:
            raise SystemExit("FAIL: the clone did not accept SSH")
        code, out = vm._guest(ip, f"curl -s -m 20 http://{vm_qemu.FWD_IP}:{port}/", timeout=60)
        print("guest -> CI server:", out)
        assert out == "ci-server-ok", "the guest cannot reach the CI server through guestfwd"
        for target in ("https://example.com", "http://10.0.2.2:%d/" % port, "http://192.168.1.1/"):
            code, out = vm._guest(ip, f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' {target}; true", timeout=40)
            print(f"guest -> {target}: {out!r} (must be 000)")
            assert out.strip() in ("000", ""), f"isolation leak: {target} answered {out!r}"
        print("OK: isolation works")
    finally:
        vm._stop_vm(None, clone, print, d.ip(clone))
        d.delete(clone)
        srv.shutdown()
    assert not any(v["name"] == clone for v in d.list()), "the clone was not deleted"
    print("OK: clone deleted, base untouched:", [v["name"] for v in d.list() if v["name"] == base])


if __name__ == "__main__":
    main()
