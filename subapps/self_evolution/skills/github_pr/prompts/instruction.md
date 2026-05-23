---
name: github_pr_instruction
category: skills
priority: 60
---

## GitHub PR 技能

你可以使用 `<tool>` 标签调用以下 GitHub 操作工具：

### 可用工具

**github_pr.clone** — 克隆仓库
```json
{"skill": "github_pr", "tool": "clone", "params": {"repo_url": "https://github.com/owner/repo.git"}}
```

**github_pr.branch** — 创建并切换到新分支
```json
{"skill": "github_pr", "tool": "branch", "params": {"name": "fix/typo-readme"}}
```

**github_pr.status** — 查看仓库状态
```json
{"skill": "github_pr", "tool": "status", "params": {}}
```

**github_pr.write_file** — 写入或修改文件
```json
{"skill": "github_pr", "tool": "write_file", "params": {"path": "README.md", "content": "new content"}}
```

**github_pr.commit** — 提交所有更改
```json
{"skill": "github_pr", "tool": "commit", "params": {"message": "fix: correct typo in README"}}
```

**github_pr.push** — 推送分支到远程
```json
{"skill": "github_pr", "tool": "push", "params": {"branch": "fix/typo-readme"}}
```

**github_pr.create_pr** — 创建 Pull Request
```json
{"skill": "github_pr", "tool": "create_pr", "params": {"title": "Fix typo", "body": "描述改动", "head": "fix/typo-readme", "base": "main"}}
```

**github_pr.list_issues** — 列出 open issues
```json
{"skill": "github_pr", "tool": "list_issues", "params": {"state": "open", "limit": 5}}
```

### 工作流程

1. `clone` 仓库（首次）/ 直接使用已有工作目录
2. `list_issues` 查看可解决的问题
3. `branch` 创建特性分支
4. `write_file` 修改代码
5. `commit` 提交
6. `push` 推送
7. `create_pr` 创建 Pull Request
