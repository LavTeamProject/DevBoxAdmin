# ADR-0002: Hypervisor for VMs and CI runners on Linux

Status: **accepted (design); implementation is stage L4**.

## Context
On macOS `tart` (Apple Virtualization) runs the VMs and `softnet` isolates the network. The panel manages VMs through the `Driver` interface and starts single-use runners in clones of a base VM. Linux needs a driver with the same properties: a fast single-use clone, SSH inside, guest network isolation, **no root** and no membership in root-equivalent groups — otherwise the agent approval channel is disabled (ADR-0001).

## Options
- **Incus/LXD** (VMs and containers, images, snapshots): convenient, but it is driven through a daemon socket available to the `incus-admin`/`lxd` group = **root-equivalent**. Rejected for a regular panel user.
- **libvirt (qemu:///system)**: needs root or the `libvirt` group (root-equivalent). `qemu:///session` is rootless, but networking and snapshots are limited and the dependency is heavy.
- **QEMU directly** (`qemu-system-*` + `qemu-img`): no daemon, no root; the `kvm` group (access to `/dev/kvm`) is not root-equivalent; cloning is a qcow2 with a backing file in a fraction of a second; SSH is a `hostfwd` to `127.0.0.1`; network isolation is QEMU user networking: `restrict=on` + `guestfwd=…-cmd:` (the `vm_relay.py` relay per guest connection) to the single CI server address. (The chardev `guestfwd` variant was dropped: it keeps ONE TCP connection opened at VM start and the server closes it on idle timeout — verified with Gitea.)

## Decision
**QEMU directly.** Storage is `~/.service-admin/vms/<name>/` (`disk.qcow2`, `meta.json` 0600 with the guest port and password, `qemu.pid`, `qmp.sock`, `qemu.log`); images are in `~/.service-admin/vm-images/`.
- **A clone** is a qcow2 over an immutable base; while a base has clones it cannot be started or deleted (the overlay disks would be corrupted). **A snapshot/restore** is a full copy (`cp --reflink=auto`), with no dependencies.
- **The base** is built from the official Ubuntu cloud image (sha256 verified); the first boot is configured by cloud-init through `ds=nocloud-net` — the address is served by a tiny HTTP server of the panel on 127.0.0.1 only for the first boot.
- **Isolation** (the analogue of softnet, stricter): the default `server-only` mode gives the guest no internet and no local network at all, only the CI server is reachable (`guestfwd` to 10.0.2.100:port; the server name is written into the guest's `/etc/hosts`). The `none` mode (plain user networking) gives the guest the internet **and** access to the host's network — it is enabled explicitly, with a warning. The internet without access to the local network cannot be had without root — recorded as a limitation.
- **Acceleration**: `kvm` if `/dev/kvm` is accessible, otherwise `tcg` (very slow; fine for verification, not for work).
- The guest password is random per VM, SSH only on loopback.

## Consequences
- The packages `qemu-system-<arch>`, `qemu-utils` and, for aarch64, `qemu-efi-aarch64` are needed; they are installed from the panel (apt, an administrator window/terminal).
- Verification on Apple Silicon inside a tart VM is possible only in `tcg` mode (no nested virtualization); `kvm` has to be confirmed in GitHub CI (a runner with KVM) or on the owner's machine.
- No container mode (Incus/Docker) for CI: workflow code must run in a VM.

## Additions after the L4 security review (implemented and verified in a VM)
- **`restrict=on` always.** Without it the guest sees the host's loopback (`10.0.2.2` → `127.0.0.1`) and could call the panel's API. Internet access — only with an explicit `extra["internet"]` and only for the trusted `build` recipe (apt packages; in that mode the guest sees the host's loopback — the recipe installs only Ubuntu packages). Runners on Linux are always isolated (`isolate=false` is rejected: `runner.isolate_required`). Building the base is also network-free: cloud-init gets its data through `guestfwd` (10.0.2.100) from a one-time HTTP server of the panel with a random token in the path.
- **Key-based login, no password.** For each base a client key and a guest host key (ed25519) are generated; cloud-init gets only the client's public key and the guest's host key. `ssh_pwauth: false`, no password is created (neither in `meta.json` nor in cloud-init), the guest's host key is pinned (`StrictHostKeyChecking=yes`, the VM's `known_hosts`, `HostKeyAlias`): neither a password nor a registration token can leak to a "fake" sshd on another user's 127.0.0.1 port. The guest's private host key is deleted on the host side after the build.
- **Content-addressed images.** The cloud image is stored as `<sha256[:16]>-<name>.img` and is never replaced in place (bases and clones refer to it).
- **Locks** (`flock`) around check-and-act in `clone/copy/delete/rename/start`; the guest console log is off (`-serial none`; only while building the base), commas in QEMU paths are doubled, `delete` no longer hides the runner's original error, the pid is re-checked before a signal.
- **Residual risks:** the image checksum comes from the same origin (the `SHA256SUMS.gpg` signature is not verified); the base and its clones share one client key (the guest holds only the public part); in the `internet` mode (the `build` recipe) the guest sees the host's loopback; on a multi-user host the guest's SSH port (127.0.0.1:port) is reachable by other users — login is possible only with the key.
