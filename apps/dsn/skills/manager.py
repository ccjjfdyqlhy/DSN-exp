# skills/manager.py
# 技能生命周期管理器 — 扫描/启用/禁用/卸载/安装

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .loader import SkillLoader, Skill
from .registry import SkillRegistry

logger = logging.getLogger("SkillManager")


class SkillManager:
    """
    技能生命周期管理器。

    职责:
    - 扫描技能目录并加载所有技能
    - 启用/禁用/卸载技能
    - 安装新技能
    - 与 SkillRegistry 交互（注册/注销工具和提示词）
    """

    def __init__(self, skill_dirs: list[str], registry: SkillRegistry):
        self._skill_dirs = [Path(d) for d in skill_dirs]
        self.registry = registry
        self.loader = SkillLoader()
        self._skills: dict[str, Skill] = {}

    # ---- 生命周期 ----

    def scan_and_load(self) -> int:
        count = 0
        for skill_dir in self._skill_dirs:
            if not skill_dir.exists():
                logger.debug("技能目录不存在: %s", skill_dir)
                continue

            # 先检查 skill_dir 根部是否有 skill.yaml（如 skills/system/）
            root_yaml = skill_dir / "skill.yaml"
            if root_yaml.exists():
                try:
                    skill = self.loader.load(str(skill_dir))
                    if skill:
                        self._skills[skill.name] = skill
                        if skill.enabled and skill.status == "active":
                            self.registry.register_skill(skill)
                            count += 1
                except Exception as e:
                    logger.error("加载技能失败 %s: %s", skill_dir, e)
                continue  # 根部 skill.yaml 是独立技能，不继续遍历子目录

            # 没有根部 skill.yaml → 遍历子目录（如 skills/builtin/ 下每个子目录一个技能）
            for sub_dir in skill_dir.iterdir():
                if not sub_dir.is_dir() or sub_dir.name.startswith("_"):
                    continue
                skill_yaml = sub_dir / "skill.yaml"
                if skill_yaml.exists():
                    try:
                        skill = self.loader.load(str(sub_dir))
                        if skill:
                            self._skills[skill.name] = skill
                            if skill.enabled and skill.status == "active":
                                self.registry.register_skill(skill)
                                count += 1
                    except Exception as e:
                        logger.error("加载技能失败 %s: %s", sub_dir, e)
        logger.info("加载了 %d 个技能", count)
        return count

    def enable(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.enabled = True
        self.registry.register_skill(skill)
        logger.info("启用技能: %s", name)
        return True

    def disable(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.enabled = False
        self.registry.unregister_skill(name)
        logger.info("禁用技能: %s", name)
        return True

    def unload(self, name: str) -> bool:
        skill = self._skills.pop(name, None)
        if not skill:
            return False
        self.registry.unregister_skill(name)
        logger.info("卸载技能: %s", name)
        return True

    def install(self, skill_dir: str) -> bool:
        try:
            skill = self.loader.load(skill_dir)
            if skill:
                self._skills[skill.name] = skill
                if skill.enabled and skill.status == "active":
                    self.registry.register_skill(skill)
                return True
        except Exception as e:
            logger.error("安装技能失败: %s", e)
        return False

    # ---- 查询 ----

    def list_skills(self, status: str = None) -> list[dict]:
        result = []
        for skill in self._skills.values():
            if status and skill.status != status:
                continue
            result.append({
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "source": skill.source,
                "enabled": skill.enabled,
                "status": skill.status,
                "tags": skill.tags,
                "has_tools": bool(skill.tools),
                "prompt_count": len(skill.prompts),
            })
        return result

    def get_skill(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def get_all_skill_prompts(self) -> str:
        return self.registry.get_all_skill_prompts()
