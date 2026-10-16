# Sites & domains

The "Sites & domains" page shows what is missing for local addresses like `myapp.test` with HTTPS. The panel **only shows status and installs components** (the "Install" button runs `brew install`). It does not change `/etc/hosts`, the macOS resolver or proxy configs.

Two ways; one is enough:
- **Herd** (PHP/Laravel): installed from "Getting started"; it manages sites and HTTPS itself; its site list is shown on the page.
- A set of `dnsmasq` + `mkcert` + `nginx` or `Caddy`.

## Steps for the set (you run them in Terminal)
1. `brew install dnsmasq mkcert nginx` (or use the buttons on the page).
2. Rule for every `*.test`: add `address=/test/127.0.0.1` to `$(brew --prefix)/etc/dnsmasq.conf` and start it **as administrator**: `sudo brew services start dnsmasq` (port 53 is privileged). The panel shows such a service as "stopped"; that is normal — check with `dig +short @127.0.0.1 myapp.test`.
3. macOS resolver (administrator rights): `sudo mkdir -p /etc/resolver && echo "nameserver 127.0.0.1" | sudo tee /etc/resolver/test`.
4. Trusted certificate: `mkcert -install`, then `mkcert myapp.test`.
5. Point nginx/Caddy at the certificate and proxy `myapp.test` to the app port. Ports 80/443 are privileged too: without `sudo` use e.g. 8443 (`https://myapp.test:8443`).

This scenario (dnsmasq → resolver → mkcert → nginx → the app answering over HTTPS) was run on a clean macOS virtual machine.

The checklist rows "dnsmasq rule", "resolver" and "mkcert root certificate" are detected by reading files (read-only).

## Tunnels
The link opens the `cloudflared` page where tunnels are managed.

## Not verified
Installing components with the buttons and the full `*.test` + HTTPS scenario were not run on a clean system; see `docs/en/unverified.md`.
