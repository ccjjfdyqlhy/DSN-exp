---
name: file_manager_examples
category: skills
priority: 63
---

### 文件管理示例

**用户**: 帮我看看当前目录有什么文件

<tool>
{
  "skill": "file_manager",
  "tool": "list_dir",
  "params": {"path": "."}
}
</tool>

**用户**: 读取 config.py 的内容

<tool>
{
  "skill": "file_manager",
  "tool": "read_file",
  "params": {"path": "config.py"}
}
</tool>

**用户**: 现在在哪个目录

<tool>
{
  "skill": "file_manager",
  "tool": "explore_fs",
  "params": {"tool": "pwd"}
}
</tool>

> 所有操作返回的 `cwd` 字段即当前进程工作目录绝对路径。`pwd` 无需操作文件即可查询。每步操作后根据 cwd 感知当前位置。
