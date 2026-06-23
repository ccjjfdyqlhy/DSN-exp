---
name: file_manager_instruction
category: skills
priority: 62
---

## 文件管理技能

你具备文件系统操作能力，包含两套工具：

### 1. 探索文件系统（`explore_fs`）

浏览系统上的文件和目录，默认在用户主目录 `~`。**只读**，不可写入。

**列出目录（默认 ~）：**
<tool>
{
  "skill": "file_manager",
  "tool": "explore_fs",
  "params": {"tool": "list_dir"}
}
</tool>

**读取文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "explore_fs",
  "params": {"tool": "read_file", "path": "~/documents/note.txt"}
}
</tool>

### 2. 管理工作区文件（`workspace_file`）

管理 AI 工作区中的文件和目录，默认在 `.dsn/workspace/`。**可读写**，路径限制在工作区内。

**列出工作区目录：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "list_dir"}
}
</tool>

**读取工作区文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "read_file", "path": "example.txt"}
}
</tool>

**写入工作区文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "write_file", "path": "output.txt", "content": "文件内容"}
}
</tool>

### 使用原则

1. `explore_fs` 浏览系统文件，默认 `~`，只读
2. `workspace_file` 管理工作区文件，读写，路径限制在工作区内
3. 1MB 以上的文件无法读取
4. 写入时自动创建父目录
5. 在回复中展示操作结果
