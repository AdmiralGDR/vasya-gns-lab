#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# VASYA GNS LAB 1.1.0 — Linux installer entry point (downloads device images and helper programs).
#   ./install.sh          open the graphical install wizard (8 steps, nothing changes before "Install")
#   ./install.sh --cli    text mode: shows the plan, asks, installs into ~/VASYA-GNS-LAB
#   ./install.sh --help
# No sudo is needed for the default "Complete Lab" mode. System changes (apt packages,
# groups, uBridge capabilities) are only LISTED with exact commands — never run silently.
set -u
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
export VASYA_BUNDLE_DIR="$HERE"
PY="${VASYA_PYTHON:-python3}"
if ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "VASYA GNS LAB needs Python 3.10 or newer (Pop!_OS/Ubuntu 22.04+ already have it)." >&2
  echo "Install it with:  sudo apt install python3" >&2
  exit 3
fi
case "${1:-}" in
  -h|--help)
    sed -n '3,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  --cli)
    shift
    "$HERE/vasya" plan --mode FULL "$@" || exit $?
    printf '\nInstall now? [y/N] '; read -r ans
    case "$ans" in y|Y|yes|д|Д|да) exec "$HERE/vasya" install --mode FULL "$@" ;; *) echo "Nothing changed."; exit 0 ;; esac ;;
esac
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  echo "No graphical session found — starting text mode (./install.sh --cli)." >&2
  exec "$0" --cli "$@"
fi
exec "$HERE/vasya-gns-manager" --screen install "$@"
