# apps/dekacode — DSN-exp Harness 复刻的 Dekacode WebUI

在 DSN-exp harness 基座上复现 `~/dekacode` 的 WebUI 代码助手。

## 运行

```bash
# 从项目根目录启动（默认工作区为当前目录）
python main.py --app dekacode

# 指定项目目录/端口（launcher 透传参数需用 -- 分隔）
python main.py --app dekacode -- --project /path/to/project --port 8080

# 或直接运行
python -m apps.dekacode --project /path/to/project --port 8080
```

打开 http://localhost:8080 即可使用。

## 配置

优先读取项目目录下的 `.env`，也支持环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEKACODE_API_KEY` / `OPENAI_API_KEY` | - | OpenAI 兼容 API Key |
| `DEKACODE_BASE_URL` / `OPENAI_API_BASE` | `https://api.deepseek.com/v1` | API 地址 |
| `DEKACODE_FLASH_MODEL` / `FLASH_MODEL` | `deepseek-v4-flash` | Flash 模型 |
| `DEKACODE_PRO_MODEL` / `PRO_MODEL` | `deepseek-v4-pro` | Pro 模型 |
| `DEKACODE_OPENAI_MODEL` / `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI 模型 |
| `DEKACODE_PROJECT` | 当前目录 | 工作区项目路径 |
| `DEKACODE_DB` | `<project>/.dekacode_web.db` | 会话数据库 |
| `DEKACODE_PORT` | `8080` | Web 端口 |

## 已实现功能

- 上下文结构图示：侧栏 `Context` 面板显示会话角色分布、工具调用数、系统提示词。
- 更多配置键：`/api/config` 支持运行时修改最大步数、输出截断、上下文预算、历史消息上限、技能目录、主题等。
- 模型 / Provider 配置 WebUI：Options → Provider / Models 可管理多个 Provider，支持新增/删除/切换/编辑 Provider 名称、Base URL、API Key、Flash/Pro/OpenAI 模型。
- 深色 / 浅色 UI：侧栏 `◐ Theme` 一键切换并持久化到 `localStorage`。
- 技能加载：自动扫描 `apps/dekacode/skills`（或 `DEKACODE_SKILLS_DIR`），支持 `TOOLS` / `register` / `SKILL` 约定，可在 WebUI 热重载。
- 扩展工具集：在 harness 标准工具之外增加 `file.grep`、`file.glob`、`code.callers`、`code.read_symbol`、`git.status`、`git.diff`、`git.commit`、`code.review`、`project.deps`、`task.split`（SubAgentRunner 并发子任务）。
- Diff 可视化编辑器：右侧侧栏 `Diff Editor` 使用 `als-highlight` 语法高亮，可加载文件、编辑新内容、实时查看行级 diff 并应用写入；AI 执行编辑工具时自动展开。
- 统计页面：侧栏 `Stats` 展示会话数、消息数、工具调用、符号数、文件数、Token/成本等聚合数据。
- 会话列表增强：后端会话与本地 Web 会话合并展示、当前会话高亮、支持删除/重命名/导出会话、加载后上下文同步。
- Token/成本追踪：流式调用自动记录 usage 并写入 `turn_usage`，`/cost` 与 Stats 页展示输入/输出 token 与估算成本。
- 上下文预算控制：发送给模型前按 `max_history_messages` 与 `context_budget` 自动剪裁历史，不破坏持久化会话。
- Prompt 片段管理：Options → Prompts 可查看/编辑 `prompts/*.md`，保存后热重载 system prompt。
- `/undo`：撤销最近一轮用户消息及其后续内容，并同步持久化到数据库。

## 实现说明

- 前端：完整复用 `~/dekacode/webui/static`（HTML/CSS/JS/logo）。
- 后端：不依赖 dekacode 私有模块，改用 harness 基座：
  - `harness.agent.AgentLoop.run_stream` 驱动流式 Agent 循环
  - `harness.tools.install_standard_tools` + `ToolDeps` 提供文件/Shell/代码/项目工具
  - `harness.codegraph.GraphBuilder` 构建 AST 调用图
  - `harness.store.SessionStore` 持久化会话
  - `harness.context_gatherer.ContextGatherer` 支持 One-Shot `@req/@sym/@grep/@ls/@tree`
  - FastAPI/uvicorn 提供与 Dekacode 一致的 `/ws` 与 `/api/*` 协议
