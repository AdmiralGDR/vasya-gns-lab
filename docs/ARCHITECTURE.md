# VASYA GNS LAB 1.1.0 — Architecture

## Layers
```
GUI (PySide6, vasya.gui)  ─┐
CLI (vasya.cli)           ─┼─> vasya.api (facade: one function per user action)
                           │
installer/  plan → apply (WAL transaction, receipts) → verify → repair/rollback
uninstall/  inventory → undo by receipt (ownership + state check) → residue scan → report
catalog/    186 blocks (data/appliances + pack manifest), statuses, template fixups (D1–D3), user image import
gns3/       REST client (2.2.x), template builder, discovery, remote compute (GNS3 VM)
runtime/    managed gns3server (own port/config/XDG inside the root), Docker backend, consoles,
            busy-node detection, GUI deps (xcb libs, PyQt6), downloaded helper programs
fetch/      pinned downloads (third_party.lock): public images, helper programs, private image sources
delivery/   release parts (split/find/verify/join), Setup.sh bootstrap, payload import
core/       ONE-ROOT layout, CAS store, state (locked JSON), transactions/receipts, op log
platform/   Linux / Windows paths and tool discovery
```
Every module stays below ~600 lines (largest: gui/screens/install_wizard.py, 370).

## ONE-ROOT
Everything VASYA writes lives under one folder: `App/ Store/ GNS3/ Runtime/ State/{txn,receipts}/ Logs/ Reports/
Demos/ Desktop/ Cache/ Imports/`. Outside it VASYA writes only after explicit consent: the `.desktop` entry, a GNS3
config backup + template additions in Integration mode, Docker images in the shared daemon, admin-approved system
packages. Each of those is receipted.

## Install transaction
`plan()` is pure (no writes) and returns operations + a preview (space, downloads, system changes with undo, re-login).
`apply()` runs each operation as `intent → act → commit` in a write-ahead transaction file (State/txn). A crash leaves
intents without commits; `resume` finishes, `rollback` undoes. Images are placed from the content-addressed store
(`Store/images/sha256/<hash>`) by hardlink after a link test, else copy with post-copy sha256 (never silently for big
images across filesystems). Names in GNS3 are `vasya-<sha16>-<file>` when a foreign file with the same name exists.

## Ownership
A resource is deleted only if (1) a receipt says VASYA created it and (2) its current state matches the receipt
(sha256 + size; inode recorded). Otherwise KEPT_MODIFIED / KEPT_UNVERIFIED and listed in the report. GNS3's own builtin
blank disks are treated as equivalent and reused, not owned. System packages: before-state recorded in
`State/receipts/system-packages.json`; removal offered only for `was_installed_before=false` with no non-VASYA reverse deps.

## Docker (Linux: rootless podman under VASYA_ROOT by default; Windows: GNS3 VM, UNVERIFIED)
`runtime/docker_backend.py` selects the backend: `VASYA_DOCKER_BACKEND` env → saved state → platform default.
- **Linux default `podman-rootless`** (tested with rootless podman 4.9 on Pop!_OS 24.04). Config lives under `<root>/Runtime/podman/xdg/config/containers/` and is selected through
  `XDG_CONFIG_HOME` (never `CONTAINERS_STORAGE_CONF`, which podman treats as the *system* file and then ignores
  graphroot in rootless mode). `containers.conf` sets `netns = "none"` (podman's compat API ignores `NetworkDisabled`),
  cgroupfs, file events; `registries.conf` blocks docker.io/quay.io/ghcr.io for the API service (gns3server cannot pull). Storage: `Runtime/podman/storage`.
  VASYA itself starts `podman system service --time=0 unix://<root>/Runtime/podman/run/podman.sock` as a user
  process (pidfile, log; no systemctl) when it starts gns3server, and stops it (only its own pid, checked via
  `/proc/<pid>/environ`) when it stops gns3server. Full uninstall removes the storage via `podman unshare rm -rf`.
- The environment `VASYA_DOCKER_SOCKET`, `DOCKER_HOST=unix://…`, `VASYA_DOCKER_FIX_UID=0`, `VASYA_DOCKER_FIX_GID=0`
  is passed **only to the VASYA-managed gns3server process** and only when the VASYA socket exists. The user's own
  Docker, `/var/run/docker.sock` and system services are never touched.
- **Bundled gns3server patch** (`data/patches/gns3server-2.2.61-vasya-docker-socket.patch`, applied to all
  bundled py310..py313 copies by `build_bundle.py`, recorded in `App/runtime/gns3server/VASYA_PATCHES.json`):
  (1) socket from `VASYA_DOCKER_SOCKET` (unset/empty → stock `/var/run/docker.sock`); (2) a 404 from
  `attach/ws` (podman 4.9) falls back to a plain hijacked `attach`; (3) `VASYA_DOCKER_FIX_UID/GID` for the
  `.gns3_perms` chown (rootless uid mapping). The earlier one-liner (`VASYA_DOCKER_SOCK`) is upgraded automatically.
- **Patch 4** (`data/patches/gns3server-2.2.61-vasya-init-su.patch`, `docker_backend.patch_init_su`):
  `compute/docker/resources/init.sh` execs `run-cmd.sh` directly when `GNS3_USER` is empty/`root`/`0`, otherwise the
  stock `su <user> -p --` line. Applied after the 3-part patch to every bundled copy (new inode, mode 0755 kept);
  both are listed in `VASYA_PATCHES.json` (`patches`).
- **Pins** (`data/docker-images.json`, same format as an archive dir's manifest, plus `blocks`): `fixups.apply_block`
  sets each Docker block's ref/digest/image ID from it; the template keeps the tag (usage notes show `ref@digest`),
  the labelled image carries `org.vasya.base_digest`/`base_id`. An archive dir without its own manifest uses the pins
  for the archives present; any archive entry whose image ID contradicts a pin is ignored. Template fixes for Docker
  blocks (`default_name_format`, `start_command`, `environment`) come from `data/appliance_fixes/<block>.json`.
- **Pinned pulls.** `fetch.prepare` and the installer pull each image as `docker.io/<repo>@<digest>` with a
  separate `registries-pull.conf` (docker.io and ghcr.io only), check the image ID against the pin (mismatch → `rmi`)
  and tag the refs. `VASYA_DOCKER_PULL=0` / `VASYA_OFFLINE=1` turn pulls off.
- **Offline archives** (optional) (one per unique image, `docker save` format, `.tar` or `.tar.zst` —
  never both) live in `Images/docker/` (or `Payload/docker/`) with `docker-images.json` (refs, archive, sha256,
  bytes, image_id, repo_digest), generated from the per-image test CSV by `scripts/import_docker_archives.py`.
  `runtime/docker_images.restore` verifies size + sha256 + the archive's own manifest (exactly one image, config ==
  image_id), streams it into `podman load`, re-checks the image ID and tags every ref. Missing images are restored
  automatically at install and **every time VASYA starts gns3server** (before any docker node can be created), and
  the labelled `FROM base + LABEL org.vasya.owner` images are rebuilt with `--pull=never`. Note: a docker-archive
  does not carry the registry manifest digest, so `repo_digest` is provenance only; the offline check is image_id.
  `import_docker_archives.py --csv tested-images.csv --index index.json` derives the archive names and image IDs;
  `--no-files` writes the manifest without the archives (sizes/sha256 from the CSV).
- `shared-daemon` is used only when chosen explicitly (`VASYA_DOCKER_BACKEND=shared-daemon`): receipts with
  `preexisting=false`, labelled images, foreign-usage refcount before `rmi`, never prune / `rmi -f`.
- Receipts record the engine; rollback/uninstall of podman-loaded images go to VASYA's podman only, never the shared
  daemon. Missing prerequisites (podman, newuidmap/newgidmap, /etc/subuid entry) block Docker components only, with
  the `apt install podman uidmap` command shown.
- **Windows**: Docker only through the GNS3 VM integration path, never rootless podman — UNVERIFIED.

## Why PySide6 (Qt for Python)
- Official Qt binding, LGPL-3 — redistributable inside an offline kit without a commercial licence (PyQt6 is GPL/commercial).
- Self-contained wheels for Linux x86_64 and Windows x64 → one code base, bundled under App/site-packages, no pip on
  the user machine; pruned to QtCore/QtGui/QtWidgets (+ platform/style/image plugins).
- Native look on GNOME/COSMIC/KDE (Wayland first, xcb fallback) and Windows; RU/EN translations and dark/light palettes.
- Testable headless (`QT_QPA_PLATFORM=offscreen`, Xvfb) — the GUI E2E runs headless in CI.
- Alternatives rejected: Tkinter (no proper HiDPI/Wayland, weak widgets), web UI (needs a local server + browser, harder
  offline/uninstall story), GTK (no practical Windows bundle), Electron (≥150 MB, Node toolchain).
GNS3's own GUI uses PyQt; VASYA does not import it — the two never share a process.

## Delivery
Linux: `VASYA-GNS-LAB-1.1.0-Linux.tar.zst` split into parts < 100 MB with `*.parts.json` (sizes + sha256) and a
self-contained `Setup.sh` (stdlib only) that finds/verifies/streams the parts into `zstd -d | tar -x` and starts the
wizard. Windows: NSIS `Setup.exe` (per-user, embedded Python 3.12 + PySide6).
The public bundle carries no images: see "Downloads" below.
Docker images: separate optional pack `VASYA-GNS-LAB-<ver>-Docker-Images.tar` (uncompressed tar of the zstd archives,
built from hardlinks by `scripts/build_docker_pack.py`, streamed into 95 MiB parts). Setup.sh embeds its file list
(`EMBEDDED_DOCKER`: name → size + sha256 from the pins and `packaging/docker-pack/`), streams the joined parts through
`tarfile r|`, accepts only those regular files, hashes each while writing to `.vasya-image-pack.partial/` and moves
them into `<VASYA>/Images/docker/` only if all match. The app reports `docker_image_pack` in the plan preview and
pulls the pinned digest when an image has no archive.

## Downloads (`vasya.fetch`)
`src/vasya/data/third_party.lock` pins every file the installer may download: helper programs (Dynamips,
uBridge, VPCS — GNS3 PPA `.deb`), the Qt xcb libraries (Ubuntu `.deb`), public device images and Docker images
(digest + image ID). Each entry lists mirror URLs, the SHA-256 and size of the download, the file inside an
archive/package, the SHA-256 of the final file and how the entry was verified (`VERIFIED` = downloaded and hashed,
`UNVERIFIED` = registry hash only). Downloads go to `.partial`, are hashed while streaming and moved into the
content-addressed store (`Store/user/sha256/<hash>`) only on a match; nothing unverified is ever used.
`fetch.prepare()` runs before the plan is built; a device whose image is missing becomes an `IMAGE_NOT_AVAILABLE`
step (shown as "image not available") and the installation continues. Vendor images come only from private
sources (`fetch/private.py`, docs/PRIVATE_IMAGES.md) and are checked against the user's private manifest.
`VASYA_OFFLINE=1` disables all network access.
