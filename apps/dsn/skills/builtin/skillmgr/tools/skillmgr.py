# skills/builtin/skillmgr/tools/skillmgr.py
# SkillMgrTool — 技能生命周期管理 + SKILL.md 转换 + 依赖安装

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

logger = logging.getLogger("skill.skillmgr")


class SkillMgrTool:
    """技能管理工具"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._project_root = Path(__file__).parent.parent.parent.parent.parent

    # ═══════════ list_skills ═══════════

    def list_skills(self) -> dict[str, Any]:
        skills = []
        for src_dir in ["builtin", "custom"]:
            d = self._project_root / "skills" / src_dir
            if not d.exists():
                continue
            for sd in sorted(d.iterdir()):
                if not sd.is_dir() or sd.name.startswith("_") or sd.name.startswith("."):
                    continue
                yf = sd / "skill.yaml"
                if not yf.exists():
                    continue
                try:
                    import yaml
                    meta = yaml.safe_load(yf.read_text(encoding="utf-8-sig")) or {}
                except Exception:
                    meta = {}
                deps = meta.get("dependencies", {})
                if isinstance(deps, list):
                    deps = {"python": deps, "system": []}
                tools = meta.get("tools", [])
                skills.append({
                    "name": meta.get("name", sd.name),
                    "display_name": meta.get("display_name", ""),
                    "description": meta.get("description", ""),
                    "source": src_dir,
                    "enabled": meta.get("enabled", True),
                    "status": meta.get("status", "active"),
                    "version": meta.get("version", "1.0"),
                    "tool_count": len(tools),
                    "tool_names": [t.get("name", "") for t in tools] if tools else [],
                    "python_deps": deps.get("python", []),
                    "system_deps": deps.get("system", []),
                })
        return {"success": True, "skills": skills, "count": len(skills)}

    # ═══════════ enable / disable ═══════════

    def enable_skill(self, name: str) -> dict[str, Any]:
        try:
            manager = self._get_skill_manager()
            if not manager:
                return {"success": False, "error": "SkillManager 不可用"}
            ok = manager.enable(name)
            return {"success": ok, "name": name, "message": f"技能 {name} 已启用" if ok else f"技能 {name} 不存在"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def disable_skill(self, name: str) -> dict[str, Any]:
        try:
            manager = self._get_skill_manager()
            if not manager:
                return {"success": False, "error": "SkillManager 不可用"}
            ok = manager.disable(name)
            return {"success": ok, "name": name, "message": f"技能 {name} 已禁用" if ok else f"技能 {name} 不存在"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ═══════════ install_deps ═══════════

    def install_deps(self, name: str, upgrade: bool = False) -> dict[str, Any]:
        yaml_path = self._find_skill_yaml(name)
        if not yaml_path:
            return {"success": False, "error": f"找不到技能 {name}"}

        import yaml
        try:
            meta = yaml.safe_load(yaml_path.read_text(encoding="utf-8-sig")) or {}
        except Exception as e:
            return {"success": False, "error": f"解析 skill.yaml 失败: {e}"}

        deps = meta.get("dependencies", {})
        if isinstance(deps, list):
            deps = {"python": deps, "system": []}

        python_deps = deps.get("python", [])
        system_deps = deps.get("system", [])

        results = {"python_installed": [], "python_skipped": [], "system_results": []}

        for pkg in python_deps:
            pkg_name = pkg.split(">=")[0].split("==")[0].split(">")[0].strip()
            try:
                __import__(pkg_name.replace("-", "_"))
                results["python_skipped"].append(pkg_name)
            except ImportError:
                try:
                    cmd = [sys.executable, "-m", "pip", "install"]
                    if upgrade:
                        cmd.append("--upgrade")
                    cmd.append(pkg)
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if proc.returncode == 0:
                        results["python_installed"].append(pkg_name)
                        logger.info("pip install %s 成功", pkg_name)
                    else:
                        results["python_installed"].append(f"{pkg_name} (失败: {proc.stderr[:200]})")
                except Exception as e:
                    results["python_installed"].append(f"{pkg_name} (异常: {e})")

        for cmd in system_deps:
            try:
                encoding = __import__("locale").getpreferredencoding(False)
                proc = subprocess.run(cmd, shell=True, capture_output=True,
                                      encoding=encoding, errors='replace', timeout=300)
                results["system_results"].append({
                    "command": cmd,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout[:500],
                    "stderr": proc.stderr[:300],
                })
            except Exception as e:
                results["system_results"].append({"command": cmd, "error": str(e)})

        return {"success": True, "name": name, **results}

    # ═══════════ convert_skill (SKILL.md → DSN-exp) ═══════════

    def convert_skill(self, source_name: str, target_name: str = None,
                      target_source: str = "custom") -> dict[str, Any]:
        claw_dir = self._project_root / "skills" / "claw_skills" / source_name
        skill_md = claw_dir / "SKILL.md"
        if not skill_md.exists():
            return {"success": False, "error": f"SKILL.md 不存在: {skill_md}"}

        name = target_name or source_name
        target_dir = self._project_root / "skills" / target_source / name
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "prompts").mkdir(exist_ok=True)
        (target_dir / "tools").mkdir(exist_ok=True)

        text = skill_md.read_text(encoding="utf-8-sig")
        frontmatter, body = self._parse_skill_md(text)

        bin_name = self._infer_binary(frontmatter, name)

        self._write_skill_yaml(target_dir, frontmatter, name, bin_name)
        self._write_instruction_md(target_dir, body, bin_name, frontmatter)
        (target_dir / "tools" / "__init__.py").write_text(
            f"# skills/{target_source}/{name}/tools/__init__.py\n", encoding="utf-8"
        )
        self._write_wrapper_py(target_dir, bin_name, name)

        logger.info("SKILL.md 转换完成: %s → skills/%s/%s/", source_name, target_source, name)
        return {
            "success": True,
            "source": str(skill_md),
            "target": str(target_dir),
            "name": name,
            "binary": bin_name,
            "message": f"技能 {name} 已转换到 skills/{target_source}/{name}/",
        }

    # ═══════════ download_skill ═══════════

    def download_skill(self, url: str, name: str = None) -> dict[str, Any]:
        if not name:
            name = self._guess_name_from_url(url)
        if not name:
            return {"success": False, "error": "无法从 URL 推断技能名，请指定 name 参数"}

        target_dir = self._project_root / "skills" / "claw_skills" / name
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / "SKILL.md"

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "DSN-exp-skillmgr/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()
        except urllib.error.URLError as e:
            return {"success": False, "error": f"下载失败: {e}"}
        except Exception as e:
            return {"success": False, "error": f"下载异常: {e}"}

        try:
            content_str = content.decode("utf-8")
        except UnicodeDecodeError:
            content_str = content.decode("utf-8-sig", errors="replace")

        if url.lower().endswith(".zip"):
            import zipfile, io, shutil
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                for member in zf.namelist():
                    if member.endswith("SKILL.md") or member.endswith("/SKILL.md"):
                        target_file.write_text(
                            zf.read(member).decode("utf-8-sig", errors="replace"),
                            encoding="utf-8",
                        )
                        break
                    elif "SKILL.md" in member:
                        target_file.write_text(
                            zf.read(member).decode("utf-8-sig", errors="replace"),
                            encoding="utf-8",
                        )
                        break
                else:
                    zf.extractall(str(target_dir))
        else:
            target_file.write_text(content_str, encoding="utf-8")

        logger.info("下载技能完成: %s → %s", url, target_file)
        return {
            "success": True,
            "url": url,
            "name": name,
            "path": str(target_file),
            "size": len(content),
            "message": f"技能已下载到 skills/claw_skills/{name}/SKILL.md",
        }

    # ═══════════ internals ═══════════

    def _find_skill_yaml(self, name: str) -> Path | None:
        for src in ["builtin", "custom", "batch"]:
            p = self._project_root / "skills" / src / name / "skill.yaml"
            if p.exists():
                return p
        return None

    def _get_skill_manager(self):
        try:
            from apps.dsn.skills.manager import SkillManager
            from apps.dsn.skills.registry import SkillRegistry
            builtin = str(self._project_root / "skills" / "builtin")
            custom = str(self._project_root / "skills" / "custom")
            batch = str(self._project_root / "skills" / "batch")
            registry = SkillRegistry()
            mgr = SkillManager(skill_dirs=[builtin, custom, batch], registry=registry)
            mgr.scan_and_load()
            return mgr
        except Exception:
            return None

    @staticmethod
    def _parse_skill_md(text: str) -> tuple[dict, str]:
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
        import yaml
        if match:
            try:
                frontmatter = yaml.safe_load(match.group(1)) or {}
            except Exception:
                frontmatter = {}
            body = match.group(2).strip()
        else:
            frontmatter = {}
            body = text.strip()
        return frontmatter, body

    @staticmethod
    def _infer_binary(frontmatter: dict, fallback: str) -> str:
        allowed = frontmatter.get("allowed-tools", "")
        if allowed:
            m = re.search(r"Bash\(([^:*]+)", allowed)
            if m:
                return m.group(1).strip()
        requires = frontmatter.get("metadata", {}).get("bot", {}).get("requires", {})
        bins = requires.get("bins", [])
        if bins and bins[0] not in ("node", "npm", "python"):
            return bins[0]
        return fallback.replace("-", "_")

    @staticmethod
    def _extract_install_commands(body: str) -> list[str]:
        cmds = []
        for line in body.split("\n"):
            stripped = line.strip()
            if stripped.startswith("npm install") or stripped.startswith("pip install"):
                cmds.append(stripped)
            elif stripped.startswith("pnpm") or stripped.startswith("yarn"):
                cmds.append(stripped)
        return cmds

    def _write_skill_yaml(self, target_dir: Path, fm: dict, name: str, bin_name: str):
        activation_keywords = fm.get("read_when", [])
        if isinstance(activation_keywords, str):
            activation_keywords = [activation_keywords]
        install_cmds = self._extract_install_commands(
            (target_dir / ".." / ".." / "claw_skills" / name / "SKILL.md").read_text(
                encoding="utf-8-sig"
            ) if (target_dir / ".." / ".." / "claw_skills" / name / "SKILL.md").exists() else ""
        )

        yaml_content = f"""name: {name}
display_name: "{fm.get('name', name).replace('-', ' ').title()}"
description: "{fm.get('description', '').replace('"', '\\"')[:200]}"
version: "1.0"
author: "claw_converted"
source: "custom"
enabled: true
status: "active"
prompt_category: "skills"
prompt_priority: 65

tools:
  - name: exec
    display_name: "执行命令"
    description: "执行 {bin_name} 命令"
    module: "tools.wrapper"
    class: "CliWrapper"
    methods:
      - name: exec
        description: "执行 {bin_name} 命令行"
        parameters:
          command:
            type: string
            description: "{bin_name} 的参数（不含二进制名）"
            required: true

dependencies:
  python: []
  system:{chr(10) + '    - "' + chr(10) + '    - "'.join(install_cmds) + '"' if install_cmds else ' []'}

activation:
  keywords: {activation_keywords}
  auto_activate: false

tags: [claw_converted, {name}]
"""
        (target_dir / "skill.yaml").write_text(yaml_content, encoding="utf-8")

    @staticmethod
    def _write_instruction_md(target_dir: Path, body: str, bin_name: str, fm: dict):
        header = f"""---
name: {fm.get('name', 'skill')}_instruction
category: skills
priority: 65
---

## {fm.get('name', 'Skill').title()}

使用 `<tool>` 标签调用，`command` 字段填 {bin_name} 的参数（不含二进制名）。

<tool>
{{"skill": "{fm.get('name', 'skill')}", "tool": "exec", "params": {{"command": "你的参数..."}}}}
</tool>

---
"""
        (target_dir / "prompts" / "instruction.md").write_text(
            header + "\n" + body, encoding="utf-8"
        )

    @staticmethod
    def _write_wrapper_py(target_dir: Path, bin_name: str, name: str):
        wrapper = f"""# skills/custom/{name}/tools/wrapper.py
# 自动生成 — {bin_name} CLI 包装器

from __future__ import annotations

import logging
import subprocess
import locale
from typing import Any

logger = logging.getLogger("skill.{name}")


class CliWrapper:
    _bin = "{bin_name}"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {{}}

    def exec(self, command: str) -> dict[str, Any]:
        try:
            encoding = locale.getpreferredencoding(False)
            proc = subprocess.run(
                f"{{self._bin}} {{command}}",
                shell=True, capture_output=True,
                encoding=encoding, errors='replace',
                timeout=120,
            )
            return {{
                "success": proc.returncode == 0,
                "stdout": proc.stdout[:4000] if proc.stdout else "",
                "stderr": proc.stderr[:1000] if proc.stderr else "",
                "exit_code": proc.returncode,
            }}
        except Exception as e:
            return {{"success": False, "error": str(e)}}
"""
        (target_dir / "tools" / "wrapper.py").write_text(wrapper, encoding="utf-8")

    @staticmethod
    def _guess_name_from_url(url: str) -> str:
        parts = url.rstrip("/").split("/")
        for p in reversed(parts):
            if p and p not in ("raw", "main", "master", "blob", "tree"):
                name = p.replace(".md", "").replace(".zip", "").replace(".git", "")
                return re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")[:40]
        return ""
