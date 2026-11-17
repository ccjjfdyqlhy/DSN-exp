# 应用层 —— 现在是四个独立仓库

> 2026-11-18 起，`apps/` 已从 core 拆走。
> 本文回答两个问题：**我该去哪个仓库改代码**，以及**新应用怎么起步**。

---

## 一、仓库矩阵

| 仓库 | 原来在哪 | 定位 | 入口 | 默认端口 |
|---|---|---|---|---|
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | `apps/dsn_ui/` | **日常主入口**，Web 控制台 | `python -m aicf_ui.server` | 8888 |
| [`aicf-dsn`](https://github.com/ccjjfdyqlhy/aicf-dsn) | `apps/dsn/` | 语音陪伴，历史最长 | `python -m aicf_dsn` | 5000 |
| [`aicf-study`](https://github.com/ccjjfdyqlhy/aicf-study) | `apps/dsn_study/` + `dsn_study_cli/` | 学习助手，Web 应用的正规范例 | `python -m aicf_study` | 5000 |
| [`aicf-code`](https://github.com/ccjjfdyqlhy/aicf-code) | `apps/coding_agent/` | **最小可读范例** | `python -m aicf_code` | — |

被丢弃的实验物（历史在 [`DSN-legacy`](https://github.com/ccjjfdyqlhy/DSN-legacy)）：
`densechat`（他人项目复刻）、`emotion_exp`、`harness_lab`、`text_agent`、`dsn_existence`。

四个应用**只依赖 aicf-core**，彼此之间不互相依赖。

---

## 二、为什么拆

| 拆之前 | 拆之后 |
|---|---|
| 一个仓装库 + 四个应用，改一处要 review 几万行 | 库与应用分开，各自 PR、各自发版 |
| 库代码里写死 `apps/dsn/...` 路径 | core 不认识任何应用；应用用环境变量/包内路径 |
| 「这个 pip 包到底装了什么」说不清 | `aicf-core` 只装 `harness` + `infra` |
| 四个应用共享的改动要在四处复制 | 共享部分下沉到 core，应用只留业务语义 |

---

## 三、三种装配风格（仍然有效）

```
① harness 原生      aicf-code
   直接用 AgentLoop / AgentRuntime，零业务依赖。学它的写法最省心。

② 标准 Web 应用    aicf-study
   Runtime + Settings + ModelProviderRegistry + AgentRuntime
   + AppBundle + FlaskGateway。写新 Web 应用照抄这个。

③ 自成体系         aicf-ui / aicf-dsn
   历史原因各有自研的模型层、上下文、路由注册。功能最全，但绕开了框架门面。
```

---

## 四、新应用怎么起步

新应用应该是**独立仓库**，依赖 `aicf-core`：

```bash
mkdir my-app && cd my-app
git init
# pyproject.toml 里：dependencies = ["aicf-core>=1.0,<2"]
pip install -e .
```

推荐的落地顺序：

1. 抄 [`aicf-code`](https://github.com/ccjjfdyqlhy/aicf-code)（最小，186 行级别）——
   看清楚 `AgentRuntime` + 工具注册 + 会话持久化是怎么串起来的；
2. 需要 Web 界面就抄 [`aicf-study`](https://github.com/ccjjfdyqlhy/aicf-study) 的分层；
3. 需要完整控制台体验就抄 [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)。

详细写法见 [app-development.md](app-development.md)（该文已按新结构更新）。

---

## 五、跨应用调用怎么办

**默认不允许**。四个应用之间没有硬依赖。

唯一存在的软依赖是 `aicf-ui → aicf-dsn`（语音 / TTS / 全局设置）：
装了 `aicf-dsn` 功能完整，没装则相关接口明确返回「未安装」，页面照常工作。
实现见 aicf-ui 仓的 `aicf_ui/dsn_bridge.py`。

---

## 六、迁移细节

旧路径怎么对应、新环境变量怎么设，见 [split_migration.md](split_migration.md)。
