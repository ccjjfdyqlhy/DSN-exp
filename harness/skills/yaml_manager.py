# harness/skills/yaml_manager.py
# 技能生命周期管理器 —— 扫描/启用/禁用/卸载/安装（配合 yaml_loader 的声明式技能）。
#
# 下沉说明（2026-10）：见 harness/skills/yaml_loader.py 的同名说明 ——
# 原先住在 apps/dsn/skills/manager.py，dsn_study 用符号链接共用。
#
# 2026-11 增强（"免踩坑"）：
#   1. 加载期做**一致性校验**（类/方法/参数/依赖），问题分级记录并可查询；
#   2. 支持**运行时安装/卸载/重载** —— 装完技能不必重启应用；
#   3. 支持**运行时追加技能目录**（add_skill_dir）—— 插件目录可以后挂；
#   4. skill.env 自动加载并挂到 Skill.env。

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Protocol

from .env_loader import load_skill_envs
from .yaml_loader import SkillLoader, Skill

logger = logging.getLogger("SkillManager")


class SkillRegistryPort(Protocol):
    """技能注册表契约 —— SkillManager 只依赖这几个方法。

    下沉说明（2026-10）：此前这里 `from .registry import SkillRegistry` 是硬导入，
    但 apps/dsn 与 apps/dsn_study **各自实现了** SkillRegistry（API 基本一致，
    study 侧多两个方法）。硬导入会让 harness 无法同时服务两个应用。
    现改为结构化协议：只要注册表提供这些方法即可接入。
    """

    def register_skill(self, skill: Skill, deps: Optional[dict] = None): ...

    def unregister_skill(self, name: str) -> None: ...

    def list_skills(self, status: Optional[str] = None) -> list: ...

    def get_all_skill_prompts(self) -> str: ...


class SkillManager:
    """
    技能生命周期管理器。

    职责:
    - 扫描技能目录并加载所有技能
    - 启用/禁用/卸载技能
    - 安装新技能（运行时，无需重启）
    - 与 SkillRegistry 交互（注册/注销工具和提示词）
    """

    def __init__(self, skill_dirs: list[str], registry: SkillRegistryPort):
        self._skill_dirs = [Path(d) for d in skill_dirs]
        self.registry = registry
        self.loader = SkillLoader()
        self._skills: dict[str, Skill] = {}
        self._skill_envs: dict[str, dict] = {}
        self._issues: list[dict] = []
        # 旧式（按实例属性名）的依赖表，由应用层提供：
        #   {技能名: {属性名: 实例}}
        # 重新注册技能会换一批新的工具实例，旧式注入必须跟着补一遍，
        # 否则 enable/reload 之后老技能就"没依赖"了。
        self._legacy_deps: dict[str, dict] = {}

    # ---- 依赖 ----

    def set_legacy_deps(self, deps_by_skill: dict[str, dict]) -> None:
        """登记旧式依赖表（{技能名: {属性名: 实例}}）。

        老技能（工具类没写 needs）靠它注入。新技能请用工具类的 needs +
        应用的 register_capabilities()，不需要这张表。
        """
        self._legacy_deps = {k: dict(v) for k, v in (deps_by_skill or {}).items()}

    def _apply_legacy_deps(self, skill: Skill) -> None:
        """给刚注册的技能补一次旧式依赖注入。"""
        deps = self._legacy_deps.get(skill.name)
        if not deps:
            return
        try:
            if not self.registry.inject_dependencies(skill.name, **deps):
                logger.warning("技能 %s 依赖注入未命中任何工具属性", skill.name)
        except Exception as exc:
            logger.warning("技能 %s 依赖注入失败: %s", skill.name, exc)

    # ---- 生命周期 ----

    def scan_and_load(self) -> int:
        """扫描所有技能目录并加载。返回成功注册的技能数。"""
        count = 0
        # 先把 skill.env 读进环境（技能自己的私有配置）
        try:
            self._skill_envs = load_skill_envs(
                [str(d) for d in self._skill_dirs], apply_environ=True)
        except Exception as exc:
            logger.warning("加载 skill.env 失败（已跳过）: %s", exc)

        for skill_dir in self._skill_dirs:
            count += self._scan_dir(skill_dir)
        logger.info("加载了 %d 个技能", count)
        return count

    def _scan_dir(self, skill_dir: Path) -> int:
        """扫描一个技能目录，返回加载成功的技能数。"""
        if not skill_dir.exists():
            logger.debug("技能目录不存在: %s", skill_dir)
            return 0

        # 先检查 skill_dir 根部是否有 skill.yaml（如 skills/system/）
        root_yaml = skill_dir / "skill.yaml"
        if root_yaml.exists():
            return 1 if self._load_skill_dir(skill_dir) else 0

        # 没有根部 skill.yaml → 遍历子目录（如 skills/builtin/ 下每个子目录一个技能）
        count = 0
        for sub_dir in sorted(skill_dir.iterdir()):
            if not sub_dir.is_dir() or sub_dir.name.startswith("_"):
                continue
            if (sub_dir / "skill.yaml").exists():
                if self._load_skill_dir(sub_dir):
                    count += 1
        return count

    def _load_skill_dir(self, skill_dir: Path) -> bool:
        """加载单个技能目录。失败返回 False（不影响其它技能）。"""
        try:
            skill = self.loader.load(str(skill_dir))
        except Exception as e:
            logger.error("加载技能失败 %s: %s", skill_dir, e)
            self._issues.append({"skill": skill_dir.name, "level": "error",
                                 "message": f"加载技能失败: {e}"})
            return False
        if not skill:
            return False

        # 挂上该技能的私有配置（skill.env）
        skill.env = dict(self._skill_envs.get(skill_dir.name, {}))

        self._skills[skill.name] = skill
        if skill.enabled and skill.status == "active":
            try:
                report = self.registry.register_skill(skill)
            except Exception as e:
                logger.error("注册技能失败 %s: %s", skill.name, e)
                self._issues.append({"skill": skill.name, "level": "error",
                                     "message": f"注册技能失败: {e}"})
                return False
            issues = getattr(report, "issues", None)
            if issues:
                for issue in issues:
                    self._issues.append(issue.to_dict()
                                        if hasattr(issue, "to_dict")
                                        else dict(issue))
            self._apply_legacy_deps(skill)
            return True
        logger.info("技能 %s 已加载但未启用 (enabled=%s status=%s)",
                    skill.name, skill.enabled, skill.status)
        return True

    def enable(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.enabled = True
        self.registry.register_skill(skill)
        self._apply_legacy_deps(skill)
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
        """运行时安装一个技能（从目录）。不需要重启应用。"""
        path = Path(skill_dir)
        if not (path / "skill.yaml").exists():
            logger.error("不是技能目录（缺 skill.yaml）: %s", path)
            return False
        try:
            skill = self.loader.load(str(path))
        except Exception as e:
            logger.error("安装技能失败 %s: %s", path, e)
            self._issues.append({"skill": path.name, "level": "error",
                                 "message": f"安装技能失败: {e}"})
            return False
        if not skill:
            return False
        self._skills[skill.name] = skill
        if skill.enabled and skill.status == "active":
            self.registry.register_skill(skill)
            self._apply_legacy_deps(skill)
            logger.info("安装技能: %s", skill.name)
            return True
        logger.info("安装技能 %s（未启用）", skill.name)
        return True

    def uninstall(self, name: str) -> bool:
        """运行时卸载一个技能。"""
        return self.unload(name)

    def reload(self, name: str) -> bool:
        """重载技能：先注销再从原目录重新加载。"""
        skill = self._skills.get(name)
        if not skill:
            return False
        skill_dir = skill.skill_dir
        self.unload(name)
        ok = self._load_skill_dir(Path(skill_dir))
        logger.info("重载技能 %s: %s", name, "成功" if ok else "失败")
        return ok

    def add_skill_dir(self, skill_dir: str) -> int:
        """运行时追加一个技能目录（插件目录后挂用）。"""
        path = Path(skill_dir)
        if path in self._skill_dirs:
            return 0
        self._skill_dirs.append(path)
        count = self._scan_dir(path)
        logger.info("追加技能目录 %s，加载 %d 个技能", path, count)
        return count

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

    def diagnostics(self) -> dict:
        """加载期发现的问题（供 REST / 日志使用）。"""
        registry_diag = {}
        getter = getattr(self.registry, "diagnostics", None)
        if callable(getter):
            registry_diag = getter()
        return {
            "skill_dirs": [str(d) for d in self._skill_dirs],
            "loaded": len(self._skills),
            "issues": list(self._issues),
            "registry": registry_diag,
        }
