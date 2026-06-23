# 统一 Agent 循环 — 引擎层全标签纠错架构

## 1. 当前问题

现有管线中只有 `<tool>` 标签能参与 Agent 循环，其他系统标签均为单次执行：

| 标签 | 当前行为 | 问题 |
|------|---------|------|
| `<tool>` | AgentPlugin 多步循环 | ✅ 但代码重复 |
| `<task>` | TaskPlugin 单次创建 | ❌ 失败无反馈 |
| `<plan_check>` | PlanPlugin 单次 check_off | ❌ 失败无反馈 |
| `<help>` | HelpPlugin 单次检索 | ❌ 失败无反馈 |
| `<recall>` | RecallPlugin 单次查记忆 | ❌ 失败无反馈 |
| `<memo>` | RecallPlugin 单次存事实 | ❌ 失败无反馈 |
| `<notebook>` | NotebookPlugin 单次存笔记 | ❌ 失败无反馈 |

更深层的问题是架构冗余：**SkillsPlugin 和 AgentPlugin 本质上是同一件事的两种实现**，区别只在于 SkillsPlugin 跑单次、AgentPlugin 跑循环。循环本身不该是一个插件的职责，而应是管线层的通用能力。

## 2. 核心思路：引擎层循环

消除 SkillsPlugin 和 AgentPlugin，把循环控制提升到引擎层。各插件只做自己最擅长的事——处理自己的标签。

```
                         Engine
┌────────────────────────────────────────────────────────┐
│  chat() / chat_stream()                                 │
│                                                         │
│  ① PRE_PROCESS (所有插件，只跑一次)                       │
│  ② LLM 调用 → 得到 original_reply                        │
│  ③ POST_PROCESS 循环:                                    │
│       ├─ 运行所有 POST_PROCESS 插件                       │
│       │  (HelpPlugin, RecallPlugin, TaskPlugin, ...)     │
│       ├─ 检查是否有标签被处理                              │
│       ├─ 有 → 清理标签 + 格式化结果 → 回馈 LLM → 回到 ③    │
│       └─ 无 → 结束                                       │
│  ④ 最终回复清洗 + 返回                                    │
│                                                         │
└────────────────────────────────────────────────────────┘
```

### 2.1 为什么不需要 AgentPlugin

当前 AgentPlugin 做的事：
1. 解析 `<tool>` 标签 → 各插件各自解析自己标签，不需要中央解析
2. 执行工具 → 各插件自己执行，不需要中央执行
3. 清理标签 → 各插件自己清理
4. 循环控制 → 提升到引擎层
5. 结果回馈 LLM → 引擎层统一做

结论：AgentPlugin 只是在重复 pipeline 已经能做的事，外加一个"再调一次 LLM"的步骤。把这个步骤提升到引擎层，AgentPlugin 和 SkillsPlugin 都可以消失。

## 3. 管线流详细设计

### 3.1 标签检测机制

不再需要统一的 TagRegistry。每个插件在 POST_PROCESS 中自然处理自己的标签，以 `_TAG_RESULTS` 作为标签是否被处理过的信号：

```python
# 每个插件在处理标签时，往 ctx 里写结果
# 而不是像现在一样只清理标签不留下痕迹

class HelpPlugin:
    def _on_post_process(self, ctx):
        results = []
        for match in _HELP_RE.finditer(ctx.original_reply):
            result = self._execute_help(match)
            results.append(result)
        ctx.reply = _HELP_RE.sub("", ctx.reply)
        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)
        return ctx
```

引擎层通过 `ctx.extra.get("_tag_results")` 判断本轮是否有标签被处理：

```python
# 引擎层
ctx = pipeline.run(HookPoint.POST_PROCESS, ctx)
if ctx.extra.get("_tag_results"):
    # 有标签被处理过 → 需要回馈 LLM 并继续循环
    ...
```

### 3.2 引擎层循环

```python
# engine.py

class DSNEngine:
    async def chat_stream(self, ...):
        ...
        # ── PRE_PROCESS（只跑一次）──
        ctx = pipeline.run(HookPoint.PRE_PROCESS, ctx)

        # ── LLM 首次调用 ──
        ctx = models_plugin.invoke(ctx)  # 得到 ctx.original_reply

        # ── Agent 循环（仅 POST_PROCESS）──
        if ctx.agent_active:
            ctx = self._agent_loop(ctx, models_plugin)
        else:
            ctx = pipeline.run(HookPoint.POST_PROCESS, ctx)

        # ── 回复清洗 ──
        ctx.reply = clean_display(ctx.reply)
        return ctx

    def _agent_loop(self, ctx, models_plugin):
        max_steps = ctx.agent_max_steps
        for step in range(max_steps):
            # 运行所有 POST_PROCESS 插件
            ctx = pipeline.run(HookPoint.POST_PROCESS, ctx)

            # 检查是否有标签被执行
            results = ctx.extra.pop("_tag_results", [])
            if not results:
                break

            # 清理所有标签 + 追加格式化结果
            reply = ctx.reply
            formatted = self._format_tag_results(results)
            if formatted:
                reply += "\n\n## 执行结果\n" + formatted

            # 回馈 LLM，得到新一轮回复
            ctx.original_reply = models_plugin.invoke_with_context(
                ctx, reply
            )
            ctx.reply = ctx.original_reply
            ctx.extra["_agent_step"] = step

            # 如果 LLM 返回空或停顿时中断
            if not ctx.original_reply or ctx.original_reply.strip() in ("…", ""):
                break

        return ctx
```

### 3.3 _format_tag_results

统一格式化所有标签返回结果，让 LLM 可理解：

```python
def _format_tag_results(self, results: list[dict]) -> str:
    lines = []
    for r in results:
        tag = r["tag"]
        success = r["success"]
        status = "✅ 成功" if success else "❌ 失败"
        summary = r.get("summary", "")
        lines.append(f"  [{tag}] {status}")
        if summary:
            lines.append(f"    {summary}")
        if not success and r.get("error"):
            lines.append(f"    错误: {r['error']}")
    return "\n".join(lines)
```

## 4. 插件改造

核心原则：**所有插件不再关心"现在是 agent 模式还是单次模式"，一律正常处理自己的标签、写 `_tag_results`。引擎层根据是否开启 agent 来决定循环次数。**

### 4.1 SkillsPlugin → 删除

SkillsPlugin 的逻辑完全被各插件自身取代。`<tool>` 标签由原本 SkillPlugin 处理？不——实际上 `<tool>` 不是一个标签名，而是一种协议（`{"skill":"xxx","tool":"yyy","params":{...}}`）。当前的 `<tool>` 处理逻辑（解析 JSON → call_tool → 格式化结果）应该保留。

但实际上，看现在的代码，`skills_plugin.py` 做的事已经被 `agent_plugin.py` 完整覆盖了。两者同时存在只是因为 `agent_active` 标志在做路由选择。既然引擎层接管了路由，SkillsPlugin 可以直接删除。

那 `<tool>` 标签谁处理？可以由一个极轻量的 `ToolPlugin` 处理，或者合并到引擎的循环逻辑里。

更简洁的方案：**创建一个 `ToolPlugin`（或者直接由引擎内置 tool 处理逻辑）**，注册 POST_PROCESS，在 `_tag_results` 中写入 `<tool>` 执行结果。

### 4.2 HelpPlugin

- 现有 `_HELP_RE` 匹配逻辑保持不变
- 在 `_on_post_process` 中，将检索结果写入 `ctx.extra["_tag_results"]`
- 非标签逻辑（如有）保持不变

```python
def _on_post_process(self, ctx):
    results = []
    for match in _HELP_RE.finditer(ctx.original_reply):
        try:
            data = self._search(match.group(1).strip())
            results.append({
                "tag": "<help>", "success": True,
                "summary": f"检索到 {len(data)} 条相关提示词",
                "data": data,
            })
        except Exception as e:
            results.append({
                "tag": "<help>", "success": False,
                "error": str(e),
            })
    ctx.reply = _HELP_RE.sub("", ctx.reply)
    if results:
        ctx.extra.setdefault("_tag_results", []).extend(results)
    return ctx
```

### 4.3 RecallPlugin

- `<recall>` 处理：解析 JSON → 查记忆 → 写结果
- `<memo>` 处理：提取文本 → 存事实 → 写结果

### 4.4 TaskPlugin

- `<task>` 处理：创建后台任务 → 写结果
- 结果中包含任务 ID，LLM 可根据 ID 后续查询状态

### 4.5 NotebookPlugin

- `<notebook>` 处理：存笔记 → 写结果

### 4.6 PlanPlugin

- `<plan_check>` 处理：check_off / skip → 写结果
- 非标签逻辑（`_handle_daily_report`、PRE_PROCESS 计划注入）保持不变

### 4.7 ToolPlugin（新增，替代 SkillsPlugin）

处理 `<tool>` 标签：

```python
_TOOL_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)

class ToolPlugin(Plugin):
    name = "tool"
    priority = 35
    hooks = [HookPoint.POST_PROCESS]

    def __init__(self, skill_registry=None):
        self._skill_registry = skill_registry

    def on_hook(self, hook, ctx):
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_post_process(self, ctx):
        results = []
        original = ctx.original_reply
        for match in _TOOL_RE.finditer(original):
            try:
                data = json.loads(match.group(1).strip())
                skill_name = data.get("skill", "")
                tool_name = data.get("tool", "")
                params = data.get("params", {})
                if not skill_name or not tool_name:
                    continue
                result = self._skill_registry.call_tool(skill_name, tool_name, params)
                results.append({
                    "tag": "<tool>", "success": True,
                    "skill": skill_name, "tool": tool_name,
                    "summary": f"{skill_name}.{tool_name} 执行成功",
                    "data": result,
                })
            except Exception as e:
                results.append({
                    "tag": "<tool>", "success": False,
                    "error": str(e),
                })
        ctx.reply = _TOOL_RE.sub("", ctx.reply)
        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)
        return ctx
```

## 5. 执行顺序

插件 priority 已经定义了 POST_PROCESS 的执行顺序，也就是标签的实际处理顺序：

| priority | 插件 | 处理的标签 |
|----------|------|-----------|
| 5 | HelpPlugin | `<help>` |
| 33 | RecallPlugin | `<recall>`, `<memo>` |
| 35 | ToolPlugin | `<tool>` |
| 39 | NotebookPlugin | `<notebook>` |
| 40 | TaskPlugin | `<task>` |
| 72 | PlanPlugin | `<plan_check>` |

引擎循环中，每个 iteration 所有插件按此顺序跑完，然后判断是否要回馈 LLM 继续循环。

## 6. 删除文件

- `plugins/builtin/skills_plugin.py` — 完全删除，功能被 ToolPlugin 替代
- `plugins/builtin/agent_plugin.py` — 完全删除，循环逻辑提升到引擎层

## 7. 配置变更

`subapp.yaml` agent 段：

```yaml
agent:
  active: true          # 是否启用 agent 循环
  max_steps: 5          # 最大循环步数
  timeout: 120.0        # 超时
```

## 8. 向后兼容

- `agent_active=True`（默认）：引擎执行 `_agent_loop`，所有标签参与循环
- `agent_active=False`：引擎只跑一次 POST_PROCESS，各插件按现有逻辑执行
- 两种模式下各插件代码**完全一致**——它们只负责处理标签、写结果，不关心是否循环
- 区别只在引擎层：跑一次 POST_PROCESS 还是循环跑

## 9. 与旧架构对比

| | 旧架构 | 新架构 |
|---|---|---|
| 循环控制 | AgentPlugin（插件内） | Engine（引擎层） |
| `<tool>` 处理 | SkillsPlugin / AgentPlugin 各写一套 | ToolPlugin 唯一 |
| 其他标签 | 各插件自扫门前雪，无循环 | 各插件照常处理，引擎层决定是否循环 |
| 插件的认知 | 需判断 agent_active 决定行为 | 不需要，只管处理标签写结果 |
| 代码重复 | SkillsPlugin ≈ AgentPlugin._single_pass | 零重复 |
| 新增标签 | 需修改 AgentPlugin 加处理 | 只需新增或修改对应插件 |

## 10. 实施步骤

1. 创建 `ToolPlugin` — 提取 skills_plugin.py 中的 `<tool>` 处理逻辑
2. 改造 `HelpPlugin` — 在 POST_PROCESS 中写 `_tag_results`
3. 改造 `RecallPlugin` — `<recall>`, `<memo>` 处理写 `_tag_results`
4. 改造 `TaskPlugin` — `<task>` 处理写 `_tag_results`
5. 改造 `NotebookPlugin` — `<notebook>` 处理写 `_tag_results`
6. 改造 `PlanPlugin` — `<plan_check>` 处理写 `_tag_results`
7. 在引擎层实现 `_agent_loop` — 循环调用 POST_PROCESS + 回馈 LLM
8. 删除 `skills_plugin.py` 和 `agent_plugin.py`
9. 调整 PluginContext — 移除 `agent_active` 等不再需要的字段（原由 AgentPlugin 消费）
10. 测试验证 — 单次模式 + agent 全标签循环 + 断点续跑
