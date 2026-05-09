# Prompt 生态实现指导

> 来源: architecture.md §五 / §八.2 / §八.3
> 目标: 将当前 prompt.py 中的单字符串硬编码，升级为可动态组装的 MD 文件库 + 性格系统

---

## 一、当前痛点

```python
# prompt.py (当前) — 一个 100 行的字符串模板，改任何内容都要改代码
DEFAULT_SYSTEM_PROMPT = """
你是一个名为EXA的人工智能系统。...
## 任务处理能力
...
"""
```

改进后：改 personality 不用改代码，加能力只要写个 MD 文件丢进目录。

---

## 二、目标目录结构

```
prompt/
├── __init__.py
├── engine.py           # PromptEngine — 组装最终 system prompt
├── library.py          # PromptLibrary — MD 文件提示词库
├── personality.py      # PersonalitySystem — 性格系统
├── prompts/            # 提示词文件目录
│   ├── core/
│   │   ├── identity.md     # 基础身份 → 从 DEFAULT_SYSTEM_PROMPT 前段拆分
│   │   ├── format.md       # 输出格式 (TTS 友好)
│   │   └── safety.md       # 安全约束
│   ├── capabilities/
│   │   ├── task_handling.md    # 任务处理能力 → 从 DEFAULT_SYSTEM_PROMPT 中段拆分
│   │   ├── code_execution.md   # 代码执行能力
│   │   ├── reminder.md         # 提醒能力
│   │   └── reasoner.md         # 推理能力
│   ├── personality/            # 性格预设 (YAML)
│   │   ├── default.yaml
│   │   ├── tsundere.yaml
│   │   ├── gentle.yaml
│   │   └── custom.yaml
│   └── extensions/             # 用户自建提示词
│       └── README.md
```

---

## 三、三层架构

```
PromptEngine (组装)
    ├── PromptLibrary (MD 文件库)
    │     ├── core/          身份·格式·安全
    │     ├── capabilities/  任务·代码·推理
    │     └── extensions/    用户扩展
    ├── PersonalitySystem (性格)
    │     ├── 大五人格维度
    │     ├── 情绪状态 (动态波动)
    │     ├── 关系亲密度
    │     └── 性格预设 (YAML)
    └── SkillRegistry (技能提示词注入，来自技能系统)
```

---

## 四、核心实现

### 4.1 PromptLibrary (`prompt/library.py`)

MD 文件解析器，支持 YAML frontmatter。

**MD 文件格式：**

```markdown
---
name: task_handling
category: capabilities
version: "1.0"
description: 任务处理能力定义
tags: [task, action, reminder]
priority: 50
enabled: true
---

## 任务处理能力

你可以通过 <task></task> 标签向系统发送任务指令...
```

**核心 API：**

| 方法 | 说明 |
|------|------|
| `scan_and_load(dirs)` | 启动时扫描所有目录，加载 MD 文件 |
| `load_file(path)` | 运行时动态加载单个文件 |
| `unload(prompt_id)` | 移除指定提示词 |
| `reload(prompt_id)` | 从磁盘重新读取（热重载） |
| `toggle(prompt_id, bool)` | 启用/禁用（不删除） |
| `get_content_by_category(cat)` | 获取某个分类所有启用的内容，按 priority 排序拼接 |
| `get_content(prompt_id)` | 获取单个提示词内容 |
| `list_all()` | 列出所有提示词及其状态 |

**PromptFile 数据模型：**

```python
@dataclass
class PromptFile:
    name: str
    category: str        # core / capabilities / extensions
    version: str
    description: str
    tags: list
    priority: int        # 在同分类内的排序
    enabled: bool
    content: str         # frontmatter 之后的正文
    source_file: str     # 源文件路径
```

---

### 4.2 PersonalitySystem (`prompt/personality.py`)

> **关键：输出不是字段拼接，而是自然语言描述。**

**PersonalityProfile 数据模型：**

```python
@dataclass
class PersonalityProfile:
    # 大五人格 (静态底层)
    openness: float          = 0.7   # 开放性
    conscientiousness: float = 0.6   # 尽责性
    extraversion: float      = 0.5   # 外向性
    agreeableness: float     = 0.7   # 宜人性
    neuroticism: float       = 0.3   # 神经质

    # 情绪状态 (短期波动，向基线自然回归)
    energy: float      = 0.6
    positivity: float  = 0.7
    patience: float    = 0.7
    curiosity: float   = 0.8

    # 语言风格
    formality: float  = 0.3
    verbosity: float  = 0.4
    humor: float      = 0.4
    sarcasm: float    = 0.1

    # 关系动态
    intimacy: float   = 0.5       # 当前亲密度
    intimacy_baseline: float = 0.5
    intimacy_max: float     = 0.9
    warming_rate: float     = 0.02

    # 额外
    catchphrases: list = []
    habits: list = []
```

**核心 API：**

| 方法 | 说明 |
|------|------|
| `load_preset(yaml_path)` | 从 YAML 文件加载性格预设 |
| `generate_personality_prompt()` | 生成自然语言性格描述 |
| `on_interaction()` | 每次交互后更新情绪 + 亲密度 |
| `decay()` | 情绪向基线自然回归（定时调用） |
| `switch_preset(name)` | 运行时切换性格 |
| `current_state()` | 获取当前性格状态 |
| `list_presets()` | 列出所有可用的性格预设 |

**generate_personality_prompt() 输出示例：**

```
## 你的性格

你的性格特点：开放性偏高（开放好奇），宜人性偏高（温和友善）。
你现在的状态：精力充沛，心情不错，充满好奇。请根据这个状态调整你的语气和表达方式。
你的说话风格：说话随意自然，像朋友聊天；回答简洁，不啰嗦。
你和用户有过一些交流，逐渐熟悉中。
```

---

### 4.3 性格预设 YAML 格式

```yaml
# prompts/personality/default.yaml
name: default
display_name: "默认"
description: "友善、理性、略带好奇"

traits:
  openness: 0.7
  conscientiousness: 0.6
  extraversion: 0.5
  agreeableness: 0.7
  neuroticism: 0.3

emotion_baseline:
  energy: 0.6
  positivity: 0.7
  patience: 0.7
  curiosity: 0.8

speech_style:
  formality: 0.3
  verbosity: 0.4
  humor: 0.4
  sarcasm: 0.1

catchphrases: []
habits:
  - "回答前会先确认理解了问题"
  - "遇到不确定的事情会坦诚说明"

relationship:
  initial_distance: 0.5
  warming_rate: 0.02
  max_intimacy: 0.9
```

---

### 4.4 PromptEngine (`prompt/engine.py`)

```python
class PromptEngine:
    """
    组装最终 system prompt。

    输入: user_info + 当前状态
    输出: 完整 system prompt 字符串
    """

    def __init__(self, library: PromptLibrary, personality: PersonalitySystem,
                 skill_registry=None):
        self.library = library
        self.personality = personality
        self.skill_registry = skill_registry

    def build_system_prompt(self, user_info: dict) -> str:
        sections = []

        # 1. core/ — 身份·格式·安全
        sections.append(self.library.get_content_by_category("core"))

        # 2. 性格描述 (动态生成)
        sections.append(self.personality.generate_personality_prompt())

        # 3. capabilities/ — 能力定义
        sections.append(self.library.get_content_by_category("capabilities"))

        # 4. 已加载技能的提示词 (从 SkillRegistry 获取)
        if self.skill_registry:
            sections.append(self.skill_registry.get_all_skill_prompts())

        # 5. extensions/ — 用户扩展
        sections.append(self.library.get_content_by_category("extensions"))

        # 6. 用户上下文
        sections.append(
            f"当前用户：{user_info.get('nickname', '用户')}\n"
            f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        return "\n\n".join(s for s in sections if s.strip())
```

---

## 五、需要从 prompt.py 拆分的内容

| 原内容 | 目的地 |
|--------|--------|
| "你是一个名为EXA的人工智能系统..." | `core/identity.md` |
| "你的输出要符合人类日常对话的习惯..." | `core/format.md` |
| "## 任务处理能力" | `capabilities/task_handling.md` |
| "### 动作执行任务" | `capabilities/code_execution.md` |
| "### 提醒任务示例" | `capabilities/reminder.md` |
| "### 推理任务示例" | `capabilities/reasoner.md` |
| "## 复杂度评估规则" | 合并到 `capabilities/reasoner.md` |

---

## 六、Prompt 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/prompts/list` | 列出所有提示词及其状态 |
| POST | `/api/prompts/<id>/toggle` | 启用/禁用指定提示词 |
| POST | `/api/prompts/reload` | 热重载全部提示词 |
| POST | `/api/prompts/upload` | 上传新提示词 MD 文件 |

---

## 七、性格管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/personality/list` | 列出所有性格预设 |
| POST | `/api/personality/switch` | 切换到指定性格 |
| GET | `/api/personality/current` | 获取当前性格完整状态 |

---

## 八、实现步骤

1. **拆分现有 prompt**
   - 将 `DEFAULT_SYSTEM_PROMPT` 内容按类别写入各 MD 文件
   - 添加 YAML frontmatter

2. **实现 PromptLibrary**
   - MD 文件解析（frontmatter + content）
   - 按 category 分类索引
   - 启用/禁用 toggle

3. **实现 PersonalitySystem**
   - PersonalityProfile 数据模型
   - YAML 预设加载
   - 自然语言描述生成
   - 情绪衰减 + 亲密度增长

4. **实现 PromptEngine**
   - 按固定顺序拼接各部分
   - 支持 SkillRegistry 注入（技能系统完成后）

5. **修改 app.py**
   - 将 `from prompt import get_system_prompt` 替换为 `prompt_engine.build_system_prompt()`

---

## 九、与其它子系统的交互

| 交互 | 方向 | 说明 |
|------|------|------|
| PromptEngine → SkillRegistry | 查询 | 获取已加载技能的提示词，注入 system prompt |
| ChatPipeline → PromptEngine | 调用 | 每次对话前构建 system prompt |
| PersonalitySystem → app | 内部 | 每次交互后调用 `on_interaction()` 更新状态 |
