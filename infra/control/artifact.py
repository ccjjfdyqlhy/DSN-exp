# infra/control/artifact.py
# AgentArtifact：Agent 的声明式统一资产模型（策划案 §4.5.1）。
#
# ── 「一种声明，多处消费」 ──
# 同一份 agent.yaml 同时是：
#   部署描述（runtime.deployment）／评测配置（Experiment 的输入）／
#   成本归因维度（cost_model）／控制面的唯一事实来源。
# 「评测用的配置」和「线上用的配置」漂移是回归分析失效的头号原因，
# 所以这里只有一种格式、一个解析器。
#
# ── 版本不可变 ──
# metadata.version 一旦与内容哈希一起入库就不许改（策划案 §4.5.3）：
# 变更 = 新版本。校验在 store 层强制，本模块只提供 content_hash。
#
# 工具引用用**版本引用**（shell@v3）而非名字引用（策划案 §4.4.2）：
# 上游升级不该打断线上 —— 线上跑的永远是声明时的那个版本。

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # PyYAML 是既有依赖（skills / datasets 都在用）
    import yaml
except ImportError:  # pragma: no cover - 与既有模块同策略：没有 yaml 才退化
    yaml = None  # type: ignore[assignment]

#: 支持的执行架构（策划案 §4.1.3）：react 是 rc0 的，workflow / planner 随 rc1
KNOWN_KERNELS: tuple[str, ...] = ('react', 'workflow', 'planner')
#: 多智能体形态复用 collab/swarm，协议统一后也是合法内核
KNOWN_KERNELS += ('multi-agent',)

API_VERSION = 'aicf.dev/v1'
KIND_AGENT = 'Agent'

#: 工具版本引用：`shell@v3` / `fs.read@1.0.0`；裸名字（无 @）也接受，
#: 但发布校验会提醒 —— 版本引用才是治理面要的形态。
_TOOL_REF = re.compile(r'^[A-Za-z0-9_.-]+(@[A-Za-z0-9_.-]+)?$')

# 记忆层（策划案 §4.3.2）
KNOWN_CONTEXT_LAYERS: tuple[str, ...] = ('L0', 'L1', 'L2', 'L3')


class ArtifactError(ValueError):
    """artifact 声明不合法。"""


@dataclass
class ModelSpec:
    primary: str = ''
    fallback: tuple[str, ...] = ()
    capability_request: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'primary': self.primary,
            'fallback': list(self.fallback),
            'capability_request': list(self.capability_request),
        }


@dataclass
class ContextSpec:
    layers: tuple[str, ...] = ('L0', 'L1', 'L2')
    budget: int = 128_000

    def to_dict(self) -> dict[str, Any]:
        return {'layers': list(self.layers), 'budget': self.budget}


@dataclass
class PolicySpec:
    approval: tuple[str, ...] = ()      # 需要审批的工具（版本引用）
    network: str = 'allowlist'
    sandbox: str = 'workspace'

    def to_dict(self) -> dict[str, Any]:
        return {
            'approval': list(self.approval),
            'network': self.network,
            'sandbox': self.sandbox,
        }


@dataclass
class RuntimeSpec:
    deployment: dict = field(default_factory=dict)   # {replicas, strategy}
    workspace: dict = field(default_factory=dict)    # {fs, net}

    def to_dict(self) -> dict[str, Any]:
        return {'deployment': dict(self.deployment),
                'workspace': dict(self.workspace)}


@dataclass
class CostModel:
    per_1k_tokens: dict = field(default_factory=dict)  # {input, output}

    def to_dict(self) -> dict[str, Any]:
        return {'per_1k_tokens': dict(self.per_1k_tokens)}


@dataclass
class ArtifactMetadata:
    name: str
    owner: str = ''
    version: str = '0.1.0'
    labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'owner': self.owner,
            'version': self.version,
            'labels': dict(self.labels),
        }


@dataclass
class AgentArtifact:
    """一份可版本化的 Agent 声明（策划案 §4.5.1 的 agent.yaml）。"""

    api_version: str = API_VERSION
    kind: str = KIND_AGENT
    metadata: ArtifactMetadata = field(
        default_factory=lambda: ArtifactMetadata(name=''))
    spec_kernel: str = 'react'
    spec_model: ModelSpec = field(default_factory=ModelSpec)
    spec_context: ContextSpec = field(default_factory=ContextSpec)
    spec_tools: tuple[str, ...] = ()
    spec_policies: PolicySpec = field(default_factory=PolicySpec)
    spec_runtime: RuntimeSpec = field(default_factory=RuntimeSpec)
    spec_cost_model: CostModel = field(default_factory=CostModel)
    #: 原文（发布时冻结进 RunVersion / 控制面）；从 yaml 解析时保留
    raw_yaml: str = ''

    # ── 标识 ─────────────────────────────────────────────
    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version

    @property
    def id(self) -> str:
        """控制面里的资产 id —— 就是 metadata.name（版本单独一列）。"""
        return self.metadata.name

    def content_hash(self) -> str:
        """内容哈希（规范 JSON，键排序）—— 判断两次声明是否同一份。"""
        return _sha256(_canonical(self.to_dict()))

    # ── 序列化 ───────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            'apiVersion': self.api_version,
            'kind': self.kind,
            'metadata': self.metadata.to_dict(),
            'spec': {
                'kernel': self.spec_kernel,
                'model': self.spec_model.to_dict(),
                'context': self.spec_context.to_dict(),
                'tools': list(self.spec_tools),
                'policies': self.spec_policies.to_dict(),
                'runtime': self.spec_runtime.to_dict(),
                'cost_model': self.spec_cost_model.to_dict(),
            },
        }

    def to_yaml(self) -> str:
        if yaml is None:  # pragma: no cover
            return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        return yaml.safe_dump(self.to_dict(), allow_unicode=True,
                              sort_keys=False)

    # ── 解析 ─────────────────────────────────────────────
    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *,
                  raw_yaml: str = '') -> AgentArtifact:
        _validate_shape(data)
        meta = data.get('metadata') or {}
        spec = data.get('spec') or {}
        model = spec.get('model') or {}
        context = spec.get('context') or {}
        policies = spec.get('policies') or {}
        runtime = spec.get('runtime') or {}
        cost = spec.get('cost_model') or {}
        artifact = cls(
            api_version=str(data.get('apiVersion') or API_VERSION),
            kind=str(data.get('kind') or KIND_AGENT),
            metadata=ArtifactMetadata(
                name=str(meta.get('name') or ''),
                owner=str(meta.get('owner') or ''),
                version=str(meta.get('version') or '0.1.0'),
                labels=dict(meta.get('labels') or {}),
            ),
            spec_kernel=str(spec.get('kernel') or 'react'),
            spec_model=ModelSpec(
                primary=str(model.get('primary') or ''),
                fallback=tuple(model.get('fallback') or ()),
                capability_request=tuple(model.get('capability_request') or ()),
            ),
            spec_context=ContextSpec(
                layers=tuple(context.get('layers') or ('L0', 'L1', 'L2')),
                budget=int(context.get('budget') or 128_000),
            ),
            spec_tools=tuple(spec.get('tools') or ()),
            spec_policies=PolicySpec(
                approval=tuple(policies.get('approval') or ()),
                network=str(policies.get('network') or 'allowlist'),
                sandbox=str(policies.get('sandbox') or 'workspace'),
            ),
            spec_runtime=RuntimeSpec(
                deployment=dict(runtime.get('deployment') or {}),
                workspace=dict(runtime.get('workspace') or {}),
            ),
            spec_cost_model=CostModel(
                per_1k_tokens=dict(cost.get('per_1k_tokens') or {}),
            ),
            raw_yaml=raw_yaml,
        )
        _validate_semantics(artifact)
        return artifact

    @classmethod
    def from_yaml(cls, text: str) -> AgentArtifact:
        if yaml is None:
            raise ArtifactError('PyYAML 未安装，无法解析 agent.yaml')
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ArtifactError(f'agent.yaml 不是合法 YAML: {error}') from error
        if not isinstance(data, Mapping):
            raise ArtifactError('agent.yaml 顶层必须是映射（apiVersion/kind/metadata/spec）')
        return cls.from_dict(data, raw_yaml=text)


def load_artifact(path: str | Path) -> AgentArtifact:
    """从文件加载 artifact。"""
    p = Path(path)
    if not p.exists():
        raise ArtifactError(f'artifact 文件不存在: {p}')
    return AgentArtifact.from_yaml(p.read_text(encoding='utf-8'))


def parse_tool_ref(ref: str) -> tuple[str, str]:
    """把 `shell@v3` 拆成 (shell, v3)；裸名字返回 (name, '')。

    版本引用是治理面的形态（§4.4.2）：Agent Artifact 用版本引用，
    避免上游升级打断线上。
    """
    text = str(ref or '').strip()
    if '@' in text:
        name, _, version = text.partition('@')
        return name, version
    return text, ''


# ── 校验 ─────────────────────────────────────────────────
def _validate_shape(data: Mapping[str, Any]) -> None:
    api = str(data.get('apiVersion') or '')
    kind = str(data.get('kind') or '')
    if api and api != API_VERSION:
        raise ArtifactError(f'不支持的 apiVersion: {api}（期望 {API_VERSION}）')
    if kind and kind != KIND_AGENT:
        raise ArtifactError(f'不支持的 kind: {kind}（期望 {KIND_AGENT}）')
    meta = data.get('metadata')
    if not isinstance(meta, Mapping) or not str(meta.get('name') or '').strip():
        raise ArtifactError('metadata.name 必填：没有名字的资产无法被纳管')


def _validate_semantics(a: AgentArtifact) -> None:
    name = a.metadata.name
    if not name.strip():
        raise ArtifactError('metadata.name 不能为空')
    if not a.metadata.version.strip():
        raise ArtifactError(f'{name}: metadata.version 不能为空')
    if a.spec_kernel not in KNOWN_KERNELS:
        raise ArtifactError(
            f'{name}: 未知执行架构 {a.spec_kernel!r}（可选: {KNOWN_KERNELS}）')
    for ref in a.spec_tools:
        if not _TOOL_REF.match(ref):
            raise ArtifactError(
                f'{name}: 工具引用不合法 {ref!r} —— 期望 name 或 name@version')
    for layer in a.spec_context.layers:
        if layer not in KNOWN_CONTEXT_LAYERS:
            raise ArtifactError(
                f'{name}: 未知记忆层 {layer!r}（可选: {KNOWN_CONTEXT_LAYERS}）')
    for ref in a.spec_policies.approval:
        if not _TOOL_REF.match(ref):
            raise ArtifactError(
                f'{name}: 审批策略里的工具引用不合法 {ref!r}')


# ── 小工具（与 infra/eval/run_version.py 同一套规范形式）────────
def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), default=str)


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


__all__ = [
    'API_VERSION',
    'KIND_AGENT',
    'KNOWN_KERNELS',
    'AgentArtifact',
    'ArtifactError',
    'ArtifactMetadata',
    'ContextSpec',
    'CostModel',
    'ModelSpec',
    'PolicySpec',
    'RuntimeSpec',
    'load_artifact',
    'parse_tool_ref',
]
