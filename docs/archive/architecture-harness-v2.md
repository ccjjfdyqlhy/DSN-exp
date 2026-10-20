# AICF 创新架构 v2

> 目标：让 AICF（Agent Infrastructure Cybernetics Framework，智能体基础设施控制论框架）
> 成为"通用 AI 应用搭建底座"，与 DSH 形成差异化定位。
> 日期：2026-08-14 · 状态：设计落地（代码与测试已入库）
>
> 分层现状：基础设施与运行时管理层位于 `infra/`，Agent 核心位于 `harness/`，
> 具体应用位于 `apps/`。本文中涉及策略、缓存、存储、网关等基础设施的路径已按此更新。

---

## 一、与 DSH 的架构对比定位

| 维度 | DSH | AICF v2 |
|---|---|---|
| 组织单元 | 插件（Cordis plugin + 配置树） | **策略对象（Policy Object）+ 段（Segment）** |
| 配置方式 | cordis.yml 组装插件 | **AgentSpec 声明组装 Agent 行为** |
| 上下文管理 | 事件溯源 + 投影 + 压缩 | **三段式 + 预算剪裁 + 符号预取 + 指令采集** |
| Token 经济 | token meter（计量） | **路由→预算→计量→预测→保活 闭环** |
| 多智能体 | 子代理 + Workflow + Goal | **swarm 黑板共识 + subagent 主管-工人** |
| 装配入口 | profile → bundle → patch | **launcher → AppBundle → AgentSpec** |

**核心创新一句话**：DSH 用"插件"描述系统怎么运行，AICF 用"策略对象 + 段"描述 Agent 怎么思考。

---

## 二、五大创新架构思想

### 1. 策略对象一级公民（Policy as First-Class）

行为决策（路由、预算、预测、激活、剪裁）不再是散落代码，而是**可序列化、可测试、可组合的策略对象**，位于 `infra/policy/`（策略）与 `harness/tools/`（工具）：

- `ModelRouter` — 模型路由决策（任务类型/高峰/预算压力/手动覆盖）
- `TokenMeter` + `TokenBudget` — 记账与预算（pressure() 驱动降级）
- `DurationPredictor` — 耗时预测（死区学习，驱动进度显示）
- `CacheWarmer` — 前缀缓存保活（空闲 keepalive）
- `ToolboxManager` — 两阶段工具激活（动态工具箱）
- `SegmentedContextAssembler` — 上下文预算剪裁

每个策略：构造即配置、方法即决策、repr 即状态。应用层只需**装配**，不实现。

### 2. 声明式 Agent（AgentSpec — 配置即代码）

`harness/agent/assembler.py` 的 `AgentAssembler` 把完整 Agent 行为收敛为一个可序列化 spec：

```python
spec = AgentSpec(
    name="code-assistant",
    system_prompt="你是一名资深工程师。",
    prompts_dir="prompts/",               # 模块化提示词
    router={"flash_model": "...", "pro_model": "..."},
    tools="standard",                      # 标准工具集
    toolbox={"enabled": True},             # 两阶段激活
    budget={"token_cap": 200000, "cost_cap": 0.5},
    memory=True,
)
agent = AgentAssembler(client).assemble(spec)
```

一个 spec = 一个 AI 应用。可存 YAML、可版本化、可热换。

### 3. 上下文资产化（Context as Assets）

把"注入上下文的东西"抽象为**段（Segment）**：备忘/摘要/原文/尾部各有类型、优先级、预算与剪裁规则（`harness/context_assembly.py`）。

- 话题系统（DSN 应用）→ 段的生产者之一
- 提示词片段（`harness/prompts`）→ 段风格的 system 组件
- 指令采集（`ContextGatherer` 的 @req/@sym/@grep/@ls/@tree）→ 输入侧上下文
- 符号预取（`SpeculativePrefetch` + `[FETCH:]` 协议）→ 错误驱动的上下文

统一由预算内核剪裁，任何应用声明自己的段类型即可获得"预算安全"。

### 4. 自适应 Token 经济闭环

`路由 → 预算 → 计量 → 预测 → 保活` 五环闭环：

```
请求 → ModelRouter 选档（任务类型/高峰/预算压力）
     → AgentLoop 执行 → TokenMeter 记账（缓存命中分账）
     → TokenBudget 检查（超限触发降级/截断回调）
     → DurationPredictor 学习（死区更新，预测下轮耗时）
     → CacheWarmer 空闲保活（前缀缓存不失效）
```

这是对 DSH"计量"的单点能力升级为**经济系统**：Agent 自己会省钱。
> 策略实现位于 `infra/policy/`（`router.py` / `token_meter.py` / `predictor.py` / `warmer.py`）。

### 5. 层级智能体原语对（Pair of Hierarchical Primitives）

- **swarm**（`harness/agent/swarm.py`）：平级黑板共识——头脑风暴/评审
- **subagent**（`harness/agent/subagent.py`）：主管-工人委派——任务拆解并发执行
- **modes**（`harness/agent/modes.py`）：agent/oneshot/swarm 三模式切换

与 DSH 的子代理/Workflow 相比：更轻、纯 Python、无脚本引擎依赖。

---

## 三、标准工具集（通用 AI 应用搭建）

`harness/tools/standard.py` 的 16 个开箱即用工具（纯 Python，依赖可注入）：

| 命名空间 | 工具 | 用途 |
|---|---|---|
| file | read / write / **edit（行范围）** / list / tree | 文件读写与探索（防目录穿越） |
| text | chunk / extract_json / diff | 文本处理 |
| code | syntax_check / locate_symbol | 代码分析 |
| proc | run | 命令执行（超时+截断） |
| web | fetch | 网页抓取 |
| project | summary / **snapshot（哈希）** / todo | 项目级操作 |
| batch | run | 批量占位 |

---

## 四、dekacode 功能对齐矩阵

| dekacode 能力 | 落点（infra/ 或 harness/） | 状态 |
|---|---|---|
| 20+ 工具 | standard.py 16 工具 + toolbox | ✅ |
| AST 调用图 | codegraph（builder/symbol/search/imports/watcher） | ✅ |
| 推测预取 + FETCH 协议 | agent/context.py SpeculativePrefetch/PrefetchPlaceholders | ✅ |
| RTK 过滤 | pipeline/filters.py OutputFilter | ✅ |
| 语义缓存 | infra/cache.py SemanticCache | ✅ |
| 缓存保活 | infra/policy/warmer.py CacheWarmer | ✅ |
| 双模型路由 | infra/policy/router.py ModelRouter | ✅ |
| 成本核算 | infra/policy/token_meter.py TokenMeter | ✅ |
| 耗时预测 | infra/policy/predictor.py DurationPredictor | ✅ |
| 会话持久化 | infra/store/chat_store.py SessionStore | ✅ |
| 模块化提示词 | prompts/ PromptEngine | ✅ |
| 文件监听 | codegraph/watcher.py FileWatcher | ✅ |
| 子代理 | agent/subagent.py SubAgentRunner | ✅ |
| 模式 | agent/modes.py ModeState | ✅ |
| @ 指令采集 | context_gatherer.py ContextGatherer | ✅ |
| 智能分块/定位/诊断 | standard text.chunk / codegraph search / standard syntax_check + diagnose 后续 | ✅/⚠️ |
| mnemosyne 记忆 | memory/（InMemoryStore + VectorIndex） | ⚠️ 简版 |
| Web UI | 引擎层 infra/gateway + dsn 应用层 psychoscope/web_admin | ⚠️ 应用层 |

---

## 五、下一步（推荐路线）

1. **P0**：会话检查点 + 事件溯源（对齐 DSH 可靠性）
2. **P0**：子代理持久化（SubTask 结果落盘，断点续跑）
3. **P1**：AgentSpec 支持 YAML 文件加载 + 热重载
4. **P1**：policy 闭环接入 AgentLoop（meter 自动回填 usage）
5. **P2**：Web UI 引擎化（基于 gateway 的通用会话面板）
