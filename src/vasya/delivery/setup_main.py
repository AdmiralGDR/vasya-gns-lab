# SPDX-License-Identifier: GPL-3.0-or-later
# ---- VASYA GNS LAB bootstrap main (appended after delivery/parts.py by build_release.py) ----
import argparse, shutil, subprocess, sys, tarfile, threading

RU = os.environ.get("LANG", "").lower().startswith("ru")


def say(ru, en):
    print(ru if RU else en, flush=True)


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{n} B"
        n /= 1024


def bundle_ok(top):
    return (top / "install.sh").is_file() and (top / "BUNDLE_MANIFEST.json").is_file() \
        and (top / "Payload" / "manifests" / "pack.json").is_file()


def extract(source_kind, src, man, dest, top_name):
    final = dest / top_name
    work = dest / f".{top_name}.partial"
    if work.exists():
        say("Удаляю незавершённую распаковку с прошлого запуска…", "Removing an unfinished extraction from a previous run…")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    zstd = subprocess.Popen(["zstd", "-dcq"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    tar = subprocess.Popen(["tar", "-xf", "-", "-C", str(work)], stdin=zstd.stdout)
    zstd.stdout.close()
    last = [-1]

    def prog(done, total):
        pct = int(done * 100 / max(total, 1))
        if pct != last[0] and pct % 5 == 0:
            last[0] = pct
            say(f"  распаковка {pct}% ({human(done)} из {human(total)})", f"  extracting {pct}% ({human(done)} of {human(total)})")
    try:
        if source_kind == "whole":
            h, done, total = hashlib.sha256(), 0, src.stat().st_size
            with open(src, "rb") as f:
                for c in iter(lambda: f.read(CHUNK), b""):
                    h.update(c); zstd.stdin.write(c); done += len(c); prog(done, total)
            if man and h.hexdigest() != man["sha256"]:
                raise PartsError("ARCHIVE_CORRUPT", "archive checksum mismatch",
                                 {"expected": man["sha256"], "actual": h.hexdigest()})
        else:
            join_stream(man, src, zstd.stdin.write, prog)
        zstd.stdin.close()
    except BrokenPipeError:
        pass
    except BaseException:
        zstd.kill(); tar.kill(); zstd.wait(); tar.wait()
        shutil.rmtree(work, ignore_errors=True)
        raise
    rz, rt = zstd.wait(), tar.wait()
    if rz or rt:
        shutil.rmtree(work, ignore_errors=True)
        raise PartsError("ARCHIVE_CORRUPT", f"unpack failed (zstd={rz}, tar={rt})")
    if not bundle_ok(work / top_name):
        shutil.rmtree(work, ignore_errors=True)
        raise PartsError("ARCHIVE_CORRUPT", "archive does not contain a complete VASYA bundle")
    if final.exists():
        shutil.rmtree(final)
    os.replace(work / top_name, final)
    shutil.rmtree(work, ignore_errors=True)
    return final


def default_root():
    env = os.environ.get("VASYA_ROOT")
    return Path(env).expanduser() if env else Path.home() / "VASYA-GNS-LAB"


def docker_pack_present(D, out):
    return all((out / n).is_file() and (out / n).stat().st_size == f["size"] for n, f in D["files"].items())


def docker_extract(D, kind, src, man, out):
    """Stream the pack (whole .tar or joined parts) through tarfile; accept only the pinned files of
    <top>/<subdir>/, hash each while writing, move into place only if size+sha256 match."""
    prefix = f"{D['top_dir']}/{D['subdir']}/"
    work = out / ".vasya-image-pack.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    r, w = os.pipe()
    err = []
    last = [-1]

    def prog(done, total):
        pct = int(done * 100 / max(total, 1))
        if pct != last[0] and pct % 5 == 0:
            last[0] = pct
            say(f"  образы Docker {pct}% ({human(done)} из {human(total)})", f"  Docker images {pct}% ({human(done)} of {human(total)})")

    def feed():
        try:
            with os.fdopen(w, "wb") as sink:
                if kind == "whole":
                    done, total = 0, src.stat().st_size
                    with open(src, "rb") as f:
                        for c in iter(lambda: f.read(CHUNK), b""):
                            sink.write(c); done += len(c); prog(done, total)
                else:
                    join_stream(man, src, sink.write, prog)
        except BaseException as e:   # BrokenPipe when the reader stops early, or ARCHIVE_CORRUPT
            err.append(e)
    th = threading.Thread(target=feed, daemon=True)
    th.start()
    got, bad = {}, []
    try:
        with os.fdopen(r, "rb") as rf, tarfile.open(fileobj=rf, mode="r|") as tf:
            for m in tf:
                if m.isdir() and (m.name.rstrip("/") + "/").startswith(D["top_dir"] + "/"):
                    continue
                if m.isfile() and m.name == f"{D['top_dir']}/PACK.json":
                    continue                      # informational, not installed
                base = m.name[len(prefix):] if m.name.startswith(prefix) else None
                spec = D["files"].get(base) if base and "/" not in base else None
                if not m.isfile() or not spec:
                    bad.append(f"unexpected entry {m.name}"); continue
                h, n = hashlib.sha256(), 0
                with tf.extractfile(m) as f, open(work / base, "wb") as o:
                    for c in iter(lambda: f.read(CHUNK), b""):
                        h.update(c); o.write(c); n += len(c)
                if n != spec["size"] or h.hexdigest() != spec["sha256"]:
                    bad.append(f"{base}: sha256/size mismatch"); (work / base).unlink(); continue
                got[base] = True
    except (tarfile.TarError, OSError) as e:
        bad.append(f"tar: {e}")
    th.join()
    if err and not isinstance(err[0], BrokenPipeError):
        bad.insert(0, str(err[0]))
    missing = sorted(set(D["files"]) - set(got))
    if bad or missing:
        shutil.rmtree(work, ignore_errors=True)
        raise PartsError("ARCHIVE_CORRUPT", "; ".join(bad[:5] + [f"missing {len(missing)} file(s)"] * bool(missing)))
    for n in got:
        os.replace(work / n, out / n)
    shutil.rmtree(work, ignore_errors=True)
    return len(got)


def docker_pack(a, dirs, here):
    """Optional second pack. Missing -> message only (return 0); damaged -> 7."""
    D = EMBEDDED_DOCKER
    if not D or a.no_docker:
        return 0
    root = Path(a.root).expanduser().resolve() if a.root else default_root()
    out = root / "Images" / "docker"
    if docker_pack_present(D, out) and not a.verify_only:
        say(f"Образы Docker уже на месте: {out}", f"Docker images already in place: {out}")
        return 0
    name = D["archive"]
    extra = [d / D["pack"] for d in dirs] + [here.parent / D["pack"]]   # the pack's own Drive folder
    dirs = dirs + [d for i, d in enumerate(extra) if d.is_dir() and d not in dirs and d not in extra[:i]]
    kind, path = locate(name, dirs)
    if kind is None and unpack_drive_zips(dirs, name, here):
        kind, path = locate(name, dirs)
    if kind is None:
        say(f"Пакет образов Docker ({D['pack']}) не найден — компоненты Docker будут показаны как «image pack missing» "
            f"(остальное ставится как обычно). Чтобы добавить его позже: скачайте части {name}.part* и {name}.parts.json "
            f"в эту папку и запустите этот файл снова.",
            f"Docker image pack ({D['pack']}) not found — Docker components will show 'image pack missing' (everything "
            f"else installs normally). To add it later: download {name}.part* and {name}.parts.json into this folder "
            f"and run this file again.")
        return 0
    try:
        man = None
        if kind == "parts":
            man = json.loads(Path(path).read_text())
            if man.get("archive") != name:
                raise PartsError("NO_MANIFEST", f"{path} is not the manifest of {name}")
            src = find_parts(man, dirs)
            say(f"Найден пакет образов Docker: {len(src)} частей. Проверяю…", f"Found the Docker image pack: {len(src)} parts. Checking…")
            verify_parts(man, src, lambda i, n, p, s: say(f"  [{i}/{n}] {p} — {'ok' if s != 'BAD' else 'ПОВРЕЖДЕНА'}",
                                                          f"  [{i}/{n}] {p} — {s}"))
        else:
            src = path
            say(f"Найден целый пакет образов Docker: {path}", f"Found the complete Docker image pack: {path}")
        if a.verify_only:
            say("Пакет образов Docker: части в порядке.", "Docker image pack: parts OK.")
            return 0
        need = sum(f["size"] for f in D["files"].values()) + (256 << 20)
        probe = out
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        if shutil.disk_usage(probe).free < need:
            say(f"Мало места для образов Docker в {out}: нужно {human(need)}.", f"Not enough space for the Docker images in {out}: {human(need)} needed.")
            return 5
        out.mkdir(parents=True, exist_ok=True)
        say(f"Распаковываю образы Docker в {out} …", f"Unpacking the Docker images into {out} …")
        n = docker_extract(D, kind, src, man, out)
        say(f"Образы Docker: {n} файлов проверены (SHA-256) и установлены в {out}",
            f"Docker images: {n} files verified (SHA-256) and placed in {out}")
        return 0
    except PartsError as e:
        if e.code == "PARTS_MISSING":
            say("Пакет образов Docker неполный, не хватает:\n  " + "\n  ".join(e.detail["missing"]),
                "The Docker image pack is incomplete, missing:\n  " + "\n  ".join(e.detail["missing"]))
        elif e.code == "PART_CORRUPT":
            say("Повреждены части пакета образов Docker (скачайте их заново):\n  " + "\n  ".join(b["name"] for b in e.detail["bad"]),
                "Damaged Docker image pack parts (re-download them):\n  " + "\n  ".join(b["name"] for b in e.detail["bad"]))
        else:
            say(f"Пакет образов Docker повреждён: {e}", f"The Docker image pack is damaged: {e}")
        say("Ничего из пакета не установлено; запустите этот файл снова после повторной загрузки.",
            "Nothing from the pack was installed; run this file again after re-downloading.")
        return 7


def main():
    here = Path(os.environ.get("VASYA_SETUP_DIR") or Path(sys.argv[0]).resolve().parent)
    ap = argparse.ArgumentParser(description="VASYA GNS LAB setup: find, verify and unpack the download, then open the installer")
    ap.add_argument("--dest", default=str(Path.home()), help="where to unpack (default: home folder)")
    ap.add_argument("--search", action="append", default=[], help="extra folder with the downloaded parts")
    ap.add_argument("--no-install", action="store_true", help="only unpack, do not start the installer")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--root", default=None, help="VASYA folder for the Docker image pack (default ~/VASYA-GNS-LAB or $VASYA_ROOT)")
    ap.add_argument("--no-docker", action="store_true", help="ignore the Docker image pack")
    ap.add_argument("--docker-only", action="store_true", help="only verify/unpack the Docker image pack")
    a = ap.parse_args()
    man = EMBEDDED_MANIFEST
    name, top_name = man["archive"], man["top_dir"]
    dest = Path(a.dest).expanduser().resolve()
    final = dest / top_name
    dirs = [here, Path.cwd(), Path.home() / "Downloads", Path.home() / "Загрузки"] + [Path(s) for s in a.search]
    dirs = [d for i, d in enumerate(dirs) if d.is_dir() and d not in dirs[:i]]
    say(f"VASYA GNS LAB {man['version']} — подготовка установки", f"VASYA GNS LAB {man['version']} — preparing the installation")
    if a.docker_only:
        return docker_pack(a, dirs, here)
    if bundle_ok(final) and not a.verify_only:
        say(f"Уже распаковано: {final}", f"Already unpacked: {final}")
    else:
        for tool, pkg in (("zstd", "zstd"), ("tar", "tar")):
            if not shutil.which(tool):
                say(f"Не найдена программа «{tool}». Установите её командой:  sudo apt install {pkg}   и запустите этот файл снова.",
                    f"Program '{tool}' not found. Install it with:  sudo apt install {pkg}   and run this file again.")
                return 4
        kind, path = locate(name, dirs)
        if kind != "whole":
            kind = "parts"
            try:
                find_parts(man, dirs)
            except PartsError:
                got = unpack_drive_zips(dirs, name, here)
                if got:
                    say(f"Достал {len(got)} частей из ZIP-архивов Google Drive", f"Took {len(got)} parts out of Google Drive ZIP downloads")
        try:
            if kind == "whole":
                src = path
                say(f"Найден целый архив: {path}", f"Found the complete archive: {path}")
            else:
                src = find_parts(man, dirs)
                say(f"Найдены все {len(src)} частей. Проверяю контрольные суммы…", f"Found all {len(src)} parts. Checking checksums…")
                verify_parts(man, src, lambda i, n, p, s: say(f"  [{i}/{n}] {p} — {'ok' if s != 'BAD' else 'ПОВРЕЖДЕНА'}{' (проверена ранее)' if s == 'cached' else ''}",
                                                              f"  [{i}/{n}] {p} — {s}"))
            if a.verify_only:
                say("Проверка пройдена.", "Verification passed.")
                return docker_pack(a, dirs, here)
            need = int(man.get("extracted_bytes", man["size"] * 3)) + (1 << 30)
            probe = Path(dest)
            while not probe.exists() and probe.parent != probe:
                probe = probe.parent          # --dest may not exist yet
            free = shutil.disk_usage(probe).free
            if free < need:
                say(f"Мало места в {dest}: свободно {human(free)}, нужно {human(need)}. Освободите место или укажите --dest другой диск.",
                    f"Not enough space in {dest}: {human(free)} free, {human(need)} needed. Free space or pass --dest on another disk.")
                return 5
            say(f"Распаковываю в {final} …", f"Unpacking into {final} …")
            Path(dest).mkdir(parents=True, exist_ok=True)
            extract(kind, src, man, dest, top_name)
        except PartsError as e:
            if e.code == "PARTS_MISSING":
                say("Не хватает частей загрузки:\n  " + "\n  ".join(e.detail["missing"]) +
                    "\nСкачайте их из той же папки Google Drive в эту папку и запустите файл снова — уже проверенные части повторно не проверяются.",
                    "Some download parts are missing:\n  " + "\n  ".join(e.detail["missing"]) +
                    "\nDownload them from the same Google Drive folder into this folder and run again — parts already checked are not re-checked.")
            elif e.code == "PART_CORRUPT":
                say("Повреждены части (скачайте только их заново и запустите снова):\n  " + "\n  ".join(b["name"] for b in e.detail["bad"]),
                    "Damaged parts (re-download only these and run again):\n  " + "\n  ".join(b["name"] for b in e.detail["bad"]))
            else:
                say(f"Ошибка: {e} ({e.code}). Скачайте файлы заново.", f"Error: {e} ({e.code}). Download the files again.")
            return 6
        say(f"Готово: {final}", f"Done: {final}")
    rc = docker_pack(a, dirs, here)
    if rc:
        return rc
    if a.no_install or a.verify_only:
        say(f"Для установки запустите: {final / 'install.sh'}", f"To install run: {final / 'install.sh'}")
        return 0
    os.execv(str(final / "install.sh"), [str(final / "install.sh")])


if __name__ == "__main__":
    sys.exit(main())
