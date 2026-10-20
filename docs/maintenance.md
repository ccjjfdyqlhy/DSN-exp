# 维护手册

> 读者：已经能跑起来、准备真正改代码的人。
> 这份文档只讲「怎么不把事情搞坏」——不是教程，是约束与惯例。

---

## 一、改代码前的五分钟

### 1.1 找到正确的落点

```
需求：'加一个新的记忆检索策略'
   ↓ 它认识业务语义吗？
     认识 → apps/<对应应用>/memory/
   ↓ 它只是通用的检索算法吗？
     是   → harness/memory/
   ↓ 它需要新的向量模型接口吗？
     需要 → infra/orchestrator/（新增 IEmbeddingClient 实现）
```

**判断口诀**：`infra` 管资源，`harness` 管思考，`apps` 管场景。

### 1.2 确认你改的是「被执行的那一套」

这个仓库最大的陷阱是**同一功能有多套实现**：

| 场景 | 并存的实现 |
|---|---|
| `dsn` 的启动装配 | `boot.create_application` / `DSNEngine(subapp)` / `create_engine_with_defaults` |
| Agent 门面 | `AgentRuntime` / `AgentAssembler` / `sdk.Agent` / 各应用的 Coordinator |
| 模型客户端 | `infra.orchestrator.*` / `apps/dsn/models/` / `apps/dsn_study/models/` |
| 语义缓存 | `infra/cache.py`（无人用） / `apps/dsn/semantic_cache/`（在用） |
| 记忆 | `harness/memory/`（抽象） / `apps/dsn/memory/`（实现） |

**动手前的自检**：在你打算修改的函数上打一个断点或加一条 `logger.warning`，
实际跑一遍，确认它真的被调用了。这能省掉大量「改完没反应」的时间。

### 1.3 读懂已有注释

**本仓库的注释就是缺陷数据库。** `infra/` 目录实测 **0 个** `TODO`/`FIXME`——
不是因为没问题，而是因为所有历史 bug 都被写成长篇中文注释贴在代码旁，
格式大致是：

```python
# 修复说明：原实现是 xxx，会导致 yyy。
# 现在改成 zzz，因为 …。别再改回去。
```

**修改时请保留这些注释。** 它们记录的是「为什么不能写成更自然的样子」，
删掉之后下一个人一定会重蹈覆辙。

---

## 二、必须守住的不变式

以下每条都是「改了会静默出错」的约定，务必逐条确认。

### 2.1 工具名：wire 名编解码

发给模型的工具名必须是 wire 名（`file__read`），解析回来必须还原成内部名（`file.read`）。
回填 assistant 的 `tool_calls` 时若用了内部点号名，会对强校验 `^[a-zA-Z0-9_-]+$`
的 provider 直接 400。

涉及：`harness/tools/base.py:24-49`、`harness/agent/adapters.py:82-88`、`loop.py:214`。

### 2.2 tool 消息必须有前置 assistant(tool_calls)

几乎所有 chat_template 都要求 `role=tool` 的消息紧跟在含 `tool_calls` 的
`assistant` 消息之后。任何剪裁上下文、合并历史的代码都要维持这个配对。

`ThreeZoneContext` 有专门的清洗逻辑（`harness/agent/context.py:68-81`），
**新增上下文处理时请复用它，不要另写一套**。

### 2.3 `reasoning_content` 必须随 assistant 回传

DeepSeek reasoner 一类模型要求把思考链原样带回。丢掉会报错或降智。

### 2.4 同步 handler 返回 coroutine 时要补 await

`Tool.run_async` 里有一个补 await 的分支（`harness/tools/base.py:141-147`）。
这不是冗余——swarm 黑板曾经因为缺这一步而「工具报成功但副作用没发生」。

### 2.5 `max_steps <= 0` 表示不限制

三个循环分支口径必须一致（`loop.py:203` / `:299` / `:349`）。这是刻意设计，不是 bug。

### 2.6 插件按 priority 升序调度

`PluginManager` 是**值小者先执行**（`harness/pipeline/manager.py:132`）。
这是从 dsn 沿用下来的约定，harness 原本是降序、已对齐。
**改成降序会静默改变十几个插件的执行顺序。**

### 2.7 上下文计划必须无副作用

`SegmentedContextAssembler.plan()` 承诺不修改入参，截断时用 `replace()` 派生副本
（`context_assembly.py:223-230`）。

### 2.8 模型子进程必须走指定线程

`Popen` 必须经 `_popen_on_launch_thread`（`infra/orchestrator/local_engine.py:61`）。
原因：`PR_SET_PDEATHSIG` 绑定发起 fork 的线程，在事件循环线程池里起进程会导致
loop 关闭时模型被误杀。

### 2.9 `load_fn` 必须在调度器锁外执行

`ModelScheduler._do_load` 里显式 `release()`/`acquire()`（`scheduler.py:432`）。
这是维护高危区，改动前先读懂那段注释。

---

## 三、按改动位置对照检查

| 你改了什么 | 必须同时检查 |
|---|---|
| `harness/agent/loop.py` | `run_async` **和** `run_stream` 两条路径；`run_rounds` 契约 |
| `harness/tools/*` | schema 与执行逻辑是否都更新；wire 名编解码 |
| `harness/pipeline/*` | 8 个 HookPoint 的消费方；插件 priority 顺序 |
| `infra/orchestrator/*` | `ModelScheduler` 锁；`_ACTIVE_LAUNCHERS`；状态自愈 |
| `infra/*` 的 import | 是否引入了 `harness`（逆向依赖红线） |
| `apps/dsn_ui/server.py` | 新路由必须在 SPA catch-all **之前**注册 |
| `apps/dsn_ui/agent.py` | `chat_stream` **和** `chat_invoke` 两份分支逻辑 |
| `apps/dsn_ui` 前端 | 必须 `npm run build`，否则后端读的还是旧 `static/` |
| `apps/dsn/skills/**` | `dsn_study` 通过**符号链接**复用，必须回归两边 |
| `harness/context_assembly.py` | 改动 `plan()` 前先读 `_fold_trailing_tools` 的注释——最近对话的保底逻辑依赖 `SEG_TAIL` 语义 |
| `infra/policy/router.py` | 改 `select()` 优先级前注意 `switch()` 会设置 `_explicitly_selected` 锁定档位 |
| `apps/dsn/boot.py` | `api/app.py` 的重新导出、`main.py` 的读取点（三层转发） |

---

## 四、提交前自检

```bash
# 1. 框架层测试（最快，几秒）
python -m pytest tests/test_harness_*.py -q

# 2. 全量测试（约 78 秒，仓库已内置配置，直接跑即可）
python -m pytest -q

# 3. 语法检查
python -m compileall -q harness infra apps
```

当前基线是 **547 通过 / 0 失败 / 0 收集错误**。

> 因为有 `known_broken` marker，默认跑分会排除 10 个资产漂移用例。
> 想看它们：`python -m pytest -m known_broken`。

---
## 五、风格约定

| 项 | 约定 |
|---|---|
| 命名 | 全仓库 snake_case（PEP 8）。例外：vendored 的 `apps/dsn/pyncm`、外部 API 属性名 |
| 注释语言 | **中文**。面向维护者的解释一律中文，即使代码是英文标识符 |
| 用户可见文案 | 中文 |
| 日志 | `logger = logging.getLogger("模块名")`，避免用 print（除 CLI 输出） |
| 异常 | 只在**确实要降级**时捕获；捕获时必须记录足够的上下文 |
| 新配置 | 优先环境变量 + `apps/<app>/config.py`，与既有惯例一致 |
| 新文档 | 放 `docs/`，并在 README 的文档索引里登记 |

---

## 六、仓库卫生

### `docs/` 已入库

`docs/` 下的 17 篇文档**随仓库分发**（2026-10-20 起从 `.gitignore` 移除 `/docs/` 一行）。
改动文档时请一并提交——这些文档是本仓库最主要的知识载体。
详见 [technical-debt.md](technical-debt.md#文档与仓库卫生)。

### 不要提交的东西

| 路径 | 说明 |
|---|---|
| `*.db` | 运行时数据（`DSN_usrdata.db`、`.emotion_exp.db` 等） |
| `.env` | 真实密钥 |
| `logs/`、`temp/` | 日志与临时区 |
| `MagicMock/` | 测试副作用产物，不是源码 |
| `apps/dsn_ui/static/` | **要提交**（是构建产物，但仓库有意跟踪它） |
| `apps/dsn_ui/frontend/` | **不提交**（源码目录被 .gitignore 忽略） |

### 统计规模时排除噪声目录

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*/__pycache__/*' \
     -not -path './temp/*' -not -path './prototypes/*' -not -path '*/node_modules/*' \
     | xargs wc -l | tail -1
```

---

## 七、什么时候该停下来问

遇到下面这些情况，**先沟通再动手**，因为改动面会远超预期：

- 要给 `ModelOrchestrator` / `ModelScheduler` 的公开方法改名；
- 要改 `AgentSpec` 的字段；
- 要改 `HookPoint` 的成员或 `PluginManager` 的排序方向；
- 要动 `apps/dsn` 的模块级全局（`boot.py` 的 20+ 个变量）；
- 要动 `infra` 对 `harness` 的依赖方向；
- 要删除任何带「修复说明」注释的代码。
