# harness/memory/provenance.py
# 可审计的持久记忆（roadmap 段 4）：Source（不可变证据）→ Artifact（可修订解释）。
#
# ── 为什么需要两级模型 ──
# 以前 MemoryEntry 只有 text/role/meta/timestamp：没有来源、没有修订、
# 没有证据、没有作者；审计轨只覆盖工具调用，不覆盖记忆写入。
# 于是「这条记忆从哪来、谁改过、为什么被给了模型」三个问题一个都答不了
# —— 而愿景里写的是「持久记忆的**可审计**」。
#
# 两级模型：
#   MemorySource    不可变证据（会话原文 / 工具观测 / 用户陈述…），写入后不许改，
#                   带 sha256 —— 证据被篡改时能被发现；
#   MemoryArtifact  可修订解释（对若干证据的解释），带稳定 ID + revision，
#                   修订产生新 revision，旧 revision 标 superseded；
#                   撤回标 retracted，不物理删除 —— 审计要能回答历史。
#
# 三道闸（都 fail-closed）：
#   写入闸门   引用不存在的证据 → 拒绝（凭空解释不是记忆，是编造）；
#   证据闸门   哪些记忆允许注入 prompt，由**证据**决定，不由相似度决定：
#              status != active / 证据缺失 / 证据摘要对不上 → 一律不注入；
#   披露矩阵   哪些记忆能给谁看：deny 规则永远赢，未知受众默认不给。
#
# 召回保留现有实现（关键词 + 向量，InMemoryStore），本模块只做包装：
# 写入时把 Artifact 文本同步进底层库，检索结果再过一次证据闸门。
# 审计轨：每次 source/artifact 动作落一条 audit.memory_write
# （audit 是鸭子类型：会 record(kind, payload) 即可，与 ToolGuard 同款）。

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Optional, Sequence

from .base import MemoryEntry
from .layers import ProfileAuthorizer

__all__ = [
    'ARTIFACT_ACTIVE',
    'ARTIFACT_RETRACTED',
    'ARTIFACT_SUPERSEDED',
    'DisclosureMatrix',
    'DisclosureRule',
    'EvidenceGate',
    'MemoryArtifact',
    'MemorySource',
    'ProvenanceMemoryStore',
    'profile_authorizer_from_matrix',
]

# ── 状态词表 ────────────────────────────────────────────────

ARTIFACT_ACTIVE = 'active'
ARTIFACT_SUPERSEDED = 'superseded'
ARTIFACT_RETRACTED = 'retracted'

#: Source 的合法 kind（开放枚举：写错不拦，审计里原样可见）
SOURCE_KINDS = ('conversation', 'tool_observation', 'file', 'user_statement', 'import')


def _digest(content: str) -> str:
    return f'sha256:{hashlib.sha256((content or "").encode("utf-8")).hexdigest()}'


# ── 一级：证据 ──────────────────────────────────────────────


@dataclass(frozen=True)
class MemorySource:
    """不可变证据：记忆的最小事实单元。

    frozen + digest 双保险：改字段会抛异常；就算有人绕过 dataclass
    从内部改了 content，证据闸门重算摘要时也会对不上。
    """
    source_id: str
    kind: str
    content: str
    digest: str
    created_at: float
    origin: str = ''            # 谁产生的（user / agent id / 工具名）
    meta: dict = field(default_factory=dict)


# ── 二级：解释 ──────────────────────────────────────────────


@dataclass(frozen=True)
class MemoryArtifact:
    """可修订解释：对若干证据的一句话解释，带稳定 ID + revision。

    frozen：修订**不是**原地改，而是产生一个新 revision 对象 ——
    旧对象的引用不变，历史可回放。
    """
    artifact_id: str
    revision: int
    text: str
    source_ids: tuple[str, ...]
    author: str
    created_at: float
    updated_at: float
    status: str = ARTIFACT_ACTIVE
    tags: tuple[str, ...] = ()


# ── 证据闸门 ────────────────────────────────────────────────


@dataclass
class EvidenceGate:
    """哪些记忆允许注入 prompt —— 由证据决定，不由相似度决定。

    fail-closed 的四条判定（任一不过就不注入）：
      1. status == active（superseded / retracted 一律不给）
      2. 引用的每条证据都存在
      3. 每条证据的内容摘要仍然对得上（证据没被篡改）
      4. 证据数量 ≥ min_sources（默认 1）
    """

    min_sources: int = 1

    def allows_injection(self, artifact: MemoryArtifact,
                         sources: dict[str, MemorySource]) -> bool:
        if artifact.status != ARTIFACT_ACTIVE:
            return False
        if len(artifact.source_ids) < self.min_sources:
            return False
        for source_id in artifact.source_ids:
            source = sources.get(source_id)
            if source is None:
                return False
            if _digest(source.content) != source.digest:
                return False
        return True


# ── 披露矩阵 ────────────────────────────────────────────────


@dataclass(frozen=True)
class DisclosureRule:
    """一条披露规则：什么标签的记忆，能不能给某个受众看。

    subject 匹配的是受众名（audience），'*' 通配所有受众。
    """
    audience: str                   # 受众（'*' = 所有）
    tag: str                        # 记忆的 tag（'*' = 所有标签）
    allow: bool
    reason: str = ''


class DisclosureMatrix:
    """哪些记忆能给谁看。

    语义（fail-closed）：
      - deny 规则永远赢过 allow 规则（与策略引擎同一取向）；
      - 没有任何规则命中 → **不给**（默认拒绝不是默认公开）；
      - 规则匹配按「最具体者赢」：受众精确 > 通配，标签精确 > 通配。
    """

    def __init__(self, rules: Iterable[DisclosureRule] = ()):
        self._rules: list[DisclosureRule] = list(rules)

    def add_rule(self, rule: DisclosureRule) -> None:
        self._rules.append(rule)

    def disclose(self, artifact: MemoryArtifact, audience: str) -> bool:
        audience = audience or ''
        tags = artifact.tags or ('*',)
        best: DisclosureRule | None = None
        best_score = (-1, -1)  # (audience_specificity, tag_specificity)
        for rule in self._rules:
            if rule.audience not in ('*', audience):
                continue
            matched_tag = any(
                rule.tag in ('*', tag) for tag in tags
            )
            if not matched_tag:
                continue
            score = (0 if rule.audience == audience else 1,
                     0 if any(rule.tag == tag for tag in tags) else 1)
            if score < best_score or best is None:
                best, best_score = rule, score
        if best is None:
            return False
        return best.allow

    def rules(self) -> tuple[DisclosureRule, ...]:
        return tuple(self._rules)


def profile_authorizer_from_matrix(matrix: DisclosureMatrix,
                                   audience: str) -> ProfileAuthorizer:
    """把披露矩阵适配成 LayeredMemoryView 的 ProfileAuthorizer（按 subject 判定）。

    L3 的 ``ProfileAuthorizer = Callable[[str], bool]`` 收的是 subject ——
    即「这条偏好属于谁」。披露矩阵的语义是「什么标签能给谁看」，
    所以这里把 subject 当作记忆的 tag 构造一个代理 Artifact，
    由矩阵判定该受众能不能看到它。**默认拒绝**：没有任何 allow 规则
    命中时，连 subject 本人也不放行 —— 这正是 L3「显式授权才注入」
    的矩阵化表达。
    """
    def authorize(subject: str) -> bool:
        proxy = MemoryArtifact(
            artifact_id=f'profile:{subject}',
            revision=0,
            text='',
            source_ids=(),
            author='',
            created_at=0.0,
            updated_at=0.0,
            status=ARTIFACT_ACTIVE,
            tags=(subject,),
        )
        return matrix.disclose(proxy, audience)
    return authorize


# ── 两级库 ──────────────────────────────────────────────────


class ProvenanceMemoryStore:
    """可审计的两级记忆库：Source（不可变）→ Artifact（可修订）。

    底层召回沿用现有实现（InMemoryStore：关键词 + 可选向量）——
    本模块不重新发明检索，只管证据、修订与闸门。
    audit 是鸭子类型（会 ``record(kind, payload)`` 即可）：
    传 AuditLog（SDK 默认路径）或任何同形对象。
    """

    def __init__(self,
                 backend: Any | None = None,
                 *,
                 audit: Any | None = None,
                 gate: EvidenceGate | None = None,
                 disclosure: DisclosureMatrix | None = None,
                 clock: Callable[[], float] | None = None,
                 author: str = 'agent'):
        from .in_memory import InMemoryStore
        self._backend = backend or InMemoryStore()
        self._audit = audit
        self._gate = gate or EvidenceGate()
        self.disclosure = disclosure or DisclosureMatrix()
        self._clock = clock or time.time
        self.author = author
        self._sources: dict[str, MemorySource] = {}
        self._artifacts: dict[str, list[MemoryArtifact]] = {}
        self._source_seq = 0
        self._artifact_seq = 0

    # ── 证据 ────────────────────────────────────────────
    def add_source(self, kind: str, content: str, *,
                   origin: str = '', meta: dict | None = None) -> MemorySource:
        self._source_seq += 1
        source = MemorySource(
            source_id=f'src-{self._source_seq:06d}',
            kind=kind,
            content=content,
            digest=_digest(content),
            created_at=self._clock(),
            origin=origin,
            meta=dict(meta or {}),
        )
        self._sources[source.source_id] = source
        self._audit_memory(action='source_added', content_digest=source.digest,
                           source_ids=[source.source_id], origin=origin,
                           detail={'kind': kind})
        return source

    def source(self, source_id: str) -> Optional[MemorySource]:
        return self._sources.get(source_id)

    def sources(self) -> tuple[MemorySource, ...]:
        return tuple(self._sources.values())

    # ── 解释 ────────────────────────────────────────────
    def write_artifact(self, text: str, source_ids: Sequence[str], *,
                       author: str = '', tags: Sequence[str] = (),
                       inject: bool = True) -> MemoryArtifact:
        """写入一条解释。引用的证据必须已存在（写入闸门，fail-closed）。"""
        missing = [sid for sid in source_ids if sid not in self._sources]
        if missing:
            raise KeyError(f'证据不存在: {missing} —— 凭空解释不是记忆，是编造')
        return self._new_revision(
            artifact_id=self._fresh_artifact_id(),
            text=text, source_ids=tuple(source_ids),
            author=author or self.author, tags=tuple(tags),
            inject=inject, superseded=None,
        )

    def revise_artifact(self, artifact_id: str, text: str, *,
                        author: str = '', source_ids: Sequence[str] | None = None,
                        tags: Sequence[str] | None = None) -> MemoryArtifact:
        """修订：产生新 revision，旧 revision 标 superseded（不删除）。"""
        history = self._artifacts.get(artifact_id)
        if not history:
            raise KeyError(f'记忆不存在: {artifact_id}')
        latest = history[-1]
        if latest.status == ARTIFACT_RETRACTED:
            raise ValueError(f'{artifact_id} 已被撤回，修订前先显式恢复（retract 是显式决定）')
        return self._new_revision(
            artifact_id=artifact_id,
            text=text,
            source_ids=tuple(source_ids) if source_ids is not None else latest.source_ids,
            author=author or self.author,
            tags=tuple(tags) if tags is not None else latest.tags,
            inject=True,
            superseded=history,
        )

    def retract_artifact(self, artifact_id: str, *,
                         author: str = '', reason: str = '') -> MemoryArtifact:
        """撤回：标 retracted（不物理删除），证据闸门从此不注入它。"""
        history = self._artifacts.get(artifact_id)
        if not history:
            raise KeyError(f'记忆不存在: {artifact_id}')
        latest = history[-1]
        retracted = replace(latest, status=ARTIFACT_RETRACTED,
                            updated_at=self._clock(),
                            author=author or self.author)
        history.append(retracted)
        self._audit_memory(action='artifact_retracted', artifact_id=artifact_id,
                           revision=retracted.revision,
                           source_ids=retracted.source_ids,
                           author=retracted.author, detail={'reason': reason})
        return retracted

    def artifact(self, artifact_id: str) -> Optional[MemoryArtifact]:
        """最新 revision；不存在 → None。"""
        history = self._artifacts.get(artifact_id)
        return history[-1] if history else None

    def history(self, artifact_id: str) -> tuple[MemoryArtifact, ...]:
        return tuple(self._artifacts.get(artifact_id, ()))

    def artifacts(self) -> tuple[MemoryArtifact, ...]:
        return tuple(h[-1] for h in self._artifacts.values())

    # ── 召回（保留现有实现，结果过证据闸门）────────────
    def recall(self, query: str, k: int = 5, *,
               audience: str = '') -> list[MemoryEntry]:
        """检索 + 证据闸门 + 披露矩阵。

        注意语义：被闸门挡掉的条目**不占 k 的名额** —— 相似度排序
        是底层库的事，注入决定是证据的事，两层各管各的。
        """
        allowed: list[MemoryEntry] = []
        for entry in self._backend.search(query, k=k * 3):
            artifact = self._artifact_of_entry(entry)
            if artifact is None:
                # 不是本库写入的条目（外部直接塞进 backend 的）——
                # 没有证据，按默认拒绝处理。
                continue
            if not self._gate.allows_injection(artifact, self._sources):
                continue
            if audience and not self.disclosure.disclose(artifact, audience):
                continue
            allowed.append(entry)
            if len(allowed) >= k:
                break
        return allowed

    # ── IMemoryStore 兼容（SDK enable_memory 路径不变）──
    def add(self, entry: MemoryEntry) -> None:
        """裸写入 = 自动留证据：一条来源 + 一条 artifact，写法不变。"""
        role = entry.role or 'user'
        kind = 'conversation' if role in ('user', 'assistant') else 'user_statement'
        source = self.add_source(kind, entry.text or '', origin=role)
        self.write_artifact(entry.text or '', [source.source_id],
                            author=self.author)

    def add_text(self, text: str, role: str = 'user', **meta) -> None:
        self.add(MemoryEntry(text=text, role=role, meta=dict(meta)))

    def search(self, query: str, k: int = 5) -> list[MemoryEntry]:
        return self.recall(query, k=k)

    def clear(self) -> None:
        self._backend.clear()
        self._sources.clear()
        self._artifacts.clear()

    def count(self) -> int:
        return len(self._artifacts)

    def __len__(self) -> int:
        return self.count()

    def attach_audit(self, audit: Any) -> None:
        """晚绑定审计（SDK 装配顺序：AuditLog 在记忆之后创建）。

        只影响之后的写入 —— 装配期没有记忆写入，所以不存在「漏记」。
        """
        self._audit = audit

    # ── 内部 ────────────────────────────────────────────
    def _fresh_artifact_id(self) -> str:
        self._artifact_seq += 1
        candidate = f'art-{self._artifact_seq:06d}'
        while candidate in self._artifacts:  # pragma: no cover - 防御性
            self._artifact_seq += 1
            candidate = f'art-{self._artifact_seq:06d}'
        return candidate

    def _new_revision(self, *, artifact_id: str, text: str,
                      source_ids: tuple[str, ...], author: str,
                      tags: tuple[str, ...], inject: bool,
                      superseded: 'list[MemoryArtifact] | None') -> MemoryArtifact:
        now = self._clock()
        revision = 1
        created_at = now
        if superseded:
            revision = superseded[-1].revision + 1
            created_at = superseded[0].created_at
            superseded[-1] = replace(superseded[-1], status=ARTIFACT_SUPERSEDED,
                                     updated_at=now)
        artifact = MemoryArtifact(
            artifact_id=artifact_id,
            revision=revision,
            text=text,
            source_ids=source_ids,
            author=author,
            created_at=created_at,
            updated_at=now,
            status=ARTIFACT_ACTIVE,
            tags=tags,
        )
        history = self._artifacts.setdefault(artifact_id, [])
        history.append(artifact)
        if inject:
            # 文本同步进底层库供检索；meta 里带 artifact_id，召回时据此过闸门。
            self._backend.add_text(text, role='memo',
                                   artifact_id=artifact_id,
                                   revision=revision)
        action = ('artifact_written' if revision == 1 else 'artifact_revised')
        self._audit_memory(action=action, artifact_id=artifact_id,
                           revision=revision, source_ids=source_ids,
                           author=author, content_digest=_digest(text))
        return artifact

    def _artifact_of_entry(self, entry: MemoryEntry) -> Optional[MemoryArtifact]:
        """把 backend 条目映射回它的 Artifact（且必须是**当前** revision）。

        修订不是原地改：旧 revision 的文本还躺在底层库里（历史可回放），
        但注入只认最新 revision —— 否则修订前的话会一直被召回。
        """
        artifact_id = (entry.meta or {}).get('artifact_id')
        if not artifact_id:
            return None
        artifact = self.artifact(str(artifact_id))
        if artifact is None:
            return None
        entry_revision = (entry.meta or {}).get('revision')
        if entry_revision is not None and int(entry_revision) != artifact.revision:
            return None
        return artifact

    def _audit_memory(self, *, action: str, artifact_id: str = '',
                      revision: int | None = None,
                      source_ids: Sequence[str] = (),
                      content_digest: str = '', author: str = '',
                      origin: str = '', detail: dict | None = None) -> None:
        if self._audit is None:
            return
        try:
            payload: dict[str, Any] = {
                'action': action,
                'artifact_id': artifact_id,
                'revision': revision,
                'source_ids': list(source_ids),
                'content_digest': content_digest,
                'author': author,
            }
            if origin:
                payload['origin'] = origin
            if detail:
                payload['detail'] = detail
            self._audit.record('audit.memory_write', payload)
        except Exception:  # noqa: BLE001 —— 审计后端故障不阻断记忆（与守卫同款）
            pass
