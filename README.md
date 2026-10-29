# VASYA GNS LAB

A guided installer and manager for a self-contained [GNS3](https://www.gns3.com/) network lab on Linux
(Windows support is experimental). It installs GNS3 server 2.2.61, a desktop manager (Qt 6) and up to
41 ready-to-use devices (routers, switches, firewalls, Linux hosts, Docker appliances) into one folder,
`~/VASYA-GNS-LAB`, without root rights. Everything it installs can be removed again.

## How it works

* **No images in the package.** Device images are downloaded during installation from the publisher's
  own site and checked against the SHA-256 pins in [`src/vasya/data/third_party.lock`](src/vasya/data/third_party.lock).
  Docker images are pulled with rootless Podman by pinned digest. Helper programs (Dynamips, uBridge,
  VPCS) and missing Qt libraries are downloaded the same way when the system does not provide them.
* **Never fails on one device.** If an image cannot be downloaded, that device is shown as
  "image not available" and the rest of the lab is installed.
* **Licensed images stay yours.** Cisco IOS and other licensed images are never shipped or downloaded
  from a public location. Put your own copies in a private source and VASYA picks them up
  automatically: see [docs/PRIVATE_IMAGES.md](docs/PRIVATE_IMAGES.md).
* **Nothing changes silently.** System changes (packages, groups, capabilities) are listed with the
  exact commands; the installer never runs `sudo`.

## Quick start

From a release: run `sh VASYA-GNS-LAB-<version>-Linux-Setup.sh` and follow the wizard
([docs/QUICK_START_EN.md](docs/QUICK_START_EN.md), [по-русски](docs/QUICK_START_RU.md)).

From source (Python 3.10–3.13, PySide6 6.x):

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install PySide6 pytest
PYTHONPATH=src python -m vasya fetch --dry-run     # what would be downloaded, and from where
PYTHONPATH=src python -m vasya --help
QT_QPA_PLATFORM=offscreen pytest                   # test suite; no network needed
```

Building release packages: [docs/BUILD.md](docs/BUILD.md). Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Known limits: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The appliance files come from the
[GNS3 registry](https://github.com/GNS3/gns3-registry) and the server patches modify
[GNS3 server](https://github.com/GNS3/gns3-server); details in [NOTICE](NOTICE),
[THIRD_PARTY.md](THIRD_PARTY.md) and [docs/RELEASE_SOURCES.md](docs/RELEASE_SOURCES.md).

## Trademarks

GNS3 is a trademark of GNS3 Technologies Inc. Cisco and Cisco IOS are trademarks of Cisco Systems, Inc.
Other names are trademarks of their respective owners. VASYA GNS LAB is an independent project and is
not affiliated with or endorsed by GNS3 Technologies Inc., Cisco Systems, Inc. or any other vendor.
Device images are subject to their publishers' license terms.
