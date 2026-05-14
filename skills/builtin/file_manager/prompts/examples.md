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
