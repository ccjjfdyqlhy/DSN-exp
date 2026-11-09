# apps/dsn_study/web_admin
# 管理面板（迁移计划阶段 8）—— 自 apps/dsn/web_admin 迁移并适配新基座。
#
# 与 dsn 版的差异：
#   - 认证：静态 WEB_ADMIN_PASSWORD → **infra/auth**（APIKeyManager + 可选 TOTP）；
#   - 挂载：独立 4500 端口第二进程 → **主应用 /api/admin 蓝图**（infra/subapps）；
#   - 数据源：apps.dsn 全家桶单例 → dsn_study engine + infra
#     （ResourcePool / ModelOrchestrator / PersonalitySystemV3 / TopicManager）；
#   - 删除：/vision/*（MJPEG 流服务未建）、/hibernate/*（不做）、/pairing/*、
#     /agents/*、/detail/*、/timer/*、/checkin/video、/exports|/imports
#     （dsn 加密库专属）；
#   - 重接：/persona/* → harness PEV3；/memory/topics/* → 阶段 7 的 TopicManager；
#     /memory/list → study 的 chat_rounds 表。
