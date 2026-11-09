# apps/dsn_study_cli
# DSN-Study 边缘设备客户端（迁移计划阶段 6）。
#
# 目标：把「摄像头 2」的画面批量变成题库里的题目 ——
#   选文档摄像头（s）→ 连拍（c）→ 结束批次（f）→ 服务端后台 VLM 提取入库 → 汇总播报。
# 附带语音输入（Space 长按 → ASR → 对话）与文字/图片输入（t）。
#
# 模块依赖单向：env/config → camera/audio → client → pollers → app。
# 入口：`python -m apps.dsn_study_cli` 或 launcher.py（先自更新再 exec）。

__version__ = "1.0.0"
