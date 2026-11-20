# infra/eval/trace_store.py
# Trace 数据结构 + 持久化 + 检索。
#
# ── 为什么这里自己定义一份 Trace，而不是直接用 harness 的事件对象？ ──
# 策划案 §6.2 明确要求：`infra/eval` **不 import** `harness`。
# 原因不是洁癖，而是依赖方向：harness 是 Kernel Plane（执行内核），
# infra 是 Runtime/Control/Evolution Plane；一旦 infra 反向依赖 harness，
# 「内核可替换」这件事就不成立了（换内核 = 换评测层）。
#
# 所以评测层只认**通用数据结构**：一份自描述的 trace 记录。
# harness 侧要把自己的事件流喂进评测层，只需要在边界上做一次适配
# （本文件 `trace_from_events` 就是这个适配器），而不是让评测层认识
# harness 的事件类型。
#
# ── 为什么 effect 默认是 "unknown" 而不是 "pure"？ ──
# `no_side_effect` 是一条**安全断言**。安全断言必须 fail-closed：
# 拿不到副作用信息时，正确的做法是「判失败并说明信息缺失」，
# 而不是默认无害、把风险悄悄放过去。未知即危险（unknown 即 unsafe）。

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Optional, Sequence

#: 工具副作用分级（与 harness/tools/spec.py 的 effect 词表对齐）。
#: pure        —— 无副作用，可自由重放
#: idempotent  —— 有副作用但重复执行安全
#: effectful   —— 有副作用且重复执行危险
EFFECT_PURE = "pure"
EFFECT_IDEMPOTENT = "idempotent"
EFFECT_EFFECTFUL = "effectful"
EFFECT_UNKNOWN = "unknown"

#: 认定为「没有副作用」的 effect 取值。
#: 注意 EFFECT_UNKNOWN 不在其中 —— 见文件头注释的 fail-closed 说明。
NO_SIDE_EFFECT_EFFECTS = frozenset({EFFECT_PURE})

#: 一次性读取 JSON 时的默认编码。
_ENCODING = "utf-8"


@dataclass
class ToolCall:
    """一次工具调用的通用记录。

    只描述「发生了什么」，不含 harness 的类型信息 —— 这样评测层
    对任何执行内核都成立（Kernel SPI 的四种架构产出的都是这个形状）。
    """

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    #: 工具返回的文本结果；None 表示「还没拿到结果」。
    result: Optional[str] = None
    #: 工具报错时的信息；None 表示没报错。
    error: Optional[str] = None
    duration_ms: float = 0.0
    #: 副作用分级；见模块级 EFFECT_* 常量。
    effect: str = EFFECT_UNKNOWN
    #: 是否被策略/审批拒绝（denied=True 时 result 通常为 None、error 有值）。
    denied: bool = False

    @property
    def has_result(self) -> bool:
        """是否拿到了结果或错误。

        L1 规则 `tool_call_without_result` 判的就是这个：
        发起了调用却没有对应结果 —— 说明轨迹断在半路，
        下游拿到的会话是不完整的（重放会得到不同答案）。
        """
        return self.result is not None or self.error is not None

    @property
    def has_side_effect(self) -> bool:
        """这次调用是否可能有副作用（unknown 也算 —— fail-closed）。"""
        return self.effect not in NO_SIDE_EFFECT_EFFECTS

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": dict(self.args),
            "call_id": self.call_id,
            "result": self.result,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "effect": self.effect,
            "denied": self.denied,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ToolCall":
        return cls(
            name=str(data.get("name") or ""),
            args=dict(data.get("args") or {}),
            call_id=str(data.get("call_id") or ""),
            result=data.get("result"),
            error=data.get("error"),
            duration_ms=float(data.get("duration_ms") or 0.0),
            effect=str(data.get("effect") or EFFECT_UNKNOWN),
            denied=bool(data.get("denied", False)),
        )


@dataclass
class Trace:
    """一次运行的完整轨迹（评测的输入单元）。

    字段刻意做得很浅：**只放评测需要的东西**。
    评测要回答的问题是「这次行为对不对、好不好、贵不贵、安全吗」，
    任何与这四问无关的字段都不该进 Trace —— 否则 trace 会慢慢
    变成第二个会话记录，既难维护又容易在评测层泄漏业务细节。
    """

    trace_id: str = ""
    session_id: str = ""
    run_version_id: str = ""
    #: 该 trace 对应的评测 case id（离线回放时写入）。
    case_id: str = ""
    #: 用户输入。
    input: str = ""
    #: 最终输出（agent 的正式回答）。
    output: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    #: 消息序列（role/content），用于结构完整性检查。
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: 模型思维链（若内核记录了）。用来判定「思维链泄漏到最终答案」。
    reasoning: str = ""
    #: token 用量：input_tokens / output_tokens / total_tokens。
    usage: dict[str, int] = field(default_factory=dict)
    #: 本次运行的花费（货币单位由调用方约定，默认 0）。
    cost: float = 0.0
    #: 端到端耗时（毫秒）。
    latency_ms: float = 0.0
    #: 运行级错误信息；非空通常意味着这次 run 失败。
    error: str = ""
    #: 原始事件流（可选，保留原样便于排查）。
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """总 token 数。usage 里没写 total 就用 input+output 兜底。"""
        usage = self.usage or {}
        total = usage.get("total_tokens")
        if total is not None:
            return int(total)
        return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)

    @property
    def input_tokens(self) -> int:
        return int((self.usage or {}).get("input_tokens") or 0)

    @property
    def output_tokens(self) -> int:
        return int((self.usage or {}).get("output_tokens") or 0)

    @property
    def tool_names(self) -> list[str]:
        """按调用顺序的工具名列表。"""
        return [tc.name for tc in self.tool_calls]

    @property
    def called_tools(self) -> set[str]:
        return set(self.tool_names)

    @property
    def side_effect_tools(self) -> list[str]:
        """有副作用（或副作用未知）的工具名。"""
        return [tc.name for tc in self.tool_calls if tc.has_side_effect]

    @property
    def failed(self) -> bool:
        return bool(self.error)

    def metrics(self) -> dict[str, float]:
        """本条 trace 的指标快照（闸门与回归都基于它）。"""
        return {
            "cost_tokens": float(self.total_tokens),
            "input_tokens": float(self.input_tokens),
            "output_tokens": float(self.output_tokens),
            "latency_ms": float(self.latency_ms),
            "cost": float(self.cost),
            "tool_calls": float(len(self.tool_calls)),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "run_version_id": self.run_version_id,
            "case_id": self.case_id,
            "input": self.input,
            "output": self.output,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "messages": list(self.messages),
            "reasoning": self.reasoning,
            "usage": dict(self.usage),
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "events": list(self.events),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Trace":
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            session_id=str(data.get("session_id") or ""),
            run_version_id=str(data.get("run_version_id") or ""),
            case_id=str(data.get("case_id") or ""),
            input=str(data.get("input") or ""),
            output=str(data.get("output") or ""),
            tool_calls=[ToolCall.from_dict(tc) for tc in (data.get("tool_calls") or [])],
            messages=list(data.get("messages") or []),
            reasoning=str(data.get("reasoning") or ""),
            usage=dict(data.get("usage") or {}),
            cost=float(data.get("cost") or 0.0),
            latency_ms=float(data.get("latency_ms") or 0.0),
            error=str(data.get("error") or ""),
            events=list(data.get("events") or []),
        )


# ── 事件流 → Trace 的适配器 ──────────────────────────────────
#
# harness 侧的事件词表（harness/agent/events.py）里，
# tool_start / tool_end / text_end / usage / tool_intent 这些 kind
# 已经足够还原一条完整轨迹。本适配器**只读 dict**，
# 不 import aicf.harness —— 依赖方向仍然满足 §6.2。


def trace_from_events(
    events: Sequence[Mapping[str, Any]],
    *,
    trace_id: str = "",
    session_id: str = "",
    case_id: str = "",
    run_version_id: str = "",
    input: str = "",
) -> Trace:
    """把一串事件（dict）拼成一条 :class:`Trace`。

    容错原则：**缺字段不抛异常**。事件流可能来自不同版本的内核，
    少一个 kind 就少一段信息，不该让整条评测挂掉。
    真正需要严格判定的地方（比如「有 tool_calls 却缺结果」）
    由 L1 规则去发现，而不是在这里提前炸掉。
    """
    trace = Trace(trace_id=trace_id, session_id=session_id, case_id=case_id,
                  run_version_id=run_version_id, input=input)
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    output_parts: list[str] = []
    usage: dict[str, int] = {}

    def _key(payload: Mapping[str, Any]) -> str:
        return str(payload.get("call_id") or payload.get("id") or payload.get("name") or "")

    for raw in events or ():
        payload = dict(raw.get("payload") or {}) if "payload" in raw else dict(raw)
        kind = str(raw.get("kind") or payload.get("kind") or "")
        key = _key(payload)

        if kind == "tool_start":
            name = str(payload.get("name") or "")
            if not key:
                key = f"{name}#{len(order)}"
            if key not in calls:
                calls[key] = ToolCall(name=name, args=dict(payload.get("args") or {}), call_id=key)
                order.append(key)
            else:
                calls[key].args = dict(payload.get("args") or calls[key].args)
                calls[key].name = calls[key].name or name
        elif kind == "tool_intent":
            # effect 分级在这里出现（工具准入时写下的意图）。
            name = str(payload.get("tool") or "")
            target = calls.get(key)
            if target is None and name:
                target = ToolCall(name=name, call_id=key)
                calls[key] = target
                order.append(key)
            if target is not None:
                target.effect = str(payload.get("effect") or target.effect)
        elif kind == "tool_end":
            target = calls.get(key)
            if target is None:
                target = ToolCall(name=str(payload.get("name") or ""), call_id=key)
                calls[key] = target
                order.append(key)
            target.result = payload.get("output") if payload.get("output") is not None else target.result
            target.error = payload.get("error") if payload.get("error") is not None else target.error
            target.duration_ms = float(payload.get("duration") or target.duration_ms)
            if payload.get("effect"):
                target.effect = str(payload["effect"])
        elif kind == "tool_blocked":
            target = calls.get(key)
            if target is None:
                target = ToolCall(name=str(payload.get("tool") or ""), call_id=key)
                calls[key] = target
                order.append(key)
            target.denied = True
            target.error = str(payload.get("reason") or target.error or "blocked")
        elif kind == "text_end":
            text = payload.get("text")
            if text:
                output_parts.append(str(text))
        elif kind == "usage":
            for src, dst in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                             ("total_tokens", "total_tokens")):
                if payload.get(src) is not None:
                    usage[dst] = int(payload[src])
            if payload.get("latency_ms") is not None:
                trace.latency_ms = float(payload["latency_ms"])
        elif kind in ("run_finished", "turn_end"):
            stats = payload.get("stats") or {}
            if isinstance(stats, Mapping):
                for src in ("input_tokens", "output_tokens", "total_tokens"):
                    if stats.get(src) is not None:
                        usage[src] = int(stats[src])
                if stats.get("latency_ms") is not None:
                    trace.latency_ms = float(stats["latency_ms"])
        elif kind == "error":
            trace.error = str(payload.get("text") or payload.get("error") or "error")

    trace.tool_calls = [calls[k] for k in order]
    trace.output = "".join(output_parts)
    trace.usage = usage
    trace.events = [dict(e) for e in (events or ())]
    return trace


# ── JSONL 落地 ────────────────────────────────────────────
#
# Trace 用 JSONL 而不是单个 JSON：一次评测可能有几千条 trace，
# JSONL 可以边跑边追加（跑崩了也有前半程结果），且能被 jq / grep 直接看。


def write_trace_jsonl(path: str | Path, traces: Iterable[Trace]) -> int:
    """把 trace 写成 JSONL，返回写入条数。"""
    p = Path(path)
    if p.parent and str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with p.open("w", encoding=_ENCODING) as fh:
        for tr in traces:
            fh.write(json.dumps(tr.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_trace_jsonl(path: str | Path) -> list[Trace]:
    """读回 JSONL trace。空行跳过；坏行抛 ValueError（静默跳过会让评测少算用例）。"""
    out: list[Trace] = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding=_ENCODING) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Trace.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"{p}:{lineno} 不是合法的 trace JSONL: {exc}") from exc
    return out


# ── Usage accounting from the event stream ────────────────
#
# The kernel emits one `usage` event per model call (loop._emit_usage wired
# through the kernel telemetry port). The CLI run used to drop them, which
# left every trace with usage={} and cost=0.0 -- so the cost gate judged
# nothing. These helpers turn the event stream into the accounting a trace
# carries; run and eval read the same numbers from this one place.


def usage_from_events(events: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Aggregate `usage` events into one usage dict (Responses wire shape)."""
    input_tokens = 0
    output_tokens = 0
    for event in events or []:
        if not isinstance(event, Mapping) or event.get("kind") != "usage":
            continue
        payload = event.get("payload") or {}
        input_tokens += int(payload.get("input_tokens") or payload.get("prompt_tokens") or 0)
        output_tokens += int(payload.get("output_tokens") or payload.get("completion_tokens") or 0)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens}


def cost_from_events(events: Iterable[Mapping[str, Any]], pricing_name: str = "flash") -> float:
    """Price the `usage` events with the shared TokenMeter pricing table."""
    from aicf.infra.policy.token_meter import TokenMeter

    meter = TokenMeter(pricing_name=pricing_name)
    for event in events or []:
        if not isinstance(event, Mapping) or event.get("kind") != "usage":
            continue
        payload = event.get("payload") or {}
        if payload:
            meter.record(payload)
    return meter.cost


# ── SQLite 持久化 ─────────────────────────────────────────
#
# 表结构照策划案 §5.1 原样建（eval_dataset / eval_case / eval_run /
# eval_result / eval_gate_report / eval_badcase），
# 另外补两张表：
#   eval_trace        —— trace 本体必须有个地方放（§5.1 没列，但 TraceStore 没它就没意义）
#   eval_run_summary  —— run 的聚合指标（§5.1 的 eval_run 只存状态与时间，
#                        光靠 eval_result 重算聚合很啰嗦，且口径容易漂）
#   eval_result_payload —— 单条结果的完整载荷（group / critical / violations）。
#                        §5.1 的 eval_result 只存 score + metrics + failed_rules，
#                        从这三列重建不出「关键用例」标记与违反明细 ——
#                        而闸门恰恰靠它们判定（关键集通过率、安全 0 容忍）。
#                        缺了它们，`aicf gate --run <id>` 会**静默变松**。
# 补表而不是改 §5.1 的列定义：§5.1 的表结构是契约，不能单方面加列。


_SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_dataset (
    id TEXT PRIMARY KEY, version TEXT, hash TEXT, path TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS eval_case (
    dataset_id TEXT, case_id TEXT, spec_json TEXT,
    PRIMARY KEY (dataset_id, case_id)
);
CREATE TABLE IF NOT EXISTS eval_run (
    id TEXT PRIMARY KEY, run_version_id TEXT, status TEXT, started_at REAL, ended_at REAL
);
CREATE TABLE IF NOT EXISTS eval_result (
    run_id TEXT, case_id TEXT, score REAL, metrics_json TEXT, failed_rules_json TEXT,
    PRIMARY KEY (run_id, case_id)
);
CREATE TABLE IF NOT EXISTS eval_gate_report (
    id TEXT PRIMARY KEY, run_version_id TEXT, verdict TEXT, report_json TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS eval_badcase (
    id TEXT PRIMARY KEY, session_id TEXT, trace_id TEXT, reason TEXT, status TEXT, created_at REAL,
    label TEXT DEFAULT '', input_text TEXT DEFAULT '', expect_json TEXT DEFAULT '[]',
    critical INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS eval_trace (
    trace_id TEXT PRIMARY KEY, run_version_id TEXT, session_id TEXT, case_id TEXT,
    payload_json TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS eval_run_summary (
    run_id TEXT PRIMARY KEY, dataset_id TEXT, dataset_hash TEXT, aggregate_json TEXT
);
CREATE TABLE IF NOT EXISTS eval_result_payload (
    run_id TEXT, case_id TEXT, payload_json TEXT, PRIMARY KEY (run_id, case_id)
);
CREATE INDEX IF NOT EXISTS idx_eval_trace_run ON eval_trace(run_version_id);
CREATE INDEX IF NOT EXISTS idx_eval_result_run ON eval_result(run_id);
"""


class TraceStore:
    """评测数据的 SQLite 存储。

    为什么用 SQLite 而不是 Postgres：rc0 阶段数据量小（单机、
    一天几千条 trace），而且「本地一个文件就能跑完 eval → gate」
    对开发者体验很重要。接口保持窄（save/get/list），
    换 Postgres 时只换这一个类。
    """

    def __init__(self, path: str = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        # label columns for older files (W5.3: the labelled fields must
        # survive a restart, otherwise --from-badcases reads empty cases)
        for column in ("label TEXT DEFAULT ''", "input_text TEXT DEFAULT ''",
                       "expect_json TEXT DEFAULT '[]'", "critical INTEGER DEFAULT 1"):
            try:
                self._conn.execute(f"ALTER TABLE eval_badcase ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass  # column already there
        self._conn.commit()

    # ── 生命周期 ──
    def get_connection(self) -> sqlite3.Connection:
        """返回共享连接（与 infra.store.IStore 协议一致）。

        调用方不得 close —— 生命周期归 store 自己管。
        """
        return self._conn

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "TraceStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── dataset ──
    def save_dataset(self, dataset: Any) -> None:
        """保存一个数据集（:class:`infra.eval.dataset.EvalDataset`）。

        用鸭子类型而非直接 import，是为了避免 trace_store → dataset → … 的循环依赖。
        """
        now = time.time()
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_dataset (id, version, hash, path, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (dataset.id, dataset.version, dataset.hash, dataset.path, dataset.created_at or now),
        )
        self._conn.execute("DELETE FROM eval_case WHERE dataset_id = ?", (dataset.id,))
        rows = []
        for case in dataset.cases:
            rows.append((dataset.id, case.id, json.dumps(case.to_dict(), ensure_ascii=False, sort_keys=True)))
        self._conn.executemany(
            "INSERT OR REPLACE INTO eval_case (dataset_id, case_id, spec_json) VALUES (?, ?, ?)", rows
        )
        self._conn.commit()

    def get_dataset(self, dataset_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT id, version, hash, path, created_at FROM eval_dataset WHERE id = ?", (dataset_id,)
        ).fetchone()
        if row is None:
            return None
        cases = self._conn.execute(
            "SELECT case_id, spec_json FROM eval_case WHERE dataset_id = ? ORDER BY case_id", (dataset_id,)
        ).fetchall()
        return {
            "id": row["id"],
            "version": row["version"],
            "hash": row["hash"],
            "path": row["path"],
            "created_at": row["created_at"],
            "cases": [json.loads(c["spec_json"]) for c in cases],
        }

    def list_datasets(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, version, hash, path, created_at FROM eval_dataset ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── run ──
    def save_run(self, run: Mapping[str, Any]) -> None:
        """保存一次评测 run。

        入参是 dict（不是 RunResult 类）—— store 只认数据，不认评测层的类，
        这样 store 可以被任何来源的数据填充（CLI / 定时任务 / 别的服务）。
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_run (id, run_version_id, status, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (run.get("id"), run.get("run_version_id", ""), run.get("status", ""),
             run.get("started_at", 0.0), run.get("ended_at", 0.0)),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_run_summary (run_id, dataset_id, dataset_hash, aggregate_json)"
            " VALUES (?, ?, ?, ?)",
            (run.get("id"), run.get("dataset_id", ""), run.get("dataset_hash", ""),
             json.dumps(run.get("aggregate") or {}, ensure_ascii=False, sort_keys=True)),
        )
        self._conn.execute("DELETE FROM eval_result WHERE run_id = ?", (run.get("id"),))
        self._conn.execute("DELETE FROM eval_result_payload WHERE run_id = ?", (run.get("id"),))
        rows = [
            (run.get("id"), r.get("case_id"), float(r.get("score") or 0.0),
             json.dumps(r.get("metrics") or {}, ensure_ascii=False, sort_keys=True),
             json.dumps(r.get("failed_rules") or [], ensure_ascii=False))
            for r in (run.get("results") or [])
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO eval_result (run_id, case_id, score, metrics_json, failed_rules_json)"
            " VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        # 完整载荷（含 group / critical / violations）：闸门要靠它判定，
        # 少了它，从库里读回来的 run 会比原始 run 宽松 —— 那是危险的。
        payloads = [
            (run.get("id"), r.get("case_id"), json.dumps(r, ensure_ascii=False, sort_keys=True))
            for r in (run.get("results") or [])
        ]
        self._conn.executemany(
            "INSERT OR REPLACE INTO eval_result_payload (run_id, case_id, payload_json)"
            " VALUES (?, ?, ?)",
            payloads,
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT id, run_version_id, status, started_at, ended_at FROM eval_run WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        summary = self._conn.execute(
            "SELECT dataset_id, dataset_hash, aggregate_json FROM eval_run_summary WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        results = self._conn.execute(
            "SELECT case_id, score, metrics_json, failed_rules_json FROM eval_result"
            " WHERE run_id = ? ORDER BY case_id",
            (run_id,),
        ).fetchall()
        run: dict[str, Any] = dict(row)
        run["dataset_id"] = summary["dataset_id"] if summary else ""
        run["dataset_hash"] = summary["dataset_hash"] if summary else ""
        run["aggregate"] = json.loads(summary["aggregate_json"]) if summary else {}
        payload_rows = {
            r["case_id"]: json.loads(r["payload_json"] or "{}")
            for r in self._conn.execute(
                "SELECT case_id, payload_json FROM eval_result_payload WHERE run_id = ?", (run_id,)
            )
        }
        run["results"] = [
            # 有完整载荷就用载荷（含 group / critical / violations），
            # 没有就退回 §5.1 的三列（此时闸门会退化成只看 failed_rules）。
            payload_rows.get(r["case_id"]) or {
                "case_id": r["case_id"],
                "score": r["score"],
                "metrics": json.loads(r["metrics_json"] or "{}"),
                "failed_rules": json.loads(r["failed_rules_json"] or "[]"),
            }
            for r in results
        ]
        return run

    def list_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, run_version_id, status, started_at, ended_at FROM eval_run ORDER BY started_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ── gate report ──
    def save_gate_report(self, report: Mapping[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_gate_report (id, run_version_id, verdict, report_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (report.get("id"), report.get("run_version_id", ""), report.get("verdict", ""),
             json.dumps(report, ensure_ascii=False, sort_keys=True), report.get("created_at", time.time())),
        )
        self._conn.commit()

    def get_gate_report(self, report_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT report_json FROM eval_gate_report WHERE id = ?", (report_id,)
        ).fetchone()
        return json.loads(row["report_json"]) if row else None

    # ── trace ──
    def save_trace(self, trace: Trace, *, run_version_id: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_trace"
            " (trace_id, run_version_id, session_id, case_id, payload_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (trace.trace_id, run_version_id or trace.run_version_id, trace.session_id,
             trace.case_id, json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True), time.time()),
        )
        self._conn.commit()

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        row = self._conn.execute(
            "SELECT payload_json FROM eval_trace WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        return Trace.from_dict(json.loads(row["payload_json"])) if row else None

    def list_traces(self, *, run_version_id: str = "", case_id: str = "") -> list[Trace]:
        sql = "SELECT payload_json FROM eval_trace"
        clauses: list[str] = []
        params: list[Any] = []
        if run_version_id:
            clauses.append("run_version_id = ?")
            params.append(run_version_id)
        if case_id:
            clauses.append("case_id = ?")
            params.append(case_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at"
        return [Trace.from_dict(json.loads(r["payload_json"])) for r in self._conn.execute(sql, params)]

    def iter_traces(self, **kwargs: Any) -> Iterator[Trace]:
        yield from self.list_traces(**kwargs)

    # ── badcase（rc1 回流用的表，rc0 先把写入通道打通）──
    def record_badcase(
        self,
        *,
        session_id: str,
        trace_id: str,
        reason: str,
        status: str = "new",
        badcase_id: str = "",
    ) -> str:
        """记录一条 bad case。

        rc0 只需要「能写进去」——线上抽样回流是 rc1 的事（§4.6.6）。
        但表和通道现在就打通，是为了让 rc1 不必回头改 schema。
        """
        bid = badcase_id or f"bc_{trace_id or session_id}_{int(time.time() * 1000)}"
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_badcase (id, session_id, trace_id, reason, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (bid, session_id, trace_id, reason, status, time.time()),
        )
        self._conn.commit()
        return bid

    def list_badcases(self, *, status: str = "") -> list[dict[str, Any]]:
        sql = ("SELECT id, session_id, trace_id, reason, status, created_at,"
               " label, input_text, expect_json, critical FROM eval_badcase")
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC"
        rows = []
        for r in self._conn.execute(sql, params):
            row = dict(r)
            try:
                row["expect"] = json.loads(row.pop("expect_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                row["expect"] = []
            row["critical"] = bool(row.get("critical", 1))
            rows.append(row)
        return rows

    def label_badcase(self, badcase_id: str, *, label: str,
                      input_text: str = '', expect: list | None = None,
                      critical: bool = True) -> bool:
        """Persist the labelled fields + status (W5.3).

        The labelled fields used to live only in the returned object, so a
        restart lost the repro steps -- the pipeline could not close.
        """
        cur = self._conn.execute(
            "UPDATE eval_badcase SET status = 'labelled', label = ?, input_text = ?,"
            " expect_json = ?, critical = ? WHERE id = ?",
            (label, input_text, json.dumps(list(expect or []), ensure_ascii=False),
             1 if critical else 0, badcase_id))
        self._conn.commit()
        return cur.rowcount > 0

    def set_badcase_status(self, badcase_id: str, status: str) -> bool:
        """推进一条 badcase 的生命周期（new → labelled → queued / dismissed）。

        回流管线（infra/eval/badcase.py）靠它把「记录」变成「回流」。
        状态值由调用方带，这里只校验非空 —— 词表归管线管。
        """
        if not str(status or "").strip():
            raise ValueError("badcase 状态不能为空")
        cur = self._conn.execute(
            "UPDATE eval_badcase SET status = ? WHERE id = ?",
            (status, badcase_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

