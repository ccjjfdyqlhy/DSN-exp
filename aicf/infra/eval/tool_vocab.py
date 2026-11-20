# infra/eval/tool_vocab.py
# 评测集的**工具词表** ↔ 框架**真实注册表**之间的绑定。
#
# ── 为什么需要这一层 ──
# 评测集刻意不绑定具体实现（见 harness/datasets/basic.yaml 顶部的命名约定）：
# 它写的是 `fs.read` / `calc.eval` / `web.search` 这类**抽象能力名**，
# 而不是 `file.read` / `web.fetch` 这种实现细节。
#
# 好处是换一套工具实现时评测集不用重写；
# 代价是**必须有一张表把抽象名落到真实工具上** —— 否则断言里写的名字
# 在注册表里根本不存在，那条断言就永远不可能成立，
# 而失败原因会被误读成「模型没调用工具」。
#
# 1.0.0 之前这张表是不存在的，于是 basic.yaml 里 27 条工具断言有 26 条
# 指向不存在的工具名（fs.read / fs.write / calc.eval / web.search …），
# 而注册表里实际叫 file.read / file.write / web.fetch。
# **这类缺陷必须在结构上被挡住**，所以：
#   · 本表是唯一的绑定入口；
#   · tests/test_eval_dataset_bindings.py 断言「评测集里出现的每个工具名
#     都能落到至少一个真实注册的工具上」，新工具集改了名就会红。
#
# ── 这张表的边界 ──
# 它只做**一对一/一对多**的名字绑定，不做语义推理：
#   · 抽象名对应的能力在框架里**不存在** → 不写进表里。
#     （比如框架没有计算器，calc.eval 就不是一张表项 —— 评测集也不该断言它。）
#   · 抽象名对应多个实现 → 一对多，命中任意一个即算通过。

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

#: 抽象工具名 → 真实注册表里等价的工具名。
#:
#: 值是元组：**命中其中任意一个即视为「调用了这类工具」**。
#: 之所以是元组而不是字符串，是因为一个抽象能力可能由多个工具实现
#: （例如「查一个文件的状态」既可以 list 也可以 read）。
#:
#: 命名规则：左边是评测集词表里的抽象名，右边是**当前实现**注册的名字。
#: 换实现时只改右边这一列，评测集一个字都不用动。
TOOL_NAME_ALIASES: Mapping[str, tuple[str, ...]] = {
    # ── 文件 ──────────────────────────────────────────────
    "fs.read": ("file.read",),
    "fs.write": ("file.write",),
    "fs.list": ("file.list",),
    # 「文件状态」：框架没有 stat 工具 —— 想知道文件多大只能把它读出来自己数。
    "fs.stat": ("file.read",),
    # 框架没有 delete；能改变既有文件内容的是 file.edit。
    "fs.delete": ("file.edit",),
    # ── 执行 ──────────────────────────────────────────────
    "shell.exec": ("proc.run",),
    # ── 网络 ──────────────────────────────────────────────
    "web.fetch": ("web.fetch",),
    # 框架没有检索工具，能取回外部内容的只有 web.fetch。
    "web.search": ("web.fetch",),
    # ── 文本 ──────────────────────────────────────────────
    "json.parse": ("text.extract_json",),
}


def resolve_tool_names(name: str) -> tuple[str, ...]:
    """一个断言里的工具名 → 允许通过的真实工具名集合。

    没有登记在表里的名字原样返回 —— 这样「直接写真实工具名」
    （比如 ``web.fetch``）和「写抽象名」（比如 ``fs.read``）都能用。
    """
    if not name:
        return ()
    return tuple(TOOL_NAME_ALIASES.get(name, (name,)))


def resolve_all(names: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """批量解析，返回 ``{原名: 真实名元组}``。"""
    return {n: resolve_tool_names(n) for n in names}


def is_abstract_tool_name(name: str) -> bool:
    """这个名字是不是评测集词表里的抽象能力名。"""
    return name in TOOL_NAME_ALIASES


def matches_tool_call(name: str, called: Sequence[str]) -> bool:
    """``called`` 里有没有一次调用命中了 ``name`` 这一类工具。

    命中条件：直接叫这个名字，或者叫它绑定到的任意一个真实工具名。
    """
    targets = resolve_tool_names(name)
    if not targets:
        return False
    called_set = set(called)
    return any(t in called_set for t in targets)
