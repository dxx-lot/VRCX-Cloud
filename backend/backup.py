"""F-22 数据库备份/恢复（SQLite 在线 backup API + 完整性校验）"""
import os
import sqlite3
import time


def create_backup(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(backup_dir, f"vrc_watch-{ts}.db")
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    chk = sqlite3.connect(dest)
    row = chk.execute("PRAGMA integrity_check").fetchone()[0]
    chk.close()
    if row != "ok":
        raise RuntimeError(f"备份完整性校验失败: {row}")
    return dest


def restore_backup(db_path, backup_file):
    if not os.path.exists(backup_file):
        raise RuntimeError("备份文件不存在")
    chk = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    row = chk.execute("PRAGMA integrity_check").fetchone()[0]
    chk.close()
    if row != "ok":
        raise RuntimeError("备份文件完整性校验失败，拒绝恢复")
    if os.path.exists(db_path):
        os.replace(db_path, db_path + ".pre-restore")
    src = sqlite3.connect(backup_file)
    dst = sqlite3.connect(db_path)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
