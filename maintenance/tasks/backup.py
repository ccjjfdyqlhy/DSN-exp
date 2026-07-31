# maintenance/tasks/backup.py
# 系统备份任务 — 备份关键文件到项目外的安全位置 (~/.dsn_backups/)

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime
from pathlib import Path

from .base import MaintenanceTask, TaskProgress

logger = logging.getLogger("maintenance.tasks.backup")

BACKUP_ROOT = Path.home() / ".dsn_backups"
PROJECT_ROOT = Path(__file__).parent.parent.parent

BACKUP_PATHS = {
    "env": [".env"],
    "db": ["DSN_usrdata.db", "chats.db"],
    "character_cards": ["character_cards/"],
    "notebook": ["notebook/"],
    "tts_profiles": ["TTS_profiles/"],
    "opencode": [".opencode/"],
    "config": ["config.py"],
}


class BackupTask(MaintenanceTask):
    """备份关键文件到 ~/.dsn_backups/"""

    name = "系统备份"
    priority = 5  # 最先执行
    requires_db = False
    requires_llm = False

    def __init__(self, backup_root: str = ""):
        super().__init__()
        self._backup_root = Path(backup_root) if backup_root else BACKUP_ROOT

    def run(self, reporter) -> dict:
        self._backup_root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_dir = self._backup_root / f"backup_{ts}"
        target_dir.mkdir(parents=True, exist_ok=True)

        stats = {"copied": [], "skipped": [], "compressed": None}

        # 1. 复制 env 和 config
        reporter(TaskProgress(current=1, total=6, message="备份 .env 和 config.py..."))
        for key in ("env", "config"):
            for rel in BACKUP_PATHS[key]:
                src = PROJECT_ROOT / rel
                if src.exists():
                    shutil.copy2(src, target_dir / src.name)
                    stats["copied"].append(rel)

        # 2. 备份数据库（使用 SQLite 在线备份 API，保证一致性快照）
        reporter(TaskProgress(current=2, total=6, message="备份数据库..."))
        db_paths = list(BACKUP_PATHS["db"])
        try:
            from config import Config as _Config
            configured = getattr(_Config, "DATABASE_PATH", None)
            if configured and configured not in db_paths:
                db_paths.append(configured)
        except Exception:
            pass
        for rel in db_paths:
            src = PROJECT_ROOT / rel
            if not src.exists():
                stats["skipped"].append(rel)
                continue
            if _backup_sqlite(src, target_dir / src.name):
                stats["copied"].append(rel)
            else:
                stats["skipped"].append(rel)

        # 3. 复制 character_cards
        reporter(TaskProgress(current=3, total=6, message="备份角色卡..."))
        cc_src = PROJECT_ROOT / "character_cards"
        cc_dst = target_dir / "character_cards"
        if cc_src.exists():
            _copy_tree(cc_src, cc_dst)
            count = len(list(cc_dst.rglob("*")))
            stats["copied"].append(f"character_cards/ ({count} files)")

        # 4. 复制 notebook
        reporter(TaskProgress(current=4, total=6, message="备份观察日记..."))
        nb_src = PROJECT_ROOT / "notebook"
        nb_dst = target_dir / "notebook"
        if nb_src.exists():
            _copy_tree(nb_src, nb_dst)
            stats["copied"].append("notebook/")

        # 5. 复制 TTS_profiles
        reporter(TaskProgress(current=5, total=6, message="备份 TTS 配置..."))
        tts_src = PROJECT_ROOT / "TTS_profiles"
        tts_dst = target_dir / "TTS_profiles"
        if tts_src.exists():
            _copy_tree(tts_src, tts_dst)
            stats["copied"].append("TTS_profiles/")

        # 6. 压缩备份日志目录
        reporter(TaskProgress(current=6, total=6, message="压缩备份日志..."))
        log_src = PROJECT_ROOT / "logs"
        if log_src.exists():
            log_count = 0
            archive_path = target_dir / "logs.tar.gz"
            with tarfile.open(archive_path, "w:gz") as tar:
                for f in sorted(log_src.iterdir()):
                    if f.is_file() and f.suffix in (".log", ".txt"):
                        tar.add(f, arcname=f.relative_to(log_src.parent))
                        log_count += 1
            if log_count > 0:
                stats["compressed"] = f"logs.tar.gz ({log_count} files)"

        # 6. 写备份元信息
        meta = {
            "timestamp": ts,
            "project": str(PROJECT_ROOT),
            "files_copied": len(stats["copied"]),
            "details": stats,
        }
        (target_dir / "backup_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # 7. 清理旧备份（保留最近 10 次）
        self._purge_old(keep=10)

        logger.info(
            "备份完成: %s (copied=%d, compressed=%s)",
            target_dir.name, len(stats["copied"]), stats["compressed"] or "none",
        )

        return {
            "success": True,
            "stats": {
                "dir": str(target_dir),
                "copied": stats["copied"],
                "compressed": stats["compressed"],
            },
        }

    def _purge_old(self, keep: int = 10):
        dirs = sorted(
            [d for d in self._backup_root.iterdir() if d.is_dir() and d.name.startswith("backup_")],
            reverse=True,
        )
        for old in dirs[keep:]:
            shutil.rmtree(old)
            logger.info("清理旧备份: %s", old.name)


def _copy_tree(src: Path, dst: Path):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _backup_sqlite(src: Path, dst: Path) -> bool:
    """用 SQLite 在线备份 API 生成一致性快照，即使数据库正在被写入也安全。"""
    src_conn = None
    try:
        try:
            src_conn = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
        except sqlite3.Error:
            src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
        return True
    except sqlite3.Error:
        logger.exception("SQLite 备份失败: %s", src)
        return False
    finally:
        if src_conn is not None:
            src_conn.close()
