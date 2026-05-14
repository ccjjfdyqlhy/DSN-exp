---
name: file_manager_instruction
category: skills
priority: 62
---

## 文件管理技能

你具备文件系统操作能力。当用户需要读写文件、列出目录内容时使用。

### 使用方式

通过 `<tool>` 标签调用文件操作工具：

**读取文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "read_file",
  "params": {"path": "example.txt"}
}
</tool>

**列出目录：**
<tool>
{
  "skill": "file_manager",
  "tool": "list_dir",
  "params": {"path": "."}
}
</tool>

**写入文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "write_file",
  "params": {"path": "output.txt", "content": "文件内容"}
}
</tool>

### 使用原则

1. 所有路径相对于服务器工作目录
2. 读取文件时注意文件大小，不要读取过大文件
3. 写入文件前确认不会覆盖重要文件
4. 在回复中展示操作结果
