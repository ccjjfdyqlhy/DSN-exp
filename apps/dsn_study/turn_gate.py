# apps/dsn_study/turn_gate.py
# 轮次闸门 —— 让后台 LLM 调用（人格判定 / 人格生成 / 话题摘要）
# **不要和用户的下一轮抢同一个 provider 队列**。
#
# 背景（实测）：provider(newapi.gay) 对同一 key 的请求会排队。
# 用户说完话 → 主回复调用 → 回复完管线里起一个后台线程做「人格判定」
# （又一次 LLM 调用）→ 用户很快又说了第二句 → 第二句的主回复调用
# 排在第一句的人格判定后面 → 表现为「model_invoke 花了 53 秒 / 108 秒」。
#
# 做法：对话轮次进出时给闸门计数；后台任务等闸门归零（且短暂去抖）后再发起。
# 这样后台调用只在**用户说完、暂时没说话**的时候才跑。

from __future__ import annotations

import os
import threading
import time

_lock = threading.Lock()
_in_flight = 0
_idle = threading.Event()
_idle.set()

#: 后台任务最多等用户空闲多久（秒）。等不到就放弃 —— 后台活儿不必太执著。
IDLE_WAIT_TIMEOUT = float(os.environ.get("STUDY_TURN_IDLE_TIMEOUT", "30"))
#: 用户空闲后还要再等一会儿才发后台请求（去抖）。
#:
#: 定这个值的依据：用户要**听完回复**才可能说下一句，而回复播放本身就要
#: 好几秒 —— 所以"下一轮很快就来"并不成立，2 秒足够躲开。
#: 之前取 8 秒太保守：既让后台判定晚到（测试里差点超时），
#: 又拉长了人格状态更新的落地延迟。
DEBOUNCE_SECS = float(os.environ.get("STUDY_TURN_DEBOUNCE", "2.0"))


class user_turn:
    """上下文管理器：标记"用户这一轮正在进行中"。"""

    def __enter__(self):
        global _in_flight
        with _lock:
            _in_flight += 1
            _idle.clear()
        return self

    def __exit__(self, *exc):
        global _in_flight
        with _lock:
            _in_flight = max(0, _in_flight - 1)
            if _in_flight == 0:
                _idle.set()
        return False


def in_flight() -> int:
    with _lock:
        return _in_flight


def wait_for_idle(timeout: float = IDLE_WAIT_TIMEOUT,
                  debounce: float = DEBOUNCE_SECS) -> bool:
    """等用户空闲。返回 True 表示等到并可以发起后台调用了。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _idle.wait(timeout=0.2):
            continue
        # 去抖：空闲后若马上又有新轮，就继续等
        end = time.time() + debounce
        while time.time() < end:
            time.sleep(0.1)
            with _lock:
                if _in_flight > 0:
                    break
        else:
            return True
    return False
