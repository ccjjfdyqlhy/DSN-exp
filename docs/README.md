# 文档索引

> 本目录下的文档**面向维护者**，目标是让接手的人能在半天内建立正确心智模型。

---

## 阅读路线

### 新人第一天

```
README.md                → 30 秒建立三层心智模型
docs/architecture.md     → 模块地图 + 依赖方向 + 单例清单
docs/getting-started.md  → 把它跑起来
docs/apps.md             → 知道每个应用是什么
```

### 准备改代码

```
docs/maintenance.md      → 必须守住的不变式 + 按改动位置的检查表
docs/technical-debt.md   → 哪些地方本来就是坏的，别背锅
docs/testing.md          → 跑测试、看懂 12 个预存失败
```

### 深入某层

```
docs/infra.md            → 模型编排四层结构、资源池、策略
docs/harness.md          → Agent 循环、工具、上下文、管线
docs/configuration.md    → 配置从哪来、为什么不生效
docs/sdk_guide.md        → 把框架当库嵌进别的项目
docs/app-development.md  → 写一个新应用
```

---

## 文档清单

| 文档 | 内容 | 什么时候读 |
|---|---|---|
| [architecture.md](architecture.md) | 三层结构、依赖方向、模块地图、一次请求的完整路径、全局单例清单、质量基线 | 任何时候先读这篇 |
| [harness.md](harness.md) | AgentLoop 控制流与 9 种事件、AgentSpec、工具系统、18 个标准工具、上下文四段剪裁、8 个 HookPoint | 改 Agent 行为时 |
| [infra.md](infra.md) | orchestrator 四层结构、调度器算法、各 provider 客户端、资源池、policy、store | 改模型/资源/存储时 |
| [apps.md](apps.md) | 7 个应用的定位与启动、dsn_ui 路由与对话四分支、dsn_study 技能表、dsn 子包速查 | 找功能在哪时 |
| [app-development.md](app-development.md) | 三种装配路线、最小应用模板、写工具/技能/Web 应用、不要抄的地方 | 要加功能或写新应用时 |
| [getting-started.md](getting-started.md) | 环境、依赖、配置、启动、端口表、常见故障排查 | 第一次跑 / 跑不起来时 |
| [configuration.md](configuration.md) | 三条配置来源、关键变量表、生效路径、凭据存储 | 改配置 / 配置不生效时 |
| [testing.md](testing.md) | 怎么跑测试、当前基线（537 通过 / 12 失败 / 6 收集错误）、跑不了的测试 | 跑测试 / 判断回归时 |
| [maintenance.md](maintenance.md) | 改代码前的落点判断、9 条不变式、按位置的检查表、提交前自检、仓库卫生 | **动代码前必读** |
| [technical-debt.md](technical-debt.md) | P0/P1/P2 技术债、验证过的 bug、修复顺序、文档与仓库卫生 | 规划工作 / 排查怪现象时 |
| [sdk_guide.md](sdk_guide.md) | 把 AICF 当 Python SDK 嵌入第三方项目 | 在别的项目里用框架时 |

---

## 本文档体系的几条约定

### 1. 只写经过核实的事实

本文档重写于对全仓库的静态分析（`fuck-u-code`）与源码精读之上。
凡是不确定的，写作时标注「未验证」，而不是写成确定结论。

已经有两条旧文档的说法被证伪并纠正：

| 旧文档说法 | 实际情况 |
|---|---|
| 「AgentLoop 经 5 个 HookPoint 处理」 | 实际 **8 个** HookPoint，且 **AgentLoop 根本不经过 Pipeline** |
| 「16 个 / 17 个标准工具」 | 实际 **18 个** |
| 「自适应 Token 经济闭环，Agent 自己会省钱」 | 只组装未接线，**闭环不存在** |
| 「SpeculativePrefetch / FETCH 协议是主链路」 | 全仓**零调用点** |
| 「`batch.run` 是占位」 | 已实现 |

### 2. 引用格式统一用 `文件:行号`

代码注释里已有大量「修复说明」式的历史叙事，文档**不复述历史**，只给定位。
想看「为什么这么写」，去读代码注释——那才是本仓库最详尽的知识库。

### 3. 区分「设计」与「现状」

凡涉及「某能力是否真的在用」，文档会明确标注：
**已接入 / 可选 / 已写未接 / 声明但不生效**。
这是避免下一任维护者被名字骗到的关键。

### 4. 文档随仓库分发

本目录**已随仓库入库**（2026-10-20 起从 `.gitignore` 移除 `/docs/` 一行）。
改动文档时请一并提交。`archive/` 子目录存放的是已被取代的旧版文档，
其自带 `README.md` 明确标注「架构已过时，不要作为现状依据」。
详见 [technical-debt.md](technical-debt.md#文档与仓库卫生)。

---

## 历史文档的处理

重写前的 5 份旧文档已处理如下：

| 旧文件 | 处理 | 原因 |
|---|---|---|
| `aicf-overview.md` | 合并进 `architecture.md` + `infra.md` | 大量内容仍准确（资源池、分层），但结构冗长、与代码有出入 |
| `harness-architecture-current.md` | 内容纠正后并入 `harness.md` | 架构图里「AgentLoop → Pipeline」的数据流是错的；工具数、HookPoint 数过时 |
| `architecture-harness-v2.md` | 并入 `technical-debt.md` | 主体是「设计愿景」，与现状差距大；有价值的对比已保留 |
| `plan-harness-engine-migration.md` | 归档为 `archive/plan-harness-engine-migration.md` | 一次性迁移记录，已完成，仅作历史参考 |
| `sdk_guide.md` | 保留并更新 | 面向外部使用者，内容基本正确 |
