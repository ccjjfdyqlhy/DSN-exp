#!/usr/bin/env python3
"""AICF 全局引导（Textual TUI）。

这个脚本不是某个应用的引导，而是**仓库级**的入口：先问清楚你想用这个仓库
做什么，再把需要的能力（远程模型 / 本地 llama.cpp / TTS / 记忆 / 浏览器
自动化 …）映射成一组可执行动作，最后自动完成：

  * 写入 / 合并根目录 ``.env``（保留原有注释与未涉及的行）
  * 安装缺少的 Python 依赖
  * ``git clone`` 需要的第三方仓库（幂等：已存在就跳过）
  * 从 Hugging Face 下载 GGUF 模型（支持断点续传、已有文件跳过）
  * 生成 ``apps/dsn/model_profiles/*.yaml``
  * 可选编译 llama.cpp

设计原则：

  * **先确认再执行**：所有仓库克隆、模型下载、pip 安装都会在「执行计划」页
    列出来，用户确认后才开始。
  * **不覆盖用户工作**：已存在的仓库不 pull、已存在的文件不覆盖；``.env``
    只改本次涉及的键。
  * **不把密钥写进状态文件**：``.onboarding_state.json`` 只记选择与路径，
    API key 只落到已被 git 忽略的 ``.env``。
  * **可重复运行**：所有动作都是幂等的，中断后重新运行即可继续。

用法::

    python3 onboarding.py            # 打开 TUI
    python3 onboarding.py --list     # 列出目标 / 应用 / 能力
    python3 onboarding.py --check    # 非交互检查环境与已有资源
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / ".onboarding_state.json"
THIRD_PARTY_DIR = ROOT / "third_party"
MODELS_DIR = ROOT / "models"

DEFAULT_LLAMA_DIR = THIRD_PARTY_DIR / "llama.cpp"
DEFAULT_LLAMA_BIN = DEFAULT_LLAMA_DIR / "build" / "bin" / "llama-server"
DEFAULT_TTS_URL = "http://127.0.0.1:9880"
DEFAULT_LMSTUDIO_URL = "http://localhost:4501"


# ══════════════════════════════════════════════════════════════════════
# 能力目录
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RepoSpec:
    key: str
    label: str
    url: str
    target: str
    purpose: str
    size_hint: str = ""

    @property
    def dest(self) -> Path:
        return _expand_path(self.target)


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    label: str
    url: str
    target: str
    size_mb: float
    purpose: str
    needs_token: bool = False

    @property
    def dest(self) -> Path:
        return _expand_path(self.target)


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    question: str
    description: str
    apps: tuple[str, ...] = ()
    repos: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    notes: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppSpec:
    key: str
    label: str
    description: str
    entry: str
    onboarding_hint: str
    launch_hint: str


@dataclass(frozen=True)
class GoalSpec:
    key: str
    label: str
    question: str
    description: str
    apps: tuple[str, ...] = ()
    features: tuple[str, ...] = ()


REPOS: dict[str, RepoSpec] = {
    "llama_cpp": RepoSpec(
        key="llama_cpp",
        label="llama.cpp",
        url="https://github.com/ggml-org/llama.cpp.git",
        target=str(DEFAULT_LLAMA_DIR),
        purpose="本地 GGUF 推理引擎（编译后得到 llama-server）",
        size_hint="约 100 MB 源码",
    ),
    "gpt_sovits": RepoSpec(
        key="gpt_sovits",
        label="GPT-SoVITS",
        url="https://github.com/RVC-Boss/GPT-SoVITS.git",
        target=str(THIRD_PARTY_DIR / "GPT-SoVITS"),
        purpose="TTS 语音合成服务（需另行下载预训练权重）",
        size_hint="约 200 MB 源码",
    ),
}

RESOURCES: dict[str, ResourceSpec] = {
    "qwen25_3b": ResourceSpec(
        key="qwen25_3b",
        label="Qwen2.5-3B-Instruct Q4_K_M（推荐，约 2 GB）",
        url=(
            "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/"
            "resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf?download=true"
        ),
        target=str(MODELS_DIR / "Qwen2.5-3B-Instruct-Q4_K_M.gguf"),
        size_mb=2000,
        purpose="轻量中文/英文对话模型，适合 8 GB 显存或纯 CPU",
    ),
    "qwen25_7b": ResourceSpec(
        key="qwen25_7b",
        label="Qwen2.5-7B-Instruct Q4_K_M（约 4.7 GB）",
        url=(
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/"
            "resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf?download=true"
        ),
        target=str(MODELS_DIR / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"),
        size_mb=4700,
        purpose="更强的中文对话能力，建议 12 GB 以上显存",
    ),
    "gemma3_4b": ResourceSpec(
        key="gemma3_4b",
        label="Gemma-3-4B-IT Q4_K_M（约 2.5 GB，需先同意许可）",
        url=(
            "https://huggingface.co/bartowski/google_gemma-3-4b-it-GGUF/"
            "resolve/main/google_gemma-3-4b-it-Q4_K_M.gguf?download=true"
        ),
        target=str(MODELS_DIR / "google_gemma-3-4b-it-Q4_K_M.gguf"),
        size_mb=2500,
        purpose="多模态 Gemma 3 4B；Hugging Face 下载前需接受模型许可",
        needs_token=True,
    ),
}

FEATURES: dict[str, FeatureSpec] = {
    "remote_api": FeatureSpec(
        key="remote_api",
        label="远程 API 模型",
        question="是否接入远程 OpenAI 兼容 API？",
        description="DeepSeek / OpenAI / Qwen / OneAPI 等，最省事，不需要下载模型。",
        apps=("dsn", "dsn_ui", "dsn_study", "coding_agent", "densechat", "emotion_exp"),
        notes=("API Key 只会写入已被 git 忽略的根目录 .env。",),
    ),
    "lmstudio": FeatureSpec(
        key="lmstudio",
        label="LM Studio 本地服务",
        question="是否连接已经运行的 LM Studio？",
        description="复用 LM Studio 的模型库与 OpenAI 兼容端点（默认 :4501）。",
        apps=("dsn", "dsn_ui", "dsn_study"),
    ),
    "local_llamacpp": FeatureSpec(
        key="local_llamacpp",
        label="本地 llama.cpp 引擎",
        question="是否准备本地 llama.cpp？",
        description="克隆 llama.cpp，可选自动编译，并把 llama-server 路径写进配置。",
        apps=("dsn", "dsn_ui", "dsn_study"),
        repos=("llama_cpp",),
        packages=(),
        notes=("编译需要 cmake 与 C++ 工具链；不编译也可以稍后手动 build。",),
    ),
    "local_model": FeatureSpec(
        key="local_model",
        label="下载本地 GGUF 模型",
        question="是否顺便下载一个可直接跑的 GGUF 模型？",
        description="从 Hugging Face 下载 Qwen / Gemma 权重，并生成 dsn_ui 模型 profile。",
        apps=("dsn", "dsn_ui", "dsn_study"),
        requires=("local_llamacpp",),
        notes=("模型文件较大；下载支持断点续传。",),
    ),
    "tts": FeatureSpec(
        key="tts",
        label="语音合成 TTS",
        question="是否需要语音合成（GPT-SoVITS）？",
        description="克隆 GPT-SoVITS，并配置 TTS 服务地址；预训练权重需另行下载。",
        apps=("dsn", "dsn_ui"),
        repos=("gpt_sovits",),
        env=(("TTS_ENABLED", "true"), ("TTS_BASE_URL", DEFAULT_TTS_URL)),
        notes=("GPT-SoVITS 的预训练权重不随仓库分发，克隆后按其 README 下载。",),
    ),
    "memory": FeatureSpec(
        key="memory",
        label="记忆与话题",
        question="是否启用长期记忆 / 话题系统？",
        description="写入 MEMORY_ENABLED 等开关；向量嵌入可以之后在界面里再开。",
        apps=("dsn", "dsn_ui", "dsn_study"),
        env=(("MEMORY_ENABLED", "true"),),
    ),
    "browser_tools": FeatureSpec(
        key="browser_tools",
        label="浏览器自动化",
        question="是否需要浏览器自动化（browser_use）？",
        description="安装 playwright 并下载 Chromium（约 150 MB）。",
        apps=("dsn", "coding_agent"),
        packages=("playwright>=1.40",),
        commands=((sys.executable, "-m", "playwright", "install", "chromium"),),
        notes=("首次安装 Chromium 需要联网；无头服务器也可用。",),
    ),
    "voice_asr": FeatureSpec(
        key="voice_asr",
        label="语音识别 ASR",
        question="是否需要本地语音识别？",
        description="安装 funasr 与麦克风采集依赖（依赖链较重，含 PyTorch）。",
        apps=("dsn",),
        packages=("funasr>=1.3.9", "pvrecorder>=1.2.7"),
        env=(("ASR_ENABLED", "true"),),
        notes=("funasr 会拉入较大的 PyTorch 依赖，确认磁盘与网络后再选。",),
    ),
    "document_parse": FeatureSpec(
        key="document_parse",
        label="文档解析服务（2md）",
        question="是否需要对接 2md 文档解析服务？",
        description="只写服务地址，不自动安装第三方 2md 服务。",
        apps=("dsn",),
        env=(("TWO_MD_API", "http://localhost:8000"),),
        notes=("2md 是外部服务，请按其文档单独部署。",),
    ),
}

APPS: dict[str, AppSpec] = {
    "dsn_ui": AppSpec(
        key="dsn_ui",
        label="DSN UI 网页控制台",
        description="现代化 Web 控制台（:8888），可管理模型、Provider、TTS 与会话。",
        entry="apps.dsn_ui.entry",
        onboarding_hint="启动后打开 http://127.0.0.1:8888 ，按「配置新实例」完成网页引导。",
        launch_hint="python3 launcher.py --app dsn_ui",
    ),
    "dsn": AppSpec(
        key="dsn",
        label="DSN 语音陪伴",
        description="语音陪伴 Agent（:5000），首次启动会进入应用自己的控制台引导。",
        entry="apps.dsn.entry",
        onboarding_hint="本页可直接进入 apps/dsn/onboarding.py 的控制台引导。",
        launch_hint="python3 launcher.py --app dsn",
    ),
    "dsn_study": AppSpec(
        key="dsn_study",
        label="DSN 学习助手",
        description="题库、模拟考试、知识图谱与学习计划（:5000，与 dsn 冲突）。",
        entry="apps.dsn_study.entry",
        onboarding_hint="需要一个可用的模型后端；启动后按页面提示初始化学习空间。",
        launch_hint="python3 launcher.py --app dsn_study",
    ),
    "coding_agent": AppSpec(
        key="coding_agent",
        label="Coding Agent",
        description="基于 harness 的代码助手示例。",
        entry="apps.coding_agent.entry",
        onboarding_hint="直接运行即可；模型配置来自根目录 .env。",
        launch_hint="python3 launcher.py --app coding_agent",
    ),
    "densechat": AppSpec(
        key="densechat",
        label="DenseChat WebUI",
        description="基于 harness 的代码助手 WebUI（:8080）。",
        entry="apps.densechat.entry",
        onboarding_hint="直接运行即可；模型配置来自根目录 .env。",
        launch_hint="python3 launcher.py --app densechat",
    ),
    "emotion_exp": AppSpec(
        key="emotion_exp",
        label="情绪伴侣 Agent",
        description="基于话题上下文与情绪状态机的伴侣 Agent。",
        entry="apps.emotion_exp.entry",
        onboarding_hint="零配置可启动；配置模型后体验完整。",
        launch_hint="python3 launcher.py --app emotion_exp",
    ),
}

GOALS: dict[str, GoalSpec] = {
    "web_console": GoalSpec(
        key="web_console",
        label="网页控制台 / 模型管理",
        question="我想要一个能管理模型与会话的网页界面",
        description="推荐第一次使用：启动 dsn_ui，接入模型后即可聊天。",
        apps=("dsn_ui",),
        features=("remote_api", "memory"),
    ),
    "voice_companion": GoalSpec(
        key="voice_companion",
        label="语音陪伴（说话/听声音）",
        question="我想要一个能语音对话的陪伴应用",
        description="dsn + 远程模型 + TTS + 记忆；按需再加 ASR。",
        apps=("dsn",),
        features=("remote_api", "tts", "memory"),
    ),
    "local_models": GoalSpec(
        key="local_models",
        label="在本机跑模型（不依赖远程 API）",
        question="我想让模型完全跑在自己的机器上",
        description="克隆/编译 llama.cpp，下载 GGUF，并生成 dsn_ui 模型配置。",
        apps=("dsn_ui", "dsn"),
        features=("local_llamacpp", "local_model", "memory"),
    ),
    "study": GoalSpec(
        key="study",
        label="学习 / 题库 / 模拟考试",
        question="我想用 DSN 的学习特化功能",
        description="dsn_study + 模型后端 + 记忆。",
        apps=("dsn_study",),
        features=("remote_api", "memory"),
    ),
    "coding": GoalSpec(
        key="coding",
        label="代码助手 / 自动化",
        question="我想要代码助手或浏览器自动化",
        description="coding_agent / dsn，可选 playwright。",
        apps=("coding_agent",),
        features=("remote_api",),
    ),
    "documents": GoalSpec(
        key="documents",
        label="文档解析 / 资料整理",
        question="我想处理 PDF / 文档资料",
        description="对接 2md 服务，配合 dsn 的文档技能使用。",
        apps=("dsn",),
        features=("document_parse", "remote_api"),
    ),
    "custom": GoalSpec(
        key="custom",
        label="我自己挑（自定义）",
        question="我还没有明确目标，想自己组合能力",
        description="下一步会列出所有能力，自行勾选。",
        apps=(),
        features=(),
    ),
}

GOAL_ORDER: tuple[str, ...] = tuple(GOALS)
FEATURE_ORDER: tuple[str, ...] = tuple(FEATURES)
APP_ORDER: tuple[str, ...] = tuple(APPS)

#: 一个能力默认服务于哪个应用。FeatureSpec.apps 表示「兼容哪些应用」，
#: 这里只表示「勾选这个能力时默认推荐启动哪个应用」，避免把全部兼容应用
#: 都塞进完成页。
DEFAULT_APP_FOR_FEATURE: dict[str, tuple[str, ...]] = {
    "remote_api": ("dsn_ui",),
    "lmstudio": ("dsn_ui",),
    "local_llamacpp": ("dsn_ui",),
    "local_model": ("dsn_ui",),
    "tts": ("dsn",),
    "memory": ("dsn_ui",),
    "browser_tools": ("dsn",),
    "voice_asr": ("dsn",),
    "document_parse": ("dsn",),
}


# ══════════════════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════════════════


def _expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value))))


def mask_secret(value: str | None) -> str:
    if not value:
        return "(未设置)"
    value = str(value)
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-2:]}"


def load_env(path: Path | None = None) -> dict[str, str]:
    path = Path(path) if path is not None else ENV_PATH
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def update_env(mapping: dict[str, str], path: Path | None = None) -> Path:
    """合并写入 .env，保留注释、空行与未涉及的键。"""
    path = Path(path) if path is not None else ENV_PATH
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    if not lines:
        lines = [
            "# 由 onboarding.py 创建。此文件已被 .gitignore 忽略。",
            "# 修改后重启应用生效。",
            "",
        ]

    seen: set[str] = set()
    pattern = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*)=")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        key = match.group(2)
        if key in mapping:
            lines[index] = f"{key}={mapping[key]}"
            seen.add(key)

    missing = [(key, value) for key, value in mapping.items() if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# ── onboarding.py 自动写入 ──")
        for key, value in missing:
            lines.append(f"{key}={value}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)
    return path


def resolve_features(selected: Iterable[str]) -> list[str]:
    """展开依赖，并按目录顺序返回，保证计划稳定。"""
    wanted = set(selected)
    changed = True
    while changed:
        changed = False
        for key in list(wanted):
            spec = FEATURES.get(key)
            if spec is None:
                wanted.discard(key)
                continue
            for dep in spec.requires:
                if dep not in wanted:
                    wanted.add(dep)
                    changed = True
    return [key for key in FEATURE_ORDER if key in wanted]


def features_for_goals(goals: Iterable[str]) -> list[str]:
    wanted: set[str] = set()
    for key in goals:
        spec = GOALS.get(key)
        if spec:
            wanted.update(spec.features)
    return resolve_features(wanted)


def apps_for_goals(goals: Iterable[str]) -> list[str]:
    wanted: set[str] = set()
    for key in goals:
        spec = GOALS.get(key)
        if spec:
            wanted.update(spec.apps)
    return [key for key in APP_ORDER if key in wanted]


def apps_for_features(features: Iterable[str]) -> list[str]:
    wanted: set[str] = set()
    for key in features:
        wanted.update(DEFAULT_APP_FOR_FEATURE.get(key, ()))
    return [key for key in APP_ORDER if key in wanted]


def resolve_apps(
    goals: Iterable[str],
    features: Iterable[str],
    apps: Iterable[str] | None = None,
) -> list[str]:
    # 用户在「应用」页显式选择的应用优先；否则按需求映射；最后才回退到
    # 能力的默认应用。这样既能自动推荐，也允许手动增删。
    if apps:
        wanted = set(apps)
        return [key for key in APP_ORDER if key in wanted]
    goal_apps = apps_for_goals(goals)
    if goal_apps:
        return goal_apps
    return apps_for_features(features)


def validate_catalog() -> list[str]:
    errors: list[str] = []
    for key, feature in FEATURES.items():
        if key != feature.key:
            errors.append(f"feature key 不一致: {key} != {feature.key}")
        for repo in feature.repos:
            if repo not in REPOS:
                errors.append(f"{key}: 未知 repo {repo}")
        for res in feature.resources:
            if res not in RESOURCES:
                errors.append(f"{key}: 未知 resource {res}")
        for app in feature.apps:
            if app not in APPS:
                errors.append(f"{key}: 未知 app {app}")
        for dep in feature.requires:
            if dep not in FEATURES:
                errors.append(f"{key}: 未知依赖 {dep}")
    for key, goal in GOALS.items():
        if key != goal.key:
            errors.append(f"goal key 不一致: {key} != {goal.key}")
        for app in goal.apps:
            if app not in APPS:
                errors.append(f"{key}: 未知 app {app}")
        for feature in goal.features:
            if feature not in FEATURES:
                errors.append(f"{key}: 未知 feature {feature}")
    for key in FEATURES:
        if key not in DEFAULT_APP_FOR_FEATURE:
            errors.append(f"{key}: 缺少默认应用映射")
        for app in DEFAULT_APP_FOR_FEATURE.get(key, ()):
            if app not in APPS:
                errors.append(f"{key}: 默认应用未知 {app}")
    return errors


# ══════════════════════════════════════════════════════════════════════
# 选择状态与执行计划
# ══════════════════════════════════════════════════════════════════════


@dataclass
class OnboardingState:
    goals: list[str] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    app_key: str = "dsn_ui"

    # 模型接入
    provider: str = "later"  # remote | lmstudio | local | later
    api_base: str = "https://api.deepseek.com/v1"
    api_key: str = ""
    api_model: str = "deepseek-chat"
    lmstudio_url: str = DEFAULT_LMSTUDIO_URL

    # 本地模型
    llama_binary: str = str(DEFAULT_LLAMA_BIN)
    model_resource: str = ""  # RESOURCES 的 key，空表示不下载
    model_path: str = ""
    build_llama: bool = True
    ctx_size: int = 8192
    n_gpu_layers: int = 99

    # 执行选项
    clone_repos: bool = True
    install_packages: bool = True
    download_resources: bool = True

    results: list["ActionResult"] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, Any]:
        data = {
            "goals": list(self.goals),
            "apps": list(self.apps),
            "features": list(self.features),
            "app_key": self.app_key,
            "provider": self.provider,
            "api_base": self.api_base,
            "api_model": self.api_model,
            "lmstudio_url": self.lmstudio_url,
            "llama_binary": self.llama_binary,
            "model_resource": self.model_resource,
            "model_path": self.model_path,
            "build_llama": self.build_llama,
            "ctx_size": self.ctx_size,
            "n_gpu_layers": self.n_gpu_layers,
            "saved_at": int(time.time()),
        }
        # 绝不落盘 api_key
        return data


@dataclass
class PlanItem:
    kind: str  # env | pip | repo | resource | command | profile
    title: str
    detail: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    size_mb: float = 0.0

    @property
    def size_label(self) -> str:
        if not self.size_mb:
            return ""
        if self.size_mb >= 1024:
            return f"{self.size_mb / 1024:.1f} GB"
        return f"{self.size_mb:.0f} MB"


@dataclass
class ActionResult:
    title: str
    status: str  # ok | skip | fail | cancel
    message: str = ""


class PlanCancelled(Exception):
    """用户中止执行。"""


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def save_state(state: OnboardingState, path: Path | None = None) -> Path:
    path = Path(path) if path is not None else STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_state(path: Path | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else STATE_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def provider_env(state: OnboardingState) -> dict[str, str]:
    env: dict[str, str] = {}
    if state.provider == "remote":
        base = (state.api_base or "").strip()
        model = (state.api_model or "").strip()
        key = (state.api_key or "").strip()
        if base:
            env["OPENAI_API_BASE"] = base
        if model:
            env["MAIN_MODEL_NAME"] = model
        if key:
            env["OPENAI_API_KEY"] = key
        env["MAIN_MODEL_TYPE"] = "openai"
    elif state.provider == "lmstudio":
        env["MAIN_MODEL_TYPE"] = "lmstudio"
        env["LMSTUDIO_ENABLED"] = "true"
        env["LMSTUDIO_BASE_URL"] = (state.lmstudio_url or DEFAULT_LMSTUDIO_URL).strip()
    elif state.provider == "local":
        binary = _expand_path(state.llama_binary or DEFAULT_LLAMA_BIN)
        env["LLAMACPP_BIN"] = str(binary)
        env["LLAMA_SERVER_BINARY"] = str(binary)
        env["DSN_UI_MODEL_ROOTS"] = str(MODELS_DIR)
    return env


def _model_path(state: OnboardingState) -> Path | None:
    if state.model_path.strip():
        return _expand_path(state.model_path.strip())
    resource = RESOURCES.get(state.model_resource)
    return resource.dest if resource else None


def build_plan(
    state: OnboardingState,
    *,
    clone_repos: bool | None = None,
    install_packages: bool | None = None,
    download_resources: bool | None = None,
    build_llama: bool | None = None,
) -> list[PlanItem]:
    """把选择翻译成有序、去重的执行计划（纯函数，便于测试）。"""
    do_clone = state.clone_repos if clone_repos is None else clone_repos
    do_pip = state.install_packages if install_packages is None else install_packages
    do_download = (
        state.download_resources if download_resources is None else download_resources
    )
    do_build = state.build_llama if build_llama is None else build_llama

    features = resolve_features(state.features)
    items: list[PlanItem] = []

    env = provider_env(state)
    for feature_key in features:
        env.update(dict(FEATURES[feature_key].env))
    # 本地能力总是把模型目录与 llama-server 路径暴露给应用
    if "local_llamacpp" in features:
        binary = _expand_path(state.llama_binary or DEFAULT_LLAMA_BIN)
        env.setdefault("LLAMACPP_BIN", str(binary))
        env.setdefault("LLAMA_SERVER_BINARY", str(binary))
    if "local_model" in features or "local_llamacpp" in features:
        env.setdefault("DSN_UI_MODEL_ROOTS", str(MODELS_DIR))
    if env:
        items.append(
            PlanItem(
                kind="env",
                title=f"更新 .env（{len(env)} 个键）",
                detail="、".join(_display_env_key(k) for k in env),
                payload={"env": env},
            )
        )
        # dsn_study 只读取自己的 apps/dsn_study/.env；为了让「学习助手」目标
        # 真正拿到模型配置，额外同步一份应用级 .env（同样保留原注释）。
        if "dsn_study" in resolve_apps(state.goals, features, state.apps):
            study_env_path = ROOT / "apps" / "dsn_study" / ".env"
            items.append(
                PlanItem(
                    kind="env",
                    title=f"更新 apps/dsn_study/.env（{len(env)} 个键）",
                    detail="dsn_study 不读取根目录 .env，需要应用级配置",
                    payload={"env": env, "path": str(study_env_path)},
                )
            )

    if do_pip:
        packages: list[str] = []
        for feature_key in features:
            for pkg in FEATURES[feature_key].packages:
                if pkg not in packages:
                    packages.append(pkg)
        if packages:
            items.append(
                PlanItem(
                    kind="pip",
                    title=f"安装 {len(packages)} 个 Python 依赖",
                    detail="、".join(packages),
                    payload={"packages": packages},
                )
            )

    if do_clone:
        seen_repos: set[str] = set()
        for feature_key in features:
            for repo_key in FEATURES[feature_key].repos:
                if repo_key in seen_repos:
                    continue
                seen_repos.add(repo_key)
                repo = REPOS[repo_key]
                exists = repo.dest.exists()
                items.append(
                    PlanItem(
                        kind="repo",
                        title=f"{'已存在，跳过' if exists else '克隆'} {repo.label}",
                        detail=f"{repo.url} → {repo.dest}",
                        payload={"repo": repo_key},
                    )
                )

    if do_download:
        selected_resources: list[str] = []
        if state.model_resource in RESOURCES:
            selected_resources.append(state.model_resource)
        for feature_key in features:
            for res_key in FEATURES[feature_key].resources:
                if res_key not in selected_resources:
                    selected_resources.append(res_key)
        for res_key in selected_resources:
            resource = RESOURCES[res_key]
            exists = resource.dest.exists()
            items.append(
                PlanItem(
                    kind="resource",
                    title=f"{'已存在，跳过' if exists else '下载'} {resource.label}",
                    detail=f"{resource.url} → {resource.dest}",
                    payload={"resource": res_key},
                    size_mb=0 if exists else resource.size_mb,
                )
            )

    if do_build and "local_llamacpp" in features:
        repo = REPOS["llama_cpp"]
        build_dir = repo.dest / "build"
        binary = build_dir / "bin" / "llama-server"
        if not binary.exists():
            items.append(
                PlanItem(
                    kind="command",
                    title="编译 llama.cpp（llama-server）",
                    detail=f"cmake 配置 + build → {binary}",
                    payload={
                        "commands": [
                            [
                                "cmake",
                                "-S",
                                str(repo.dest),
                                "-B",
                                str(build_dir),
                                "-DGGML_NATIVE=ON",
                            ],
                            [
                                "cmake",
                                "--build",
                                str(build_dir),
                                "-j",
                                str(max(1, (os.cpu_count() or 4) - 1)),
                                "--target",
                                "llama-server",
                            ],
                        ],
                        "cwd": str(repo.dest),
                    },
                )
            )

    for feature_key in features:
        for command in FEATURES[feature_key].commands:
            if feature_key == "local_llamacpp":
                continue
            items.append(
                PlanItem(
                    kind="command",
                    title=f"执行：{' '.join(command)}",
                    detail=FEATURES[feature_key].label,
                    payload={"commands": [list(command)], "cwd": str(ROOT)},
                )
            )

    model_path = _model_path(state)
    # 用户关掉「下载模型」且模型文件不存在时，不要生成指向空路径的 profile。
    if (
        model_path is not None
        and state.model_resource in RESOURCES
        and not do_download
        and not model_path.exists()
        and not state.model_path.strip()
    ):
        model_path = None
    if "local_llamacpp" in features and model_path is not None:
        slug = (
            RESOURCES[state.model_resource].key
            if state.model_resource in RESOURCES
            else model_path.stem.lower().replace(".", "-")
        )
        items.append(
            PlanItem(
                kind="profile",
                title=f"生成模型 profile：onboarding_{slug}.yaml",
                detail=f"{model_path} → apps/dsn/model_profiles/onboarding_{slug}.yaml",
                payload={
                    "slug": slug,
                    "model_path": str(model_path),
                    "binary": str(_expand_path(state.llama_binary or DEFAULT_LLAMA_BIN)),
                    "ctx_size": state.ctx_size,
                    "n_gpu_layers": state.n_gpu_layers,
                },
            )
        )

    return items


def _display_env_key(key: str) -> str:
    if "KEY" in key or "TOKEN" in key or "SECRET" in key:
        return key
    return key


def plan_summary(
    items: Sequence[PlanItem],
    features: Sequence[str],
    goals: Sequence[str] = (),
    apps: Sequence[str] | None = None,
) -> str:
    lines: list[str] = []
    labels = [FEATURES[k].label for k in features if k in FEATURES]
    lines.append("**已选能力：** " + ("、".join(labels) if labels else "（无）"))
    selected_apps = resolve_apps(goals, features, apps)
    if selected_apps:
        lines.append(
            "**涉及应用：** " + "、".join(APPS[k].label for k in selected_apps)
        )
    total_mb = sum(item.size_mb for item in items)
    if total_mb:
        label = f"{total_mb / 1024:.1f} GB" if total_mb >= 1024 else f"{total_mb:.0f} MB"
        lines.append(f"**预计下载：** 约 {label}（已有文件会自动跳过）")
    lines.append("")
    if not items:
        lines.append("没有需要执行的动作。")
        return "\n".join(lines)
    for index, item in enumerate(items, 1):
        size = f"  ·  {item.size_label}" if item.size_label else ""
        lines.append(f"{index}. **{item.title}**{size}")
        if item.detail:
            lines.append(f"   {item.detail}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 执行
# ══════════════════════════════════════════════════════════════════════


async def _run_stream(
    command: Sequence[str],
    *,
    cwd: Path,
    log: Callable[[str], None],
    cancel: Callable[[], bool] | None = None,
) -> int:
    log("$ " + " ".join(str(part) for part in command))
    try:
        proc = await asyncio.create_subprocess_exec(
            *[str(part) for part in command],
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        raise RuntimeError(f"找不到命令：{command[0]}（请先安装）") from None

    assert proc.stdout is not None
    while True:
        if cancel and cancel():
            proc.terminate()
            await proc.wait()
            raise PlanCancelled()
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            log(text)
    return await proc.wait()


async def _clone_repo(repo: RepoSpec, log: Callable[[str], None]) -> ActionResult:
    dest = repo.dest
    if dest.exists():
        if (dest / ".git").exists():
            return ActionResult(repo.label, "skip", f"已存在：{dest}")
        return ActionResult(repo.label, "skip", f"目录已存在但不是 git 仓库：{dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    code = await _run_stream(
        ["git", "clone", "--depth", "1", repo.url, str(dest)],
        cwd=dest.parent,
        log=log,
    )
    if code != 0:
        raise RuntimeError(f"git clone 失败（退出码 {code}）")
    return ActionResult(repo.label, "ok", f"已克隆到 {dest}")


async def _download(
    resource: ResourceSpec,
    *,
    log: Callable[[str], None],
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ActionResult:
    dest = resource.dest
    if dest.exists() and dest.stat().st_size > 0:
        return ActionResult(resource.label, "skip", f"已存在：{dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    existing = part.stat().st_size if part.exists() else 0
    headers: dict[str, str] = {}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if "huggingface.co" in resource.url and token:
        headers["Authorization"] = f"Bearer {token}"
    if existing:
        headers["Range"] = f"bytes={existing}-"

    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - requirements 已包含
        raise RuntimeError("缺少 httpx，请先 pip install httpx") from exc

    total = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            async with client.stream("GET", resource.url, headers=headers) as response:
                if response.status_code == 401:
                    raise RuntimeError(
                        "Hugging Face 返回 401：请先在网页接受模型许可，"
                        "并设置 HF_TOKEN 环境变量后重试"
                    )
                if response.status_code == 416 and existing:
                    part.replace(dest)
                    return ActionResult(resource.label, "ok", f"已保存到 {dest}")
                response.raise_for_status()
                if existing and response.status_code != 206:
                    existing = 0
                    part.unlink(missing_ok=True)
                length = int(response.headers.get("content-length") or 0)
                total = length + existing if length else 0
                mode = "ab" if existing else "wb"
                log(f"开始下载 {resource.label} → {dest}")
                done = existing
                with part.open(mode) as handle:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        if cancel and cancel():
                            raise PlanCancelled()
                        handle.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
    except PlanCancelled:
        log(f"已暂停下载，可用断点续传继续：{part}")
        raise
    except Exception:
        if part.exists():
            log(f"下载中断，保留断点文件：{part}")
        raise

    part.replace(dest)
    return ActionResult(resource.label, "ok", f"已保存到 {dest}")


def write_model_profile(payload: dict[str, Any]) -> Path:
    slug = str(payload["slug"])
    target = ROOT / "apps" / "dsn" / "model_profiles" / f"onboarding_{slug}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# 由 onboarding.py 自动生成。
# 如果模型或 llama-server 路径变化，改这里即可；重启 dsn_ui 生效。
model: {slug}
engine: llama_cpp
priority: 80
orchestrated: true
resident: false
immediate: false
load_timeout: 180
request_timeout: 300

llama_config:
  binary_path: {json.dumps(str(payload['binary']))}
  model_path: {json.dumps(str(payload['model_path']))}
  n_gpu_layers: {payload.get('n_gpu_layers', 99)}
  ctx_size: {payload.get('ctx_size', 8192)}
"""
    target.write_text(content, encoding="utf-8")
    return target


def _log_env_summary(env: dict[str, str], log: Callable[[str], None]) -> None:
    for key, value in env.items():
        if any(marker in key for marker in ("KEY", "TOKEN", "SECRET")):
            log(f"  {key}={mask_secret(value)}")
        else:
            log(f"  {key}={value}")


async def execute_item(
    item: PlanItem,
    *,
    log: Callable[[str], None],
    progress: Callable[[int, int], None] | None = None,
    cancel: Callable[[], bool] | None = None,
) -> ActionResult:
    if cancel and cancel():
        raise PlanCancelled()

    if item.kind == "env":
        env = dict(item.payload["env"])
        target = item.payload.get("path")
        update_env(env, path=Path(target) if target else None)
        _log_env_summary(env, log)
        return ActionResult(item.title, "ok", f"已写入 {target or '.env'}")

    if item.kind == "pip":
        packages = list(item.payload["packages"])
        code = await _run_stream(
            [sys.executable, "-m", "pip", "install", *packages],
            cwd=ROOT,
            log=log,
            cancel=cancel,
        )
        if code != 0:
            raise RuntimeError(f"pip install 失败（退出码 {code}）")
        return ActionResult(item.title, "ok", "依赖安装完成")

    if item.kind == "repo":
        return await _clone_repo(REPOS[item.payload["repo"]], log)

    if item.kind == "resource":
        return await _download(
            RESOURCES[item.payload["resource"]],
            log=log,
            progress=progress,
            cancel=cancel,
        )

    if item.kind == "command":
        for command in item.payload.get("commands", []):
            code = await _run_stream(
                command,
                cwd=_expand_path(item.payload.get("cwd", ROOT)),
                log=log,
                cancel=cancel,
            )
            if code != 0:
                raise RuntimeError(f"命令失败（退出码 {code}）：{' '.join(command)}")
        return ActionResult(item.title, "ok", "命令执行完成")

    if item.kind == "profile":
        target = write_model_profile(item.payload)
        return ActionResult(item.title, "ok", f"已写入 {target}")

    raise RuntimeError(f"未知计划类型：{item.kind}")


# ══════════════════════════════════════════════════════════════════════
# 环境概览 / CLI
# ══════════════════════════════════════════════════════════════════════


def collect_environment() -> dict[str, Any]:
    env = load_env()
    configured = [
        key
        for key, value in env.items()
        if value and value != "sk-your-key-here" and not key.startswith("#")
    ]
    return {
        "python": sys.version.split()[0],
        "git": shutil.which("git"),
        "cmake": shutil.which("cmake"),
        "node": shutil.which("node"),
        "npm": shutil.which("npm"),
        "env_exists": ENV_PATH.exists(),
        "configured_keys": configured,
        "repos": {
            key: (spec.dest.exists(), str(spec.dest)) for key, spec in REPOS.items()
        },
        "models": {
            key: (spec.dest.exists(), str(spec.dest))
            for key, spec in RESOURCES.items()
        },
        "textual": _textual_version(),
    }


def _textual_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("textual")
    except Exception:
        return ""


def render_environment(env: dict[str, Any]) -> str:
    def yes_no(value: Any) -> str:
        return "✓" if value else "✗"

    lines = [
        f"Python {env['python']}   git {yes_no(env['git'])}   "
        f"cmake {yes_no(env['cmake'])}   node {yes_no(env['node'])}",
        f"Textual {env['textual'] or '未安装'}",
        f".env {'已存在' if env['env_exists'] else '不存在'}，"
        f"已配置 {len(env['configured_keys'])} 个键",
    ]
    missing = [k for k, (ok, _) in env["repos"].items() if not ok]
    if missing:
        lines.append("未就绪仓库：" + "、".join(REPOS[k].label for k in missing))
    else:
        lines.append("第三方仓库：全部就绪")
    models = [k for k, (ok, _) in env["models"].items() if ok]
    lines.append(
        "已下载模型：" + ("、".join(RESOURCES[k].label for k in models) if models else "无")
    )
    return "\n".join(lines)


def print_catalog() -> None:
    print("AICF 全局引导目录\n")
    print("目标（可多选）：")
    for key in GOAL_ORDER:
        goal = GOALS[key]
        print(f"  {key:<16} {goal.label} — {goal.description}")
    print("\n应用：")
    for key in APP_ORDER:
        app = APPS[key]
        print(f"  {key:<16} {app.label} — {app.description}")
    print("\n能力：")
    for key in FEATURE_ORDER:
        feature = FEATURES[key]
        extras = []
        if feature.repos:
            extras.append("仓库 " + "/".join(REPOS[r].label for r in feature.repos))
        if feature.packages:
            extras.append("依赖 " + "/".join(feature.packages))
        if feature.requires:
            extras.append("依赖能力 " + "/".join(feature.requires))
        suffix = f"  [{'; '.join(extras)}]" if extras else ""
        print(f"  {key:<16} {feature.label} — {feature.description}{suffix}")
    print("\n资源：")
    for key in RESOURCES:
        res = RESOURCES[key]
        print(f"  {key:<16} {res.label} — {res.purpose}")
    errors = validate_catalog()
    if errors:
        print("\n⚠ 目录自检失败：")
        for error in errors:
            print("  - " + error)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="onboarding.py",
        description="AICF 全局引导：选择需求 → 自动配置应用、克隆仓库、下载资源。",
    )
    parser.add_argument("--list", action="store_true", help="列出目标 / 应用 / 能力")
    parser.add_argument("--check", action="store_true", help="检查环境与已有资源")
    parser.add_argument(
        "--features",
        default="",
        help="预选能力（逗号分隔，例如 remote_api,tts）",
    )
    parser.add_argument("--goal", default="", help="预选目标（逗号分隔）")
    args = parser.parse_args(argv)

    if args.list:
        print_catalog()
        return 0

    env = collect_environment()
    if args.check:
        print(render_environment(env))
        return 0 if validate_catalog() == [] else 1

    if not _TEXTUAL_AVAILABLE:
        print(
            "未安装 Textual，无法启动 TUI。\n"
            "请先运行：python3 -m pip install 'textual>=1.0'\n"
            "（或安装完整依赖：python3 -m pip install -r requirements.txt）"
        )
        return 2

    state = OnboardingState()
    if args.goal:
        state.goals = [g.strip() for g in args.goal.split(",") if g.strip() in GOALS]
        state.features = features_for_goals(state.goals)
        state.apps = apps_for_goals(state.goals) or apps_for_features(state.features)
    if args.features:
        state.features = resolve_features(
            [f.strip() for f in args.features.split(",") if f.strip()]
        )

    app = OnboardingApp(state=state, environment=env)
    app.run()
    return 0


# ══════════════════════════════════════════════════════════════════════
# Textual UI（延迟导入：没有 textual 时 --list / --check 仍可用）
# ══════════════════════════════════════════════════════════════════════

try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.screen import Screen
    from textual.widgets import (
        Button,
        Input,
        Label,
        Markdown,
        ProgressBar,
        RadioButton,
        RadioSet,
        RichLog,
        SelectionList,
        Static,
        Switch,
    )
    from textual.widgets.selection_list import Selection

    _TEXTUAL_AVAILABLE = True
except Exception:  # pragma: no cover - 可选依赖
    _TEXTUAL_AVAILABLE = False


if _TEXTUAL_AVAILABLE:

    WELCOME_TEXT = """
# 先聊聊你想做什么

这是**仓库级**引导：不是某个应用的固定问卷，而是先理解你的需求，
再把应用、模型、仓库和资源一次配好。

所有下载与克隆都会先列在「执行计划」里，确认后才开始。
随时可以用 `Ctrl+C` 退出，已完成的步骤会保留。
"""

    CSS = """
    Screen {
        background: $surface;
    }
    .title {
        text-style: bold;
        color: $accent;
        padding: 1 2 0 2;
    }
    .question {
        text-style: bold;
        padding: 1 2 0 2;
    }
    .hint {
        color: $text-muted;
        padding: 0 2 1 2;
    }
    .section {
        padding: 0 2;
    }
    SelectionList {
        height: auto;
        max-height: 18;
        margin: 0 2;
    }
    RadioSet {
        height: auto;
        margin: 0 2;
    }
    Input {
        margin: 0 2;
    }
    .buttons {
        height: auto;
        padding: 1 2;
    }
    Button {
        margin-right: 1;
    }
    #env-summary {
        border: round $primary;
        padding: 1 2;
        margin: 0 2;
    }
    #plan {
        border: round $primary;
        padding: 1 2;
        margin: 0 2;
        height: auto;
        max-height: 24;
    }
    #status {
        padding: 0 2;
        color: $text-muted;
    }
    #log {
        height: 1fr;
        min-height: 10;
        margin: 0 2;
        border: round $primary;
    }
    #bar {
        margin: 1 2;
    }
    """

    def _state(screen: Screen) -> OnboardingState:
        return screen.app.state  # type: ignore[attr-defined]

    class BaseScreen(Screen):
        BINDINGS = [("escape", "back", "返回")]

        def action_back(self) -> None:
            if len(self.app.screen_stack) > 1:
                self.app.pop_screen()

        def footer(self, *buttons: Button) -> ComposeResult:
            with Horizontal(classes="buttons"):
                yield from buttons

    class WelcomeScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            yield Static("AICF 全局引导", classes="title")
            with VerticalScroll():
                yield Markdown(WELCOME_TEXT)
                yield Static("正在检测环境…", id="env-summary")
            yield from self.footer(
                Button("开始配置", id="start", variant="primary"),
                Button("刷新环境", id="refresh"),
                Button("退出", id="quit"),
            )

        def on_mount(self) -> None:
            self.refresh_environment()

        def refresh_environment(self) -> None:
            env = collect_environment()
            self.app.environment = env  # type: ignore[attr-defined]
            self.query_one("#env-summary", Static).update(render_environment(env))

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "start":
                self.app.push_screen(GoalsScreen())
            elif event.button.id == "refresh":
                self.refresh_environment()
            elif event.button.id == "quit":
                self.app.exit()

    class GoalsScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("第 1 步 / 5 · 你的需求", classes="title")
            yield Label("可以多选。选完后下一步会列出对应的应用与能力。", classes="question")
            selections = [
                Selection(
                    f"{GOALS[key].label} — {GOALS[key].description}",
                    key,
                    initial_state=(key in state.goals),
                )
                for key in GOAL_ORDER
            ]
            yield SelectionList[str](*selections, id="goals")
            yield from self.footer(
                Button("上一步", id="back"),
                Button("下一步：选择应用", id="next", variant="primary"),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                self.app.pop_screen()
                return
            if event.button.id != "next":
                return
            state = _state(self)
            state.goals = list(self.query_one("#goals", SelectionList).selected)
            if state.goals:
                state.features = features_for_goals(state.goals)
            state.apps = apps_for_goals(state.goals) or apps_for_features(
                state.features
            )
            self.app.push_screen(AppsScreen())

    class AppsScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("第 2 步 / 5 · 应用", classes="title")
            yield Label(
                "这些应用会出现在完成页，可一键启动。取消勾选不想装/不想启动的。",
                classes="question",
            )
            selections = [
                Selection(
                    f"{APPS[key].label} — {APPS[key].description}",
                    key,
                    initial_state=(key in state.apps),
                )
                for key in APP_ORDER
            ]
            yield SelectionList[str](*selections, id="apps")
            yield from self.footer(
                Button("上一步", id="back"),
                Button("下一步：选择能力", id="next", variant="primary"),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                _state(self).apps = list(
                    self.query_one("#apps", SelectionList).selected
                )
                self.app.pop_screen()
                return
            if event.button.id != "next":
                return
            state = _state(self)
            state.apps = list(self.query_one("#apps", SelectionList).selected)
            self.app.push_screen(FeaturesScreen())

    class FeaturesScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("第 3 步 / 5 · 能力", classes="title")
            yield Label(
                "这些能力会被自动配置。取消勾选你不需要的；带依赖的能力会自动补齐。",
                classes="question",
            )
            selections = [
                Selection(
                    f"{FEATURES[key].label} — {FEATURES[key].description}",
                    key,
                    initial_state=(key in state.features),
                )
                for key in FEATURE_ORDER
            ]
            yield SelectionList[str](*selections, id="features")
            yield from self.footer(
                Button("上一步", id="back"),
                Button("下一步：模型接入", id="next", variant="primary"),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                _state(self).features = resolve_features(
                    self.query_one("#features", SelectionList).selected
                )
                self.app.pop_screen()
                return
            if event.button.id != "next":
                return
            state = _state(self)
            state.features = resolve_features(
                self.query_one("#features", SelectionList).selected
            )
            self.app.push_screen(ProviderScreen())

    class ProviderScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("第 4 步 / 5 · 模型从哪里来", classes="title")
            yield Label("只选一个；之后也可以在 dsn_ui 里随时改。", classes="question")
            with RadioSet(id="provider"):
                yield RadioButton(
                    "远程 OpenAI 兼容 API（推荐，最省事）",
                    id="remote",
                    value=state.provider == "remote",
                )
                yield RadioButton(
                    "已经运行的 LM Studio（本地服务）",
                    id="lmstudio",
                    value=state.provider == "lmstudio",
                )
                yield RadioButton(
                    "本地 llama.cpp（会克隆 / 编译 / 下载模型）",
                    id="local",
                    value=state.provider == "local",
                )
                yield RadioButton(
                    "稍后再配置（只写其他能力）",
                    id="later",
                    value=state.provider in ("later", ""),
                )
            yield Static(
                "提示：本地 llama.cpp 需要额外磁盘与编译时间；"
                "如果只想先跑起来，远程 API 最快。",
                classes="hint",
            )
            yield from self.footer(
                Button("上一步", id="back"),
                Button("下一步", id="next", variant="primary"),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                self.app.pop_screen()
                return
            if event.button.id != "next":
                return
            state = _state(self)
            pressed = self.query_one("#provider", RadioSet).pressed_button
            state.provider = (pressed.id if pressed else "later") or "later"
            if state.provider == "remote":
                self.app.push_screen(RemoteAPIScreen())
            elif state.provider == "lmstudio":
                self.app.push_screen(LmStudioScreen())
            elif state.provider == "local":
                if "local_llamacpp" not in state.features:
                    state.features = resolve_features(
                        [*state.features, "local_llamacpp"]
                    )
                self.app.push_screen(LocalModelScreen())
            else:
                self.app.push_screen(ReviewScreen())

    class RemoteAPIScreen(BaseScreen):
        PRESETS = {
            "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
            "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
            "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
        }

        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("远程 OpenAI 兼容 API", classes="title")
            yield Label("常见预设：", classes="question")
            with Horizontal(classes="buttons"):
                yield Button("DeepSeek", id="preset-deepseek")
                yield Button("OpenAI", id="preset-openai")
                yield Button("Qwen", id="preset-qwen")
            yield Label("API Base（不包含 /chat/completions）", classes="hint")
            yield Input(value=state.api_base, id="base", placeholder="https://api.deepseek.com/v1")
            yield Label("API Key（只写入 .env，不写入状态文件）", classes="hint")
            yield Input(
                value=state.api_key,
                id="key",
                password=True,
                placeholder="sk-...",
            )
            yield Label("模型名称", classes="hint")
            yield Input(value=state.api_model, id="model", placeholder="deepseek-chat")
            yield Static("", id="status")
            yield from self.footer(
                Button("上一步", id="back"),
                Button("测试连接", id="test"),
                Button("下一步：确认计划", id="next", variant="primary"),
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            if button_id == "back":
                self.app.pop_screen()
                return
            if button_id.startswith("preset-"):
                preset = self.PRESETS.get(button_id.removeprefix("preset-"))
                if preset:
                    self.query_one("#base", Input).value = preset[0]
                    self.query_one("#model", Input).value = preset[1]
                return
            self._read_inputs()
            if button_id == "test":
                self.test_connection()
                return
            if button_id == "next":
                if not _state(self).api_key:
                    self.query_one("#status", Static).update(
                        "还没有填 API Key；可以点「下一步」先跳过，稍后在 .env 或 dsn_ui 里补。"
                    )
                self.app.push_screen(ReviewScreen())

        def _read_inputs(self) -> None:
            state = _state(self)
            state.api_base = self.query_one("#base", Input).value.strip()
            state.api_key = self.query_one("#key", Input).value.strip()
            state.api_model = self.query_one("#model", Input).value.strip()

        @work(exclusive=True)
        async def test_connection(self) -> None:
            state = _state(self)
            status = self.query_one("#status", Static)
            base = state.api_base.rstrip("/")
            if not base:
                status.update("请先填写 API Base")
                return
            status.update("正在请求 /models …")
            try:
                import httpx

                headers = (
                    {"Authorization": f"Bearer {state.api_key}"} if state.api_key else {}
                )
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(f"{base}/models", headers=headers)
                if response.status_code < 400:
                    status.update(f"连接成功（HTTP {response.status_code}）")
                elif response.status_code in (401, 403):
                    status.update(
                        f"端点可达，但认证失败（HTTP {response.status_code}），请检查 Key"
                    )
                else:
                    status.update(f"端点返回 HTTP {response.status_code}（可能不支持 /models）")
            except Exception as exc:
                status.update(f"连接失败：{exc}")

    class LmStudioScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("LM Studio", classes="title")
            yield Label(
                "在 LM Studio 中打开 Local Server，并确认端口（默认 4501）。",
                classes="question",
            )
            yield Label("Base URL", classes="hint")
            yield Input(value=state.lmstudio_url, id="url")
            yield Static("", id="status")
            yield from self.footer(
                Button("上一步", id="back"),
                Button("测试连接", id="test"),
                Button("下一步：确认计划", id="next", variant="primary"),
            )

        def _read(self) -> None:
            _state(self).lmstudio_url = self.query_one("#url", Input).value.strip()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                self.app.pop_screen()
                return
            self._read()
            if event.button.id == "test":
                self.test_connection()
            elif event.button.id == "next":
                self.app.push_screen(ReviewScreen())

        @work(exclusive=True)
        async def test_connection(self) -> None:
            state = _state(self)
            status = self.query_one("#status", Static)
            status.update("正在请求 /v1/models …")
            try:
                import httpx

                url = state.lmstudio_url.rstrip("/") + "/v1/models"
                async with httpx.AsyncClient(timeout=5) as client:
                    response = await client.get(url)
                status.update(
                    f"连接成功（HTTP {response.status_code}）"
                    if response.status_code < 400
                    else f"HTTP {response.status_code}，请检查地址或 LM Studio 状态"
                )
            except Exception as exc:
                status.update(f"连接失败：{exc}")

    class LocalModelScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("本地 llama.cpp 与模型", classes="title")
            yield Label(
                "会克隆 llama.cpp 到 third_party/llama.cpp；模型下载到 models/。",
                classes="question",
            )
            yield Label("llama-server 路径（编译后）", classes="hint")
            yield Input(value=state.llama_binary, id="binary")
            yield Label("下载一个 GGUF 模型：", classes="hint")
            with RadioSet(id="model"):
                yield RadioButton(
                    "不下载（使用已有文件或稍后手动放置）",
                    id="none",
                    value=(state.model_resource == ""),
                )
                for key in RESOURCES:
                    resource = RESOURCES[key]
                    yield RadioButton(
                        f"{resource.label} — {resource.purpose}",
                        id=key,
                        value=(state.model_resource == key),
                    )
            yield Label("已有模型路径（可留空；留空则使用下载的模型）", classes="hint")
            yield Input(value=state.model_path, id="model-path", placeholder="/path/to/model.gguf")
            with Horizontal(classes="buttons"):
                yield Label("克隆后自动编译 llama.cpp（需要 cmake）", classes="hint")
                yield Switch(value=state.build_llama, id="build")
            yield Static(
                "提示：下载 Gemma 需要在 Hugging Face 先接受许可，并设置 HF_TOKEN。",
                classes="hint",
            )
            yield from self.footer(
                Button("上一步", id="back"),
                Button("下一步：确认计划", id="next", variant="primary"),
            )

        def _read(self) -> None:
            state = _state(self)
            state.llama_binary = self.query_one("#binary", Input).value.strip()
            state.model_path = self.query_one("#model-path", Input).value.strip()
            state.build_llama = self.query_one("#build", Switch).value
            pressed = self.query_one("#model", RadioSet).pressed_button
            state.model_resource = "" if not pressed or pressed.id == "none" else pressed.id
            if state.model_resource:
                state.features = resolve_features([*state.features, "local_model"])

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                self.app.pop_screen()
                return
            if event.button.id == "next":
                self._read()
                self.app.push_screen(ReviewScreen())

    class ReviewScreen(BaseScreen):
        def compose(self) -> ComposeResult:
            state = _state(self)
            yield Static("第 5 步 / 5 · 执行计划", classes="title")
            yield Markdown(id="plan")
            with Horizontal(classes="buttons"):
                yield Label("克隆仓库", classes="hint")
                yield Switch(value=state.clone_repos, id="opt-clone")
                yield Label("安装依赖", classes="hint")
                yield Switch(value=state.install_packages, id="opt-pip")
                yield Label("下载模型", classes="hint")
                yield Switch(value=state.download_resources, id="opt-download")
                yield Label("编译 llama.cpp", classes="hint")
                yield Switch(value=state.build_llama, id="opt-build")
            yield Static(
                "确认后才会真正执行。已存在的仓库与文件会自动跳过。",
                classes="hint",
            )
            yield from self.footer(
                Button("上一步", id="back"),
                Button("开始执行", id="run", variant="primary"),
                Button("退出", id="quit"),
            )

        def on_mount(self) -> None:
            self.refresh_plan()

        def _options(self) -> dict[str, bool]:
            return {
                "clone_repos": self.query_one("#opt-clone", Switch).value,
                "install_packages": self.query_one("#opt-pip", Switch).value,
                "download_resources": self.query_one("#opt-download", Switch).value,
                "build_llama": self.query_one("#opt-build", Switch).value,
            }

        def refresh_plan(self) -> None:
            state = _state(self)
            options = self._options()
            items = build_plan(state, **options)
            self.app.plan = items  # type: ignore[attr-defined]
            self.query_one("#plan", Markdown).update(
                plan_summary(
                    items,
                    resolve_features(state.features),
                    state.goals,
                    state.apps,
                )
            )

        @on(Switch.Changed)
        def on_switch_changed(self, _event: Switch.Changed) -> None:
            self.refresh_plan()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "back":
                self.app.pop_screen()
                return
            if event.button.id == "quit":
                self.app.exit()
                return
            if event.button.id != "run":
                return
            state = _state(self)
            for key, value in self._options().items():
                setattr(state, key, value)
            self.app.plan = build_plan(state, **self._options())  # type: ignore[attr-defined]
            self.app.push_screen(RunScreen())

    class RunScreen(BaseScreen):
        BINDINGS = []  # 执行中禁止 Esc 返回，避免计划在后台继续跑

        def compose(self) -> ComposeResult:
            yield Static("正在执行 …", classes="title")
            yield Static("", id="status")
            yield ProgressBar(total=1, show_eta=False, id="bar")
            yield RichLog(id="log", markup=True, wrap=True)
            yield from self.footer(Button("中止", id="cancel", variant="error"))

        def on_mount(self) -> None:
            self.run_plan()

        def _log(self, message: str) -> None:
            self.query_one("#log", RichLog).write(message)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "cancel":
                self.app.cancelled = True  # type: ignore[attr-defined]
                self.query_one("#status", Static).update("正在中止…")

        @work(exclusive=True)
        async def run_plan(self) -> None:
            state = _state(self)
            items = list(getattr(self.app, "plan", []))
            bar = self.query_one("#bar", ProgressBar)
            status = self.query_one("#status", Static)
            bar.update(total=max(1, len(items)))
            state.results = []
            log = self._log

            log(f"[b]共 {len(items)} 个动作[/b]")
            for index, item in enumerate(items, 1):
                if getattr(self.app, "cancelled", False):
                    state.results.append(ActionResult(item.title, "cancel", "用户中止"))
                    break
                status.update(f"[{index}/{len(items)}] {item.title}")
                log(f"\n[b cyan]▶ {item.title}[/b cyan]")
                current_size = {"total": 0}

                def progress(done: int, total: int) -> None:
                    if total <= 0:
                        status.update(
                            f"[{index}/{len(items)}] {item.title}  "
                            f"{done / (1024 * 1024):.1f} MB"
                        )
                        return
                    if total != current_size["total"]:
                        current_size["total"] = total
                    percent = done / total * 100
                    status.update(
                        f"[{index}/{len(items)}] {item.title}  "
                        f"{done / (1024 * 1024):.1f}/"
                        f"{total / (1024 * 1024):.1f} MB ({percent:.0f}%)"
                    )

                try:
                    result = await execute_item(
                        item,
                        log=log,
                        progress=progress,
                        cancel=lambda: bool(getattr(self.app, "cancelled", False)),
                    )
                except PlanCancelled:
                    state.results.append(ActionResult(item.title, "cancel", "用户中止"))
                    log("[yellow]已中止当前动作[/yellow]")
                    break
                except Exception as exc:  # noqa: BLE001 - 单个动作失败不应中断整体
                    state.results.append(ActionResult(item.title, "fail", str(exc)))
                    log(f"[red]✗ {exc}[/red]")
                else:
                    state.results.append(result)
                    if result.status == "skip":
                        log(f"[yellow]○ {result.message}[/yellow]")
                    elif result.status == "ok":
                        log(f"[green]✓ {result.message}[/green]")
                    else:
                        log(f"○ {result.message}")
                bar.advance(1)

            save_state(state)
            ok = sum(1 for r in state.results if r.status == "ok")
            skipped = sum(1 for r in state.results if r.status == "skip")
            failed = sum(1 for r in state.results if r.status == "fail")
            status.update(f"完成：成功 {ok}，跳过 {skipped}，失败 {failed}")
            self.app.push_screen(DoneScreen())

    class DoneScreen(BaseScreen):
        BINDINGS = []  # 已完成后不再返回执行页

        def compose(self) -> ComposeResult:
            state = _state(self)
            features = resolve_features(state.features)
            apps = resolve_apps(state.goals, features, state.apps)
            yield Static("配置完成", classes="title")
            with VerticalScroll():
                yield Markdown(self._summary_markdown(features, apps), id="plan")
                yield Static("", id="status")
            with Horizontal(classes="buttons"):
                for app_key in apps:
                    yield Button(f"启动 {APPS[app_key].label}", id=f"launch-{app_key}")
                if "dsn" in apps:
                    yield Button("进入 dsn 应用内引导", id="app-onboarding")
                yield Button("退出", id="quit", variant="primary")

        def _summary_markdown(self, features: Sequence[str], apps: Sequence[str]) -> str:
            state = _state(self)
            lines = ["**本次结果**", ""]
            for result in state.results:
                icon = {"ok": "✓", "skip": "○", "fail": "✗", "cancel": "—"}.get(
                    result.status, "·"
                )
                line = f"- {icon} {result.title}"
                if result.message:
                    line += f" — {result.message}"
                lines.append(line)
            lines.extend(["", "**后续步骤**", ""])
            if not apps:
                lines.append("- 还没有选择应用；可以重新运行本脚本。")
            for app_key in apps:
                app = APPS[app_key]
                lines.append(f"- **{app.label}**：`{app.launch_hint}`")
                lines.append(f"  {app.onboarding_hint}")
            if state.provider == "later":
                lines.append(
                    "- 模型尚未配置：可编辑 `.env`，或启动 dsn_ui 后在页面里添加 Provider。"
                )
            if "tts" in features:
                lines.append(
                    "- GPT-SoVITS 已克隆；预训练权重需要按其 README 下载后启动 :9880 服务。"
                )
            if "local_llamacpp" in features and state.build_llama:
                lines.append(
                    f"- llama-server 预期路径：`{_expand_path(state.llama_binary)}`"
                )
            lines.extend(
                [
                    "",
                    f"选择已保存到 `{_display_path(STATE_PATH)}`（不含 API Key）。",
                ]
            )
            return "\n".join(lines)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            status = self.query_one("#status", Static)
            if button_id == "quit":
                self.app.exit()
                return
            if button_id == "app-onboarding":
                self.run_dsn_onboarding()
                return
            if button_id.startswith("launch-"):
                app_key = button_id.removeprefix("launch-")
                self.launch_app(app_key, status)

        def launch_app(self, app_key: str, status: Static) -> None:
            app = APPS.get(app_key)
            if app is None:
                return
            try:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / "launcher.py"), "--app", app_key],
                    cwd=str(ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception as exc:  # noqa: BLE001
                status.update(f"启动失败：{exc}")
                return
            extra = ""
            if app_key == "dsn_ui":
                extra = "，打开 http://127.0.0.1:8888"
            elif app_key == "densechat":
                extra = "，打开 http://127.0.0.1:8080"
            status.update(f"已在后台启动 {app.label}（pid {process.pid}）{extra}")

        def run_dsn_onboarding(self) -> None:
            status = self.query_one("#status", Static)
            try:
                with self.app.suspend():
                    from apps.dsn.onboarding import run as run_dsn_onboarding

                    run_dsn_onboarding()
            except Exception as exc:  # noqa: BLE001
                status.update(f"应用内引导失败：{exc}")
                return
            status.update("dsn 应用内引导已结束。")

    class OnboardingApp(App):
        TITLE = "AICF 全局引导"
        SUB_TITLE = "选择需求 → 自动配置"
        CSS = CSS
        BINDINGS = [("ctrl+q", "quit", "退出")]

        def __init__(
            self,
            state: OnboardingState | None = None,
            environment: dict[str, Any] | None = None,
        ) -> None:
            super().__init__()
            self.state = state or OnboardingState()
            self.environment = environment or collect_environment()
            self.plan: list[PlanItem] = []
            self.cancelled = False

        def on_mount(self) -> None:
            self.push_screen(WelcomeScreen())


if __name__ == "__main__":
    raise SystemExit(main())
