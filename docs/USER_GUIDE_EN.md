# VASYA GNS LAB 1.1.0 — User guide

VASYA GNS LAB is a training-lab manager for GNS3: a catalog of 186 devices, automatic download and install of verified images,
runtime verification, repair, an operations log, diagnostics and clean uninstall. Everything VASYA creates lives in
**one folder** (default `~/VASYA-GNS-LAB`, on Windows `%LOCALAPPDATA%\VASYA-GNS-LAB`) and is recorded in receipts
(State/receipts).

## Screens
| Screen | What it does |
|---|---|
| Home | Health: installed/ready/errors, GNS3 server, "Open lab", "Verify", "Import images" (when no images yet) |
| Install | 8-step wizard (below) |
| Catalog | 186 components; search and filters by category, runtime (QEMU/Docker/Dynamips/IOU), status |
| Verify | Quick file/template check; "Runtime check" creates/starts/opens the console/stops each device |
| Repair | Reinstalls damaged/removed images and templates (only what VASYA owns) |
| Uninstall | 4-step wizard (below) |
| Log | Human-readable operations log (Logs/operations.log) |
| Diagnostics | Support ZIP (no passwords, no personal files) |
| Tools | Wireshark, VNC, telnet, VPCS, Packet Tracer — found or not, with the exact install command |
| Lab | Demo projects (e.g. OSPF + packet capture) |

Language (RU/EN) and theme (light/dark/system) are at the bottom of the menu.

## Install wizard
1. **Welcome**. 2. **System check** — Python, KVM, Docker, uBridge, Dynamips, free space.
3. **Mode**: *Complete Lab* — VASYA's own GNS3 server 2.2.61 inside the VASYA folder (your GNS3 is untouched);
   *Integration* — add templates to your existing GNS3 (its config is backed up first); *Selective* — only the checked components.
4. **Components**. 5. **Location**. 6. **Change preview** — space, downloads, system changes with commands and how to
   undo them, whether a re-login is needed. 7. **Installing** — human progress; Cancel is safe (the transaction is rolled back).
8. **Done** — summary and verification.

### Component statuses
READY — image downloaded automatically from its official source; NEEDS_IMAGE — bring your own image file (Catalog → Import image, sha256 checked);
NEEDS_DOWNLOAD — download from the vendor; NEEDS_REGISTRATION / NEEDS_LICENSE — vendor account or licence;
OBSOLETE / UNAVAILABLE — not available, reason in the catalog. A **BLOCKED** component (e.g. openwrt-realview without
`qemu-system-arm`) is not an error: the needed package and the admin command are shown.

## Image sources
Public images are downloaded from the URLs pinned in `third_party.lock` and checked by SHA-256 (`vasya fetch --dry-run`
shows what is missing and where it comes from). Vendor images (Cisco IOS) come only from your private source, see
PRIVATE_IMAGES.md. A device without its image is shown as "image not available".

## Importing images from a private offline bundle
Home → "Import images" or `vasya import-payload --search`. Looks for `*.parts.json` in the kit folder, Downloads and the
current folder, checks every part and every image by sha256 and atomically unpacks only images + manifests into
`<folder>/Store` (on any error nothing changes).

## GNS3 GUI (Linux)
The GNS3 GUI needs PyQt6 and `libxcb-cursor0` (+ `libxcb-icccm4`, `libxcb-keysyms1`). `vasya gui-deps` shows what is
missing. Missing xcb libraries are downloaded (pinned Ubuntu packages, SHA-256 checked) into `<folder>/Runtime/lib` (no sudo, receipted):
`vasya gui-deps --bundle`. VASYA never pip-installs PyQt6 into a Python environment it does not own; it shows the command.

## VPCS
If there is no `vpcs` (or `dynamips`, `ubridge`) on the system, VASYA downloads the GNS3 PPA build (version and
SHA-256 pinned in `third_party.lock`) and places it at `<folder>/Runtime/bin/vpcs`
and written into VASYA's server config.

## Wireshark and VNC consoles in the GNS3 GUI
The installer writes VASYA's own GNS3 GUI profile (`<folder>/Runtime/managed_gns3/xdg/config/GNS3/2.2/gns3_gui.conf`,
used only when the GNS3 GUI is started from VASYA): Wireshark live capture
(`tail -f -c +0b {pcap_file} | wireshark -k -i -`), VNC console `vncviewer {host}:{port}` and the VPCS path.
Your own GNS3 settings are not touched.

## Things created outside the VASYA folder
vncviewer creates `~/.vnc` the first time a VNC console opens. VASYA records this and lists it in the uninstall report
("Known external side effects"); it is never deleted automatically.

## Windows
The manager runs, but QEMU/Docker devices on Windows run only through the GNS3 VM (remote compute). VASYA uploads images
to the GNS3 VM and creates templates; it cannot delete them from the VM automatically — the report shows the exact hint.
**Windows status: UNVERIFIED** (see SUPPORTED_PLATFORMS.md).

## Command line
`vasya status | plan | install | verify [--runtime] | repair | retry | rollback | uninstall | import-payload | catalog |
import-image | tools | diagnostics | inventory | demo | logs | desktop | gns3-config | gui-deps` (`--json` for machine
output, `--root` for another folder).
