# 技能系统 —— 可插拔技能的写法与规矩

> 读者：要写一个新技能、或排查"技能不生效 / 工具调用报错"的人。
>
> 技能 = 一组具名工具的可装卸单元。声明式技能（YAML）由
> `harness/skills/` 承载，`apps/dsn` 与 `apps/dsn_study` 共用同一份实现。

---

## 一、目录布局

```
apps/<应用>/skills/
├── builtin/          # 内置技能（随仓库走）
├── custom/           # 插件目录：放这里的就是"可插拔"的
└── <其它>/            # 某些应用还有 system/ batch/ 等专有目录

每个技能包 =
├── skill.yaml        # 必需：元信息 + 工具声明
├── prompts/*.md      # 可选：注入 system prompt
├── tools/*.py        # 可选：工具实现
└── skill.env         # 可选：技能私有配置（KEY=VALUE）
```

扫描规则（`harness/skills/yaml_manager.py`）：

* 目录根部有 `skill.yaml` → 该目录本身就是一个技能；
* 否则遍历其子目录，每个含 `skill.yaml` 的子目录是一个技能；
* 子目录名以 `_` 开头会被跳过。

---

## 二、最小技能

`skills/custom/hello/skill.yaml`：

```yaml
name: hello
display_name: "打个招呼"
description: "示例技能"
version: "1.0.0"
author: "user"
source: "custom"
enabled: true
status: "active"
prompt_priority: 70

tools:
  - name: greet
    display_name: "问候"
    description: "向某人问好"
    module: "tools.hello"          # → <技能目录>/tools/hello.py
    class: "HelloTool"
    methods:
      - name: greet
        description: "问好"
        parameters:
          who:
            type: string
            description: "对象"
            required: true

activation:
  keywords: ["打招呼"]
  auto_activate: false

dependencies: []      # 语义能力名，见第四节
tags: [demo]
```

`skills/custom/hello/tools/hello.py`：

```python
class HelloTool:
    def greet(self, who: str) -> dict:
        return {"success": True, "message": f"你好，{who}"}
```

三条硬规矩：

1. **工具名 = 方法名**。注册表按 `skill.tool` 找实例上的同名方法；
   方法名对不上 → 加载期就会被拦下（见第五节）。
2. **参数名 = 签名里的参数名**。schema 里的参数名必须能被实现接受。
3. **工具方法返回 `dict`**。统一用 `{"success": bool, ...}`，
   异常在工具内部吃掉并转成 `{"success": False, "error": "..."}`。

---

## 三、`module` 的三种写法

`harness/skills/yaml_loader.py: resolve_tool_module_path`：

| 写法 | 解析结果 |
|---|---|
| `tools.hello` | `<技能目录>/tools/hello.py` |
| `tools/hello.py` | `<技能目录>/tools/hello.py` |
| `hello.py` | `<技能目录>/tools/hello.py` |
| `pkg.sub.mod` | `<技能目录>/pkg/sub/mod.py` |

---

## 四、依赖注入：能力（capability）

### 4.1 以前是怎么做的（别再这么写）

应用层维护一张**硬编码的属性名映射表**
（`apps/dsn_study/boot.py: _build_skill_dep_map`）：

```python
"question_bank": dict(_store=..., _tm=..., _models=...)
```

坑：

* 表里没有的技能 → 依赖**静默丢失**，工具里 `self._store` 一直是 `None`，
  直到用户真的调它才报错，错误还指向业务逻辑而不是"依赖没注入"；
* 表里的 key 是**属性名**（`_store`），而 `skill.yaml` 的 `dependencies` 写的是
  **语义名**（`question_store`）—— 两套命名空间对不上，
  `dependencies` 字段实际上是**死字段**，没有任何代码读它；
* 写新技能必须去改应用的 `boot.py` —— 技能没法真正"插拔"。

### 4.2 现在怎么做

应用层注册**语义能力**（`apps/dsn_study/boot.py: _register_skill_capabilities`）：

```python
skill_registry.register_capabilities({
    "question_store": question_store,
    "template_manager": template_manager,
    "models_plugin": llm,
    "workspace": workspace,
    ...
})
```

工具类用类属性 `needs` 声明"语义能力 → 实例属性名"：

```python
class HelloTool:
    needs = {"workspace": "_workspace"}

    def __init__(self):
        self._workspace = None      # 注入前是 None，注入后是实例
```

也可以在 `skill.yaml` 的工具项里写 `needs:`（不改工具源码也能声明）。

注入规则：

* 能力**已注册** → 注入到 `needs` 指定的属性；
* 能力**没注册** → 该工具**不注册**（并记一条 error 级诊断），
  技能里的其它工具照常可用。

> 老技能（不写 `needs`）仍然走旧的属性名映射表，行为不变。

### 4.3 可用能力清单

`GET /api/skills`（dsn_study）返回 `capabilities` 字段。dsn_study 当前注册：

`question_store` `template_manager` `models_plugin` `llm` `db_mgr`
`exam_engine` `exam_scorer` `scorer` `graph_store` `graph_engine`
`knowledge_matcher` `kg_matcher` `kg_builder` `scanner_pipeline`
`plan_engine` `task_manager` `memory_system` `cache_engine`
`studylog` `checkin_store` `workspace`

---

## 五、加载期校验（`harness/skills/validator.py`）

技能包写错时，**加载期**就会报出具体是哪一条不对，而不是等用户调工具时炸。

| 级别 | 含义 | 处理 |
|---|---|---|
| `error` | 工具类加载失败 / 方法不存在 / 参数与签名对不上 / 需要的能力没注册 | **该工具不注册**，技能其余工具照常可用 |
| `warning` | 声明了依赖但没工具用 `needs` 引用 / 工具名重复 / schema 说必填但实现有默认值 | 只记录 |

诊断查询：

```bash
GET /api/skills        # diagnostics.issues 里是全部问题
```

> 校验器上线当天就抓到两个**现存的真 bug**：
> `question_bank.get_error_stats` / `recommend_questions` 的实现里
> `user_id` 没有默认值，而 schema 又不声明它 → Agent 调用必然 TypeError。
> 已修（实现侧给默认值）。

---

## 六、提示词聚合

`skill.yaml` 的 `prompt_category` / `prompt_priority` 现在真的生效：
所有技能的 `prompts/*.md` 按 `prompt_priority` **降序**拼接进 system prompt
（同优先级按名称稳定排序）。此前 priority 被完全忽略。

单个 prompt 文件可带 front-matter：

```markdown
---
name: my_skill_instruction
category: skills
priority: 70
---

正文…
```

---

## 七、技能私有配置 `skill.env`

```
skills/<分类>/<技能>/skill.env
```

```
GAOKZX_DELAY=1.2
GAOKZX_USER_AGENT=Mozilla/5.0 ...
```

* 加载器：`harness/skills/env_loader.py`，应用启动时扫描并写进 `os.environ`；
* **已存在的环境变量优先于文件里的值**（现场配置覆盖仓库默认值）；
* 结果同时挂在 `Skill.env` 上；
* 格式错误（缺 `=`、空键名）会跳过该行并告警，不会整份文件失效。

> dsn_study 此前有 `Config.load_skill_configs()`，但**从来没被调用过** ——
> 写 skill.env 是静默失效的。现统一由 harness 的 env_loader 负责。

---

## 八、运行时管理（不必重启）

dsn_study 暴露了技能管理 API：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/skills` | 技能清单 + 工具索引 + 能力清单 + 诊断 |
| POST | `/api/skills/install` | 从目录安装（body: `{"skill_dir": "..."}`） |
| POST | `/api/skills/reload` | 全量重扫技能目录 |
| POST | `/api/skills/<name>/enable` | 启用 |
| POST | `/api/skills/<name>/disable` | 禁用 |
| POST | `/api/skills/<name>/reload` | 重载单个技能 |
| POST | `/api/skills/<name>/uninstall` | 卸载 |

改完 `skill.yaml` / `tools/*.py` 后，重启或调 `reload` 都行。

---

## 九、代码地图

| 文件 | 职责 |
|---|---|
| `harness/skills/yaml_loader.py` | 解析 `skill.yaml` / `prompts/*.md`，生成 function-calling schema |
| `harness/skills/yaml_manager.py` | 扫描 / 安装 / 卸载 / 重载 / 启停，收集诊断 |
| `harness/skills/registry.py` | 工具实例、调用、提示词聚合、schema 生成、**唯一实现** |
| `harness/skills/capabilities.py` | 能力注册表（依赖注入的唯一来源） |
| `harness/skills/validator.py` | 加载期一致性校验 |
| `harness/skills/env_loader.py` | `skill.env` 加载 |
| `harness/skills/agent_bridge.py` | 技能工具 → AgentLoop 工具（同步 + 协程） |
| `apps/dsn_study/api/skills.py` | 技能管理 REST API |

---

## 十、实例：`gaokzx` —— 从高考在线抓试题/答案图

`apps/dsn_study/skills/builtin/gaokzx/`，四个工具：

| 工具 | 作用 |
|---|---|
| `search_papers(keyword, page, page_size)` | 站内搜索试题文章（返回 id/标题/链接/是否含答案） |
| `inspect_paper(paper_id \| url)` | 解析文章：分页数、试题图/答案图清单（带判别依据）、附件 PDF |
| `find_answer_paper(paper_id \| title)` | 找配套答案文章（比对**学年**，不瞎猜） |
| `download_images(paper_id, kind, user_id, max_images)` | 下载试题图/答案图到工作区（幂等） |

它体现了这套插件机制的几个要点：

* **站点逆向结论写在文件头注释里** —— 参数名（`searchName` / `sourceType: GAOKZX`）、
  分页标记（`<!-- pagebreak -->`）、图片文件名前缀（`无答案` / `有答案`）
  都是实测确认的，不靠猜；
* **能力注入**：`needs = {"workspace": "_workspace"}` 拿工作区落盘，
  拿不到时退到临时目录并在返回里标记，不静默失败；
* **私有配置**：`skill.env` 里放 `GAOKZX_DELAY` / `GAOKZX_TIMEOUT` / `GAOKZX_USER_AGENT`；
* **对第三方站点礼貌**：请求之间 sleep（默认 0.8s）、失败指数退避重试 2 次、
  429 尊重 `Retry-After`。

> 站点接口的关键事实（实测）：
> * 所有 API 请求必须带请求头 `sourceType: GAOKZX` —— 不带会拿到「自主选拔在线」站的数据，文章 id 对不上；
> * 搜索参数名是 `searchName` / `searchType`（`title`、`keyword`、`titleLike` 一律无效）；
> * `columnId` 必须是 **int**（`314` = 试题库，`139` = 高考真题，`145` = 期中期末）。
