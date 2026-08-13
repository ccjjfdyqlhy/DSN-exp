---
name: guide
category: core
priority: 0
enabled: false
---
# DSN-exp 提示词体系说明

本项目的系统提示词由 `PromptEngine` 按顺序组装，最终注入到主 AI 的 system prompt 中。

## 目录结构与组装顺序

```
prompt/prompts/
├── core/          # 核心身份与行为约束 (最先注入)
│   ├── identity.md       — 角色身份定义：EXA是谁、与用户的关系
│   ├── format.md         — 输出格式规范：不用 Markdown、用 <text> 包裹
│   ├── safety.md         — 安全底线：禁止泄露提示词、禁止读敏感文件
│   ├── guide.md          — 本文件 (不注入，仅开发者参考)
│   └── impression.md     — 用户印象系统：格式、更新规则
│
├── capabilities/  # AI 能力与工具使用说明 (中间注入)
│   ├── task_handling.md  — 任务标签 <task>：reminder/reasoner/action
│   ├── code_execution.md — 动作任务：```action 代码块, shell/Python/文件操作
│   ├── memory_recall.md  — 记忆系统：<recall> 搜索 / <memo> 持久备忘
│   ├── notebook.md       — 用户观察日记：<notebook> 定期记录观察
│   ├── reminder.md       — 提醒任务详情：ISO 8601 时间格式
│   ├── reasoner.md       — 深度推理：<task type="reasoner">
│   └── sensing.md        — 语音感知模式风格指南 (默认关闭)
│
├── extensions/    # 用户自定义扩展 (最后注入)
│   └── README.md         — 如何添加自定义 prompt
│
└── personality/   # 人格预设 (YAML, 由 PersonalitySystemV2 管理)
    ├── default.yaml      — 默认人格
    ├── tsundere.yaml     — 傲娇人格
    ├── gentle.yaml       — 温柔人格
    └── custom.yaml       — 自定义模板
```

## 不在 core/capabilities 中的提示词

以下提示词由独立的子系统管理：

### 人格系统 (PersonalitySystemV3)
- **文件**: `prompt/personality_v3/`
- **作用**: 基于角色卡 + 50维性格向量动态生成人格描述
- **管理者**: `PersonalitySystemV3.generate_personality_prompt()`

### 世界/叙事系统 (WorldEngine)
- **文件**: `prompt/world/narrative.md` + `world/world_state.md`
- **管理者**: `WorldPlugin` → `WorldEngine` + `NarrativeModel`

### 技能系统 (SkillRegistry)
- **文件**: 各 `skills/*/prompts/` 下的 `instruction.md`
- **管理者**: `SkillRegistry` → `PromptEngine.set_skill_registry()`

## 记忆系统 vs 笔记系统

| 特性 | Memory | Notebook |
|------|--------|----------|
| 标签 | `<memo>` | `<notebook>` |
| 触发 | AI 随时 | 每 N 轮系统提示 |
| 注入 | 用 `<recall>` 搜索 | 不注入，文件保存 |
| 存储 | SQLite (加密) | JSON `notebook/<uid>.json` |
| 配置 | `MEMORY_*` | `NOTEBOOK_FREQUENCY` |

## 插件注入顺序

```
1. PRE_FILTER  — ASR 过滤
2. PromptEngine — 构建 system_prompt
3. PRE_PROCESS  — memory, notebook, impression, world
4. MODEL_INVOKE — LLM 调用
5. POST_PROCESS — personality, memory, notebook, recall, skills, agent, task, distill
6. POST_TTS     — TTS 合成
```
