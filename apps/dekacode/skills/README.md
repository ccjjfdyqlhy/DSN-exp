# Skills

把任意 `.py` 文件放在此目录（或 `DEKACODE_SKILLS_DIR` 指向的目录），
启动时会自动加载。

约定：

- 模块定义 `TOOLS = [func1, func2, ...]`：每个函数自动注册为 `skill.<函数名>`。
- 模块定义 `def register(registry, deps)`：手动注册。
- 模块定义 `SKILL = {"name": ..., "description": ..., "handler": ..., "parameters": ...}`：注册单个工具。

可在 WebUI 的 **Options → Skills** 中查看加载结果并点击 `Reload Skills` 热重载。
