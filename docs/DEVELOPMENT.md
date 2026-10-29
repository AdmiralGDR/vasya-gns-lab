# VASYA GNS LAB 1.1.0 — Development

## Layout
`src/vasya` (package), `tests/` (pytest), `packaging/linux|windows|payload`, `scripts/` (build tools), `docs/`.

## Environment
```
python3 -m venv .venv && .venv/bin/pip install PySide6 pytest zstandard
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests
```
Optional integration tests are driven by environment variables (see `tests/conftest.py` and
`scripts/testenv.example.sh`): `VASYA_GNS3SERVER_BIN` (gns3server 2.2.61 in its own venv), `VASYA_TEST_PATH`,
`VASYA_TEST_GNS3RT`, `VASYA_TEST_STAGE`, `VASYA_TEST_PACK`, `VASYA_TEST_NETWORK=1` (real downloads). Tests whose
input is missing are skipped with the reason (`-rs`). System packages used by runtime tests: qemu-system-x86,
qemu-utils, docker.io or podman, busybox-static, telnet, Xvfb, xdotool.

## Rules
- No module above ~600 lines; the GUI never contains business logic — it calls `vasya.api`.
- Every write outside a dry run goes through a transaction (`core/txn.py`) and a receipt.
- Deletion only via receipts + state check (`installer/rollback.py:owned_state_mismatch`).
- Never run system changes silently; return the exact command (`installer/requirements.py`, `system_packages.py`).
- User-visible strings: `gui/i18n.py` (RU/EN); errors: `errors.py` (code → title/why/state/action).
- Add a regression test for every fixed defect (see tests/test_template_fixes.py, test_ownership.py).
- Never add images or binaries to the repository. Pin new downloads in `src/vasya/data/third_party.lock`
  (URL + SHA-256 checked with a real download); `tests/test_public_release.py` enforces this.

## Template fixes
`python3 scripts/merge_template_fixes.py FIXES_DIR` copies per-appliance template overrides (GNS3 template JSON
exported after a manual fix) into `src/vasya/data/appliance_fixes/<block_id>.json`; `build_template()` applies them.

## GNS3 GUI testing harness
Xvfb + xdotool: `Xvfb :99 &`, `DISPLAY=:99 gns3 &`, drive with `xdotool search --name GNS3 key/type`; screenshots
with `import -window root`. The manager's own GUI end-to-end test (tests/test_gui_e2e.py) drives Qt directly and
writes its screenshots to `VASYA_E2E_SHOTS` (default: a temporary folder).
