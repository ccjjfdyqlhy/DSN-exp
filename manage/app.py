"""
DSN-exp 配置管理终端 — Configuration Manager
后端 HTTP 服务器 + 配置文件读写
"""

import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    import yaml
except ImportError:
    print("[WARN] PyYAML 未安装，YAML 读写不可用。pip install PyYAML")
    yaml = None

from .static import HTML_PAGE

logging.basicConfig(
    level=logging.DEBUG,
    format="[manage] %(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("manage")

PORT = 7432
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
ENV_FILE = PROJECT_ROOT / ".env"
PERSONALITY_DIR = PROJECT_ROOT / "prompt" / "personality_v2" / "presets"
AFFINITY_FILE = PROJECT_ROOT / "prompt" / "personality_v2" / "affinity_rules.yaml"
WORLD_FILE = PROJECT_ROOT / "world" / "worlds" / "default.yaml"
SUBAPPS_DIR = PROJECT_ROOT / "subapps"
PROMPTS_DIR = PROJECT_ROOT / "prompt" / "prompts"


# ============================================================
# .env 解析与写入
# ============================================================

def parse_env() -> dict:
    result = {}
    log.debug("parse_env: start path=%s", ENV_FILE)
    if ENV_FILE.exists():
        text = ENV_FILE.read_text(encoding="utf-8")
        lines = text.splitlines()
        log.debug("parse_env: read %d lines from %s", len(lines), ENV_FILE)
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                result[key] = val
        log.debug("parse_env: parsed %d keys", len(result))
    else:
        log.warning("parse_env: .env file not found at %s", ENV_FILE)
    return result


def write_env(updates: dict) -> None:
    log.debug("write_env: updating %d keys: %s", len(updates), list(updates.keys()))
    backup = str(ENV_FILE) + ".bak"
    if ENV_FILE.exists():
        shutil.copy2(ENV_FILE, backup)
        log.debug("write_env: backed up to %s", backup)

    lines = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        log.debug("write_env: read %d existing lines", len(lines))

    for up_key, up_val in updates.items():
        up_val_str = str(up_val)
        if up_val_str and (" " in up_val_str or "#" in up_val_str or '"' in up_val_str):
            up_val_str = f'"{up_val_str}"'
        found = False
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k == up_key:
                    tail = ""
                    comment_pos = stripped.find("#")
                    if comment_pos >= 0:
                        tail = " " + stripped[comment_pos:]
                    lines[idx] = f"{up_key}={up_val_str}{tail}\n"
                    found = True
                    break
        if not found:
            lines.append(f"{up_key}={up_val_str}\n")

    ENV_FILE.write_text("".join(lines), encoding="utf-8")
    log.debug("write_env: wrote %d lines", len(lines))


# ============================================================
# YAML 读写
# ============================================================

def read_yaml(path: Path) -> dict:
    log.debug("read_yaml: %s", path)
    if yaml and path.exists():
        with open(path, "r", encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
            log.debug("read_yaml: loaded %s with %d top keys", path.name, len(data))
            return data
    log.warning("read_yaml: %s not found or yaml unavailable", path)
    return {}


def write_yaml(path: Path, data: dict) -> None:
    log.debug("write_yaml: %s (%d top keys)", path, len(data))
    if not yaml:
        return
    backup = str(path) + ".bak"
    if path.exists():
        shutil.copy2(path, backup)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log.debug("write_yaml: saved %s", path)


# ============================================================
# 配置状态聚合
# ============================================================

def load_full_config() -> dict:
    log.debug("load_full_config: start")
    cfg = {"_sources": {}, "_prompts": []}

    env = parse_env()
    cfg["_sources"]["env"] = {"type": "env", "path": str(ENV_FILE), "keys": {}}
    for k, v in env.items():
        cfg["_sources"]["env"]["keys"][k] = v
    log.debug("load_full_config: env keys=%d", len(env))

    presets = []
    if PERSONALITY_DIR.exists():
        for yf in sorted(PERSONALITY_DIR.glob("*.yaml")):
            data = read_yaml(yf)
            presets.append({
                "file": yf.name,
                "name": data.get("name", yf.stem),
                "display_name": data.get("display_name", yf.stem),
                "description": data.get("description", ""),
                "data": data,
            })
    cfg["_sources"]["personality_presets"] = {"type": "yaml_list", "path": str(PERSONALITY_DIR), "presets": presets}
    log.debug("load_full_config: personality presets=%d", len(presets))

    affinity = read_yaml(AFFINITY_FILE)
    cfg["_sources"]["affinity_rules"] = {"type": "yaml", "path": str(AFFINITY_FILE), "data": affinity}
    log.debug("load_full_config: affinity rules actions=%d", len(affinity.get('actions', [])))

    world = read_yaml(WORLD_FILE)
    cfg["_sources"]["world"] = {"type": "yaml", "path": str(WORLD_FILE), "data": world}
    log.debug("load_full_config: world name=%s", world.get('name', 'N/A'))

    subapps = []
    if SUBAPPS_DIR.exists():
        for sd in sorted(SUBAPPS_DIR.iterdir()):
            if sd.is_dir():
                yf = sd / "subapp.yaml"
                if yf.exists():
                    data = read_yaml(yf)
                    subapps.append({"dir": sd.name, "file": str(yf), "data": data})
    cfg["_sources"]["subapps"] = {"type": "yaml_list", "path": str(SUBAPPS_DIR), "subapps": subapps}
    log.debug("load_full_config: subapps=%d", len(subapps))

    cfg["_prompts"] = _scan_prompts()
    log.debug("load_full_config: prompts=%d", len(cfg["_prompts"]))
    log.debug("load_full_config: complete")
    return cfg


def _scan_prompts() -> list:
    result = []
    if not PROMPTS_DIR.exists():
        return result
    for yf in sorted(PROMPTS_DIR.rglob("*")):
        if yf.is_file() and yf.suffix in (".md", ".yaml", ".yml"):
            rel = yf.relative_to(PROMPTS_DIR)
            category = str(rel.parts[0]) if len(rel.parts) > 1 else ""
            meta = _parse_frontmatter(yf.read_text(encoding="utf-8"))
            result.append({
                "path": str(rel),
                "abspath": str(yf),
                "category": category,
                "name": meta.get("name", yf.stem),
                "description": meta.get("description", ""),
                "enabled": meta.get("enabled", True),
                "priority": meta.get("priority", 99),
                "version": meta.get("version", "1.0"),
                "meta": meta,
            })
    return result


def _parse_frontmatter(text: str) -> dict:
    meta = {}
    stripped = text.strip()
    if stripped.startswith("---"):
        end = stripped.find("---", 3)
        if end > 3:
            fm = stripped[3:end].strip()
            if yaml:
                try:
                    meta = yaml.safe_load(fm) or {}
                except Exception:
                    pass
    return meta


# ============================================================
# HTTP 处理器
# ============================================================

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        log.info("HTTP %s %s", self.command, self.path)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        log.debug("do_GET: %s", path)

        if path == "/api/config":
            log.debug("do_GET: loading full config")
            cfg = load_full_config()
            log.debug("do_GET: config loaded, sections=%d, prompts=%d",
                      len(cfg.get("_sources", {})), len(cfg.get("_prompts", [])))
            self._json(200, cfg)
        elif path == "/api/file":
            qs = parse_qs(parsed.query)
            fp = qs.get("path", [None])[0]
            log.debug("do_GET: file path=%s", fp)
            if fp:
                full_path = (PROJECT_ROOT / fp).resolve()
                try:
                    full_path.relative_to(PROJECT_ROOT)
                except ValueError:
                    log.warning("do_GET: path traversal blocked: %s", fp)
                    self._json(403, {"error": "路径越界"})
                    return
                if not full_path.exists():
                    log.warning("do_GET: file not found: %s", full_path)
                    self._json(404, {"error": "文件不存在"})
                    return
                text = full_path.read_text(encoding="utf-8")
                log.debug("do_GET: file read %s (%d chars)", fp, len(text))
                self._json(200, {"path": fp, "content": text})
            else:
                log.warning("do_GET: missing path param")
                self._json(400, {"error": "缺少 path 参数"})
        elif path == "/api/prompts/reload":
            log.debug("do_GET: reloading prompts")
            self._json(200, {"prompts": _scan_prompts()})
        else:
            log.debug("do_GET: serving HTML page (%d chars)", len(HTML_PAGE))
            html = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        log.debug("do_POST: %s body=%d chars", path, len(body))

        try:
            payload = json.loads(body)
            log.debug("do_POST: parsed payload keys=%s", list(payload.keys()))
        except json.JSONDecodeError as e:
            log.warning("do_POST: invalid JSON: %s", e)
            self._json(400, {"error": "无效 JSON"})
            return

        if path == "/api/config/save":
            self._handle_save(payload)
        elif path == "/api/file/save":
            fp = parse_qs(parsed.query).get("path", [None])[0]
            log.debug("do_POST: file/save path=%s", fp)
            if fp:
                full_path = (PROJECT_ROOT / fp).resolve()
                try:
                    full_path.relative_to(PROJECT_ROOT)
                except ValueError:
                    log.warning("do_POST: path traversal blocked: %s", fp)
                    self._json(403, {"error": "路径越界"})
                    return
                if full_path.exists():
                    shutil.copy2(full_path, str(full_path) + ".bak")
                    log.debug("do_POST: backed up %s", full_path)
                content = payload.get("content", "")
                full_path.write_text(content, encoding="utf-8")
                log.debug("do_POST: wrote %s (%d chars)", fp, len(content))
                self._json(200, {"status": "ok"})
            else:
                self._json(400, {"error": "缺少 path 参数"})
        elif path == "/api/prompts/meta":
            self._handle_prompt_meta(payload)
        else:
            log.warning("do_POST: unknown endpoint: %s", path)
            self._json(404, {"error": "unknown endpoint"})

    def _handle_save(self, payload: dict):
        section = payload.get("section", "")
        data = payload.get("data", {})
        log.info("_handle_save: section=%s keys=%s", section, list(data.keys())[:10])

        if section == "env":
            if data:
                write_env(data)
                log.info("_handle_save: env saved %d fields", len(data))
                self._json(200, {"status": "ok", "field_count": len(data)})
            else:
                self._json(200, {"status": "ok"})
        elif section == "preset":
            for fname, ydata in data.items():
                ypath = PERSONALITY_DIR / fname
                write_yaml(ypath, ydata)
                log.info("_handle_save: preset saved %s", fname)
            self._json(200, {"status": "ok"})
        elif section == "affinity":
            write_yaml(AFFINITY_FILE, data)
            log.info("_handle_save: affinity saved")
            self._json(200, {"status": "ok"})
        elif section == "world":
            write_yaml(WORLD_FILE, data)
            log.info("_handle_save: world saved")
            self._json(200, {"status": "ok"})
        elif section == "subapp":
            for sname, sdata in data.items():
                sub_dir = SUBAPPS_DIR / sname
                ypath = sub_dir / "subapp.yaml"
                if ypath.exists() and sub_dir.exists():
                    write_yaml(ypath, sdata)
                    log.info("_handle_save: subapp %s saved", sname)
            self._json(200, {"status": "ok"})
        else:
            log.warning("_handle_save: unknown section: %s", section)
            self._json(400, {"error": f"未知 section: {section}"})

    def _handle_prompt_meta(self, payload: dict):
        fp = payload.get("path", "")
        log.debug("_handle_prompt_meta: path=%s", fp)
        if not fp:
            self._json(400, {"error": "缺少 path"})
            return
        full_path = (PROMPTS_DIR / fp).resolve()
        try:
            full_path.relative_to(PROMPTS_DIR)
        except ValueError:
            log.warning("_handle_prompt_meta: path traversal: %s", fp)
            self._json(403, {"error": "路径越界"})
            return
        if not full_path.exists():
            self._json(404, {"error": "文件不存在"})
            return

        text = full_path.read_text(encoding="utf-8")
        if "enabled" in payload:
            new_val = "true" if payload["enabled"] else "false"
            text = re.sub(r"(?<=enabled:\s*)(true|false)", new_val, text)
            log.debug("_handle_prompt_meta: enabled->%s", new_val)
        if "priority" in payload:
            text = re.sub(r"(?<=priority:\s*)\d+", str(int(payload["priority"])), text)
            log.debug("_handle_prompt_meta: priority->%d", int(payload["priority"]))
        if "description" in payload:
            text = re.sub(r"(?<=description:\s*).+", str(payload["description"]), text)

        backup = str(full_path) + ".bak"
        shutil.copy2(full_path, backup)
        full_path.write_text(text, encoding="utf-8")
        log.info("_handle_prompt_meta: saved %s", fp)
        self._json(200, {"status": "ok"})

    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ============================================================
# 启动
# ============================================================

def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(
        f"""
  DSN-exp 配置管理终端 — Config Manager
  ├─ 服务器 → {url}
  ├─ 项目   → {PROJECT_ROOT}
  └─ 退出   → Ctrl + C
"""
    )

    def open_browser():
        time.sleep(0.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ✓ 配置终端已关闭。\n")
        server.shutdown()
