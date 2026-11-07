# 自定义技能目录（可插拔）

把一个技能包放进本目录的子目录里，重启应用即可生效（也可调用
`POST /api/skills/install` 在运行时安装，不必重启）。

## 目录结构

```
skills/custom/<技能名>/
├── skill.yaml          # 必需：技能元信息 + 工具声明
├── prompts/*.md        # 可选：注入 system prompt 的说明
├── tools/*.py          # 可选：工具实现
└── skill.env           # 可选：技能私有配置（KEY=VALUE）
```

## 依赖注入（不再需要改 boot.py）

工具类用类属性 `needs` 声明需要哪些**能力**，harness 会自动注入：

```python
class MyTool:
    needs = {"question_store": "_store", "workspace": "_workspace"}

    def __init__(self):
        self._store = None
        self._workspace = None
```

可用能力见 `GET /api/skills` 的 `capabilities` 字段。
能力缺失时该工具**不会被注册**（而不是静默拿到 None）。

## 声明与实现不一致时

工具类名、方法名、参数名必须与 skill.yaml 一致，否则加载期就会报出
具体是哪一条不对（见 `GET /api/skills` 的 `issues`）。
