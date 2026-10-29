# VASYA GNS LAB 1.1.0 — Supported platforms

| Platform | Status | Evidence |
|---|---|---|
| Debian 13 x86_64 | Tested | Full pytest suite, GUI end-to-end test, runtime checks of QEMU/Docker/Dynamips/VPCS devices |
| Pop!_OS 24.04 LTS (COSMIC/GNOME, x86_64) | Target platform; 1.1.0 end-to-end run **pending** | 1.0.1 was run there (defects D1–D7, fixed in 1.1.0 with regression tests); rootless podman and all Docker appliances tested there |
| Ubuntu 22.04 / 24.04 x86_64 | Expected to work (same packages as Pop!_OS 24.04), not tested | — |
| Windows 10 1903+ / 11 x64 | **UNVERIFIED** | Setup.exe built with makensis; wine smoke test only (install, CLI, uninstall); no run on real Windows |
| macOS, ARM64 Linux | Not supported | — |

## Linux requirements
- Python ≥ 3.10 (system `python3`); PySide6 6.x is bundled (App/site-packages).
- Internet access for the first installation of each device (images, helper programs and Docker images are
  downloaded from their upstream sources and checked against `third_party.lock`), unless you use a private
  offline bundle.
- Free space: shown on the plan page (all public devices ≈ 7 GB in the VASYA folder).
- Optional, listed with exact commands, never run silently: `qemu-system-x86` + `qemu-utils` (QEMU devices),
  `qemu-system-arm` (openwrt-realview), `podman` + `uidmap` (Docker devices), group `kvm`, `wireshark`,
  `tigervnc-viewer`, `telnet`, `traceroute`.
- Downloaded on demand when not installed system-wide: Dynamips 0.2.25, uBridge 1.0.1, VPCS 0.8.5 (GNS3 PPA,
  Ubuntu 24.04 builds) and the Qt xcb libraries. uBridge needs `cap_net_admin,cap_net_raw` (admin step).
- Bundled: gns3server 2.2.61 runtime (Python 3.10–3.13).

## Windows requirements (UNVERIFIED)
- Windows 10 1903+ (Qt 6 uses the system ICU) x64, no admin rights (per-user install).
- Embedded Python 3.12.10 + PySide6 (pruned to the Qt modules the manager imports).
- Devices need GNS3 2.2.x with the GNS3 VM (remote compute).
