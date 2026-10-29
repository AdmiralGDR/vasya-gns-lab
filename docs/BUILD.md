# VASYA GNS LAB 1.1.0 — Build

All builds run on a Linux x86_64 host. Archives are built **once**, after measuring sizes and free space.

## 1. Linux bundle stage
```
python3 scripts/build_bundle.py --out build/stage \
   --pyside <PySide6 site-packages> --gns3rt <gns3server runtimes py310..py313> --docs docs
```
Produces `VASYA-GNS-LAB-1.1.0/` with App (vasya + PySide6 + gns3server runtime), Payload (manifest and appliance
files only), install.sh, launchers, .desktop, Docs, BUNDLE_MANIFEST.json. The default `--profile public` never
contains images and refuses `--images` / `--docker-archives`; only devices whose images are pinned in
`third_party.lock` are included (the installer downloads them).

`--profile private --pack <Pack dir> --images <dir>` builds `VASYA-GNS-LAB-1.1.0-PRIVATE/`, an offline bundle with
every image hardlinked in. It may contain licensed vendor images: keep it on your own machines, never publish it.

## 2. Release archive + parts
```
python3 scripts/build_release.py --stage build/stage/VASYA-GNS-LAB-1.1.0 \
   --out build/release --part-size 95MiB
```
Measures the stage and free space (refuses if free < 1.2 × stage), runs `tar -cf - | zstd -T0 -19 --long` once, splits
into `drive-parts/*.partNNN` (< 100 MB each) + `*.parts.json`, writes `VASYA-GNS-LAB-1.1.0-Linux-Setup.sh` and
`SHA256SUMS`.

## 3. Windows Setup.exe
```
python3 scripts/build_windows.py --docs docs --out build/release/VASYA-GNS-LAB-1.1.0-Setup.exe
```
Inputs: python-3.12.10-embed-amd64.zip, PySide6 win_amd64 wheel contents, zstandard cp312 wheel; makensis.
PySide6 is pruned to the PE-import closure of QtCore/QtGui/QtWidgets. Output status is always UNVERIFIED until run on
real Windows.

## 4. Third-party binaries
None are stored in this repository or in a public bundle. Dynamips, uBridge and VPCS (GNS3 PPA builds
for Ubuntu 24.04) and the Qt xcb libraries (libxcb-cursor0 0.1.4-1build1, libxcb-icccm4 0.4.1-1.1build3,
libxcb-keysyms1 0.4.0-1build4, Ubuntu noble) are pinned in `src/vasya/data/third_party.lock`
(package URLs, package SHA-256, extracted file SHA-256, source package). The installer downloads,
verifies and places them under `<root>/Runtime` (see `vasya fetch --help`). A system copy always wins.
To rebuild one from source, use the `source` entry of the lock (Debian source package from the PPA).
