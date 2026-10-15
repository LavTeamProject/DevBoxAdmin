# -*- coding: utf-8 -*-
"""Реле для `guestfwd=...-cmd:` QEMU: stdin/stdout ↔ TCP-соединение с ОДНИМ заранее заданным сервером (хост и порт — аргументы командной строки,
выбирает панель; гость выбрать назначение не может). QEMU запускает команду на каждое соединение гостя. Только стандартная библиотека."""
import socket
import sys
import threading


def pump(src, dst, shutdown_dst):
    try:
        while True:
            data = src(65536)
            if not data:
                break
            dst(data)
    except OSError:
        pass
    finally:
        shutdown_dst()


def main(argv):
    if len(argv) != 3 or not argv[2].isdigit():
        print("usage: vm_relay.py HOST PORT", file=sys.stderr)
        return 2
    s = socket.create_connection((argv[1], int(argv[2])), timeout=20)
    s.settimeout(None)
    out = sys.stdout.buffer

    def to_guest(data):
        out.write(data)
        out.flush()
    t = threading.Thread(target=pump, args=(s.recv, to_guest, lambda: None), daemon=True)
    t.start()
    pump(lambda n: sys.stdin.buffer.read1(n), s.sendall, lambda: s.shutdown(socket.SHUT_WR))
    t.join(timeout=30)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
