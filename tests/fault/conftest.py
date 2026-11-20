# tests/fault/conftest.py
# 故障注入测试的公共夹具。
#
# 夹具只提供「环境」：一个文件型 sqlite（崩溃恢复必须跨进程，内存库不行）、
# 一个跨进程可见的副作用计数器、一个开好会话与第 0 轮的托管运行时。
#
# 工具函数（起子进程、等文件、拼脚本）放在 faultkit.py ——
# conftest 里的东西不能被测试模块 import（没有包上下文），
# 而 faultkit 可以（pytest 会把 tests/fault 放进 sys.path）。

from __future__ import annotations

import pytest

from faultkit import SideEffectCounter
from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
from aicf.infra.store.sqlite import SqliteStore


@pytest.fixture()
def db_path(tmp_path) -> str:
    """文件型 sqlite 路径 —— 崩溃恢复必须跨进程，内存库不行。"""
    return str(tmp_path / 'runtime.db')


@pytest.fixture()
def counter(tmp_path) -> SideEffectCounter:
    """跨进程可验证的副作用计数器（文件落地 + fsync）。"""
    return SideEffectCounter(tmp_path / 'side_effects.log')


@pytest.fixture()
def store(db_path):
    st = SqliteStore(db_path)
    migrate_runtime(st)
    yield st
    st.close()


@pytest.fixture()
def port(store):
    return SqliteRuntimeStore(store)


@pytest.fixture()
def runtime(port):
    """一个开好会话与第 0 轮的托管运行时。"""
    rt = ManagedRuntime(port, session_id='s1')
    rt.start_session(tenant='t1', artifact_id='a1')
    rt.start_turn(0, input={'q': 'hello'})
    return rt
