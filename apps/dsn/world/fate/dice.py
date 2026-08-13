# world/fate/dice.py
# 骰子系统 — D4/D6/D8/D10/D12/D20/D100 + 骰池 + 优劣势

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiceResult:
    """单次投骰结果"""
    values: list[int]       # 每个骰子的值
    total: int              # 总和
    sides: int              # 骰子面数
    count: int              # 骰子个数
    crit_success: bool = False   # D20=20
    crit_fail: bool = False      # D20=1
    advantage: bool = False     # 优势
    disadvantage: bool = False  # 劣势
    label: str = ""             # 可读标签，如"侦查检定"

    def __str__(self) -> str:
        prefix = f"[{self.label}] " if self.label else ""
        detail = "+".join(str(v) for v in self.values)
        if self.advantage or self.disadvantage:
            detail = f"({detail})"
        label = ""
        if self.crit_success:
            label = " ★大成功"
        elif self.crit_fail:
            label = " ✗大失败"
        return f"{prefix}{self.count}d{self.sides}={self.total}{label} ({detail})"


class Dice:
    """骰子基础类 — 支持单次投掷各种面数骰子"""

    @staticmethod
    def roll(sides: int, count: int = 1, label: str = "",
             advantage: bool = False, disadvantage: bool = False) -> DiceResult:
        """
        投掷 count 个 sides 面骰子。

        advantage=True: 投两轮取高（用于 D20 检定）
        disadvantage=True: 投两轮取低（用于 D20 检定）
        """
        if advantage and disadvantage:
            advantage = disadvantage = False  # 抵消

        if sides == 0:
            return DiceResult(values=[0], total=0, sides=0, count=1, label=label)

        if advantage or disadvantage:
            # 优劣势：投两轮取高/低
            roll_a = [random.randint(1, sides) for _ in range(count)]
            roll_b = [random.randint(1, sides) for _ in range(count)]
            values = [max(a, b) if advantage else min(a, b)
                      for a, b in zip(roll_a, roll_b)]
        else:
            values = [random.randint(1, sides) for _ in range(count)]

        total = sum(values)
        crit_success = False
        crit_fail = False
        if sides == 20 and count == 1:
            if values[0] == 20:
                crit_success = True
            elif values[0] == 1:
                crit_fail = True

        return DiceResult(
            values=values,
            total=total,
            sides=sides,
            count=count,
            crit_success=crit_success,
            crit_fail=crit_fail,
            advantage=advantage,
            disadvantage=disadvantage,
            label=label,
        )

    @staticmethod
    def d4(count: int = 1, label: str = "") -> DiceResult:
        return Dice.roll(4, count, label=label)

    @staticmethod
    def d6(count: int = 1, label: str = "") -> DiceResult:
        return Dice.roll(6, count, label=label)

    @staticmethod
    def d8(count: int = 1, label: str = "") -> DiceResult:
        return Dice.roll(8, count, label=label)

    @staticmethod
    def d10(count: int = 1, label: str = "") -> DiceResult:
        return Dice.roll(10, count, label=label)

    @staticmethod
    def d12(count: int = 1, label: str = "") -> DiceResult:
        return Dice.roll(12, count, label=label)

    @staticmethod
    def d20(count: int = 1, label: str = "", advantage: bool = False,
            disadvantage: bool = False) -> DiceResult:
        return Dice.roll(20, count, label=label,
                         advantage=advantage, disadvantage=disadvantage)

    @staticmethod
    def d100(label: str = "") -> DiceResult:
        """百分骰 = D100"""
        return Dice.roll(100, 1, label=label)


class DicePool:
    """骰池 — 组合多种骰子，一次投掷"""

    def __init__(self, label: str = ""):
        self._rolls: list[DiceResult] = []
        self._modifier: int = 0
        self._label = label

    def add(self, sides: int, count: int = 1,
            advantage: bool = False, disadvantage: bool = False) -> DicePool:
        self._rolls.append(Dice.roll(sides, count,
                                      advantage=advantage,
                                      disadvantage=disadvantage))
        return self

    def modifier(self, value: int) -> DicePool:
        self._modifier += value
        return self

    def roll(self) -> DiceResult:
        values = []
        total = 0
        for r in self._rolls:
            values.extend(r.values)
            total += r.total
        total += self._modifier

        crit = any(r.crit_success for r in self._rolls)
        crit_f = any(r.crit_fail for r in self._rolls)

        return DiceResult(
            values=values,
            total=total,
            sides=sum(r.sides for r in self._rolls),
            count=sum(r.count for r in self._rolls),
            crit_success=crit,
            crit_fail=crit_f,
            label=self._label,
        )

    @staticmethod
    def from_expression(expr: str, label: str = "") -> DiceResult:
        """解析骰子表达式: '2d6+1d4+3'"""
        pool = DicePool(label=label)
        expr = expr.replace(" ", "")
        i = 0
        n = len(expr)
        sign = 1
        while i < n:
            if expr[i] == '+':
                sign = 1
                i += 1
            elif expr[i] == '-':
                sign = -1
                i += 1
            if i >= n:
                break
            start = i
            while i < n and expr[i].isdigit():
                i += 1
            num1 = int(expr[start:i]) if i > start else 1
            if i < n and expr[i] == 'd':
                i += 1
                start = i
                while i < n and expr[i].isdigit():
                    i += 1
                num2 = int(expr[start:i]) if i > start else 1
                pool.add(num2, num1)
            else:
                pool.modifier(sign * num1)
            sign = 1
        return pool.roll()
