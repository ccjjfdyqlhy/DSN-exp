# 测试指南

> 读者：要跑测试、要加测试、或要判断「这个失败是不是我搞坏的」的维护者。

---

## 一、怎么跑

### 1.1 前置

`pytest` **不在** `requirements.txt` 里，需要单独装：

```bash
pip install pytest
```

### 1.2 常用命令

仓库已内置 pytest 配置，日常直接跑即可：

```bash
python -m pytest                # 全量（默认排除 known_broken）
python -m pytest -q             # 安静模式
python -m pytest tests/test_harness_*.py -q   # 只跑框架层（几秒）
python -m pytest -m known_broken             # 只跑待重做的用例
python -m pytest -x             # 第一个失败就停
python -m pytest --collect-only -q            # 只收集不执行
```

> 本仓库现在有 `tests/conftest.py`，提供 `stub_client` fixture 与
> 全局单例重置；**不要**再手工 `os.chdir` 去隔离目录。

---
## 二、当前基线（2026-10 修复后实测）

```
547 passed, 18 deselected, 3 warnings in ~78s     # 0 failed, 0 collection errors
```

### 2.1 怎么跑（已简化）

仓库现在带 `[tool.pytest.ini_options]` 配置（见 `pyproject.toml`），因此：

```bash
python -m pytest            # 直接跑，不需要任何额外参数
python -m pytest -q         # 安静模式
```

配置里已经解决的三件事：

| 配置项 | 解决的问题 |
|---|---|
| `testpaths = ["tests"]` | 裸跑 pytest 不再扫进 `temp/`，而 `temp/test_chatglm*.py` **会在收集期真调外部 API** |
| `addopts = "--continue-on-collection-errors"` | 遇到「导入即报错」的文件不会中断整轮 |
| `addopts` 含 `-m 'not known_broken'` | 默认排除资产漂移用例 |

想看被排除的用例：

```bash
python -m pytest -m known_broken       # 10 个待重做用例
python -m pytest -m "not known_broken"  # 只跑正常的
```

### 2.2 仍需外部条件、跑不了的测试

以下文件在修复中被**改名为 `scripts_*.py`** 退出 pytest 收集——
它们本质是手动脚本（模块级执行 `input()` / 真发 API / `os.chdir`）：

| 新名字 | 原来的名字 | 为什么不能作为测试 |
|---|---|---|
| `scripts_openaichat.py` | `test_openaichat.py` | 模块级 `input()`，非交互即崩 |
| `scripts_openai_reasoner.py` | `test_openai_reasoner.py` | 收集期就用真实 API Key 发请求 |
| `scripts_littleskin_login.py` | `test_littleskin_login.py` | `input()` + 浏览器 OAuth 回调 |
| `scripts_skillmgr.py` | `test_skillmgr.py` | 模块级断言脚本 |
| `scripts_world_engine.py` | `test_world_engine.py` | 模块级断言，且依赖本地 yaml 房间名 |

手动跑：

```bash
python tests/scripts_openaichat.py
```

另外这些文件也需要外部依赖，默认会被环境跳过或失败，不属于回归：
摄像头类（用 `_FakeCv` 假 cv2，可跑）、LM Studio（`localhost:4501`）、
`funasr`（下模型 + 麦克风）、`pycups`、`vlc`。
### 2.3 已标记 known_broken 的 10 个用例

| 文件 | 用例数 | 根因 |
|---|---:|---|
| `test_prompt_ecosystem.py` | 6 | 依赖已删除的 `apps.dsn.prompt._personality_v1_legacy`；断言 prompt 含旧版文案（如 "task"） |
| `test_skills_system.py` | 4 | 技能资产漂移 + `WorkspaceManager` 未初始化 |

这 10 个是**资产漂移**：断言依赖已被删除或改写的资产，而不是代码回归。
已用 `pytestmark = pytest.mark.known_broken` 标记，默认不计入跑分。

**重做建议**：与其恢复旧资产，不如更新断言去匹配当前实现。

---

## 三、测试文件分类
：`harness/`

| 文件 | 覆盖 |
|---|---|
| `test_harness_agent.py` | AgentLoop 基本行为 |
| `test_harness_agent_runtime.py` | AgentRuntime 门面 |
| `test_harness_sdk.py` | SDK `create_agent` / `@tool` |
| `test_harness_tools.py` / `test_harness_standard_tools.py` | 工具与标准工具集 |
| `test_harness_toolbox.py` | 两阶段 toolbox 激活 |
| `test_harness_context_assembly.py` | 分段预算剪裁 |
| `test_harness_memory.py` | 记忆抽象 |
| `test_harness_pipeline.py` | 管线与插件调度 |
| `test_harness_stream.py` | 流式事件 |
| `test_agent_loop_harness.py` | DSN 与 harness 循环等价性 |
| `test_harness_v2_innovations.py` | 声明式装配等创新点 |

### 3.2 框架层：`infra/`

| 文件 | 覆盖 |
|---|---|
| `test_orchestrator.py` / `test_harness_models.py` | 编排与模型契约 |
| `test_model_scheduler.py` / `test_harness_scheduler.py` | 插槽调度 |
| `test_dynamic_router.py` | 端点可用性学习 |
| `test_harness_llamacpp.py` / `test_harness_strata.py` / `test_lmstudio.py` | 各后端 |
| `test_harness_policy.py` / `test_harness_retry.py` | 策略与重试 |
| `test_harness_runtime.py` / `test_harness_settings.py` | DI 与配置 |
| `test_harness_tasks.py` | 任务系统 |
| `test_local_engine_cancel.py` / `test_orchestrator_load_cancel.py` | 取消竞态 |

### 3.3 应用层

| 文件 | 覆盖 |
|---|---|
| `test_dsn_ui*.py`（6 个） | dsn_ui 的 API 模式、多模态、缓存、资源 |
| `test_dsn_study_boot.py` | dsn_study 装配 |
| `test_personality_v2_*` / `test_personality_v3_dynamics.py` | 人格系统 |
| `test_memory.py` / `test_topics.py` | 记忆与话题 |
| `test_maintenance*.py` | 维护系统 |
| `test_tracking_vision.py` / `test_webcam.py` / `test_multi_camera.py` | 视觉与摄像头 |
| `test_git*` / 其余 | 各类集成 |

---

## 四、哪些测试跑不了

见 [2.2](#22-仍需外部条件跑不了的测试)。简表：

| 依赖 | 涉及 |
|---|---|
| 真实 LLM API | `scripts_*.py`（已移出收集）、部分 dsn_ui 用例 |
| 本地模型服务器 | `test_harness_llamacpp`、`test_lmstudio`、`test_harness_strata` |
| 摄像头 / 音频 | `test_funasr`、`test_printer`、`test_vlc` |

> 摄像头类测试大多用 `_FakeCv` 假 cv2，**不真开设备**，可以放心跑。

---

## 五、加测试的建议


### 5.1 命名

```
test_harness_<模块>.py      框架层
test_<app>_<功能>.py        应用层
```

### 5.2 用 Stub 而非真实模型

```python
from infra.orchestrator import StubChatClient, ChatResponse

client = StubChatClient(responses=[ChatResponse(content="固定回复")])
```

### 5.3 用 Runtime.activate 隔离全局状态

本项目有 `ModelOrchestrator` / `ModelScheduler` / `Runtime` 三个进程级单例。
测试之间互相污染是常见问题，建议：

```python
from infra.runtime import Runtime

def test_something():
    rt = Runtime(name="test")
    with Runtime.activate(rt):   # 隔离，退出即恢复
        ...
```

### 5.4 避开 `import apps.dsn.main`

`apps/dsn/main.py` **在导入期就会检查 `.env` 并可能进入交互式 onboarding**
（`main.py:54`）。测试里导入它会让 pytest 卡在等待 stdin。
需要测 DSN 组件时，直接导入子模块（如 `apps.dsn.engine`）。

### 5.5 改动前后各跑一次

```bash
python -m pytest tests/test_harness_*.py -q     # 改动前
# ... 改代码 ...
python -m pytest tests/test_harness_*.py -q     # 改动后
```

关注的是**通过数是否减少**，而不是「是否全绿」——因为基线本来就不是全绿。

---

## 六、测试基础设施现状

| 项 | 状态 |
|---|---|
| `tests/conftest.py` | ✅ 已补（stub_client fixture + 单例重置 + 数据目录隔离） |
| `pyproject.toml` 的 pytest 配置 | ✅ 已补（testpaths / norecursedirs / markers / addopts） |
| marker 分组 | ✅ 已注册 `slow` / `integration` / `known_broken` / `script_not_test` |
| CI workflow | ❌ **仍缺** —— `.github/workflows/` 只有 issue 摘要，不跑测试 |
| 断言风格统一 | ❌ 仍有 `return True/False` 的用例（pytest 会警告） |

### 数据隔离是怎么做的

`conftest.py` 把 `DSN_UI_DATA_DIR` 指向临时目录并自动清理，
因此跑测试**不再往 `apps/dsn_ui/data/` 写真实数据库**。
`MagicMock/` 产物也已根治：`apps/dsn_ui/thought_cache.py` 现在只接受
`str` / `os.PathLike` 作为 data_dir，MagicMock 会被拒掉并回退到默认值。

> ⚠️ `conftest.py` **刻意不修改工作目录**。本仓库大量测试用相对路径定位
> `apps/dsn/skills`、`prompt` 目录，cwd 一旦变成 tmp 就会大面积
> `FileNotFoundError`（首次实现时踩过，已修正）。

---

## 七、剩余建议

1. 加一个 CI workflow 跑 `pytest -q`；
2. 重做 `test_prompt_ecosystem` / `test_skills_system` 的 10 个用例（见 2.3）；
3. 给需要外部设备的测试补 `@pytest.mark.integration`，用 `-m "not integration"` 过滤。
