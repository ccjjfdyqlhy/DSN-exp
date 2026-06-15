# tools/git_tool.py
# GitTool — 封装 git CLI + gh CLI，供 GitHub 技能使用

from __future__ import annotations

import json
import os
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("GitTool")

DEFAULT_WORK_DIR = os.path.join(os.path.expanduser("~"), "dsn_workspace")


class GitTool:
    """提供 git 和 gh 命令行操作的工具类"""

    def __init__(self, work_dir: str | None = None):
        self._work_dir = work_dir or os.environ.get("GIT_WORK_DIR", DEFAULT_WORK_DIR)
        os.makedirs(self._work_dir, exist_ok=True)

    # ---- 内部 ----

    def _run(self, cmd: list[str], cwd: str | None = None, timeout: int = 120) -> dict:
        """执行命令，返回 {success, stdout, stderr, exit_code}"""
        cwd = cwd or self._work_dir
        try:
            result = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True,
                timeout=timeout,
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

    # ---- 仓库操作 ----

    def clone(self, repo_url: str, repo_name: str | None = None,
              target_path: str | None = None) -> dict:
        """克隆仓库到本地，已存在则 pull

        target_path: 自定义克隆目标路径（绝对路径或相对路径）。
                     未指定时默认克隆到 dsn_workspace。
                     支持 ~ 展开和相对路径（相对于当前工作目录）。
        """
        if target_path:
            target = os.path.expanduser(target_path)
            target = os.path.abspath(target)
        else:
            if not repo_name:
                repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            target = os.path.join(self._work_dir, repo_name)

        if os.path.exists(os.path.join(target, ".git")):
            result = self._run(["git", "pull"], cwd=target)
            repo = os.path.basename(target)
            return {
                "success": True, "action": "pulled", "path": target,
                "repo_name": repo, "detail": result,
            }

        result = self._run(["git", "clone", repo_url, target])
        if result["success"]:
            repo = repo_name or os.path.basename(target)
            return {
                "success": True, "action": "cloned", "path": target,
                "repo_name": repo, "detail": result,
            }
        return {"success": False, "error": result.get("stderr") or "clone failed"}

    def pull(self, repo_path: str | None = None, branch: str | None = None) -> dict:
        """从远程拉取最新代码"""
        cwd = repo_path or self._work_dir
        cmd = ["git", "pull"]
        if branch:
            cmd += ["origin", branch]
        result = self._run(cmd, cwd=cwd)
        if result["success"]:
            return {"success": True, "action": "pulled", "detail": result}
        return {"success": False, "error": result.get("stderr") or "pull failed"}

    def fetch(self, repo_path: str | None = None, remote: str = "origin") -> dict:
        """从远程获取所有分支信息"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "fetch", remote], cwd=cwd)
        if result["success"]:
            return {"success": True, "detail": result}
        return {"success": False, "error": result.get("stderr") or "fetch failed"}

    # ---- 分支操作 ----

    def branch(self, name: str, repo_path: str | None = None) -> dict:
        """创建并切换到新分支"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "checkout", "-b", name], cwd=cwd)
        if result["success"]:
            return {"success": True, "branch": name, "detail": result}
        return {"success": False, "error": result.get("stderr") or "branch failed"}

    def checkout(self, branch: str, repo_path: str | None = None) -> dict:
        """切换到已有分支"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "checkout", branch], cwd=cwd)
        if result["success"]:
            return {"success": True, "branch": branch, "detail": result}
        return {"success": False, "error": result.get("stderr") or "checkout failed"}

    def list_branches(self, repo_path: str | None = None) -> dict:
        """列出本地和远程分支"""
        cwd = repo_path or self._work_dir
        local = self._run(["git", "branch"], cwd=cwd)
        remote = self._run(["git", "branch", "-r"], cwd=cwd)
        return {
            "success": True,
            "local": [b.strip().lstrip("* ") for b in local.get("stdout", "").split("\n") if b.strip()],
            "remote": [b.strip() for b in remote.get("stdout", "").split("\n") if b.strip()],
        }

    # ---- 查看与对比 ----

    def status(self, repo_path: str | None = None) -> dict:
        """查看仓库状态"""
        cwd = repo_path or self._work_dir
        result = self._run(["git", "status", "--porcelain"], cwd=cwd)
        files = []
        if result["success"]:
            for line in result.get("stdout", "").split("\n"):
                line = line.strip()
                if line:
                    files.append({"status": line[:2], "file": line[3:]})
        return {
            "success": True, "files": files, "changed_count": len(files),
            "detail": result,
        }

    def diff(self, repo_path: str | None = None, staged: bool = False,
             files: list[str] | None = None) -> dict:
        """查看文件差异"""
        cwd = repo_path or self._work_dir
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        if files:
            cmd.append("--")
            cmd.extend(files)
        result = self._run(cmd, cwd=cwd, timeout=60)
        return {"success": True, "diff": result.get("stdout", ""), "detail": result}

    def log(self, repo_path: str | None = None, count: int = 10) -> dict:
        """查看提交历史"""
        cwd = repo_path or self._work_dir
        result = self._run(
            ["git", "log", f"-{count}", "--oneline", "--decorate"], cwd=cwd,
        )
        commits = []
        if result["success"]:
            for line in result.get("stdout", "").split("\n"):
                line = line.strip()
                if line:
                    commits.append(line)
        return {"success": True, "commits": commits, "count": len(commits), "detail": result}

    # ---- 文件操作 ----

    def write_file(self, path: str, content: str, repo_path: str | None = None) -> dict:
        """在仓库中写入或修改文件"""
        cwd = repo_path or self._work_dir
        full_path = os.path.join(cwd, path)

        if os.path.isabs(path):
            return {"success": False, "error": "不允许使用绝对路径，请使用相对路径"}

        # 防止路径穿越
        resolved = os.path.realpath(full_path)
        if not resolved.startswith(os.path.realpath(cwd)):
            return {"success": False, "error": "路径穿越不被允许"}

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return {
                "success": True, "path": path, "size": len(content),
                "detail": f"wrote {len(content)} bytes",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_file(self, path: str, repo_path: str | None = None,
                  limit: int = 5000) -> dict:
        """读取仓库中的文件"""
        cwd = repo_path or self._work_dir
        full_path = os.path.join(cwd, path)

        if os.path.isabs(path):
            return {"success": False, "error": "不允许使用绝对路径"}

        resolved = os.path.realpath(full_path)
        if not resolved.startswith(os.path.realpath(cwd)):
            return {"success": False, "error": "路径穿越不被允许"}

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read(limit)
            return {
                "success": True, "path": path, "content": content,
                "size": len(content), "truncated": len(content) >= limit,
            }
        except FileNotFoundError:
            return {"success": False, "error": f"文件不存在: {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ---- 提交与推送 ----

    def commit(self, message: str, repo_path: str | None = None) -> dict:
        """git add 并 commit 所有更改"""
        cwd = repo_path or self._work_dir
        add_result = self._run(["git", "add", "."], cwd=cwd)
        if not add_result["success"]:
            return {"success": False, "error": add_result.get("stderr") or "git add failed"}

        commit_result = self._run(["git", "commit", "-m", message], cwd=cwd)
        if commit_result["success"]:
            return {"success": True, "message": message, "detail": commit_result}
        return {"success": False, "error": commit_result.get("stderr") or "commit failed"}

    def push(self, branch: str, repo_path: str | None = None,
             force: bool = False) -> dict:
        """推送分支到远程"""
        cwd = repo_path or self._work_dir
        cmd = ["git", "push", "origin", branch]
        if force:
            cmd.append("--force")
        result = self._run(cmd, cwd=cwd, timeout=180)
        if result["success"]:
            return {"success": True, "branch": branch, "detail": result}
        return {"success": False, "error": result.get("stderr") or "push failed"}

    # ---- GitHub 操作 (gh CLI) ----

    def create_pr(self, title: str, body: str, head: str,
                  base: str = "main", repo_path: str | None = None) -> dict:
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
        return {"success": False, "error": result.get("stderr") or "PR creation failed"}

    def list_issues(self, state: str = "open", limit: int = 10,
                    repo_path: str | None = None) -> dict:
        """列出仓库 issues"""
        cwd = repo_path or self._work_dir
        cmd = [
            "gh", "issue", "list", "--state", state,
            "--limit", str(limit), "--json", "title,number,url,labels,state",
        ]
        result = self._run(cmd, cwd=cwd, timeout=30)
        if result["success"]:
            try:
                issues = json.loads(result["stdout"])
                return {"success": True, "issues": issues, "count": len(issues)}
            except json.JSONDecodeError:
                return {"success": True, "raw": result["stdout"], "count": 0}
        return {"success": False, "error": result.get("stderr") or "list issues failed"}

    def list_prs(self, state: str = "open", limit: int = 10,
                 repo_path: str | None = None) -> dict:
        """列出仓库 Pull Requests"""
        cwd = repo_path or self._work_dir
        cmd = [
            "gh", "pr", "list", "--state", state,
            "--limit", str(limit), "--json", "title,number,url,headRefName,baseRefName,author",
        ]
        result = self._run(cmd, cwd=cwd, timeout=30)
        if result["success"]:
            try:
                prs = json.loads(result["stdout"])
                return {"success": True, "prs": prs, "count": len(prs)}
            except json.JSONDecodeError:
                return {"success": True, "raw": result["stdout"], "count": 0}
        return {"success": False, "error": result.get("stderr") or "list PRs failed"}
