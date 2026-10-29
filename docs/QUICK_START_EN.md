# VASYA GNS LAB 1.1.0 — Quick start

## Linux (Pop!_OS 24.04 / Ubuntu 22.04+)
1. Download **all** `VASYA-GNS-LAB-1.1.0-Linux.tar.zst.partNNN` files, `VASYA-GNS-LAB-1.1.0-Linux.tar.zst.parts.json`
   and `VASYA-GNS-LAB-1.1.0-Linux-Setup.sh` into one folder (usually Downloads). Do **not** join the parts by hand.
   If Google Drive gave you ZIP files, leave them as they are.
2. Run `sh VASYA-GNS-LAB-1.1.0-Linux-Setup.sh` (or double-click → Run). It finds the parts, checks the sha256 of each,
   unpacks the kit and opens the install wizard.
   Device images are not part of the download: the installer fetches each one from its official source and checks
   its SHA-256. Docker images are pulled by pinned digest. A device whose image cannot be fetched is shown as
   "image not available"; everything else is installed. Cisco IOS images are never distributed — see
   PRIVATE_IMAGES.md for how to use your own licensed copies.
3. Wizard (8 steps): Welcome → System check → Install mode (recommended: "Complete Lab") → Components →
   Location (default `~/VASYA-GNS-LAB`) → Change preview → Installing → Done. Nothing changes before you press Install.
4. Home → "Open lab". The applications-menu entry is only created if you agree.

Text mode: `./install.sh --cli` (shows the plan and asks).

The Complete Lab mode needs no sudo. System changes (apt packages, kvm/docker groups, uBridge capabilities) are only
**listed** with exact commands, never run silently.

## Windows 10/11 (status: UNVERIFIED on real Windows)
1. Run `VASYA-GNS-LAB-1.1.0-Setup.exe` (no admin rights; installs to `%LOCALAPPDATA%\VASYA-GNS-LAB`).
2. Device images are downloaded automatically during installation (Internet needed), like on Linux.
3. Running devices on Windows needs GNS3 with the GNS3 VM — see USER_GUIDE.

## Uninstall
"Uninstall" in the left menu (4 steps) or `vasya uninstall --level components|full`. See UNINSTALL_GUIDE.md.
