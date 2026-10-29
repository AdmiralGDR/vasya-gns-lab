"""VASYA GNS LAB Manager launcher for the Windows Setup.exe install (pythonw, no console).
Layout: <root>\App\python\pythonw.exe, <root>\App\vasya, <root>\App\site-packages."""
import os, sys
from pathlib import Path

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.dont_write_bytecode = True
for p in (str(APP / "site-packages"), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("VASYA_ROOT", str(ROOT))
if __name__ == "__main__":
    try:
        from vasya.gui.app import main
        sys.exit(main(["--root", str(ROOT)] + sys.argv[1:]))
    except Exception:  # pythonw has no console: leave the reason where the user can find it
        import traceback
        (ROOT / "Logs").mkdir(parents=True, exist_ok=True)
        (ROOT / "Logs" / "manager-crash.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
