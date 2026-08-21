# 示例技能：演示 apps/densechat 的技能加载机制。
# 约定：模块内定义 TOOLS = [函数, ...]，启动/重载时自动注册为 skill.<函数名>。


def echo(text: str) -> str:
    """返回传入文本（示例技能）。"""
    return text


def project_health() -> str:
    """返回一个简单的项目健康提示（示例技能）。"""
    return "Sample skill loaded. DSN DenseChat harness is ready."


TOOLS = [echo, project_health]
