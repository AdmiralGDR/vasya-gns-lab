# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic acquisition of third-party components.

Nothing that VASYA GNS LAB cannot redistribute is stored in the source tree or in public
release packages. Instead the installer obtains each component on the user's machine:

* lock.py      -- ``data/third_party.lock``: every public component with its upstream URL(s)
                  and pinned SHA-256 (download and content).
* download.py  -- HTTP(S) download into a cache with size and SHA-256 verification.
* unpack.py    -- gzip / bzip2 / xz / zip / Debian package extraction (no root needed).
* tools.py     -- Dynamips, uBridge, VPCS and the Qt xcb libraries under <root>/Runtime.
* images.py    -- QEMU/Dynamips disk images into the content-addressed user store.
* private.py   -- images that may not be redistributed (for example Cisco IOS), taken only
                  from sources the user controls (local folders, a private GitHub release,
                  a private HTTPS URL), verified against the user's private manifest.

Every function reports a status instead of raising, so a missing network or an unavailable
private source only marks the affected components as "image not available".
"""
