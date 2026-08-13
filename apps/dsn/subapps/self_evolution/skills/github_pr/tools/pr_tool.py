# tools/pr_tool.py
# GitHub PR 工具 — 封装 git CLI + gh CLI

import subprocess
import os
import logging
from pathlib import Path

logger = logging.getLogger("GitHubPRTool")


class GitHubPRTool:
    """提供 git 和 gh 命令行操作的工具类"""

    def __init__(self, work_dir: str = None):
        if work_dir:
            self._work_dir = work_dir
        else:
            from apps.dsn.utils.workspace import get_workspace_manager
            wm = get_workspace_manager()
            wm.register_subdir("repos")
            self._work_dir = str(wm.root_subdir("repos"))
        os.makedirs(self._work_dir, exist_ok=True)

    def _run(self, cmd: list[str], cwd: str = None, timeout: int = 120) -> dict:
        """执行命令，返回 {success, stdout, stderr, exit_code}"""
        cwd = cwd or self._work_dir
        try:
            result = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True,
                timeout=timeout, shell=True if os.name == 'nt' else False
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "exit_code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令超时: {' '.join(cmd)}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clone(self, repo_url: str, repo_name: str = None) -> dict:
        """克隆仓库"""
        if not repo_name:
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        target = os.path.join(self._work_dir, repo_name)
        if os.path.exists(target):
            result = self._run(["git", "pull"], cwd=target)
            return {"success": True, "action": "pulled", "path": target, "detail": result}
        result = self._run(["git", "clone", repo_url, target])
        if result["success"]:
            return {"success": True, "action": "cloned", "path": target, "detail": result}
        return {"success": False, "error": result.get("stderr", "clone failed")}

    def branch(self, name: str, repo_path: str = None) -> dict:
        """创建并切换到新分支"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "checkout", "-b", name], cwd=cwd)
        if result["success"]:
            return {"success": True, "branch": name, "detail": result}
        return {"success": False, "error": result.get("stderr", "branch failed")}

    def status(self, repo_path: str = None) -> dict:
        """查看仓库状态"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "status", "--porcelain"], cwd=cwd)
        files = []
        if result["success"]:
            for line in result["stdout"].split("\n"):
                line = line.strip()
                if line:
                    status_code = line[:2]
                    filename = line[3:]
                    files.append({"status": status_code, "file": filename})
        return {"success": True, "files": files, "changed_count": len(files), "detail": result}

    def write_file(self, path: str, content: str, repo_path: str = None) -> dict:
        """写入或修改文件"""
        cwd = repo_path or self._work_dir
        full_path = os.path.join(cwd, path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding='utf-8-sig') as f:
                f.write(content)
            return {"success": True, "path": path, "size": len(content), "detail": f"wrote {len(content)} bytes"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def commit(self, message: str, repo_path: str = None) -> dict:
        """git add 并 commit"""
        cwd = repo_path or self._work_dir
        add_result = self._run(["git", "add", "."], cwd=cwd)
        if not add_result["success"]:
            return {"success": False, "error": add_result.get("stderr", "git add failed")}
        commit_result = self._run(["git", "commit", "-m", message], cwd=cwd)
        if commit_result["success"]:
            return {"success": True, "message": message, "detail": commit_result}
        return {"success": False, "error": commit_result.get("stderr", "commit failed")}

    def push(self, branch: str, repo_path: str = None, force: bool = False) -> dict:
        """推送分支到远程"""
        cwd = repo_path or self._work_dir
        cmd = ["git", "push", "origin", branch]
        if force:
            cmd.append("--force")
        result = self._run(cmd, cwd=cwd, timeout=180)
        if result["success"]:
            return {"success": True, "branch": branch, "detail": result}
        return {"success": False, "error": result.get("stderr", "push failed")}

    def create_pr(self, title: str, body: str, head: str, base: str = "main",
                  repo_path: str = None) -> dict:
        """使用 gh CLI 创建 Pull Request"""
        cwd = repo_path or self._work_dir
        cmd = [
            "gh", "pr", "create",
            "--title", title,
            "--body", body,
            "--head", head,
            "--base", base,
        ]
        result = self._run(cmd, cwd=cwd, timeout=60)
        if result["success"]:
            return {"success": True, "pr_url": result["stdout"].strip(), "detail": result}
        return {"success": False, "error": result.get("stderr", "PR creation failed")}

    def list_issues(self, state: str = "open", limit: int = 5,
                    repo_path: str = None) -> dict:
        """列出仓库 issues"""
        cwd = repo_path or self._work_dir
        cmd = ["gh", "issue", "list", "--state", state, "--limit", str(limit), "--json", "title,number,url,labels"]
        result = self._run(cmd, cwd=cwd, timeout=30)
        if result["success"]:
            import json
            try:
                issues = json.loads(result["stdout"])
                return {"success": True, "issues": issues, "count": len(issues)}
            except json.JSONDecodeError:
                return {"success": True, "raw": result["stdout"], "count": 0}
        return {"success": False, "error": result.get("stderr", "list issues failed")}
