# Third-party components

VASYA GNS LAB is licensed under GPL-3.0-or-later (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
This file lists material written by others. "Repository" means this source tree; "release" means the
Linux bundle or the Windows Setup.exe; "downloaded" means fetched by the installer on the user's machine.

## In the source repository

| Component | Where | License | Upstream |
|---|---|---|---|
| GNS3 appliance files (183 × .gns3a) | src/vasya/data/appliances/ | GPL-3.0 | https://github.com/GNS3/gns3-registry, commit `0c04ba6100a2fed7f25d9bac5fc289d836db27fa` |
| Copies of 41 appliance files | packaging/payload/appliances/ | GPL-3.0 | same; `ntopng.gns3a` from commit `8ce90a6a35aaddb85bb10413a46fdf98f0993023` |
| Patches to GNS3 server 2.2.61 | src/vasya/data/patches/ | GPL-3.0-or-later (modifications of GNS3 server) | https://github.com/GNS3/gns3-server, tag v2.2.61 |
| init.sh test fixtures from GNS3 server 2.2.61 | tests/gns3server_patch/init_su/ | GPL-3.0-or-later | same as above |

No third-party binaries and no device images are stored in the repository
(`tests/test_public_release.py` checks this).

## Shipped in release packages

| Component | Version | License | Source | Notes |
|---|---|---|---|---|
| GNS3 server (+ VASYA patches) | 2.2.61 | GPL-3.0-or-later | https://github.com/GNS3/gns3-server | Modified; the patches are in `src/vasya/data/patches` |
| Python packages required by GNS3 server | see `THIRD_PARTY/python-licenses.txt` in the release | various (MIT, BSD, Apache-2.0, ...) | PyPI | List generated during the build |
| PySide6 / Shiboken6 / Qt 6 (Core, Gui, Widgets) | 6.12.0 | LGPL-3.0 | https://code.qt.io/ | Shared libraries that users can replace |
| CPython embeddable | 3.12.10 | PSF-2.0 | https://www.python.org/ | Windows only |
| zstandard | 0.25.0 | BSD-3-Clause | https://pypi.org/project/zstandard/ | Windows only |
| Microsoft Visual C++ runtime DLLs | as shipped in the PySide6 wheel | Microsoft redistributable terms | — | Windows only |

## Downloaded by the installer (not redistributed)

Pinned in `src/vasya/data/third_party.lock` (URL, SHA-256, size, verification status). The installer
downloads them only when no system copy exists and checks every file before use.

| Component | Version | License | Downloaded from |
|---|---|---|---|
| Dynamips | 0.2.25-1~noble1 | GPL-2.0-or-later | GNS3 PPA (ppa.launchpadcontent.net/gns3/ppa), source package listed in the lock |
| uBridge | 1.0.1-1~noble1 | GPL-3.0-or-later | GNS3 PPA, source package listed in the lock |
| VPCS | 0.8.5-1~noble2 | BSD-2-Clause AND ISC | GNS3 PPA, source package listed in the lock |
| libxcb-cursor0 / libxcb-icccm4 / libxcb-keysyms1 | 0.1.4-1build1 / 0.4.1-1.1build3 / 0.4.0-1build4 | MIT (X11) | Ubuntu 24.04 archive (archive.ubuntu.com) |
| Public device images (22 files for 41 devices) | see the lock | each publisher's own terms | the publisher's site (SourceForge GNS3 project, OpenWrt, Fedora, CentOS, Ubuntu, MikroTik, ...) |
| Docker images (20 images for 21 devices) | pinned by digest | each image's own terms | docker.io / ghcr.io |

Not shipped or downloaded by VASYA, installed separately by the user or the OS:
QEMU, Podman/Docker, Wireshark, TigerVNC, Cisco Packet Tracer. Licensed vendor images (Cisco IOS and others)
are never shipped or downloaded from a public location; see [docs/PRIVATE_IMAGES.md](docs/PRIVATE_IMAGES.md).

Each release package has a `THIRD_PARTY/` directory with the full license text of every component above.
For the exact sources of every binary in a release, see [docs/RELEASE_SOURCES.md](docs/RELEASE_SOURCES.md).

## Trademarks

GNS3 is a trademark of GNS3 Technologies Inc. Cisco, Cisco IOS and Packet Tracer are trademarks or
registered trademarks of Cisco Systems, Inc. Other product and company names are trademarks of their
respective owners. They are used only to name the products this tool works with. VASYA GNS LAB is an
independent project and is not affiliated with or endorsed by these companies.
