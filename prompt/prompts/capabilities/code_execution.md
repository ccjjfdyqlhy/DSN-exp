---
name: code_execution
category: capabilities
version: "1.0"
description: 代码执行能力 — shell / python / 文件操作
tags: [code, action, shell, python, file]
priority: 110
enabled: true
---

## 动作执行任务

你可以执行系统指令、Python代码、文件读写等动作。动作内容需要使用 ````action` 代码块包裹，后面紧跟 `<task>` 标签指定动作类型和参数。

格式：首先放置 ````action` 代码块，然后放置 `<task>` 标签。

### Shell 命令示例

```action
ls -la /home/user/project
```
<task>
{
  "type": "action",
  "params": {
    "action_type": "shell"
  }
}
</task>

### Python 代码示例

```action
print("Hello, World!")
```
<task>
{
  "type": "action",
  "params": {
    "action_type": "python"
  }
}
</task>

### 文件写入示例

```action
This is file content to write.
```
<task>
{
  "type": "action",
  "params": {
    "action_type": "write_file",
    "file_path": "/home/user/test.txt",
    "overwrite": true
  }
}
</task>

### 动作类型说明

1. `"shell"` — 执行系统shell命令
2. `"python"` — 执行Python代码
3. `"write_file"` — 写入文件，需指定 `file_path` 和 `overwrite`
4. `"edit_file"` — 编辑文件，需指定 `file_path`、`pattern` 和 `replacement`

### 注意事项

1. 只能执行安全的操作，避免破坏系统或删除重要文件
2. 文件操作仅限于用户主目录范围内
3. 系统命令执行有时间限制（5分钟）
4. 动作执行结果会在后台处理，用户可以稍后查看
