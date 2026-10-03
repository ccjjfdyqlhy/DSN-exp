# apps/dsn_study/bundles.py
# DSN 学习特化应用（dsn_study）的 AppBundle 拆包定义。
#
# 学习应用不承载语音/陪伴/媒体等场景，bundle 集合收敛为:
#   core           — 数据库、模型客户端、工作区（无路由）
#   study          — 扫题/扫印、学习时间表、异步任务
#   plan           — 计划系统（Goal/Phase/DailyTask）
#   agent_chat     — 对话入口

from __future__ import annotations

from typing import Any, Optional

from harness import AppBundle


class DsnStudyBundle(AppBundle):
    """DSN Study bundle 基类：install 时把声明到的路由解析到 blueprints。"""

    blueprint_names: list[str] = []

    def __init__(self, *, blueprints: Optional[dict[str, Any]] = None):
        super().__init__()
        self._blueprint_map = blueprints or {}

    def install(self, runtime=None) -> None:
        self.blueprints = [
            self._blueprint_map[n]
            for n in self.blueprint_names
            if self._blueprint_map.get(n) is not None
        ]

    def __repr__(self) -> str:
        return f"<DsnStudyBundle {self.name}>"


class CoreBundle(DsnStudyBundle):
    name = "core"
    description = "题库主库、模型客户端、认证垫片、工作区"
    settings_namespaces = ["model", "study"]
    blueprint_names = []


class StudyBundle(DsnStudyBundle):
    name = "study"
    description = "扫题/扫印、学习时间表、异步任务状态"
    settings_namespaces = ["study", "vision"]
    blueprint_names = ["scan", "study_timetable", "async_tasks"]


class PlanBundle(DsnStudyBundle):
    name = "plan"
    description = "计划系统 REST（Goal/Phase/DailyTask）"
    settings_namespaces = []
    blueprint_names = ["plan"]


class AgentChatBundle(DsnStudyBundle):
    name = "agent_chat"
    description = "AI 对话入口（harness AgentLoop）"
    settings_namespaces = []
    blueprint_names = ["chat"]


def make_dsn_study_bundles(blueprints: dict[str, Any]) -> list[DsnStudyBundle]:
    """按装配顺序构造所有 DSN 学习版 bundles。"""
    return [
        CoreBundle(blueprints=blueprints),
        StudyBundle(blueprints=blueprints),
        PlanBundle(blueprints=blueprints),
        AgentChatBundle(blueprints=blueprints),
    ]
