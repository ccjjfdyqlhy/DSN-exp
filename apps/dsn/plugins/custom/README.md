# plugins/custom — 用户自定义插件目录
# 将你的 .py 插件文件放在这里，启动时会被自动扫描并加载。
#
# 插件编写步骤:
# 1. 继承 plugins.Plugin 或 plugins.AsyncPlugin
# 2. 设置 name / hooks / priority
# 3. 实现 on_hook(hook, ctx) 方法
# 4. 在 app.py 初始化代码中实例化并 pm.register()
