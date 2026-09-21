# apps/dsn_study/bundles.py
# DSN 学习特化应用（dsn_study）的 AppBundle 拆包定义。

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
    description = "认证、数据库、任务管理、工作区、模型客户端"
    settings_namespaces = ["model", "memory", "cache"]
    blueprint_names = ["auth", "update"]


class VoiceBundle(DsnStudyBundle):
    name = "voice"
    description = "ASR / ASR过滤 / TTS / 心跳 / 打卡 + 语音前端"
    settings_namespaces = ["voice"]
    blueprint_names = ["heartbeat", "checkin"]


class CompanionBundle(DsnStudyBundle):
    name = "companion"
    description = "人格 V2/V3、世界模拟、叙事、印象、剧本"
    settings_namespaces = ["companion"]
    blueprint_names = []


class PersonalBundle(DsnStudyBundle):
    name = "personal"
    description = "提醒 / 闹钟 / 待办 / 计划"
    settings_namespaces = ["personal"]
    blueprint_names = ["todo", "reminder", "plan", "alarm"]


class StudyBundle(DsnStudyBundle):
    name = "study"
    description = "题库、考点知识图谱、模考系统与做题/学习时间表"
    settings_namespaces = ["study"]
    blueprint_names = ["scan", "study_timetable"]


class MediaBundle(DsnStudyBundle):
    name = "media"
    description = "网易云音乐"
    settings_namespaces = []
    blueprint_names = ["music"]


class VisionBundle(DsnStudyBundle):
    name = "vision"
    description = "摄像头 / OCR / 文档 / 主动视觉"
    settings_namespaces = ["vision"]
    blueprint_names = ["vision"]


class TrackingBundle(DsnStudyBundle):
    name = "tracking"
    description = "用户行为日记（多模态记录 / 作息与进度建模）"
    settings_namespaces = ["tracking"]
    blueprint_names = []


class AgentApiBundle(DsnStudyBundle):
    name = "agent_api"
    description = "对外 Agent API（本地 AI Agent 接口）"
    settings_namespaces = []
    blueprint_names = ["agent", "async_tasks"]


class MaintenanceBundle(DsnStudyBundle):
    name = "maintenance"
    description = "维护系统（记忆压缩 / 人格蒸馏 / 日志清理）"
    settings_namespaces = []
    blueprint_names = ["maintenance"]


def make_dsn_study_bundles(blueprints: dict[str, Any]) -> list[DsnStudyBundle]:
    """按装配顺序构造所有 DSN 学习版 bundles。"""
    return [
        CoreBundle(blueprints=blueprints),
        CompanionBundle(blueprints=blueprints),
        VoiceBundle(blueprints=blueprints),
        PersonalBundle(blueprints=blueprints),
        StudyBundle(blueprints=blueprints),
        MediaBundle(blueprints=blueprints),
        VisionBundle(blueprints=blueprints),
        TrackingBundle(blueprints=blueprints),
        AgentApiBundle(blueprints=blueprints),
        MaintenanceBundle(blueprints=blueprints),
    ]
