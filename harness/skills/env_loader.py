# harness/skills/env_loader.py
# load per-skill configuration files (skill.env). shared by every application.
#
# The old behavior: an application config class could scan
# skills/{builtin,custom}/*/skill.env and copy the values onto class attributes,
# but nothing called that path. A skill's own environment variable was therefore
# silently missing, and os.environ.get() always returned None.
#
# This module is the single implementation:
#   * an existing environment variable wins over the file value;
#   * file values are also attached to Skill.env, readable through the injected
#     skill_env capability.
#
# 格式：KEY=VALUE，一行一个；# 开头为注释；值可带引号。

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("SkillEnvLoader")

ENV_FILE_NAME = "skill.env"


def parse_skill_env(text: str) -> dict[str, str]:
    """解析 skill.env 文本 → {键: 值}。非法行跳过并告警。"""
    result: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            logger.warning("skill.env 第 %d 行格式非法（缺少 '='），已跳过: %r",
                           lineno, raw.strip()[:60])
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            logger.warning("skill.env 第 %d 行键名为空，已跳过", lineno)
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def iter_skill_dirs(skill_dirs: list[str]):
    """遍历技能目录，产出每个技能包目录。

    与 SkillManager.scan_and_load 的遍历规则保持一致：
      * 目录根部有 skill.yaml → 该目录本身就是一个技能；
      * 否则其子目录各是一个技能。
    """
    for base in skill_dirs or ():
        base_path = Path(base)
        if not base_path.exists():
            continue
        if (base_path / "skill.yaml").exists():
            yield base_path
            continue
        for sub in sorted(base_path.iterdir()):
            if not sub.is_dir() or sub.name.startswith("_"):
                continue
            if (sub / "skill.yaml").exists():
                yield sub


def load_skill_envs(skill_dirs: list[str], *,
                     apply_environ: bool = True) -> dict[str, dict[str, str]]:
    """加载所有技能目录下的 skill.env。

    返回 {技能名: {键: 值}}。apply_environ=True 时把值写进 os.environ
    （**不覆盖**已存在的环境变量）。
    """
    result: dict[str, dict[str, str]] = {}
    for skill_dir in iter_skill_dirs(skill_dirs):
        env_file = skill_dir / ENV_FILE_NAME
        if not env_file.exists():
            continue
        try:
            values = parse_skill_env(env_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取 %s 失败: %s", env_file, exc)
            continue
        if not values:
            continue
        result[skill_dir.name] = values
        if apply_environ:
            for key, value in values.items():
                # an existing environment variable wins
                if key not in os.environ:
                    os.environ[key] = value
        logger.info("skill.env: %s (%d 项)", skill_dir.name, len(values))
    return result
