# 技能系统实现指导

> 来源: architecture.md §六 / §八.4
> 目标: 实现可加载/卸载的能力包（MD 提示词 + Python 工具代码）

---

## 一、核心概念

**技能 = 一组 MD 提示词 + 可选的 Python 工具代码，打包成一个可加载/卸载的能力单元。**

### 技能 vs 插件

| 维度 | 插件 (Plugin) | 技能 (Skill) |
|------|--------------|-------------|
| 本质 | 运行时代码钩子 | 提示词 + 工具的能力包 |
| 影响范围 | 拦截/修改管道流程 | 扩展 AI 的知识和能力 |
| 触发方式 | 自动 (钩子) | AI 主动选择使用 |
| 用户感知 | 透明 | AI 会说"我用XX技能帮你..." |
| 典型用途 | ASR过滤、TTS合成 | 网页搜索、代码审查、翻译 |
| 可蒸馏 | 否 | **是** |

---

## 二、目标目录结构

```
skills/
├── __init__.py
├── loader.py           # SkillLoader — 从目录加载技能定义
├── registry.py         # SkillRegistry — 技能注册与工具管理
├── manager.py          # SkillManager — 技能生命周期管理
├── distill.py          # DistillationEngine (见 guide-distillation.md)
│
├── builtin/            # 内置技能
│   ├── file_manager/
│   │   ├── skill.yaml
│   │   ├── prompts/
│   │   │   ├── instruction.md
│   │   │   └── examples.md
│   │   └── tools/
│   │       └── file_ops.py
│   └── web_search/
│       ├── skill.yaml
│       ├── prompts/
│       │   ├── instruction.md
│       │   └── examples.md
│       └── tools/
│           └── search.py
│
├── distilled/          # 蒸馏生成的技能
│   └── _drafts/        # 待审核草案
│
└── custom/             # 用户自建技能
    └── README.md
```

---

## 三、技能元数据 (skill.yaml)

```yaml
# skills/builtin/web_search/skill.yaml
name: web_search
display_name: "网页搜索"
description: "搜索互联网获取最新信息"
version: "1.0"
author: "system"              # system / distilled / user
source: "builtin"             # builtin / distilled / custom
enabled: true
status: "active"              # active / draft / archived

# 提示词注入配置
prompt_category: "skills"     # 注入位置 (固定 "skills")
prompt_priority: 60           # 在 system prompt 中的排序

# 工具注册 (可选)
tools:
  - name: search
    display_name: "搜索"
    description: "搜索互联网获取信息"
    module: "tools.search"    # 对应 tools/search.py
    class: "WebSearchTool"
    methods:
      - name: search
        description: "执行网页搜索"
        parameters:
          query:
            type: string
            description: "搜索关键词"
            required: true
          max_results:
            type: integer
            description: "最大结果数"
            default: 5

# 激活条件 (可选)
activation:
  keywords: ["搜索", "查找", "最新", "新闻", "搜一下"]
  auto_activate: false

dependencies: []
tags: [search, web, information]
```

---

## 四、提示词文件格式

```markdown
<!-- skills/builtin/web_search/prompts/instruction.md -->
---
name: web_search_instruction
category: skills
priority: 60
---

## 网页搜索技能

你具备网页搜索能力。当用户需要查找最新信息、新闻、资料时，你可以使用搜索工具。

### 使用方式

通过 <tool> 标签调用搜索工具：

<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {
    "query": "搜索内容",
    "max_results": 5
  }
}
</tool>

### 使用原则

1. 当用户明确要求搜索时，直接使用
2. 当你需要最新信息来回答问题时，主动使用
3. 搜索后整合结果，用自己的话总结给用户
4. 如果搜索结果不够好，可以换关键词再搜一次
```

---

## 五、工具代码格式

```python
# skills/builtin/web_search/tools/search.py
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger("skill.web_search")

class WebSearchTool:
    """搜索工具 — 技能工具的参考实现"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """执行网页搜索"""
        try:
            # ... 实现搜索逻辑 ...
            return {"success": True, "query": query, "results": [...], "count": N}
        except Exception as e:
            logger.error("搜索失败: %s", e)
            return {"success": False, "error": str(e)}
```

**工具方法签名约定：**
- 所有方法使用 `**params` 接收参数
- 返回值必须是 dict，包含 `success: bool` 字段
- 错误信息放在 `error` 字段

---

## 六、核心类实现

### 6.1 SkillLoader (`skills/loader.py`)

```
职责: 从目录加载技能定义
输入: 技能目录路径 (如 skills/builtin/web_search/)
输出: Skill 数据类实例

流程:
1. 读取 skill.yaml → 解析元数据
2. 遍历 prompts/*.md → 解析 frontmatter + content
3. 解析 tools 定义 → 生成 ToolSpec 列表
4. 构造 Skill 对象返回
```

**关键数据类：**

```python
@dataclass
class Skill:
    name: str
    display_name: str
    description: str
    version: str
    author: str          # system / distilled / user
    source: str          # builtin / distilled / custom
    enabled: bool
    status: str          # active / draft / archived
    prompt_category: str
    prompt_priority: int
    tools: list          # [ToolSpec, ...]
    prompts: list        # [PromptFile, ...]
    activation: dict
    dependencies: list
    tags: list
    skill_dir: str       # 技能目录绝对路径

@dataclass
class ToolSpec:
    name: str
    display_name: str
    description: str
    module: str          # "tools.search"
    class_name: str      # "WebSearchTool"
    methods: list

@dataclass
class PromptFile:
    name: str
    category: str
    priority: int
    content: str
    source_file: str
```

---

### 6.2 SkillRegistry (`skills/registry.py`)

```
职责:
- 管理已注册技能的工具实例
- 提供工具调用接口 (供 task_plugin 调用)
- 聚合所有已启用技能的提示词内容 (供 PromptEngine 使用)
```

**核心 API：**

| 方法 | 说明 |
|------|------|
| `register_skill(skill)` | 注册技能：动态加载工具 + 聚合提示词 |
| `unregister_skill(name)` | 注销技能：移除工具实例和提示词 |
| `call_tool(skill_name, tool_name, params)` | 调用技能工具 |
| `get_tool_spec(skill_name, tool_name)` | 获取工具规格 |
| `get_all_tool_specs()` | 获取全部工具规格（用于注入 prompt 告知 AI） |
| `get_all_skill_prompts()` | 获取全部已启用技能的聚合提示词 |
| `has_skill(name)` | 检查技能是否已注册 |
| `list_active_tools()` | 列出所有已注册的工具 |

**动态加载工具的实现：**

```python
def _load_tool(self, tool_spec, skill_dir) -> Any:
    module_path = tool_spec.get("module", "")  # 如 "tools.search"
    class_name = tool_spec.get("class", "")    # 如 "WebSearchTool"

    # 解析路径: "tools.search" → skill_dir/tools/search.py
    parts = module_path.split(".")
    file_path = Path(skill_dir) / "/".join(parts[:-1]) / (parts[-1] + ".py")

    # importlib 动态加载
    spec = importlib.util.spec_from_file_location(...)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cls = getattr(mod, class_name)
    return cls()
```

---

### 6.3 SkillManager (`skills/manager.py`)

```
职责:
- 扫描并加载技能
- 启用/禁用/卸载技能
- 安装新技能
- 与 SkillRegistry 交互
```

**核心 API：**

| 方法 | 说明 |
|------|------|
| `scan_and_load()` | 扫描 builtin/ + custom/ 目录，加载所有技能 |
| `enable(name)` | 启用技能 → 注册到 SkillRegistry |
| `disable(name)` | 禁用技能 → 从 SkillRegistry 注销（但不卸载） |
| `unload(name)` | 完全卸载技能 |
| `install(skill_dir)` | 安装新技能（从目录） |
| `list_skills(status)` | 列出技能及其状态 |
| `get_skill(name)` | 获取单个技能 |

---

## 七、技能管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 列出所有技能 |
| GET | `/api/skills/<name>` | 技能详情 |
| POST | `/api/skills/<name>/enable` | 启用技能 |
| POST | `/api/skills/<name>/disable` | 禁用技能 |
| DELETE | `/api/skills/<name>` | 卸载技能 |
| POST | `/api/skills/install` | 安装新技能 (上传 ZIP 或指定路径) |

---

## 八、task_plugin 中的技能工具调用

`task_plugin` 在 POST_PROCESS 阶段需要处理 `<tool>` 标签：

```python
# 解析 AI 回复中的 <tool> 标签
tool_pattern = r'<tool>\s*(.*?)\s*</tool>'
for match in re.finditer(tool_pattern, reply, re.DOTALL):
    tool_data = json.loads(match.group(1))
    result = skill_registry.call_tool(
        tool_data["skill"],
        tool_data["tool"],
        tool_data["params"]
    )
    # 将结果追加到回复或通过 notification 机制返回
```

---

## 九、实现步骤

1. **实现 SkillLoader**
   - YAML 解析 + MD frontmatter 解析
   - Skill / ToolSpec / PromptFile 数据类

2. **实现 SkillRegistry**
   - 工具动态加载 (`importlib`)
   - 工具调用接口
   - 提示词聚合

3. **实现 SkillManager**
   - 目录扫描
   - 生命周期管理 (enable/disable/unload/install)

4. **创建内置技能示例**
   - `web_search`（含工具代码）- 参考 example
   - `file_manager`（含工具代码）

5. **集成**
   - PromptEngine 调用 `SkillRegistry.get_all_skill_prompts()`
   - task_plugin 调用 `SkillRegistry.call_tool()`
