---
name: github_instruction
category: skills
priority: 55
---

## GitHub 技能

你可以通过 `<tool>` 标签调用以下 Git / GitHub 操作工具。

### 可用工具一览

| 工具 | 用途 |
|------|------|
| `clone` | 克隆仓库到本地，已存在则 pull |
| `pull` | 拉取远程最新代码 |
| `fetch` | 获取远程分支信息 |
| `branch` | 创建并切换到新分支 |
| `checkout` | 切换到已有分支 |
| `list_branches` | 列出所有分支 |
| `status` | 查看文件变更状态 |
| `diff` | 查看代码差异 |
| `log` | 查看提交历史 |
| `write_file` | 写入或修改文件 |
| `read_file` | 读取文件内容 |
| `commit` | 暂存并提交所有更改 |
| `push` | 推送分支到远程 |
| `create_pr` | 创建 Pull Request |
| `list_issues` | 列出 Issues |
| `list_prs` | 列出 Pull Requests |

### 使用示例

**克隆仓库（默认位置）：**
<tool>
{
  "skill": "github",
  "tool": "clone",
  "params": {"repo_url": "https://github.com/user/repo.git"}
}
</tool>
未指定 `target_path` 时默认克隆到工作区 `repos/<repo_name>`。

**克隆仓库（指定位置）：**
<tool>
{
  "skill": "github",
  "tool": "clone",
  "params": {"repo_url": "https://github.com/user/repo.git", "target_path": "/home/user/projects/my-project"}
}
</tool>

### 克隆路径规则

- 用户**明确指定**了克隆位置时，使用 `target_path` 参数传入该路径
- 用户**未指定**克隆位置时，不传 `target_path`，自动使用工作区默认目录
- `target_path` 支持 `~` 展开和相对路径

**查看状态：**
<tool>
{
  "skill": "github",
  "tool": "status",
  "params": {"repo_path": "/home/user/.dsn/workspace/repos/repo"}
}
</tool>

**创建分支并提交 PR：**
<tool>
{
  "skill": "github",
  "tool": "branch",
  "params": {"name": "fix/typo"}
}
</tool>
<tool>
{
  "skill": "github",
  "tool": "write_file",
  "params": {"path": "README.md", "content": "# 新内容"}
}
</tool>
<tool>
{
  "skill": "github",
  "tool": "commit",
  "params": {"message": "docs: 更新 README"}
}
</tool>
<tool>
{
  "skill": "github",
  "tool": "push",
  "params": {"branch": "fix/typo"}
}
</tool>
<tool>
{
  "skill": "github",
  "tool": "create_pr",
  "params": {"title": "修复文档", "body": "修正了 README 中的拼写错误", "head": "fix/typo", "base": "main"}
}
</tool>

**拉取最新代码：**
<tool>
{
  "skill": "github",
  "tool": "pull",
  "params": {"repo_path": "/home/user/.dsn/workspace/repos/repo"}
}
</tool>

**查看提交历史：**
<tool>
{
  "skill": "github",
  "tool": "log",
  "params": {"repo_path": "/home/user/.dsn/workspace/repos/repo", "count": 5}
}
</tool>

### 注意事项

- 首次操作需先 `clone` 仓库
- `repo_path` 首次 clone 后会返回路径，后续操作传入该路径
- 用户指定克隆位置时用 `target_path`，否则使用默认 `~/dsn_workspace`
- 默认工作目录在 `.dsn/workspace/repos/`，可通过 `WORKSPACE_DIR` 配置
- `push` 和 `create_pr` 需要已配置 `gh auth login` 认证
- 文件路径必须使用相对路径，不能使用绝对路径或路径穿越
