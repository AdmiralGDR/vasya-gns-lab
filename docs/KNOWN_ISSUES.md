# VASYA GNS LAB 1.1.0 — Known issues

1. **Windows is UNVERIFIED.** Setup.exe was only smoke-tested under wine on a Linux build host; the GUI was not
   started there (wine has no `icuuc.dll`). The first run on real Windows may reveal issues.
2. **1.1.0 has not been run end to end on Pop!_OS 24.04 yet.** The defects found with 1.0.1 there (D1 vde uplink,
   D2 ARM emulator, D3 ISO appliances, D6 rollback by name) are fixed and covered by regression tests.
3. **Images are downloaded, not shipped.** The public release contains no device images. The installer downloads
   every public image from its upstream site (URL and SHA-256 pinned in `third_party.lock`) the first time it is
   needed. Without Internet, use the private offline bundle (`build_bundle.py --profile private`) or put the files
   into `~/VASYA-GNS-LAB/Images`. A device whose image cannot be fetched is shown as **"image not available"**; the
   rest of the installation continues.
4. **Some image download sites could not be checked automatically** (marked `UNVERIFIED` in `third_party.lock`).
   Their content SHA-256 comes from the GNS3 registry and is still enforced at install time; only the download
   URL and the size of the download are unconfirmed. See docs/RELEASE_SOURCES.md.
5. **Cisco IOS and other vendor images are never distributed.** They are fetched only from a private source you
   control (see docs/PRIVATE_IMAGES.md). Without one, the c7200 and other Dynamips devices are "image not available".
6. **openwrt-realview** is BLOCKED until `qemu-system-arm` is installed (admin step, shown with the command).
7. **Docker on Linux uses VASYA's own rootless podman by default** (storage, config, socket and service inside the
   VASYA folder; an existing Docker is not used or changed). It needs `podman` and `uidmap`
   (`sudo apt install podman uidmap`) and a `/etc/subuid` entry; otherwise only Docker components are BLOCKED.
   Images are pulled by pinned digest (docker.io / ghcr.io only) and their image ID is checked; the offline image
   pack remains an alternative. `VASYA_DOCKER_PULL=0` or `VASYA_OFFLINE=1` disables pulls. All 21 Docker
   appliances were started with rootless podman 4.9 on Pop!_OS 24.04 (turnkey-wordpress partially, see 14).
   Windows Docker = GNS3 VM, **UNVERIFIED**.
8. **Downloaded helper programs have no file capabilities.** uBridge fetched into `<root>/Runtime` cannot carry
   `cap_net_admin,cap_net_raw` without an admin step. The plan shows the `setcap` command; a system `ubridge`
   package (which sets them) is always preferred.
9. **Remote GNS3 VM cleanup is manual.** Images uploaded to a GNS3 VM cannot be deleted through the GNS3 API; the
   uninstall report shows the exact path/command.
10. **GNS3 builtin blank disks** (`empty8G.qcow2` etc. copied by gns3server into images/QEMU) are reused, not owned,
    by VASYA, so they stay after uninstall (they belong to GNS3).
11. **Pre-existing residue** outside the VASYA folder from older versions or other tools is only listed in the
    uninstall report, never deleted (D7).
12. **Big images are never auto-copied** (D5): VASYA hardlinks (same filesystem), else symlinks; a full copy happens
    only when explicitly allowed, and the plan shows the space it needs.
13. **`~/.vnc` is created by vncviewer** (TigerVNC) outside the VASYA folder the first time a VNC console is opened.
    VASYA records it in `State/receipts/external-side-effects.json` and lists it in the uninstall report; it is never
    deleted automatically.
14. **turnkey-wordpress first boot is interactive.** TurnKey's inithooks open a dialog on the container console;
    until it is answered WordPress returns HTTP 500. Answer it in the node's console, then reload.
    **Opt-in preseed (UNVERIFIED):** `VASYA_TURNKEY_PRESEED=1` before Install makes the VASYA template pass the
    answers as container environment plus a `start_command` that writes `/etc/inithooks.conf` and then runs
    `/usr/sbin/start.sh`; the generated passwords are shown in the template's usage notes.
15. **gns3server patch 4 (init.sh, skip `su` for root)** covers only root containers. For an image whose user is not
    root, busybox `su` still runs and can crash (exit 139) with an old glibc.
16. **KVM probe.** `/dev/kvm` being accessible is not enough: VASYA starts `qemu -accel kvm` once (8 s timeout); if
    that fails or hangs, VASYA's server config gets `enable_kvm = false` (log `KVM_UNUSABLE`) and VMs run under TCG.
17. **The GUI on a desktop without the Qt xcb libraries needs the network once.** The libraries are no longer
    bundled; `vasya-gns-manager` downloads the pinned Ubuntu packages and caches them in `~/.cache/vasya-gns-lab`.
    Installing `libxcb-cursor0` (or running under Wayland) avoids this.
