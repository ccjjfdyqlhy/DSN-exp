# tests/conftest.py
# 全局测试配置。
#
# 为什么需要它（2026-10 新增）：
#   1. 此前没有 conftest.py，任何测试都可能把真实数据写进仓库：
#      - tests/test_dsn_ui.py 的 fixture 会写 apps/dsn_ui/data/dsn_ui_memory.db
#      - tests/test_harness_strata.py 把 MagicMock 当 settings.data_dir 用，
#        于是在仓库根创建 MagicMock/mock.agent.data_dir/<id>/ 目录
#      （源头已在 apps/dsn_ui/thought_cache.py 加类型守卫，此处再做数据目录隔离）。
#   2. 本仓库有进程级单例（ModelOrchestrator / ModelScheduler / Runtime），
#      用例之间容易互相污染，这里在每个用例后统一重置。
#
# ⚠️ 刻意**不**改变工作目录：
#   本仓库大量测试用相对路径定位 apps/dsn/skills、prompt 目录等资源
#   （见 test_skills_system / test_batch_skill / test_prompt_ecosystem），
#   cwd 一旦变成 tmp 就会大面积 FileNotFoundError。

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# 保证 `import apps.*` / `import harness.*` 可用（仓库未以包形式安装时）
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    """注册自定义 marker，并补齐"无 .env 也能收集"的最小环境。"""
    config.addinivalue_line("markers", "slow: 运行较慢的测试")
    config.addinivalue_line(
        "markers", "integration: 需要外部服务/设备/网络的测试"
    )

    # 为什么需要这个占位 key：
    #   1. apps/dsn/config.py 在 MAIN_MODEL_TYPE=openai（默认值）时强制要求
    #      OPENAI_API_KEY，缺了就 EnvironmentError，收集期直接报错；
    #   2. apps/dsn/main.py 的导入期检查发现"未配置"会拉起**交互式引导**，
    #      而引导要读 stdin —— 在 pytest 里会把整个收集过程挂死。
    #   3. 用 setdefault：机器上真的有 key 时以真的为准。
    #   测试全程不访问真实模型后端（用 StubChatClient），这个值只是过导入关。
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-not-real")


@pytest.fixture(autouse=True)
def _isolate_repo_state(monkeypatch):
    """隔离测试副作用：把「会写文件的数据目录」指向临时目录，并重置全局单例。"""
    tmp_path = Path(tempfile.mkdtemp(prefix="dsn_test_"))

    # dsn_ui 的数据目录：<db / 凭据密文 / 思考链缓存 / 设置覆盖> 都落在这里
    monkeypatch.setenv("DSN_UI_DATA_DIR", str(tmp_path / "dsn_ui_data"))

    try:
        yield
    finally:
        # 1) 清理进程级单例，避免用例之间串味
        try:
            from infra.orchestrator import ModelOrchestrator

            ModelOrchestrator.reset_instance()
        except Exception:  # noqa: BLE001 - 未导入该模块时无需清理
            pass
        # 2) 清空本地引擎子进程的全局注册表。
        #    背景：用例里用 mock 启动 launcher 会把它登记进
        #    infra.orchestrator.local_engine._ACTIVE_LAUNCHERS，而 atexit 的
        #    _cleanup_active_launchers() 会在 pytest 关闭输出流**之后**再去
        #    stop() 它们——既刷出一串 "Logging error: I/O operation on closed
        #    file"，又会对着「永不退出」的 mock 空等满 15s 超时。
        #    这里在用例结束时就地清空，避免噪声与无谓等待。
        try:
            from infra.orchestrator import local_engine

            for launcher in list(local_engine._ACTIVE_LAUNCHERS):
                local_engine._ACTIVE_LAUNCHERS.discard(launcher)
                with contextlib.suppress(Exception):
                    launcher.stop(timeout=0.1)
        except Exception:  # noqa: BLE001 - 未导入该模块时无需清理
            pass
        # 3) 删除临时数据目录
        shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def stub_client():
    """开箱可用的确定性模型客户端（离线测试用）。"""
    from infra.orchestrator import ChatResponse, StubChatClient

    return StubChatClient(responses=[ChatResponse(content="固定回复")])
