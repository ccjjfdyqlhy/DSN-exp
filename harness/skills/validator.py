# harness/skills/validator.py
# 技能声明 ↔ 实现 一致性校验 —— 在**加载期**把坑挖出来，而不是等用户调工具时炸。
#
# 改造前的问题（2026-11）：
#   skill.yaml 里 tools[].methods[].name 写错、parameters 写错、class 名写错，
#   全都要等到 Agent 真的调用那个工具时才会暴露，而且错误信息是
#   "工具方法不存在: xxx.yyy" —— 用户和写技能的人都不知道是哪里写错了。
#   更糟的是：工具照样被注册进 Agent 的工具列表，模型能看见、能选，
#   然后调用失败 —— 模型会反复重试或编造结果。
#
# 现在：加载期逐条校验，问题分级处理：
#   error   —— 工具级致命问题（类不存在 / 方法不存在 / 参数对不上 /
#              依赖能力缺失）。**该工具不注册**，技能其余工具照常可用。
#   warning —— 技能级问题（声明了依赖但没有工具用 needs 声明 / 工具名重复）。
#              只记录，不阻断。
#
# 校验结果挂在 SkillRegistry 上，可通过 REST (/api/skills) 查出来，
# 也写进日志 —— 写技能的人能立刻看到"我哪里写错了"。

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("SkillValidator")

LEVEL_ERROR = "error"
LEVEL_WARNING = "warning"


@dataclass
class ValidationIssue:
    """一条校验问题。"""

    level: str
    code: str
    skill: str
    tool: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "skill": self.skill,
            "tool": self.tool,
            "message": self.message,
        }

    def __str__(self) -> str:
        where = f"{self.skill}.{self.tool}" if self.tool else self.skill
        return f"[{self.level}] {where}: {self.message}"


@dataclass
class ValidationReport:
    """一次校验的汇总。"""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, level: str, code: str, skill: str, message: str,
            tool: str = "") -> ValidationIssue:
        issue = ValidationIssue(level=level, code=code, skill=skill,
                                tool=tool, message=message)
        self.issues.append(issue)
        return issue

    def extend(self, issues: list[ValidationIssue]) -> None:
        self.issues.extend(issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == LEVEL_ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == LEVEL_WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if not self.issues:
            return "无问题"
        return f"{len(self.errors)} 个错误, {len(self.warnings)} 个警告"

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }


class SkillValidator:
    """校验一个技能包（skill.yaml + tools/*.py）是否自洽。"""

    def __init__(self, capabilities: Any = None) -> None:
        # capabilities: CapabilityRegistry 或任何提供 get(name) 的对象
        self._capabilities = capabilities

    # ── 能力 ──

    def _capability_available(self, name: str) -> bool:
        if self._capabilities is None:
            return True
        getter = getattr(self._capabilities, "get", None)
        if getter is None:
            return True
        return getter(name, None) is not None

    # ── 技能级 ──

    def validate_skill(self, skill: Any) -> ValidationReport:
        """技能级校验：依赖声明 vs 工具 needs 声明、重名工具。"""
        report = ValidationReport()
        name = getattr(skill, "name", "?")

        declared = list(getattr(skill, "dependencies", None) or [])
        used: set[str] = set()
        for tool_spec in getattr(skill, "tools", None) or []:
            needs = getattr(tool_spec, "needs", None) or {}
            used.update(needs.keys())

        for dep in declared:
            if not self._capability_available(dep):
                report.add(LEVEL_WARNING, "dependency-missing", name,
                           f"声明依赖 '{dep}'，但应用没有注册这个能力；"
                           f"依赖不会被注入（若工具用 needs 声明了它，该工具会被跳过）")
            elif used and dep not in used:
                # 只有当技能已经在用 needs 机制时，这条警告才有意义 ——
                # 全是老技能（靠应用层的属性名映射表注入）时不报，避免启动噪音。
                report.add(LEVEL_WARNING, "dependency-unused", name,
                           f"声明依赖 '{dep}'，但没有任何工具用 needs 引用它 —— "
                           f"要么在工具类里写 needs = {{\"{dep}\": \"_xxx\"}}，"
                           f"要么删掉这条依赖声明")

        seen: dict[str, int] = {}
        for tool_spec in getattr(skill, "tools", None) or []:
            tname = getattr(tool_spec, "name", "")
            seen[tname] = seen.get(tname, 0) + 1
        for tname, count in seen.items():
            if count > 1:
                report.add(LEVEL_WARNING, "duplicate-tool", name,
                           f"工具名 '{tname}' 重复声明 {count} 次", tool=tname)
        return report

    # ── 工具级 ──

    def validate_tool(self, skill_name: str, tool_spec: Any,
                      cls: Optional[type]) -> list[ValidationIssue]:
        """工具级校验：类是否存在、方法是否存在、参数与签名是否对得上、依赖是否齐。"""
        issues: list[ValidationIssue] = []
        tname = getattr(tool_spec, "name", "")

        if cls is None:
            issues.append(ValidationIssue(
                LEVEL_ERROR, "class-missing", skill_name, tname,
                f"工具类无法加载（module={getattr(tool_spec, 'module', '')!r}, "
                f"class={getattr(tool_spec, 'class_name', '')!r}）"))
            return issues

        # 依赖能力齐不齐
        needs = getattr(cls, "needs", None) or {}
        if isinstance(needs, dict):
            for cap, attr in needs.items():
                if not self._capability_available(cap):
                    issues.append(ValidationIssue(
                        LEVEL_ERROR, "capability-missing", skill_name, tname,
                        f"工具需要能力 '{cap}'（注入到 {attr!r}），"
                        f"但应用没有注册它"))
                elif not isinstance(attr, str) or not attr:
                    issues.append(ValidationIssue(
                        LEVEL_ERROR, "needs-attr-invalid", skill_name, tname,
                        f"needs['{cap}'] 必须是属性名字符串，实际是 {attr!r}"))

        methods = [m for m in (getattr(tool_spec, "methods", None) or [])
                   if isinstance(m, dict)]
        for method in methods:
            issues.extend(self._validate_method(skill_name, tname, cls, method))
        issues.extend(self._validate_wire_name(skill_name, tname))
        return issues

    def _validate_wire_name(self, skill_name: str, tname: str) -> list[ValidationIssue]:
        """检查工具名能不能被模型回调时还原。

        内部工具名是 "{技能}.{工具}"，发给模型前点号会被编码成双下划线
        （harness/tools/base.py: to_wire_name），模型回调时再还原
        （from_wire_name）。**如果技能名或工具名里有非 ASCII 字符**，
        编码后无法还原成原名 —— 模型调得动，但 AgentLoop 找不到这个工具，
        于是每次调用都报"工具不存在"，而且没有任何提示。
        这是插件作者最容易踩的一个坑，所以放到加载期拦。
        """
        issues: list[ValidationIssue] = []
        from harness.tools.base import from_wire_name, to_wire_name

        key = f"{skill_name}.{tname}"
        wire = to_wire_name(key)
        restored = from_wire_name(wire, {key})
        if restored != key:
            issues.append(ValidationIssue(
                LEVEL_ERROR, "wire-name-unrecoverable", skill_name, tname,
                f"工具名 '{key}' 编码成 wire 名 '{wire}' 后无法还原 —— "
                f"模型调用时会找不到这个工具。技能名/工具名只能用 "
                f"字母、数字、下划线和短横线"))
        elif len(wire) > 64:
            issues.append(ValidationIssue(
                LEVEL_WARNING, "wire-name-too-long", skill_name, tname,
                f"wire 名 '{wire}' 有 {len(wire)} 个字符，超过部分 provider "
                f"对 function 名 64 字符的上限"))
        return issues

    def _validate_method(self, skill_name: str, tname: str, cls: type,
                         method: dict) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        mname = method.get("name", "")
        if not mname:
            issues.append(ValidationIssue(
                LEVEL_ERROR, "method-name-missing", skill_name, tname,
                "methods 条目缺少 name"))
            return issues

        func = getattr(cls, mname, None)
        if func is None:
            issues.append(ValidationIssue(
                LEVEL_ERROR, "method-missing", skill_name, tname,
                f"类 {cls.__name__} 上没有方法 '{mname}' —— "
                f"skill.yaml 声明的工具方法在实现里不存在"))
            return issues
        if not callable(func):
            issues.append(ValidationIssue(
                LEVEL_ERROR, "method-not-callable", skill_name, tname,
                f"'{mname}' 不是可调用对象"))
            return issues

        params = method.get("parameters") or {}
        if not isinstance(params, dict):
            issues.append(ValidationIssue(
                LEVEL_ERROR, "parameters-invalid", skill_name, tname,
                f"方法 '{mname}' 的 parameters 不是字典"))
            return issues

        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            return issues

        real = {name: p for name, p in sig.parameters.items()
                if name not in ("self", "cls")}
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD
                         for p in real.values())
        has_var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL
                          for p in real.values())

        # 声明的参数，实现必须能接
        for pname in params:
            if pname in real:
                continue
            if has_var_kw:
                continue
            issues.append(ValidationIssue(
                LEVEL_ERROR, "param-unknown", skill_name, tname,
                f"方法 '{mname}' 声明了参数 '{pname}'，但实现里没有这个参数"))

        # 实现的必填参数，schema 必须声明，否则模型永远传不进来
        if not has_var_pos:
            for pname, p in real.items():
                if p.default is not inspect.Parameter.empty:
                    continue
                if p.kind in (inspect.Parameter.VAR_POSITIONAL,
                              inspect.Parameter.VAR_KEYWORD):
                    continue
                if pname not in params:
                    issues.append(ValidationIssue(
                        LEVEL_ERROR, "param-required-missing", skill_name, tname,
                        f"方法 '{mname}' 的参数 '{pname}' 是必填的，"
                        f"但 skill.yaml 的 parameters 里没有声明 —— "
                        f"Agent 无法传值，调用必然失败"))

        # schema 说必填，实现却有默认值 —— 不致命，但容易误解
        for pname, pdef in params.items():
            if not isinstance(pdef, dict):
                continue
            if not pdef.get("required"):
                continue
            p = real.get(pname)
            if p is not None and p.default is not inspect.Parameter.empty:
                issues.append(ValidationIssue(
                    LEVEL_WARNING, "param-required-but-default", skill_name, tname,
                    f"方法 '{mname}' 的参数 '{pname}' 在 schema 里标了 required，"
                    f"但实现里有默认值"))
        return issues
