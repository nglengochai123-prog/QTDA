"""Sao lưu và phục hồi (NFR-09): hằng ngày ra nơi lưu trữ ngoài máy chủ, giữ tối thiểu 30 bản, phục hồi vào CSDL riêng để kiểm tra.

SQLite dùng API sao lưu trực tuyến (chép nhất quán khi máy chủ vẫn chạy); PostgreSQL dùng pg_dump định dạng nén.
Phục hồi không bao giờ ghi đè CSDL đang chạy: luôn vào một tệp hoặc CSDL đích khác, rồi kiểm tra toàn vẹn ở đó.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings

PREFIX = "lamcoffee-"


def _db():
    return settings.DATABASES["default"]


def is_sqlite():
    return _db()["ENGINE"].endswith("sqlite3")


def _pg_tool(name):
    folder = settings.LAM_PG_BIN
    return str(Path(folder) / name) if folder else name


def _pg_env(db):
    return {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}


def _pg_args(db):
    return ["-h", db.get("HOST") or "localhost", "-p", str(db.get("PORT") or 5432), "-U", db["USER"]]


def _run(cmd, env):
    """Chạy công cụ PostgreSQL; khi lỗi, đưa nguyên thông báo của công cụ vào lỗi để người vận hành đọc được."""
    done = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if done.returncode:
        raise RuntimeError(f"{Path(cmd[0]).name}: {(done.stderr or done.stdout).strip()}")
    return done


def sqlite_integrity(path):
    con = sqlite3.connect(str(path))
    try:
        return con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()


def backups(folder=None):
    folder = Path(folder or settings.LAM_BACKUP_DIR)
    if not folder.exists():
        return []
    return sorted((p for p in folder.iterdir() if p.name.startswith(PREFIX) and p.suffix in (".sqlite3", ".dump")),
                  key=lambda p: p.name)


def make_backup(folder=None, keep=None, now=None):
    """Tạo một bản sao lưu, kèm thư mục ảnh chứng từ nếu có; xóa bản cũ vượt số bản giữ lại. Trả (tệp, bản đã xóa)."""
    folder = Path(folder or settings.LAM_BACKUP_DIR)
    keep = keep or settings.LAM_BACKUP_KEEP
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    db = _db()
    if is_sqlite():
        target = folder / f"{PREFIX}{stamp}.sqlite3"
        # Kết nối đọc riêng: chép trạng thái đã ghi xong, không vướng giao dịch đang mở của tiến trình này.
        src, dest = sqlite3.connect(str(db["NAME"]), timeout=60), sqlite3.connect(target)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        result = sqlite_integrity(target)
        if result != "ok":
            raise RuntimeError(f"Bản sao lưu lỗi toàn vẹn: {result}")
    else:
        target = folder / f"{PREFIX}{stamp}.dump"
        _run([_pg_tool("pg_dump"), *_pg_args(db), "-Fc", "-f", str(target), db["NAME"]], _pg_env(db))
    media = Path(settings.MEDIA_ROOT)
    if media.exists() and any(media.rglob("*")):
        with zipfile.ZipFile(folder / f"{PREFIX}{stamp}-media.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for f in media.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(media))
    removed = []
    for old in backups(folder)[:-keep] if keep > 0 else []:
        old.unlink()
        media_zip = old.with_name(old.stem + "-media.zip")
        if media_zip.exists():
            media_zip.unlink()
        removed.append(old.name)
    return target, removed


def restore(source, target, overwrite=False):
    """Phục hồi `source` vào `target` (đường dẫn tệp SQLite hoặc tên CSDL PostgreSQL) khác CSDL đang chạy."""
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Không thấy bản sao lưu {source}")
    db = _db()
    if source.suffix == ".sqlite3":
        target = Path(target).resolve()
        if target == Path(db["NAME"]).resolve():
            raise ValueError("Không phục hồi đè lên CSDL đang chạy. Chọn tệp đích khác.")
        if target.exists() and not overwrite:
            raise ValueError(f"Tệp đích {target} đã có. Chọn tên khác hoặc thêm --ghi-de nếu chắc chắn đó là bản thử.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        result = sqlite_integrity(target)
        if result != "ok":
            raise RuntimeError(f"CSDL phục hồi lỗi toàn vẹn: {result}")
        return {"DB_ENGINE": "sqlite", "SQLITE_NAME": str(target)}
    if source.suffix == ".dump":
        if target == db["NAME"]:
            raise ValueError("Không phục hồi đè lên CSDL đang chạy. Chọn tên CSDL đích khác.")
        args, env = _pg_args(db), _pg_env(db)
        if overwrite:
            _run([_pg_tool("dropdb"), *args, "--if-exists", target], env)
        _run([_pg_tool("createdb"), *args, "-O", db["USER"], target], env)
        _run([_pg_tool("pg_restore"), *args, "--no-owner", "-d", target, str(source)], env)
        return {"DB_ENGINE": "postgresql", "DB_NAME": target}
    raise ValueError("Chỉ nhận tệp .sqlite3 hoặc .dump do lệnh sao_luu tạo.")


def verify(env_overrides, migrate=False):
    """Chạy kiểm tra trên CSDL đã phục hồi trong một tiến trình riêng: còn thiếu bước cập nhật cấu trúc và đối chiếu toàn vẹn."""
    env = {**os.environ, **env_overrides}
    env.pop("LAM_ENV_FILE", None)
    manage = str(Path(settings.BASE_DIR) / "manage.py")
    checks = []
    steps = ([["migrate", "--noinput"]] if migrate else []) + [["migrate", "--check"], ["kiem_tra_toan_ven"]]
    for args in steps:
        run = subprocess.run([sys.executable, manage, *args], env=env, capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        output = (run.stdout + run.stderr).strip()
        if args == ["migrate", "--check"] and run.returncode:
            pending = subprocess.run([sys.executable, manage, "showmigrations", "--plan"], env=env, capture_output=True,
                                     text=True, encoding="utf-8", errors="replace").stdout
            missing = [line.strip()[3:].strip() for line in pending.splitlines() if line.strip().startswith("[ ]")]
            output = ("Bản sao lưu có cấu trúc cũ hơn mã nguồn, còn thiếu: " + ", ".join(missing)
                      + ". Chạy lại với --cap-nhat-cau-truc để cập nhật bản phục hồi.")
        checks.append((" ".join(args), run.returncode, output))
    return checks
