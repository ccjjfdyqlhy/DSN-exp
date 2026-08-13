# apps/dsn/bundles.py
# DSN 应用的 AppBundle 拆包定义。
#
# 每个 bundle 声明它拥有的路由（blueprints）与配置命名空间，以及身份元数据。
# 共享服务（db / engine / task_manager ...）由 boot.py 统一注册进 Runtime，
# 各 bundle 通过 Runtime 解析，不重复注册。
#
# 这层定义了"解耦边界"：语音/人格/提醒等能力彼此独立，
# 各自通过网关挂载路由，最终由 boot 统一装配。

from __future__ import annotations

from typing import Any, Optional

from harness import AppBundle


class DsnBundle(AppBundle):
    """DSN bundle 基类：install 时把声明到的路由解析到 blueprints。"""

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
        return f"<DsnBundle {self.name}>"


class CoreBundle(DsnBundle):
    name = "core"
    description = "认证、数据库、任务管理、工作区、模型客户端"
    settings_namespaces = ["model", "memory", "cache"]
    blueprint_names = ["auth", "update"]


class VoiceBundle(DsnBundle):
    name = "voice"
    description = "ASR / ASR过滤 / TTS / 心跳 / 打卡 + 语音前端"
    settings_namespaces = ["voice"]
    blueprint_names = ["heartbeat", "checkin"]


class CompanionBundle(DsnBundle):
    name = "companion"
    description = "人格 V2/V3、世界模拟、叙事、印象、剧本"
    settings_namespaces = ["companion"]
    blueprint_names = []


class PersonalBundle(DsnBundle):
    name = "personal"
    description = "提醒 / 闹钟 / 待办 / 计划"
    settings_namespaces = ["personal"]
    blueprint_names = ["todo", "reminder", "plan", "alarm"]


class MediaBundle(DsnBundle):
    name = "media"
    description = "网易云音乐"
    settings_namespaces = []
    blueprint_names = ["music"]


class VisionBundle(DsnBundle):
    name = "vision"
    description = "摄像头 / OCR / 文档 / 主动视觉"
    settings_namespaces = ["vision"]
    blueprint_names = ["vision"]


class TrackingBundle(DsnBundle):
    name = "tracking"
    description = "用户行为日记（多模态记录 / 作息与进度建模）"
    settings_namespaces = ["tracking"]
    blueprint_names = []


class AgentApiBundle(DsnBundle):
    name = "agent_api"
    description = "对外 Agent API（本地 AI Agent 接口）"
    settings_namespaces = []
    blueprint_names = ["agent", "async_tasks"]


class MaintenanceBundle(DsnBundle):
    name = "maintenance"
    description = "维护系统（记忆压缩 / 人格蒸馏 / 日志清理）"
    settings_namespaces = []
    blueprint_names = ["maintenance"]


def make_dsn_bundles(blueprints: dict[str, Any]) -> list[DsnBundle]:
    """按装配顺序构造所有 DSN bundles。"""
    return [
        CoreBundle(blueprints=blueprints),
        CompanionBundle(blueprints=blueprints),
        VoiceBundle(blueprints=blueprints),
        PersonalBundle(blueprints=blueprints),
        MediaBundle(blueprints=blueprints),
        VisionBundle(blueprints=blueprints),
        TrackingBundle(blueprints=blueprints),
        AgentApiBundle(blueprints=blueprints),
        MaintenanceBundle(blueprints=blueprints),
    ]
