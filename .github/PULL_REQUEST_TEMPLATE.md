# Pull Request

> 改代码前先读 [docs/maintenance.md](docs/maintenance.md) 的不变量清单。

## 这个 PR 做了什么

<!-- 一段话说清楚：改了什么行为，为什么。评审的人只有这一段可依赖。 -->

## 对齐检查（按实际情况勾选，不适用就删掉对应行）

- [ ] 行为有测试钉住（新增行为有新测试；修 bug 的测试在修复前会红）
- [ ] `pytest -q tests/` 本地全绿（入库口径不含 `tests/fault/` 与本机专用用例）
- [ ] 依赖方向没破坏：`aicf/infra` 不 import `aicf.harness`（CI 的 contract job 会查）
- [ ] 事件词表 / ToolSpec 字段**只增不改**（公开 API 自 rc0 起冻结）
- [ ] 安全声明如实：沙箱 / 审批 / 审计口径与 docs/security.md 一致，没有「以为在沙箱里」
- [ ] 文档同步：行为改了，对应 docs/*.md / README 跟着改了
- [ ] 评测集改动符合两条编辑规矩（只断言存在的工具；同一用例不矛盾）
      —— `tests/test_eval_dataset_bindings.py` 会查

## 给评审者的路标

<!-- 从哪看起？核心 diff 在哪个文件？ -->
