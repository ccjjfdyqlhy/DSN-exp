---
name: file_manager_instruction
category: skills
priority: 62
---

## 文件管理技能

你具备文件系统操作能力，包含两套工具：

### 1. 探索文件系统（`explore_fs`）

浏览系统上的文件和目录，默认在用户主目录 `~`。**只读**，不可写入。

**查询当前工作目录：**
<tool>
{
  "skill": "file_manager",
  "tool": "explore_fs",
  "params": {"tool": "pwd"}
}
</tool>

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

**工作区目录结构：**
```
.dsn/workspace/
  <用户名>/               # 每个用户一个子目录
    uploads/              # 扫描仪生成的原始图片（scan_1.png, scan_2.png ...）
    documents/            # 处理后的文档（.hmd 文件，每次扫描只产生 1 个）
    notebook/             # AI 观察笔记
    repos/                # Git 仓库
    projects/             # 用户项目
```

**重要规则：**
- 扫描文档经过处理后只生成 **1 个** `.hmd` 文件，不会被拆分成多个编号文件
- 若 `list_dir` 返回空或错误，**不要虚构文件名**，如实报告未找到即可
- 查找文档时应先 `list_dir` 列出当前目录，再按需进入子目录

**查询当前工作目录：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "pwd"}
}
</tool>

**列出工作区目录（先列根目录，再进用户子目录）：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "list_dir"}
}
</tool>

**列出用户目录下的文档：**
```json
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "list_dir", "path": "<用户名>/documents"}
}
</tool>
```

**读取工作区文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "read_file", "path": "<用户名>/documents/scan_1.hmd"}
}
</tool>

**写入工作区文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "write_file", "path": "<用户名>/documents/output.txt", "content": "文件内容"}
}
</tool>

### 使用原则

1. `explore_fs` 浏览系统文件，默认 `~`，只读
2. `workspace_file` 管理工作区文件，读写，路径限制在工作区内
3. 1MB 以上的文件无法读取
4. 写入时自动创建父目录
5. **所有操作（包括错误）自动返回 `cwd` 字段**，值为当前进程工作目录的绝对路径（如 `/home/darkstar/DSN-exp`）。每次操作后根据 cwd 判断当前位置
6. 使用 `pwd` 子命令可单独查询当前位置，无需操作文件
7. 在回复中展示操作结果
8. **禁止虚构**：工具返回的 `items` 数组即真实文件列表。若为空或与预期不符，如实告知用户，不要捏造文件名或数量
9. **扫描文档定位**：扫描处理后的 `.hmd` 文件存储在 `<用户名>/documents/` 目录下，每次扫描只产生一个 `.hmd` 文件
