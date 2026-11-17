# 拆分迁移说明：monorepo → 一库四应用

> 2026-11-18 生效。本文回答两个问题：**旧路径去哪了**，以及**我该怎么改我的代码**。

---

## 1. 为什么要拆

原仓 `DSN-exp` 同时装着「底层库」和「四个产品」，结果是：

- 库和应用互相污染——`harness/personality` 里写死了 `apps/dsn/character_cards` 这种路径；
- 一次提交动辄几万行，review 成本高到没人 review；
- 库发布到 PyPI 时无法说清「这个包到底装了什么」；
- 四个应用各自为战，共享的改动要在 monorepo 里四处复制。

拆完之后：**一个库 + 四个应用**，依赖方向单一（应用 → 库），每个仓都能独立发版。

---

## 2. 新的仓库矩阵

| 仓库 | 内容 | 安装方式 | 内部依赖 |
|---|---|---|---|
| [`aicf-core`](https://github.com/ccjjfdyqlhy/aicf-core) | 底层库：`harness/` + `infra/` | `pip install aicf-core` | — |
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | Web 控制台 | `pip install -e .` | aicf-core |
| [`aicf-dsn`](https://github.com/ccjjfdyqlhy/aicf-dsn) | 语音伴侣 | `pip install -e .` | aicf-core |
| [`aicf-study`](https://github.com/ccjjfdyqlhy/aicf-study) | 学习助手 | `pip install -e .` | aicf-core |
| [`aicf-code`](https://github.com/ccjjfdyqlhy/aicf-code) | 终端编码助手 | `pip install -e .` | aicf-core |
| [`DSN-legacy`](https://github.com/ccjjfdyqlhy/DSN-legacy) | 旧 monorepo 归档快照 | 只读 | — |

`aicf-core` 的 1.0.0 **尚未发布到 PyPI**（线上仍是 0.6.1）。在它发布前：

```bash
pip install "aicf-core @ git+https://github.com/ccjjfdyqlhy/aicf-core.git"
```

---

## 3. 旧路径 → 新路径

### 3.1 Python 模块路径

| 旧 | 新 | 在哪个仓 |
|---|---|---|
| `apps.dsn_ui.*` | `aicf_ui.*` | aicf-ui |
| `apps.dsn.*` | `aicf_dsn.*` | aicf-dsn |
| `apps.dsn_study.*` | `aicf_study.*` | aicf-study |
| `apps.dsn_study_cli.*` | `aicf_study_cli.*` | aicf-study |
| `apps.coding_agent.*` | `aicf_code.*` | aicf-code |
| `harness.*` / `infra.*` | **不变** | aicf-core |

### 3.2 被丢弃的应用

`apps/densechat`、`apps/emotion_exp`、`apps/harness_lab`、`apps/text_agent`、`apps/dsn_existence`
是实验与占位物，**不迁移**。历史保留在 `DSN-legacy` 快照里。

### 3.3 根目录胶水

`main.py` / `launcher.py` / `installer.py` / `onboarding.py` / `apps.yaml` 属于「应用套件启动器」，
随 **aicf-ui** 迁移。启动器现在按入口模块探测：装了就显示，没装显示 `[未安装]` 而不是崩。

---

## 4. 配置与路径变化

拆仓后没有「仓库根」了，所有可写数据都落到用户目录：

| 旧 | 新 | 说明 |
|---|---|---|
| `<仓库根>/apps/dsn_ui/data/` | `~/.aicf/ui/data/`（或 `DSN_UI_DATA_DIR`） | 控制台数据 |
| `<仓库根>/apps/dsn/model_profiles/` | `~/.aicf/model_profiles/`（或 `DSN_UI_MODEL_PROFILES_DIR`） | 本地模型 profile |
| `<仓库根>/.env` | `AICF_ENV_FILE` → `./.env` → `~/.aicf/ui/.env` | 逐级查找 |
| `<仓库根>/apps/dsn/character_cards/` | `AICF_CHARACTER_CARDS_DIR` | core 的 personality 模块支持环境变量 |
| `<仓库根>/apps/dsn/skills/` | `AICF_DSN_SKILLS_DIR` | 只读枚举技能包 |

> core 侧的 `harness/personality` 以前硬编码 `apps/dsn/character_cards`，
> 拆仓后必然失效，已改为「环境变量 → 本包同级 → 仓库根」三级查找。

---

## 5. 跨应用引用怎么处理

唯一存在跨应用引用的是 **aicf-ui → aicf-dsn**（TTS profile、ASR 资源池、DSN 全局设置）。

处理方式：**软依赖**。

- 装了 `aicf-dsn` → 语音 / TTS / 全局设置面板功能完整；
- 没装 → 相关接口返回 `{"available": false, "reason": "未安装 aicf-dsn"}`，页面照常工作。

实现见 `aicf_ui/dsn_bridge.py`（aicf-ui 仓）。四个应用之间**不允许硬依赖**。

---

## 6. 我该怎么改我的代码

### 6.1 我只是用这个项目

```bash
# 以前
git clone https://github.com/ccjjfdyqlhy/DSN-exp.git && cd DSN-exp
python3 installer.py

# 现在（要 Web 控制台）
git clone https://github.com/ccjjfdyqlhy/aicf-ui.git && cd aicf-ui
pip install -e .
python -m aicf_ui.server --port 8888
```

### 6.2 我在用 SDK

```python
# 以前
from harness import Agent
# 现在：不变，只是换安装源
pip install "aicf-core @ git+https://github.com/ccjjfdyqlhy/aicf-core.git"
```

`harness` / `infra` 的公开 API 在 1.0.0 冻结。破坏性变更（如果有）会走 minor 版本。

### 6.3 我在改应用代码

1. 先到对应的新仓（`aicf-ui` / `aicf-dsn` / `aicf-study` / `aicf-code`）；
2. import 路径按 §3.1 改；
3. 路径假设按 §4 改（包内相对路径或环境变量）；
4. 依赖声明改成 `aicf-core>=1.0,<2`。

---

## 7. 旧仓的状态

- `DSN-exp` 已改名为 **`aicf-core`**（GitHub 会重定向旧链接，8 个 star 与 issue 都保留）。
- `DSN-legacy` 是**只读归档快照**，包含旧 `main`（扁平单体结构）与 `harness-refactor`
  （拆分前的三层结构）两个分支，供查历史与回退用，不再接受 issue 与 PR。
- 旧 `main` 分支与 `harness-refactor` 分支已收口：主干线性推进，功能走 PR。
