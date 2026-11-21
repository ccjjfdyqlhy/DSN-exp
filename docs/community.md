# 社区

> 这个页面是社区入口的总索引。渠道当前的状态是**如实记录**，不是宣传。

## 渠道

| 渠道 | 状态 | 适合 |
|---|---|---|
| [GitHub Issues](https://github.com/ccjjfdyqlhy/aicf-core/issues) | ✅ 开放 | 明确的 bug 与功能请求（有模板引导） |
| [GitHub Discussions](https://github.com/ccjjfdyqlhy/aicf-core/discussions) | ✅ 开放 | 使用问题、设计讨论、展示你做的东西 |
| GitHub PR | ✅ 开放 | 直接改代码（模板里有不变量清单） |
| 即时聊天群 | ⬜ 未开 | 等外部使用者出现再开 —— 空群比没有群更劝退 |

> 讨论区用中文或英文都可以，维护者两种都回。
> Questions in either Chinese or English are welcome.

## 问问题之前

1. `aicf --version` 确认版本 ≥ 1.0.0（更早版本没有 `aicf` 命令）；
2. 照 [README 的九十秒](../README.md#ninety-seconds) 走一遍 ——
   大多数「跑不起来」是版本或环境问题，走完这段能自己定位到哪一步断的；
3. 搜索现有 issue 与 Discussions。

## 第一次贡献

- 看 [CONTRIBUTING.md](../CONTRIBUTING.md) 与 PR 模板里的不变量清单；
- 好下手的位置：`docs/` 的翻译与勘误、`examples/`、技能包（[skill-spec](skill-spec.md)）；
- 改核心前先跑 `pytest -q tests/`，确认基线是绿的。

## 行为准则

见 [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)。简单说：对事不对人，
诚实优先 —— 这个仓库的文化是把「不知道 / 没做到」写明白，欢迎同样的风格。
