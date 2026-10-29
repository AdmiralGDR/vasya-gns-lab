# VASYA GNS LAB 1.1.0 — Troubleshooting / Решение проблем

Every error in VASYA has a code, a plain explanation, the current state and the next action
(GUI dialog, `--json` output and Logs/operations.log). / Каждая ошибка имеет код, объяснение, состояние и действие.

| Code | Meaning | Action |
|---|---|---|
| NO_INTERNET | No Internet connection | Reconnect and press "Retry failed" (`vasya retry`) |
| PARTIAL_DOCKER_PULL | Docker download interrupted | "Retry failed" — continues from cached layers |
| CORRUPT_DOWNLOAD | A release part is damaged | Re-download only that part (shown by name); verified parts are kept |
| PAYLOAD_DAMAGED | Image in the VASYA store damaged | Re-run the import / Setup, or "Repair" |
| LOW_DISK | Not enough space | Free space or choose another folder/disk |
| INTERRUPTED | Previous operation interrupted | "Resume" (`vasya resume`) or "Roll back" (`vasya rollback`) |
| NO_ADMIN | Admin rights required | Pick a folder in your home, or run the shown command as admin |
| EXISTING_GNS3 | Existing GNS3 found | "Add to existing GNS3" or "Complete lab" (own server, port 3088) |
| PORT_CONFLICT | Port busy | Nothing — VASYA moved its server to a free port and saved it |
| BUSY_VM | Lab devices running | Stop nodes in GNS3 or press "Stop nodes", retry |
| IMAGE_MISSING / IMAGE_CORRUPT | Image deleted/damaged | "Repair" (`vasya repair`) |
| GNS3_UNREACHABLE | GNS3 / GNS3 VM unreachable | Start it, check address/network, retry |
| MISSING_PROGRAMS | Programs missing | Install the listed packages (command on the Plan page) |
| UBRIDGE_CAPS | uBridge lacks capabilities | Run the shown `setcap` command (admin) |
| BLOCKED (component) | A dependency like qemu-system-arm is missing | Run the shown `apt-get install` (admin) and install again |

## Common situations
- **Setup.sh says parts are missing** — it lists the missing part names; download them into the same folder and rerun.
  Parts already verified are not re-hashed.
- **Manager window does not open on Linux ("could not load the Qt platform plugin xcb")** — the launcher downloads the pinned
  `libxcb-cursor`/`icccm`/`keysyms` once (cached in `~/.cache/vasya-gns-lab`); if it still fails, run `vasya gui-deps` and send the output.
- **GNS3 GUI does not start** — `vasya gui-deps`: shows whether PyQt6 and the xcb libraries are present and how to fix.
- **KVM not accessible** — QEMU devices run without acceleration (slow). Plan page shows `sudo usermod -aG kvm $USER`
  (re-login needed).
- **KVM_UNUSABLE** (log) — `/dev/kvm` is writable but a test VM with `-accel kvm` hangs (broken nested virtualisation,
  e.g. inside another VM). VASYA then writes `enable_kvm = False` for its own server so QEMU devices still start
  (slowly). Fix the hypervisor / BIOS VT-x setting, then Repair.
- **Docker devices skipped** — on Linux VASYA uses its own rootless podman: install `podman uidmap` (the plan page shows the command) and make sure your user has a `/etc/subuid` entry. You never start podman or move archives yourself — VASYA restores images from `<folder>/Images/docker/` automatically (never pulled). With the explicit shared-daemon choice, Docker must be installed and your user in group `docker`.
- **openwrt-realview BLOCKED** — needs `qemu-system-arm` (`sudo apt-get install --no-install-recommends qemu-system-arm`).
- **Diagnostics** — Diagnostics screen or `vasya diagnostics --out ~/vasya-diag.zip`; attach the ZIP.
- **Windows: manager does not start** — see `%LOCALAPPDATA%\VASYA-GNS-LAB\Logs\manager-crash.txt`. Windows 10 1903+ is
  required (Qt 6 uses the system ICU, `icuuc.dll`).
