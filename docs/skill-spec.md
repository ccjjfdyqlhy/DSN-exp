# 技能包格式规格（skill-spec v1）

> 这是 `skill.yaml` 技能包的**公开规格** —— 技能生态的接口。
> 任何人按这份规格写的技能包，都能被 `aicf` 的技能管理器发现、校验、装载。
> 实现参考：[skills.md](skills.md)（工程视角）；实现代码 `aicf/harness/skills/`。

---

## 一、技能包是什么

一个技能包 = 一个目录，**声明**（skill.yaml）+ **提示词**（prompts/*.md）+
**工具**（tools/*.py）+ **环境变量**（skill.env）：

```text
my-skill/
  skill.yaml        # 必需 —— 技能的唯一声明入口
  prompts/*.md      # 可选 —— 聚合进系统提示词
  tools/*.py        # 可选 —— 工具实现
  skill.env         # 可选 —— KEY=VALUE 环境变量
```

发现规则（`yaml_manager.py`）：

- 目录里有 `skill.yaml` → 本身是一个技能包；
- 否则，每个**含 `skill.yaml` 的子目录**是一个技能包；
- `_` 开头的目录跳过。

## 二、skill.yaml 字段规格

### 2.1 顶层字段

| 字段 | 类型 | 必需 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | str | **是** | — | 技能名（唯一标识）。缺失 → 拒绝装载 |
| `display_name` | str | 否 | `""` | 给人看的名字 |
| `description` | str | 否 | `""` | 给人看的用途摘要 |
| `version` | str | 否 | `"1.0"` | 语义化版本，参与版本治理 |
| `author` | str | 否 | `"system"` | 作者 |
| `source` | str | 否 | `"builtin"` | 来源标记（builtin / custom / external） |
| `enabled` | bool | 否 | `true` | 是否启用 |
| `status` | str | 否 | `"active"` | 状态标记（active / disabled / deprecated） |
| `prompt_category` | str | 否 | `"skills"` | 提示词聚合的分类 |
| `prompt_priority` | int | 否 | `60` | 提示词排序优先级（大者优先） |
| `tools` | list | 否 | `[]` | 工具声明列表（见 2.2） |
| `activation` | map | 否 | `{}` | 激活词与自动激活（`keywords: [...]`, `auto_activate: bool`） |
| `dependencies` | list | 否 | `[]` | 其它技能名（装载顺序由管理器处理） |
| `tags` | list | 否 | `[]` | 自由标签 |
| `env` | map | 否 | `{}` | 技能级环境变量（合并进 skill.env 的语义） |

未知顶层字段**不报错**（前向兼容 —— 老管理器读新技能包只忽略新增字段）。
与之相对，**tools 里的字段拼错会报错**（见 2.2 与《失败方向》）。

### 2.2 tools 字段

每条工具声明：

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `name` | str | **是** | 工具名（== 实现类上的方法名，硬规则见下） |
| `display_name` | str | 否 | 给人看的名字 |
| `description` | str | 否 | 给模型看的用途说明 |
| `module` | str | **是** | 实现模块路径（解析规则见 2.3） |
| `class` | str | **是** | 实现类名（实例化一次，方法即工具） |
| `methods` | list | **是** | 方法声明：`{name, description, parameters}`；`parameters` 是 JSON-Schema 风格的 `{参数名: {type, description, required}}` |
| `needs` | map | 否 | 能力依赖：`{属性名: 能力名}`（见 2.4） |
| `async_mode` | bool | 否 | 异步标记（实现可动态写入） |
| `estimated_duration` | str | 否 | 预估时长（实现可动态写入） |

**三条硬规则**（违反即工具装载失败）：

1. 工具名 == 实例方法名：`name: ping` 必须真的有 `def ping(self, ...)`；
2. 参数名 == 方法签名参数名：`parameters` 里声明的每个参数都要在签名里；
3. 工具返回 `{"success": bool, ...}`：异常也被吞成 `{"success": False, "error": ...}`，**不向调用方抛**。

### 2.3 module 路径解析

按顺序尝试（命中即停）：

| 写法 | 解析为 |
|---|---|
| `tools/x` 或 `tools/x.py` | 技能目录内 `tools/x.py` |
| `x.py` 或 `x` | 技能目录内 `x.py` |
| `pkg.sub.mod` | 真实 Python 模块（可从已安装包导入） |

### 2.4 能力依赖注入（`needs`）

工具类通过 `needs` 声明它需要的**能力**（连接池 / 工作区 / 服务客户端……），
应用在装载技能前把能力注册进 `CapabilityRegistry`：

```yaml
tools:
  - name: search_notes
    module: tools/search.py
    class: SearchTool
    needs: { workspace: "_workspace" }
    methods: [...]
```

```python
class SearchTool:
    needs = {"workspace": "_workspace"}   # 类属性写法与 yaml 等价
```

应用侧：`skill_registry.register_capabilities({"workspace": ws})`。
**能力未注册 → 该工具跳过装载并记入诊断**，技能包其余部分照常装载 ——
缺一个能力不该让整包变黑盒。

## 三、prompts/*.md

- 每个文件是一段提示词；可用 YAML front-matter 覆盖名字 / 分类 / 优先级：

  ```markdown
  ---
  name: tone-guide
  category: skills
  priority: 80
  ---
  （正文）
  ```

- 聚合规则：`get_all_skill_prompts()` 汇总所有启用技能的提示词，
  按 `priority` 降序进入系统提示词。

## 四、skill.env

`KEY=VALUE` 行；载入 `os.environ` 时**已存在的环境变量赢**
（宿主环境 > 技能包声明 —— 技能不许悄悄覆盖运行时配置）。
同时原样挂到 `Skill.env` 供代码读取。

## 五、装载与校验（失败方向）

- 装载时校验分两级：`error`（工具无法注册等）与 `warning`；
  **error 级只跳过出错的那件东西**（工具 / 提示词文件），技能包其余部分照常；
- 但 `skill.yaml` 本身不合法（非 YAML / 缺 `name`）→ 整包拒绝；
- 诊断可查：`SkillManager.diagnostics()` 返回每个包的问题明细；
- 一个技能**永远不该**因为另一个技能的问题而装载失败。

## 六、版本与兼容承诺

- 本规格版本：**v1**（对应 `version: "1.0"` 字段习惯）；
- v1 内字段**只增不改**：新增字段不破坏旧管理器，旧字段语义不变；
- 工具名 / 参数名的硬规则是生态契约 —— 破坏它们需要大版本并给出迁移说明；
- `name@version` 版本引用：上层（Agent artifact）引用工具时用
  `工具名@版本`；版本不符时返回 None 并显式报错，**拒绝静默换版**。

## 七、最小完整示例

```yaml
# my-skill/skill.yaml
name: my-skill
display_name: 我的技能
description: 演示完整格式的最小技能包
version: "1.0"
author: your-name
source: custom
enabled: true
status: active
prompt_priority: 60
tools:
  - name: greet
    display_name: Greet
    description: 打一声招呼
    module: tools/greet.py
    class: GreetTool
    methods:
      - name: hello
        description: 返回一句问候
        parameters:
          who:
            type: string
            description: 对象
            required: true
activation:
  keywords: ["greet"]
  auto_activate: false
dependencies: []
tags: [example]
```

```python
# my-skill/tools/greet.py
class GreetTool:
    def hello(self, who: str) -> dict:
        """返回一句问候。"""
        return {"success": True, "reply": f"你好，{who}"}
```

## 八、发布一个技能包

1. 目录 + `skill.yaml` 按本规格写好；
2. 装进技能目录（应用配置的 skill_dirs，如 `skills/custom/`）；
3. `SkillManager.scan_and_load()` 发现并校验；`diagnostics()` 确认零 error；
4. 验证：模型端工具名是 `skill-<技能名>-<工具名>`（function-calling schema）。

> 规格本身的变更走 PR，改 `docs/skill-spec.md` 时必须同步
> `aicf/harness/skills/yaml_loader.py` 的解析行为与对应测试。
