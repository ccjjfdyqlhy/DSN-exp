# apps/harness_lab/__init__.py
"""harness_lab —— harness 记忆与人格系统的专用验证台。

**它是什么**：一个独立应用，把 `harness/personality`（PEV3）与
`harness/memory`（契约 + 原语）拉起来跑，用一组**预设的人格演化方向**
驱动它们，然后对每一项「应该发生的行为」做断言，最后产出一份可读的验证报告。

**它不是**：dsn_study 的替身，也不是新设计的实现。它只做一件事 ——
**回答「harness 现有的记忆与人格系统，是否真的按预期工作」。**

设计要点：
  * **完全离线可跑**：默认用 `ScriptedChat` 确定性桩客户端，不需要任何凭据；
    桩会**如实遵守 `max_tokens`**，因此能离线复现线上截断类故障。
  * **场景隔离**：每个场景一个独立工作区（独立 DB / 独立角色卡目录），
    互不污染，可单独重跑。
  * **断言的是"预期"而不是"现状"**：检查项按 harness 自己的文档契约编写；
    当现状与契约不符时，报告会 FAIL 并给出证据 —— 那正是我们要找的东西。

用法：
    python -m apps.harness_lab                 # 跑全部场景
    python -m apps.harness_lab --list          # 列出预设人格演化方向
    python -m apps.harness_lab --scenario praise_streak
    python -m apps.harness_lab --no-truncate   # 对照实验：桩不遵守 max_tokens
    python -m apps.harness_lab --llm live      # 真实模型（需要凭据）
"""

__version__ = "1.0.0"
