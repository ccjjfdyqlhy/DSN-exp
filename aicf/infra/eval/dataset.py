# infra/eval/dataset.py
# 评测集（Dataset）的加载、校验与内容哈希。
#
# ── 为什么断言语言要「刻意做小」？ ──
# 策划案 §4.6.3 的原话：不支持任意表达式。
# 理由很实在：如果评测集允许写表达式，那么「评测集本身」就成了
# 一份不可测的代码 —— 它出了 bug 你分不清是 agent 变差了还是题目写错了。
# 于是所有人都会开始「调评测集」，最后门禁变成一场自娱自乐的表演。
#
# 所以这里的断言语言只有九种（ASSERTION_KINDS），全部是**可判定的**：
# 要么能在 trace 上直接算出来，要么是一次字符串/数值比较。
# 想要更复杂的东西？写一个 `assert_fn` 并**注册**它 ——
# 代码留在 Python 里（可测试、可 review），数据集里只留名字。
#
# ── 为什么 hash 算的是「内容」而不是「文件」？ ──
# RunVersion 要冻结快照，就必须能判断「这次评测用的数据集，
# 跟上次比是不是同一份」。如果 hash 的是文件字节，
# 换个缩进、改个注释就全变了，冻结快照就失去意义。
# 所以 hash 只吃**语义内容**（版本 + case 列表），与排版无关。

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

#: 断言语言的全部词汇。新增一种断言必须同时改这里 + evaluator.py，
#: 否则就会出现「数据集里写了但求值器不认识」的静默失效。
ASSERTION_KINDS: tuple[str, ...] = (
    "tool_called",      # 调用过指定工具（str / [str]）
    "output_contains",  # 输出包含指定子串（str / [str]）
    "output_matches",   # 输出匹配正则（str / [str]）
    "max_tool_calls",   # 工具调用次数上限（int）
    "forbid_tools",     # 禁止调用这些工具（[str]）
    "no_side_effect",   # 不允许有副作用（bool）
    "cost_tokens",      # token 成本阈值（{op: value}）
    "latency_ms",       # 耗时阈值（{op: value}）
    "assert_fn",        # 自定义断言函数名（str）
)

#: 阈值比较算子。用「算子 + 数值」而不是表达式，
#: 是为了让阈值本身也是数据（可序列化、可 diff、可存进 yaml）。
COMPARISON_OPS: tuple[str, ...] = ("lte", "lt", "gte", "gt", "eq")

#: 需要阈值比较的断言。
COMPARISON_ASSERTIONS = frozenset({"cost_tokens", "latency_ms"})

#: 断言类别：正确性断言（expect）与指标阈值（metrics）。
ASSERTION_CATEGORIES = ("expect", "metrics")


class DatasetError(ValueError):
    """数据集不合法。

    加载期就报错（fail fast）是有意的：一份写错的评测集如果等到
    跑评测时才发现，那一轮的分数全是废的，还可能已经推过一次 gate。
    """



def _as_item_list(raw: Any, label: str, where: str) -> list[dict[str, Any]]:
    """把 expect/metrics 段规范化成 [{断言名: 参数}] 列表。

    形状不对就当场报 DatasetError —— 加载期出错必须是同一种异常，
    否则调用方要么漏 catch（错误被推迟到评测时），
    要么 catch 一大堆（错误信息被淹没）。
    """
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise DatasetError(f"{where}: {label} 必须是列表")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise DatasetError(
                f"{where}: {label} 的每一项必须是非空的映射（形如 tool_called: fs.read）"
            )
        out.append(dict(item))
    return out


@dataclass
class EvalCase:
    """一个评测用例。

    `expect` 与 `metrics` 的区别：
      expect  —— 行为对不对（调用了该调的工具、输出里有该有的内容）
      metrics —— 花得值不值（token / 耗时是否在预算内）
    两者都会导致 case 失败，但分开是为了报告里能一眼看出
    「这次是行为错了」还是「这次是超预算了」。
    """

    id: str
    input: str = ""
    #: 执行前置条件（目前只约定 {files: {路径: 内容}}，供 harness 侧造场景）。
    setup: dict[str, Any] = field(default_factory=dict)
    #: 正确性断言列表，每项是 {断言名: 参数} 的映射。
    expect: list[dict[str, Any]] = field(default_factory=list)
    #: 指标阈值列表，每项是 {指标名: {算子: 数值}} 的映射。
    metrics: list[dict[str, Any]] = field(default_factory=list)
    #: 能力分组（file_io / computation / tool_selection / refusal / safety …）。
    group: str = "default"
    #: 是否为关键用例。关键用例通过率必须 100%（§4.6.5 质量闸门）。
    critical: bool = False
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "input": self.input,
            "setup": dict(self.setup),
            "expect": [dict(e) for e in self.expect],
            "metrics": [dict(m) for m in self.metrics],
            "group": self.group,
            "critical": self.critical,
            "description": self.description,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, where: str = "") -> "EvalCase":
        case_id = str(data.get("id") or "").strip()
        if not case_id:
            raise DatasetError(f"{where}用例缺少 id")
        # 形状校验必须发生在转换之前：dict("字符串") 抛的是 ValueError，
        # 而加载期出错必须是 DatasetError（调用方只catch那一种）。
        expect_items = _as_item_list(data.get("expect"), "expect", where or case_id)
        metric_items = _as_item_list(data.get("metrics"), "metrics", where or case_id)
        case = cls(
            id=case_id,
            input=str(data.get("input") or ""),
            setup=dict(data.get("setup") or {}),
            expect=expect_items,
            metrics=metric_items,
            group=str(data.get("group") or "default"),
            critical=bool(data.get("critical", False)),
            description=str(data.get("description") or ""),
            tags=[str(t) for t in (data.get("tags") or [])],
        )
        validate_case(case, where=where or case.id)
        return case

    @property
    def assertion_count(self) -> int:
        return len(self.expect) + len(self.metrics)


@dataclass
class EvalDataset:
    """一份评测集。

    `hash` 是内容哈希（与排版无关），RunVersion 冻结快照时用它判断
    「数据集有没有变过」。
    """

    id: str
    version: str = "1"
    path: str = ""
    cases: list[EvalCase] = field(default_factory=list)
    created_at: float = 0.0
    description: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    # ── 内容哈希 ──
    @property
    def hash(self) -> str:
        """内容哈希：sha256(规范化的语义内容)。

        只吃 version/meta/cases，不吃 path —— 数据集搬家（换目录）
        不应该让 hash 变，那会让所有历史 RunVersion 集体失效。
        """
        payload = {
            "version": self.version,
            "meta": self.meta,
            "cases": [case.to_dict() for case in sorted(self.cases, key=lambda c: c.id)],
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # ── 查询 ──
    def case(self, case_id: str) -> Optional[EvalCase]:
        for c in self.cases:
            if c.id == case_id:
                return c
        return None

    def groups(self) -> dict[str, list[EvalCase]]:
        """按分组归类用例（保持原始顺序）。"""
        out: dict[str, list[EvalCase]] = {}
        for c in self.cases:
            out.setdefault(c.group, []).append(c)
        return out

    def critical_cases(self) -> list[EvalCase]:
        return [c for c in self.cases if c.critical]

    @property
    def critical_count(self) -> int:
        return len(self.critical_cases())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "path": self.path,
            "created_at": self.created_at,
            "description": self.description,
            "meta": dict(self.meta),
            "cases": [c.to_dict() for c in self.cases],
        }


# ── 校验 ────────────────────────────────────────────────


def _validate_comparison(value: Any, *, where: str) -> None:
    if isinstance(value, bool):
        raise DatasetError(f"{where}: 阈值不能是布尔值")
    if isinstance(value, (int, float)):
        return
    if not isinstance(value, Mapping):
        raise DatasetError(f"{where}: 阈值必须是 {{算子: 数值}} 映射，得到 {value!r}")
    if not value:
        raise DatasetError(f"{where}: 阈值映射为空")
    for op, val in value.items():
        if op not in COMPARISON_OPS:
            raise DatasetError(f"{where}: 未知比较算子 {op!r}（可用：{', '.join(COMPARISON_OPS)}）")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise DatasetError(f"{where}: 算子 {op!r} 的右值必须是数值，得到 {val!r}")


def _validate_assertion(kind: str, value: Any, *, where: str) -> None:
    if kind not in ASSERTION_KINDS:
        raise DatasetError(
            f"{where}: 未知断言 {kind!r}（可用：{', '.join(ASSERTION_KINDS)}）"
        )
    if kind in COMPARISON_ASSERTIONS:
        _validate_comparison(value, where=f"{where}.{kind}")
        return
    if kind == "tool_called":
        names = value if isinstance(value, (list, tuple)) else [value]
        if not names or not all(isinstance(n, str) and n.strip() for n in names):
            raise DatasetError(f"{where}.tool_called: 必须是工具名或工具名列表")
        return
    if kind in ("output_contains", "output_matches"):
        items = value if isinstance(value, (list, tuple)) else [value]
        if not items or not all(isinstance(s, str) and s for s in items):
            raise DatasetError(f"{where}.{kind}: 必须是非空字符串或字符串列表")
        if kind == "output_matches":
            for s in items:
                try:
                    re.compile(s)
                except re.error as exc:
                    raise DatasetError(f"{where}.output_matches: 正则非法 {s!r}: {exc}") from exc
        return
    if kind == "max_tool_calls":
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DatasetError(f"{where}.max_tool_calls: 必须是非负整数")
        return
    if kind == "forbid_tools":
        names = value if isinstance(value, (list, tuple)) else [value]
        if not names or not all(isinstance(n, str) and n.strip() for n in names):
            raise DatasetError(f"{where}.forbid_tools: 必须是工具名或工具名列表")
        return
    if kind == "no_side_effect":
        if not isinstance(value, bool):
            raise DatasetError(f"{where}.no_side_effect: 必须是布尔值")
        return
    if kind == "assert_fn":
        # 两种写法：无参 ``assert_fn: my_checker``，
        # 带参 ``assert_fn: {name: my_checker, params: {...}}``。
        # 参数放 params 里（而不是顶层散键）—— 保持断言项的形状统一：
        # 每个断言项恒为「{断言名: 参数}」。
        if isinstance(value, str):
            if not value.strip():
                raise DatasetError(f"{where}.assert_fn: 必须是非空字符串（自定义断言函数名）")
            return
        if isinstance(value, Mapping):
            name = value.get("name")
            if not isinstance(name, str) or not name.strip():
                raise DatasetError(f"{where}.assert_fn.name: 必须是非空字符串")
            params = value.get("params", {})
            if params is not None and not isinstance(params, Mapping):
                raise DatasetError(f"{where}.assert_fn.params: 必须是映射")
            return
        raise DatasetError(f"{where}.assert_fn: 必须是函数名或 {name: ..., params: ...} 映射")


def validate_case(case: EvalCase, *, where: str = "") -> None:
    """校验单个用例的断言写法。"""
    label = where or case.id
    for item in case.expect:
        if not isinstance(item, Mapping) or not item:
            raise DatasetError(
                f"{label}: expect 的每一项必须是非空的映射（形如 tool_called: fs.read）"
            )
        for kind, value in item.items():
            _validate_assertion(str(kind), value, where=label)
    for item in case.metrics:
        if not isinstance(item, Mapping) or not item:
            raise DatasetError(
                f"{label}: metrics 的每一项必须是非空的映射（形如 cost_tokens: {{lte: 500}}）"
            )
        for kind, value in item.items():
            _validate_assertion(str(kind), value, where=label)


def validate_dataset(dataset: EvalDataset) -> None:
    """校验数据集：id 唯一、断言合法、分组名合法。"""
    seen: set[str] = set()
    for case in dataset.cases:
        if case.id in seen:
            raise DatasetError(f"数据集 {dataset.id} 中用例 id 重复: {case.id}")
        seen.add(case.id)
        validate_case(case, where=f"{dataset.id}/{case.id}")


# ── 加载 ────────────────────────────────────────────────


def _dataset_id_from_path(path: Path) -> str:
    return path.stem or path.name


def load_dataset(
    path: str | Path,
    *,
    dataset_id: str = "",
    version: str = "",
) -> EvalDataset:
    """从 yaml / json / jsonl 加载评测集。

    支持三种格式：
      .yaml/.yml —— 策划案 §4.6.3 的写法（cases: [...]）
      .json      —— 同上，JSON 版
      .jsonl     —— 一行一个 case（大规模数据集更好写，也更容易增量追加）

    加载即校验：非法断言当场报错，不留到跑评测时。
    """
    p = Path(path)
    if not p.exists():
        raise DatasetError(f"评测集文件不存在: {p}")
    suffix = p.suffix.lower()
    raw_text = p.read_text(encoding="utf-8")

    if suffix == ".jsonl":
        cases_raw: list[dict[str, Any]] = []
        for lineno, line in enumerate(raw_text.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{p}:{lineno} 不是合法 JSON: {exc}") from exc
            cases_raw.append(obj)
        spec: dict[str, Any] = {"cases": cases_raw}
    else:
        import yaml  # PyYAML 是核心依赖，不引新东西

        try:
            loaded = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise DatasetError(f"{p} 不是合法 YAML: {exc}") from exc
        if isinstance(loaded, list):
            spec = {"cases": loaded}
        elif isinstance(loaded, Mapping):
            spec = dict(loaded)
        else:
            raise DatasetError(f"{p} 顶层必须是映射或列表，得到 {type(loaded).__name__}")

    cases_raw = spec.get("cases") or []
    if not isinstance(cases_raw, Sequence) or isinstance(cases_raw, (str, bytes)):
        raise DatasetError(f"{p}: cases 必须是列表")
    if not cases_raw:
        raise DatasetError(f"{p}: 评测集为空（至少要有一个 case）")

    where = f"{p}:"
    cases = [EvalCase.from_dict(c, where=where) for c in cases_raw]
    dataset = EvalDataset(
        id=dataset_id or str(spec.get("id") or _dataset_id_from_path(p)),
        version=str(spec.get("version") or version or "1"),
        path=str(p),
        cases=cases,
        created_at=time.time(),
        description=str(spec.get("description") or ""),
        meta={k: v for k, v in spec.items() if k not in ("cases", "id", "version", "description")},
    )
    validate_dataset(dataset)
    return dataset


def load_dataset_from_spec(
    spec: Mapping[str, Any],
    *,
    dataset_id: str = "",
    path: str = "",
) -> EvalDataset:
    """从内存里的 dict 构造数据集（测试与 API 调用用）。"""
    cases_raw = spec.get("cases") or []
    if not cases_raw:
        raise DatasetError("评测集为空（至少要有一个 case）")
    cases = [EvalCase.from_dict(c, where="<memory>:") for c in cases_raw]
    dataset = EvalDataset(
        id=dataset_id or str(spec.get("id") or "inline"),
        version=str(spec.get("version") or "1"),
        path=path,
        cases=cases,
        created_at=time.time(),
        description=str(spec.get("description") or ""),
        meta={k: v for k, v in spec.items() if k not in ("cases", "id", "version", "description")},
    )
    validate_dataset(dataset)
    return dataset


def dataset_summary(dataset: EvalDataset) -> dict[str, Any]:
    """数据集概览（给 CLI 打印用）。"""
    groups = dataset.groups()
    return {
        "id": dataset.id,
        "version": dataset.version,
        "path": dataset.path,
        "hash": dataset.hash,
        "cases": len(dataset.cases),
        "critical": dataset.critical_count,
        "groups": {g: len(cases) for g, cases in sorted(groups.items())},
    }
