# harness/conversation.py
# 通用会话管理 — 多会话历史维护 + 上下文裁剪。

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from aicf.infra.models.base import ChatMessage


@dataclass
class Conversation:
    """一次对话会话。"""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    def add(self, message: ChatMessage) -> "Conversation":
        self.messages.append(message)
        return self

    def add_text(self, role: str, content: str) -> "Conversation":
        return self.add(ChatMessage(role=role, content=content))

    def history(self, *, max_messages: Optional[int] = None,
                max_chars: Optional[int] = None) -> list[ChatMessage]:
        """返回裁剪后的历史（非 system 消息受 max_messages 限制）。"""
        msgs = [m for m in self.messages if m.role != "system"]
        if max_messages is not None and len(msgs) > max_messages:
            msgs = msgs[-max_messages:]
        if max_chars is not None:
            total = 0
            kept = []
            for m in reversed(msgs):
                total += len(m.content)
                if total > max_chars and kept:
                    break
                kept.append(m)
            msgs = list(reversed(kept))
        return msgs

    def clear(self) -> None:
        self.messages.clear()

    def __len__(self) -> int:
        return len(self.messages)

    def __bool__(self) -> bool:
        # 会话对象作为实体始终为真，避免空会话被 __len__ == 0 判为假
        return True


class ConversationManager:
    """多会话管理。"""

    def __init__(self):
        self._conversations: dict[str, Conversation] = {}

    def create(self, *, title: str = "", session_id: Optional[str] = None,
               **meta) -> Conversation:
        conv = Conversation(session_id=session_id or uuid.uuid4().hex,
                            title=title, meta=meta)
        self._conversations[conv.session_id] = conv
        return conv

    def get(self, session_id: str) -> Optional[Conversation]:
        return self._conversations.get(session_id)

    def require(self, session_id: str) -> Conversation:
        conv = self._conversations.get(session_id)
        if conv is None:
            raise KeyError(f"会话不存在: {session_id}")
        return conv

    def delete(self, session_id: str) -> bool:
        return self._conversations.pop(session_id) is not None

    def sessions(self) -> list[Conversation]:
        return list(self._conversations.values())

    def __len__(self) -> int:
        return len(self._conversations)


# ── conversation state: draft-commit history, stable prefixes, compaction ──
#
# `Conversation` above is a flat message list.  Long-running engines need
# more: an in-flight turn staged in a draft and committed atomically, a
# stable prompt prefix whose fingerprint drives provider cache keys, and
# compaction that replaces old turns with a summary instead of dropping
# them.  `ManagedConversation` provides that on top of the same provider-
# shaped dicts the wire uses.

import hashlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from dataclasses import replace  # noqa: E402
from typing import Any, AsyncIterator, Callable, Iterable  # noqa: E402

from .usage import TokenBudget, TokenBudgetExceeded, estimate_tokens  # noqa: E402

PROMPT_VERSION = 'harness-v1'

# Text used to answer a tool call that never produced a result.  Providers
# reject an assistant message whose tool calls have no matching results, and
# a turn that is interrupted (or a checkpoint written mid-turn) leaves
# exactly that shape behind.
INTERRUPTED_TOOL_RESULT = (
    '[interrupted] this tool call did not run to completion; no result is '
    'available. Re-run it if the result is still needed.'
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).replace('\r\n', '\n').replace('\r', '\n')


def repair_messages(messages: Iterable[dict[str, Any]]
                    ) -> tuple[list[dict[str, Any]], int]:
    """Return a provider-safe copy of ``messages`` plus how many repairs it took.

    Two shapes break every wire in a different way and both are reachable
    here: an assistant message whose ``tool_calls`` were never answered (the
    turn was interrupted, the app crashed, or a checkpoint was written
    between the call and its result), and a ``tool`` message whose call no
    longer exists (a rewind or a compaction removed the assistant message
    but kept the result).  The first gets a synthetic result so the
    conversation stays answerable; the second is dropped.
    """
    repaired: list[dict[str, Any]] = []
    changed = 0
    pending: list[str] = []

    def answer_pending() -> None:
        nonlocal changed
        for call_id in pending:
            repaired.append({'role': 'tool', 'tool_call_id': call_id,
                             'content': INTERRUPTED_TOOL_RESULT})
            changed += 1
        pending.clear()

    for message in messages:
        if not isinstance(message, dict):
            changed += 1
            continue
        role = message.get('role')
        if role == 'tool':
            call_id = str(message.get('tool_call_id') or '')
            if call_id and call_id in pending:
                pending.remove(call_id)
                repaired.append(dict(message))
            else:
                # No assistant call owns this result; sending it would be
                # rejected as an unknown tool_use_id.
                changed += 1
            continue
        answer_pending()
        copy = dict(message)
        calls = copy.get('tool_calls')
        if role == 'assistant' and isinstance(calls, list):
            # Rebuild the list so repairing an id never edits the caller's
            # history in place.
            rebuilt: list[Any] = []
            for index, call in enumerate(calls):
                if not isinstance(call, dict):
                    changed += 1
                    continue
                call = dict(call)
                call_id = str(call.get('id') or '')
                if not call_id:
                    changed += 1
                    call_id = f'call_repair_{index}'
                    call['id'] = call_id
                rebuilt.append(call)
                if call_id not in pending:
                    pending.append(call_id)
            copy['tool_calls'] = rebuilt
        repaired.append(copy)
    answer_pending()
    return repaired, changed


def messages_need_repair(messages: Iterable[dict[str, Any]]) -> bool:
    """Cheap structural check, so the common case never copies the history."""
    pending: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            return True
        role = message.get('role')
        if role == 'tool':
            call_id = str(message.get('tool_call_id') or '')
            if call_id not in pending:
                return True
            pending.discard(call_id)
            continue
        if pending:
            return True
        if role == 'assistant':
            for call in message.get('tool_calls') or []:
                if isinstance(call, dict):
                    pending.add(str(call.get('id') or ''))
    return bool(pending)


def normalized_endpoint(endpoint: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(endpoint.strip())
    path = parts.path.rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, '', ''))


def stable_tools(tools: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    def name(tool: dict[str, Any]) -> str:
        function = tool.get('function', tool)
        return str(function.get('name', ''))

    return tuple(json.loads(canonical_json(tool)) for tool in sorted(tools, key=name))


@dataclass(frozen=True)
class StablePrefix:
    """The immutable head of a request: system + tool schemas, fingerprinted.

    Providers cache a prompt by its prefix; the fingerprint summarizes
    everything that would invalidate the cache.  Any change to system or
    tools yields a new fingerprint, and the caller bumps ``generation`` so
    telemetry can tell cache hits apart.
    """

    generation: int
    prompt_version: str
    provider: str
    endpoint: str
    model: str
    system: str
    tools: tuple[dict[str, Any], ...]
    fingerprint: str

    @classmethod
    def create(cls, *, provider: str, endpoint: str, model: str, system: str,
               tools: Iterable[dict[str, Any]], generation: int = 1,
               wire: str = '') -> 'StablePrefix':
        canonical_tool_list = stable_tools(tools)
        canonical_endpoint = normalized_endpoint(endpoint)
        canonical_system = system.replace('\r\n', '\n').replace('\r', '\n')
        payload = {
            'provider': provider,
            'endpoint': canonical_endpoint,
            'model': model,
            'system': canonical_system,
            'tools': canonical_tool_list,
            'prompt_version': PROMPT_VERSION,
            'wire': wire,
        }
        fingerprint = 'sha256:' + hashlib.sha256(
            canonical_json(payload).encode('utf-8')).hexdigest()
        return cls(generation, PROMPT_VERSION, provider, canonical_endpoint, model,
                   canonical_system, canonical_tool_list, fingerprint)


@dataclass
class CompactionPlan:
    removed: list[dict[str, Any]]
    kept_messages: list[dict[str, Any]]
    target_tokens: int


@dataclass
class ManagedConversation:
    """Committed history, an in-flight draft and the compaction archive.

    The draft holds the current turn's messages.  A turn stages user,
    assistant and tool messages into it and commits atomically on success;
    on failure the draft is rolled back (or partially committed after
    repair) so the stored history never shows a half-finished turn.
    """

    stable_prefix: StablePrefix
    committed: list[dict[str, Any]]
    draft: list[dict[str, Any]] = field(default_factory=list)
    archived: list[dict[str, Any]] = field(default_factory=list)
    _revision: int = 0
    _token_cache: tuple[int, int] | None = None

    def _touch(self) -> None:
        self._revision += 1
        self._token_cache = None

    def request_messages(self) -> list[dict[str, Any]]:
        return [*self.committed, *self.draft]

    def stage(self, *messages: dict[str, Any]) -> None:
        if messages:
            self.draft.extend(messages)
            self._touch()

    def commit(self) -> None:
        if not self.draft:
            return
        self.committed.extend(self.draft)
        self.draft.clear()
        self._touch()

    def rollback(self) -> None:
        if self.draft:
            self.draft.clear()
            self._touch()

    def restore(self, archived: Iterable[dict[str, Any]], generation: int) -> None:
        self.draft.clear()
        self.archived[:] = archived
        self.stable_prefix = replace(
            self.stable_prefix, generation=max(1, int(generation)))
        self._touch()

    def estimated_tokens(self) -> int:
        # The UI asks for this several times per frame; reuse the last result
        # until the conversation actually changes.
        if self._token_cache is not None and self._token_cache[0] == self._revision:
            return self._token_cache[1]
        try:
            total = estimate_tokens(self.committed) + estimate_tokens(self.draft)
        except (RuntimeError, TypeError, ValueError):
            # The worker thread may be appending while the UI samples this.
            return self._token_cache[1] if self._token_cache else 0
        self._token_cache = (self._revision, total)
        return total

    def needs_compaction(self, budget: TokenBudget, threshold_percent: int = 85) -> bool:
        usable = budget.usable()
        if usable <= 0:
            return True
        used = self.estimated_tokens()
        return used >= usable * threshold_percent / 100

    def compaction_plan(self, target_tokens: int,
                        keep_recent_turns: int = 2) -> CompactionPlan | None:
        """Select complete historical turns for replacement without mutating state."""
        if not self.committed:
            return None
        groups = _conversation_groups(self.committed)
        keep_recent = max(0, min(keep_recent_turns, len(groups)))
        kept: list[list[dict[str, Any]]] = list(groups[len(groups) - keep_recent:]) \
            if keep_recent else []
        kept_tokens = sum(estimate_tokens(group) for group in kept)
        keep_budget = max(1, target_tokens * 2 // 3)
        for group in reversed(groups[:len(groups) - keep_recent]):
            size = estimate_tokens(group)
            if kept and kept_tokens + size > keep_budget:
                break
            kept.insert(0, group)
            kept_tokens += size
        removed_count = len(groups) - len(kept)
        if removed_count <= 0:
            return None
        removed = [message for group in groups[:removed_count] for message in group]
        kept_messages = [message for group in kept for message in group]
        return CompactionPlan(removed, kept_messages, target_tokens)

    def apply_compaction(self, plan: CompactionPlan, summary: dict[str, Any]) -> int:
        if not plan.removed:
            return 0
        # Keep the summary as its own user message.  Merging it into the first
        # retained user message hid that real turn from turn_starts() and
        # broke rewind (and edit prefill) after any compaction.
        self.archived.extend(plan.removed)
        self.committed[:] = [summary, *plan.kept_messages]
        self.stable_prefix = replace(
            self.stable_prefix, generation=self.stable_prefix.generation + 1)
        self._touch()
        return len(plan.removed)

    def invalidate(self) -> None:
        """Drop cached estimates after the message lists were replaced."""
        self._touch()

    def enforce_budget(self, budget: TokenBudget,
                       keep_recent_turns: int = 2) -> dict[str, int | bool]:
        available = budget.usable()
        draft_tokens = estimate_tokens(self.draft)
        if draft_tokens > available:
            _trim_tool_outputs(self.draft, max(256, available // 2))
            draft_tokens = estimate_tokens(self.draft)
        if draft_tokens > available:
            raise TokenBudgetExceeded(
                f'the current turn needs about {draft_tokens} tokens; '
                f'the usable budget is {available}')
        committed_budget = available - draft_tokens
        before = estimate_tokens(self.committed)
        removed = 0
        if before > committed_budget:
            plan = self.compaction_plan(committed_budget, keep_recent_turns)
            if plan is not None:
                summary = structured_summary(
                    plan.removed, max_tokens=max(256, committed_budget // 3))
                removed = self.apply_compaction(plan, summary)
        after = estimate_tokens(self.committed)
        if after > committed_budget:
            _trim_tool_outputs(self.committed, max(256, committed_budget // 2))
            self._touch()
            after = estimate_tokens(self.committed)
        if after > committed_budget:
            raise TokenBudgetExceeded(
                f'history needs about {after} tokens; the usable budget is '
                f'{committed_budget}')
        return {
            'compacted': bool(removed), 'removed_messages': removed,
            'committed_tokens': after, 'draft_tokens': draft_tokens,
        }


def _conversation_groups(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    for message in messages:
        if message.get('role') == 'user' or not groups:
            groups.append([])
        groups[-1].append(message)
    return groups


def _message_text(message: dict[str, Any], limit: int = 600) -> str:
    if not isinstance(message, dict):
        return str(message)[:limit]
    content = message.get('content') or ''
    if not isinstance(content, str):
        content = canonical_json(content)
    content = re.sub(r'\s+', ' ', content).strip()
    if len(content) > limit:
        content = content[:limit] + '...'
    calls = message.get('tool_calls') or []
    if isinstance(calls, dict):
        calls = [calls]
    if isinstance(calls, list):
        names = [
            str(call.get('function', {}).get('name', ''))
            for call in calls if isinstance(call, dict)
            and isinstance(call.get('function'), dict)
        ]
        names = [name for name in names if name]
        if names:
            content = f'{content} [tools: {", ".join(names)}]'.strip()
    return content


def structured_summary(messages: list[dict[str, Any]],
                       max_tokens: int = 2_000) -> dict[str, Any]:
    """Deterministic fallback summary used when a streamed summary fails."""
    facts: list[str] = []
    files: list[str] = []
    commands: list[str] = []
    last_results: list[str] = []
    active_task = ''
    for message in messages:
        role = message.get('role', 'unknown')
        text = _message_text(message, limit=900)
        if not text:
            continue
        if not active_task and role == 'user' and '<conversation_summary>' not in text:
            active_task = text[:400]
        facts.append(f'- {role}: {text}')
        files.extend(re.findall(r'(?:[A-Za-z]:\\|\.?\.?/)[^\s`"\']+', text))
        if role == 'tool':
            commands.append(f'- {text[:300]}')
            last_results.append(text[:400])
    max_chars = max_tokens * 4
    fixed_reserve = min(1_200, max_chars // 2)
    fact_budget = max(128, max_chars - fixed_reserve)
    selected: list[str] = []
    used = 0
    for fact in reversed(facts):
        if selected and used + len(fact) + 1 > fact_budget:
            break
        selected.insert(0, fact[:fact_budget])
        used += len(selected[0]) + 1
    goal_line = f'- {active_task}' if active_task else \
        'Continue the active user task using the preserved facts below.'
    body = '\n'.join([
        '## Goal',
        goal_line,
        '## State of work',
        '- The task is NOT finished. Continue from the completed work below; do not redo it.',
        '## Confirmed facts',
        *selected,
        '## Decisions and constraints',
        '- Earlier messages were compacted deterministically to fit the context window.',
        '## Files changed',
        *[f'- {path}' for path in dict.fromkeys(files[-12:])],
        '## Commands and test results',
        *commands[-10:],
        '## Last tool results',
        *[f'- {line}' for line in last_results[-3:]],
        '## Unresolved items',
        '- Re-check archived history when exact earlier wording is required.',
    ])
    return {'role': 'user',
            'content': f'<conversation_summary>\n{body}\n</conversation_summary>'}


COMPACTION_SYSTEM = (
    'You are the conversation compactor. Return only a concise, durable context. '
    'Preserve the user objective, concrete progress (files edited and their '
    'state, commands run and outcomes, latest tool results), hard constraints, '
    'decisions, file paths, identifiers, and unresolved work. The task is not '
    'finished; the summary must let the next turn continue exactly where it '
    'stopped. Do not invent facts and do not call tools.'
)


def compaction_source(messages: list[dict[str, Any]], max_tokens: int = 24_000) -> str:
    limit = max(1, max_tokens) * 4
    chunks: list[str] = []
    used = 0
    for message in messages:
        role = message.get('role', 'unknown')
        text = _message_text(message, limit=2_000)
        chunk = f'{role}: {text}'
        if chunks and used + len(chunk) + 1 > limit:
            break
        chunks.append(chunk)
        used += len(chunk) + 1
    return '\n'.join(chunks)


async def stream_compact(conversation: ManagedConversation, target_tokens: int,
                         stream_factory: Callable[..., AsyncIterator[Any]],
                         emit: Callable[[str], None] | None = None,
                         keep_recent_turns: int = 2) -> int:
    """Compact with a streaming model call and a deterministic fallback.

    ``stream_factory(messages, *, system, max_tokens, tools)`` returns an
    async iterator of client events: str for text deltas, dict otherwise.
    Any failure (including an interrupt raised as an exception) falls back
    to the deterministic summary, so compaction never loses the turn.
    """
    plan = conversation.compaction_plan(target_tokens, keep_recent_turns)
    if plan is None:
        return 0
    prompt = (
        '<compaction_request>\n'
        'Rewrite the following earlier conversation into durable context.\n\n'
        f'{compaction_source(plan.removed)}\n'
        '</compaction_request>'
    )
    parts: list[str] = []
    try:
        events = stream_factory(
            [{'role': 'user', 'content': prompt}],
            system=COMPACTION_SYSTEM,
            max_tokens=max(256, min(2_048, target_tokens // 3)),
            tools=None,
        )
        if inspect.isawaitable(events):
            # tolerate async factories: they return a coroutine, not a stream
            events = await events
        async for event in events:
            if isinstance(event, str):
                content = event
            elif isinstance(event, dict) and isinstance(event.get('content'), str):
                content = event['content']
            else:
                continue
            if content:
                parts.append(content)
                if emit is not None:
                    emit(content)
    except Exception:
        parts.clear()
    summary_text = ''.join(parts).strip()
    if summary_text:
        summary = {
            'role': 'user',
            'content': f'<conversation_summary>\n{summary_text}\n</conversation_summary>',
        }
    else:
        summary = structured_summary(
            plan.removed, max_tokens=max(256, target_tokens // 3))
    return conversation.apply_compaction(plan, summary)


def _trim_tool_outputs(messages: list[dict[str, Any]], total_tokens: int) -> None:
    tools = [message for message in messages if message.get('role') == 'tool']
    if not tools:
        return
    per_tool_chars = max(256, total_tokens * 4 // len(tools))
    for message in tools:
        content = message.get('content')
        if isinstance(content, str) and len(content) > per_tool_chars:
            head = per_tool_chars * 2 // 3
            tail = per_tool_chars - head
            message['content'] = (
                f'{content[:head]}\n... <tool output compacted> ...\n{content[-tail:]}'
            )
