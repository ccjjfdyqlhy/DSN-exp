# cli/webui_server.py
# EXA Web UI standalone server — 静态文件 + 加密凭据存储
# 用法: python cli/webui_server.py [--port 8080]
# 不依赖 app.py，独立运行

import os
import sys
import json
import base64
import secrets
import hashlib
import hmac
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

WEBUI_DIR = Path(__file__).parent / "webui"
KEY_FILE = WEBUI_DIR / ".secret_key"
CRED_FILE = WEBUI_DIR / ".credentials"
DEFAULT_PORT = 8080


# ═══════════════════════════════════════════
#  加密模块 (XOR + HMAC，零外部依赖)
# ═══════════════════════════════════════════

def _get_key() -> bytes:
    """获取或生成加密密钥"""
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = secrets.token_bytes(32)
    KEY_FILE.write_bytes(key)
    return key


def encrypt(data: str) -> str:
    """加密字符串，返回 base64 密文"""
    key = _get_key()
    raw = data.encode("utf-8")
    nonce = secrets.token_bytes(16)
    keystream = hashlib.sha256(key + nonce).digest()
    encrypted = bytes(
        a ^ b for a, b in zip(raw, (keystream * (len(raw) // 32 + 1))[:len(raw)])
    )
    mac = hmac.new(key, nonce + encrypted, "sha256").digest()
    result = nonce + mac + encrypted
    return base64.b64encode(result).decode()


def decrypt(encoded: str) -> str:
    """解密 base64 密文，失败抛异常"""
    key = _get_key()
    result = base64.b64decode(encoded)
    nonce, mac, encrypted = result[:16], result[16:48], result[48:]
    expected = hmac.new(key, nonce + encrypted, "sha256").digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("凭据完整性校验失败")
    keystream = hashlib.sha256(key + nonce).digest()
    decrypted = bytes(
        a ^ b for a, b in zip(encrypted, (keystream * (len(encrypted) // 32 + 1))[:len(encrypted)])
    )
    return decrypted.decode("utf-8")


def save_credentials(token: str) -> None:
    """加密并持久化 token"""
    CRED_FILE.write_text(encrypt(token), encoding="utf-8")
    CRED_FILE.chmod(0o600)


def load_credentials() -> str | None:
    """加载并解密 token，如果失败返回 None"""
    if not CRED_FILE.exists():
        return None
    try:
        return decrypt(CRED_FILE.read_text(encoding="utf-8"))
    except Exception:
        CRED_FILE.unlink(missing_ok=True)
        return None


def clear_credentials() -> None:
    """删除凭据文件"""
    CRED_FILE.unlink(missing_ok=True)


# ═══════════════════════════════════════════
#  HTTP 请求处理器
# ═══════════════════════════════════════════

class WebUIHandler(SimpleHTTPRequestHandler):
    """处理 Web UI 静态文件 + 凭据 API"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def log_message(self, fmt, *args):
        print(f"[webui] {args[0]}")

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        """CORS 预检"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "3600")
        self.end_headers()

    # ─── 凭据管理 API ───
    def _handle_token_get(self):
        token = load_credentials()
        self._json_response({"token": token})

    def _handle_token_post(self):
        body = self._read_body()
        token = body.get("token", "").strip()
        if not token:
            self._json_response({"error": "缺少 token"}, 400)
            return
        try:
            save_credentials(token)
            self._json_response({"ok": True})
        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def _handle_token_delete(self):
        clear_credentials()
        self._json_response({"ok": True})

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/_webui/token":
            return self._handle_token_get()

        # SPA fallback: 非文件路径返回 index.html
        if path == "/":
            self.path = "/index.html"
        elif not os.path.splitext(path)[1]:
            # 无扩展名 -> 尝试 index.html（SPA 路由）
            file_path = WEBUI_DIR / path.lstrip("/")
            if file_path.is_dir() or not file_path.exists():
                self.path = "/index.html"

        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/_webui/token":
            return self._handle_token_post()
        self.send_response(405)
        self.end_headers()

    def do_DELETE(self):
        if urlparse(self.path).path == "/_webui/token":
            return self._handle_token_delete()
        self.send_response(405)
        self.end_headers()


# ═══════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════

def main():
    port = DEFAULT_PORT
    args = sys.argv[1:]
    if "--port" in args:
        idx = args.index("--port")
        if idx + 1 < len(args):
            port = int(args[idx + 1])
    elif len(args) == 1:
        try:
            port = int(args[0])
        except ValueError:
            pass

    # 确保目录存在
    WEBUI_DIR.mkdir(parents=True, exist_ok=True)

    server = HTTPServer(("0.0.0.0", port), WebUIHandler)
    print(f"EXA Web UI server started at http://localhost:{port}")
    print(f"Serving: {WEBUI_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
