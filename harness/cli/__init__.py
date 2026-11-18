# harness/cli —— aicf 命令行。
#
# 为什么 CLI 住在 core 而不是 apps/：
# 策划案原写 apps/aicf_cli/，但本仓库已经完成「收敛为纯库」的拆分
# （apps/ 已 gitignore，Web 控制台在独立仓库 aicf-ui）。CLI 是核心库
# 的门面 —— 用户 `pip install aicf-core` 之后就该有 `aicf` 命令，
# 不该再装第二个包才能用核心能力。

__all__ = ['main']


def main(argv=None):
    """CLI 入口（延迟导入，避免 `import harness` 时拉起 argparse）。"""
    from .main import main as _main
    return _main(argv)
