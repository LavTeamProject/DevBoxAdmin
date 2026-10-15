#!/usr/bin/env python3
"""Example client for the Service Admin remote API (stdlib only). Pin the certificate by its SHA-256 fingerprint shown in the panel.

  export SA_URL=https://HOST:8766 SA_TOKEN=sao_... SA_FINGERPRINT=<sha256 hex>
  python3 examples/remote_client.py plans
  python3 examples/remote_client.py approve <plan_id> <digest> <totp_code>
  python3 examples/remote_client.py reject <plan_id>
  python3 examples/remote_client.py agent-tools      # with an agent token instead of an operator token
"""
import hashlib
import json
import os
import socket
import ssl
import sys
import urllib.parse
import urllib.request

URL, TOKEN, FP = os.environ["SA_URL"], os.environ["SA_TOKEN"], os.environ.get("SA_FINGERPRINT", "").lower()


class PinnedHTTPS(urllib.request.HTTPSHandler):
    def __init__(self):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # самоподписанный сертификат: доверие — по отпечатку ниже
        super().__init__(context=ctx)


def check_pin():
    if not FP:
        sys.exit("Set SA_FINGERPRINT to the fingerprint shown in the panel (refusing to talk without pinning)")
    u = urllib.parse.urlparse(URL)
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    with socket.create_connection((u.hostname, u.port or 443), timeout=10) as raw, ctx.wrap_socket(raw) as s:
        if hashlib.sha256(s.getpeercert(True)).hexdigest() != FP:
            sys.exit("Certificate fingerprint mismatch — refusing to send the token")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data, {"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.build_opener(PinnedHTTPS()).open(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


if __name__ == "__main__":
    check_pin()
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else "plans"), sys.argv[2:]
    if cmd == "plans":
        out = call("GET", "/operator/v1/plans")
    elif cmd == "approve" and len(args) == 3:
        out = call("POST", "/operator/v1/plans/approve", {"id": args[0], "digest": args[1], "totp": args[2]})
    elif cmd == "reject" and len(args) == 1:
        out = call("POST", "/operator/v1/plans/reject", {"id": args[0]})
    elif cmd == "agent-tools":
        out = call("GET", "/agent/v1/tools")
    else:
        sys.exit(__doc__)
    print(json.dumps(out, ensure_ascii=False, indent=2))
