# 分层认证系统 — FIDO2/WebAuthn + 设备信任 + 配对码

> 策划案 | 版本: v1.0 | 2026-06-02
> 关联: `auth/`（新建认证模块）、`app.py`（login_required 改造）、`psychoscope/`（客户端登录流程）、`chatdbmgr.py`（auth 表扩展）
> 状态: 草案，待评审

---

## 一、背景

当前 DSN-exp 完全依赖 LittleSkin OAuth（第三方），存在以下问题：

| # | 问题 |
|---|------|
| 1 | 内网环境 LittleSkin 不可用时无法登录 |
| 2 | 没有用户自主注册能力——必须先去 LittleSkin 创建账号 |
| 3 | JWT 永不过期，无撤销机制 |
| 4 | 无设备信任概念——每次换浏览器都需要重新 OAuth |
| 5 | 无多因素认证——JWT 被窃取即完全沦陷 |
| 6 | 无 API Key 体系——自动化脚本无法认证 |

---

## 二、目标

- **内网极简**：已绑定设备仅需输入用户 ID 恢复登录
- **外网安全**：新设备必须通过 WebAuthn 通行密钥（指纹/面容/安全密钥）
- **初始装机**：终端打印一次性配对码，用户输入即可创建管理员
- **无需第三方**：所有认证自托管，LittleSkin 降级为可选身份绑定

---

## 三、分层模型

```
┌─────────────────────────────────────────────────────────┐
│ L0 恢复层   配对码 (Pairing Code)                        │
│             终端打印 8 位数字，一次性，5 分钟过期          │
│             仅用于初始装机或所有设备丢失的灾难恢复           │
├─────────────────────────────────────────────────────────┤
│ L1 信任设备  Session (httpOnly Cookie + Server验证)      │
│             已绑定设备，内网 + 外网均可用                  │
│             恢复时仅需输入用户 ID（不显示用户名列表）       │
├─────────────────────────────────────────────────────────┤
│ L2 通行密钥  WebAuthn (平台验证器 / 漫游验证器)           │
│             新设备登录的唯一方式（外网强制）                │
│             指纹/面容/安全密钥，一步完成                   │
├─────────────────────────────────────────────────────────┤
│ L3 后备     TOTP (RFC 6238)                              │
│             仅当用户主动在安全设置中开启                    │
│             用于无法使用 WebAuthn 的旧设备                 │
├─────────────────────────────────────────────────────────┤
│ L4 API 密钥  API Key (SHA-256 哈希存储)                   │
│             脚本/自动化工具使用，不与浏览器会话互通          │
│             支持 scope 权限 + IP 白名单                    │
└─────────────────────────────────────────────────────────┘
```

---

## 四、模块架构

```
auth/                              ★ 独立认证模块
├── __init__.py                    导出 AuthManager, auth_bp
├── auth_manager.py                AuthManager — 统一认证入口
├── pairing.py                     PairingManager — L0 配对码
├── session.py                     SessionManager — L1 设备信任 Cookie
├── webauthn_manager.py            WebAuthnManager — L2 FIDO2/WebAuthn
├── totp_manager.py                TOTPManager — L3 TOTP
├── api_key_manager.py             APIKeyManager — L4 API Key
├── network.py                     NetworkDetector — 内外网判断
├── endpoints.py                   Flask 端点 — 全部 /api/auth/* 路由
└── models.py                      AuthUser, AuthCredential, AuthSession dataclass
```

### 不修改的现有文件

| 文件 | 改动策略 |
|------|----------|
| `usermgr.py` | **保留但降级**：LittleSkin OAuth 改为可选身份绑定，通过 AuthManager 注册 |
| `app.py` `login_required` | **扩展**：支持多种 Authorization header 格式（Bearer JWT / Session / X-DSN-API-Key） |
| `chatdbmgr.py` | **扩展**：`users` 表新增字段 + 新增 5 个 auth 表 |
| `psychoscope/` | **重写登录界面**：ID 输入 + 配对码 + 通行密钥 + 自动恢复 |
| `config.py` | **新增** 15 个认证配置键 |
| `requirements.txt` | **新增** `webauthn>=2.0`, `pyotp`, `qrcode` |

---

## 五、数据库变更

### 5.1 `users` 表扩展

```sql
-- 在现有 users 表基础上新增列
ALTER TABLE users ADD COLUMN display_name TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN created_at TEXT DEFAULT (datetime('now'));
ALTER TABLE users ADD COLUMN littleskin_uid INTEGER DEFAULT NULL;
```

### 5.2 新增认证表

```sql
CREATE TABLE IF NOT EXISTS auth_credentials (
    credential_id TEXT PRIMARY KEY,            -- WebAuthn credential ID (base64url)
    uid INTEGER NOT NULL,
    public_key BLOB NOT NULL,                  -- WebAuthn 公钥
    sign_count INTEGER DEFAULT 0,
    transports TEXT DEFAULT '',
    device_name TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    uid INTEGER NOT NULL,
    device_token_hash TEXT NOT NULL,
    device_name TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    is_trusted INTEGER DEFAULT 0,
    ip_address TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    last_used_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT,
    revoked INTEGER DEFAULT 0,
    FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_totp (
    uid INTEGER PRIMARY KEY,
    secret TEXT NOT NULL,
    enabled INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth_pairing_codes (
    code TEXT PRIMARY KEY,
    uid INTEGER,
    expires_at TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS auth_api_keys (
    key_hash TEXT PRIMARY KEY,
    uid INTEGER NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT 'read',
    ip_whitelist TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    last_used_at TEXT,
    expires_at TEXT,
    revoked INTEGER DEFAULT 0,
    FOREIGN KEY (uid) REFERENCES users(uid) ON DELETE CASCADE
);
```

---

## 六、AuthManager 统一入口

```python
class AuthManager:
    def __init__(self, db, jwt_secret):
        self._db = db
        self._pairing = PairingManager(db)
        self._session = SessionManager(db, jwt_secret)
        self._webauthn = WebAuthnManager(db)
        self._totp = TOTPManager(db)
        self._api_key = APIKeyManager(db)
        self._network = NetworkDetector()

    def authenticate(self, request) -> dict | None:
        """统一认证入口。按优先级：Session → JWT Bearer → API Key"""
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Session "):
            session = self._session.validate(auth[8:])
            if session:
                return {"uid": session.uid, "auth_source": "session"}
        if auth.startswith("Bearer "):
            from jwt import decode as jwt_decode
            try:
                payload = jwt_decode(auth[7:], self._jwt_secret, algorithms=["HS256"])
                return {"uid": payload["uid"], "auth_source": "jwt"}
            except Exception:
                pass
        api_key = request.headers.get("X-DSN-API-Key", "")
        if api_key:
            uid = self._api_key.validate(api_key)
            if uid:
                return {"uid": uid, "auth_source": "api_key"}
        return None
```

---

## 七、`login_required` 装饰器改造 (app.py)

```python
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = app.config["AUTH_MANAGER"].authenticate(request)
        if not user:
            return jsonify({"error": "Unauthorized"}), 401
        g.user = user
        db.add_or_update_user(user["uid"], user.get("nickname", "用户"))
        return f(*args, **kwargs)
    return decorated_function
```

---

## 八、客户端登录流程（Psychoscope 重设计）

### 8.1 新登录界面

```html
<div id="login-overlay">
    <div class="login-content">
        <h1>DSN-exp</h1>
        <p>PSYCHOSCOPE CLIENT</p>
        <input id="server-url" type="text" placeholder="服务器地址" value="http://localhost:5000" />

        <!-- 配对码（初始装机） -->
        <input id="pairing-code" type="text" placeholder="配对码（终端显示的8位数字）" maxlength="8" />
        <input id="user-name" type="text" placeholder="你的名字" />
        <button id="btn-pair">完成配对</button>

        <div class="or-divider">— 或 —</div>

        <!-- 通行密钥登录 -->
        <input id="user-id" type="text" placeholder="用户 ID" autocomplete="username" />
        <button id="btn-webauthn">使用通行密钥登录</button>
        <span class="hint">支持指纹、面容、安全密钥</span>
    </div>
</div>
```

### 8.2 JS 核心流程

```javascript
init():
  1. 尝试信任设备自动恢复 → 成功则直接进入主界面
  2. 检查服务器状态 → need_pairing → 显示配对界面 / 否则显示 WebAuthn 界面

loginWithWebAuthn():
  1. 用户输入 ID
  2. GET /api/auth/webauthn/login/begin → challenge
  3. navigator.credentials.get() → assertion
  4. POST /api/auth/webauthn/login/complete → session_id
  5. 存入 localStorage → 进入主界面
```

### 8.3 信任设备恢复

服务器下发 `Set-Cookie: dsn_device=<device_token>`，链接触发自动验证：

```javascript
// 页面加载时自动发送 Cookie
fetch('/api/auth/session/recover', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({uid: localStorage.getItem('dsn_user_id')}),
    credentials: 'include',
})
```

---

## 九、网络位置判断

```python
class NetworkDetector:
    def __init__(self, internal_cidrs="192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"):
        from ipaddress import ip_network
        self._cidrs = [ip_network(c) for c in internal_cidrs.split(",")]

    def is_internal(self, request) -> bool:
        from ipaddress import ip_address
        ip = request.remote_addr or ""
        if ip in ("127.0.0.1", "::1", "localhost"):
            return True
        return any(ip_address(ip) in cidr for cidr in self._cidrs)
```

### 内外网策略差异

| 操作 | 内网 | 外网 |
|------|------|------|
| 信任设备恢复 | ✅ 仅需 ID | ✅ 仅需 ID |
| 新设备登录 | ✅ WebAuthn 通行密钥 | WebAuthn **强制** |
| 配对码 | ✅ | ❌ |
| TOTP | ❌ 不需要 | ✅ 可选 |
| API Key | ✅ | ✅ 建议 IP 白名单 |

---

## 十、API 端点总览

| 方法 | 路径 | Auth | 说明 |
|------|------|------|------|
| GET | `/api/auth/status` | 无 | 服务器认证状态 |
| POST | `/api/auth/pairing/verify` | 无 | 提交配对码+名字 → 创建用户 |
| POST | `/api/auth/webauthn/register/begin` | session | 开始注册通行密钥 |
| POST | `/api/auth/webauthn/register/complete` | session | 完成注册 |
| POST | `/api/auth/webauthn/login/begin` | 无 | 开始通行密钥登录 |
| POST | `/api/auth/webauthn/login/complete` | 无 | 验证 → 返回 session_id |
| POST | `/api/auth/session/recover` | cookie | 信任设备恢复 |
| DELETE | `/api/auth/session` | session | 退出登录 |
| GET | `/api/auth/sessions` | session | 列出活跃 session |
| POST | `/api/auth/totp/setup` | session | 生成 TOTP 种子 |
| POST | `/api/auth/totp/verify` | 无 | TOTP 登录 |
| POST | `/api/auth/api-key/create` | session | 创建 API Key |
| DELETE | `/api/auth/api-key/<hash>` | session | 撤销 API Key |
| GET | `/api/auth/littleskin/start` | 无 | LittleSkin OAuth（保留） |
| GET | `/api/auth/littleskin/callback` | 无 | LittleSkin 回调 |
| POST | `/api/auth/littleskin/bind` | session | 绑定 LittleSkin 身份 |

---

## 十一、启动流程变更 (app.py)

```python
from auth import AuthManager, auth_bp

auth_manager = AuthManager(db, Config.JWT_SECRET)
pairing_code = auth_manager.generate_pairing_if_needed()
if pairing_code:
    print(f"[DSN-exp] 配对码: {pairing_code} (仅显示一次，5分钟有效)")

app.config["AUTH_MANAGER"] = auth_manager
app.register_blueprint(auth_bp)

# 保留 LittleSkin OAuth 蓝图降级
from usermgr import init_usermgr
init_usermgr(app)
```

---

## 十二、配置键

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `AUTH_INTERNAL_CIDRS` | `"192.168.0.0/16,10.0.0.0/8,172.16.0.0/12"` | 内网 CIDR |
| `AUTH_SESSION_DAYS` | `30` | 信任设备 session 过期 |
| `AUTH_PAIRING_TIMEOUT` | `300` | 配对码有效秒数 |
| `AUTH_PAIRING_DIGITS` | `8` | 配对码位数 |
| `AUTH_WEBAUTHN_RP_NAME` | `"DSN-exp"` | WebAuthn 站点名 |
| `AUTH_TOTP_ISSUER` | `"DSN-exp"` | TOTP 发行者名 |
| `AUTH_API_KEY_LENGTH` | `32` | API Key 字节长度 |

---

## 十三、文件清单

| 文件 | 行数 | 内容 |
|------|------|------|
| `auth/__init__.py` | 10 | 导出 |
| `auth/auth_manager.py` | 200 | 统一认证入口 + bootstrap |
| `auth/pairing.py` | 80 | L0 配对码 |
| `auth/session.py` | 120 | L1 设备信任 |
| `auth/webauthn_manager.py` | 200 | L2 WebAuthn |
| `auth/totp_manager.py` | 80 | L3 TOTP |
| `auth/api_key_manager.py` | 80 | L4 API Key |
| `auth/network.py` | 40 | 内外网判断 |
| `auth/models.py` | 40 | dataclass |
| `auth/endpoints.py` | 250 | 路由 |
| `chatdbmgr.py` | +60 | 5 个新表 |
| `app.py` | +30/-20 | login_required + 初始化 |
| `config.py` | +15 | 配置键 |
| `psychoscope/index.html` | +40/-15 | 登录界面 |
| `psychoscope/app.js` | +100/-20 | 登录流程 |

---

## 十四、安全特性

| 特性 | 实现 |
|------|------|
| 防暴力破解 | 配对码/ID 连续 5 次失败锁定 5 分钟 |
| 防钓鱼 | WebAuthn challenge 绑定 origin + session |
| 防 CSRF | Cookie SameSite=Strict |
| 防 XSS | session 存放在 httpOnly Cookie，JS 不可读 |
| 防重放 | WebAuthn sign_count 递增 |
| 防密钥泄露 | SHA-256 双哈希存储 |
| 内网限制 | 配对码仅内网可用 |
| Session 过期 | 可配置，滑动续期 |
