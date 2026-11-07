# apps/dsn/CLI/__init__.py
# DSN-exp CLI 客户端 — 边缘设备（含树莓派）用的多模态 I/O 终端客户端。
#
# 由原 psychoscope/minimal.py 单文件拆分而来，配套自动更新体系：
#   - launcher.py：自更新启动器（可独立运行，仅依赖 stdlib + requests）
#   - 后端 apps/dsn/api/update.py 按相对路径分发本包全部文件
#
# 运行方式：
#   python -m apps.dsn.CLI                       # 仓库内直接运行
#   python apps/dsn/CLI/launcher.py --host X     # 边缘设备：先同步再启动
#
# 模块依赖单向：env/config → camera/audio → client → pollers/vision/sensing/checkin → app

__version__ = "2.0.0"
