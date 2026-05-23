# 无人值守鉴权 & 自主凭证管理

> 策划案 | 版本: v1.0 | 2026-05-23
> 关联: SubApp 生态 (`subapps/`)、引擎层 (`engine.py`)
> 状态: 草案，待实现

---

## 一、问题

当前 DSN-exp 在以下场景需要用户**手动介入**：

| 场景 | 当前方式 | 痛点 |
|------|---------|------|
| 首次启动 | 手动创建 `.env`，填 `DEEPSEEK_API_KEY` | 用户得先搞到 key，自己找地方填 |
| GitHub 认证 | `gh auth login` 跳浏览器 | SubApp 独立运行时没人去浏览器点确认 |
| Token 过期 | API 调不通，日志里报 401 | 用户发现时 SubApp 已静默失败半天 |
| 多 SubApp | 每个 SubApp 各自依赖用户提前设好的全局 env | 无法隔离，无法一个 App 用一套凭证 |

**目标：SubApp 丢出去就能自己跑，首次引导一次，后续全自主。**

---

## 二、总体设计

```
┌──────────────────────────────────────────────────────────────────┐
│                      SubApp 配置层                               │
│  subapp.yaml:                                                    │
│    credentials:                  ← 声明需要什么凭证              │
│      - id: github_pat                                           │
│        type: github_token                                       │
│        scopes: [repo, workflow]                                 │
│      - id: deepseek_api                                         │
│        type: api_key                                            │
├──────────────────────────────────────────────────────────────────┤
│                      DSNEngine (引擎层)                          │
│  初始化时:                                                       │
│    1. 读 SubAppConfig.credentials                               │
│    2. 交给 CredentialProvider 去匹配/获取                        │
│    3. 注入到 ModelClient / Skill 工具实例                        │
├──────────────────────────────────────────────────────────────────┤
│                   CredentialProvider (凭证层)                     │
│                                                                  │
│  匹配优先级（逐级回退）:                                         │
│    CLI --env 参数                                                │
│      → 环境变量 (os.environ)                                     │
│        → 加密 secrets 文件 (~/.dsn/secrets.yaml)                 │
│          → 系统 Keyring (Windows/macOS/Linux)                    │
│            → 引导流程 (首次弹交互)                               │
│                                                                  │
│  后端:  env | file | keyring | headless_oauth | bootstrap        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、需新增 / 改动的模块

### 3.1 `credentials.py` — 凭证提供者（新增）

核心类：`CredentialProvider`

```python
class CredentialProvider:
    """统一凭证入口，SubApp 不关心来源"""

    def __init__(self, backends: list[str] = None):
        """
        backends 优先级顺序:
          ["env", "file", "keyring"]   ← 默认
        支持:
          "env"     — 从 os.environ 读
          "file"    — 从 ~/.dsn/secrets.yaml 读（AES 加密）
          "keyring" — 从系统凭证管理器读
        """

    def get(self, credential_id: str) -> str | None:
        """按优先级依次查找，返回第一个命中的值"""

    def set(self, credential_id: str, value: str):
        """写入持久化后端（file + keyring）"""

    def list_required(self, config: SubAppConfig) -> list[CredentialDecl]:
        """从 SubAppConfig 中提取声明的凭证清单"""

    def bootstrap(self, config: SubAppConfig) -> bool:
        """
        首次引导流程（交互式）:
        1. 列出所有缺失的凭证
        2. 逐个提示用户输入 / 发起 OAuth Device Flow
        3. 收集完毕后持久化保存
        返回: 是否全部就绪
        """

    def check_all(self, config: SubAppConfig) -> dict[str, bool]:
        """检查所有声明凭证是否可用 → {id: True/False}"""
```

#### 加密存储格式 (`~/.dsn/secrets.yaml`)

```yaml
# 主密钥: DSN_MASTER_KEY 环境变量 (AES-256-GCM)
# 若未设置 DSN_MASTER_KEY，首次引导时自动生成并提示用户保存

secrets:
  deepseek_api: "enc:aes256gcm:base64ciphertext..."
  github_pat: "enc:aes256gcm:base64ciphertext..."

meta:
  created: "2026-05-23T..."
  provider: "dsn-credential-provider"
```

#### CredentialDecl 数据类

```python
@dataclass
class CredentialDecl:
    id: str              # "github_pat"
    type: str            # "api_key" | "github_token" | "oauth2_device" | "oauth2_client"
    env: str = ""        # 对应环境变量名 "GITHUB_TOKEN"
    scopes: list = []    # GitHub: [repo, workflow]
    description: str = "" # 给用户看的说明
    required: bool = True
```

### 3.2 `subapp_loader.py` 改动

`SubAppConfig` 新增字段：

```python
@dataclass
class SubAppConfig:
    # ... 现有字段 ...
    credentials: list[CredentialDecl] = field(default_factory=list)
```

`subapp.yaml` 示例片段：

```yaml
credentials:
  - id: deepseek_api
    type: api_key
    env: DEEPSEEK_API_KEY
    description: "DeepSeek API 密钥 (从 platform.deepseek.com 获取)"
  - id: github_pat
    type: github_token
    env: GITHUB_TOKEN
    scopes: [repo, workflow]
    description: "GitHub Personal Access Token (需 repo + workflow 权限)"
```

### 3.3 `engine.py` 改动

初始化中增加凭证注入：

```python
class DSNEngine:
    def __init__(self, subapp_path: str | None = None):
        # ... 现有初始化 ...
        self._cred_provider = CredentialProvider()
        self._init_credentials()

    def _init_credentials(self):
        if not self._cfg or not self._cfg.credentials:
            return
        # 检查凭证可用性
        missing = [c.id for c, ok in self._cred_provider.check_all(self._cfg).items() if not ok]
        if missing:
            # 自动进入引导（--bootstrap 模式）或报错退出
            self._logger.warning("凭证缺失: %s，请运行 --bootstrap", missing)

    def _create_model_client(self):
        api_key = self._cred_provider.get("deepseek_api") or self._cfg.model_api_key
        # ... 创建客户端时使用从 provider 拿到的 key ...

    def bootstrap(self):
        """运行首次凭证引导"""
        return self._cred_provider.bootstrap(self._cfg)
```

Skill 注入方式（`skills/registry.py` 改动）：工具类实例化时注入环境变量：

```python
# registry.py — 注册技能时设置环境变量
class SkillRegistry:
    def __init__(self, cred_provider: CredentialProvider = None):
        self._cred_provider = cred_provider

    def register_skill(self, skill):
        # ... 现有逻辑 ...
        # 将凭证作为环境变量注入到工具进程可见的上下文
        if self._cred_provider:
            for cred_id in skill.requires_creds:
                token = self._cred_provider.get(cred_id)
                if token:
                    os.environ[cred_id.upper()] = token
```

### 3.4 `skills/loader.py` 改动

`Skill` 数据类新增字段：

```python
@dataclass
class Skill:
    # ... 现有字段 ...
    requires_creds: list[str] = field(default_factory=list)  # ["github_pat", ...]
```

从 `skill.yaml` 解析：

```yaml
# skills/github_pr/skill.yaml
name: github_pr
requires_creds:
  - github_pat
```

---

## 四、Headless OAuth 流程

标准 OAuth2 需要浏览器回调，不适合无人值守。两种方案：

### 方案 A：Device Flow（推荐）

用于 GitHub / GitLab 等支持 Device Flow 的服务：

```
1. SubApp 启动
2. CredentialProvider 发现 github_pat 缺失
3. 调用 GitHub Device Flow API:
   POST https://github.com/login/device/code
4. 获得: { device_code, user_code, verification_uri }
5. 打印: "请访问 https://github.com/login/device 输入代码: XXXX-XXXX"
6. 轮询 POST /login/oauth/access_token (用 device_code)
7. 用户第一次在网页确认后，轮询拿到 access_token
8. 持久化保存 token，后续不再需要交互
```

代码骨架：

```python
class DeviceFlowAuth:
    """GitHub Device Flow 自动授权"""

    DEVICE_CODE_URL = "https://github.com/login/device/code"
    TOKEN_URL = "https://github.com/login/oauth/access_token"
    CLIENT_ID = "从 DSN-exp 的 GitHub App 注册获取"

    def start_flow(self) -> dict:
        """发起 Device Flow，返回 {user_code, verification_uri}"""

    def poll_token(self, device_code: str, timeout: int = 300) -> str | None:
        """轮询等待用户确认，返回 access_token 或 None"""

    def get_token(self) -> str:
        """全流程：发起 → 提示用户 → 轮询 → 返回 token"""
```

### 方案 B：Fine-grained PAT（更简单）

社区 SubApp 作者直接生成 PAT，写进 subapp 的文档：

```
# self_evolution/README.md
## 凭证要求
1. 生成 GitHub Fine-grained PAT: Settings → Developer settings → PAT → Fine-grained tokens
2. 权限: Contents (Read & Write) + Pull requests (Read & Write)
3. 导出: export GITHUB_TOKEN=github_pat_xxx
4. 启动: python entry.py
```

适用场景：用户信任这个 SubApp 且愿意手动生成一次 token。

两种方案共存：引导时给用户选择。

---

## 五、凭证刷新 & 容错

### 5.1 过期检测

```python
class CredentialProvider:
    def _mark_invalid(self, credential_id: str):
        """API 返回 401/403 时调用，标记凭证不可用"""
        self._invalid_cache[credential_id] = time.time()

    def _on_auth_failure(self, credential_id: str, error_info: dict):
        """认证失败时的处理策略"""
        self._mark_invalid(credential_id)
        # 尝试从备用源获取
        fallback = self.get(credential_id, skip_backend=["file"])
        if fallback:
            return fallback
        # 触发通知
        self._notify(credential_id, error_info)
        raise CredentialExpiredError(f"凭证 {credential_id} 已失效")
```

### 5.2 降级策略

| 场景 | 策略 |
|------|------|
| 主 API key 失效 | 尝试 `{KEY_NAME}_BACKUP` 环境变量 |
| GitHub token 失效 | 如果存了 refresh_token，尝试刷新；否则标记需要重新引导 |
| secrets 文件损坏 | 回退到 env / keyring，同时告警 |
| keyring 不可用 | 回退到 env / file，日志记录 |

### 5.3 通知渠道

```python
class NotificationChannel(ABC):
    """凭证异常通知基类"""
    def send(self, message: str, level: str = "error"): ...

class LogNotification(NotificationChannel):
    """日志通知（默认，永远可用）"""

class WebhookNotification(NotificationChannel):
    """Webhook 通知（企业微信 / Slack / Discord）"""

class DesktopNotification(NotificationChannel):
    """系统桌面通知（plyer / notify-send）"""
```

---

## 六、安全边界

```
┌─────────────────────────────────────────────────────┐
│  SubApp 代码 (只读配置 + skills/)                    │
│  不直接持有凭证，通过引擎注入                         │
│  ├─ skill.yaml: requires_creds: [github_pat]         │
│  └─ tools/*.py 里 os.environ["GITHUB_TOKEN"] 读取    │
│     或 construct 注入 access_token                    │
├─────────────────────────────────────────────────────┤
│  DSNEngine                                          │
│  从 CredentialProvider 拿凭证，注入到下游             │
│  自己不在内存中长期缓存明文（用完即弃）               │
├─────────────────────────────────────────────────────┤
│  CredentialProvider                                 │
│  管理 secrets 文件的加密 / 解密                      │
│  主密钥 DSN_MASTER_KEY 仅在环境变量，不落盘           │
├─────────────────────────────────────────────────────┤
│  存储后端                                           │
│  ~/.dsn/secrets.yaml    ← AES-256-GCM 加密          │
│  系统 Keyring           ← 平台原生加密               │
│  环境变量               ← 进程内存                   │
└─────────────────────────────────────────────────────┘
```

**铁律：**
- SubApp 代码中 **绝不出现** 明文密钥
- 主密钥 `DSN_MASTER_KEY` 只存在于环境变量，不落盘，不提交
- 加密文件的内容即使泄露，没有主密钥也无法解密
- 凭证在内存中的生命周期尽量短 —— 每次 API 调用前获取，用完即释放引用

---

## 七、首次引导流程

```
$ python entry.py --bootstrap

╔══════════════════════════════════════════════╗
║  DSN-exp SubApp 凭证引导                     ║
║  SubApp: self_evolution v1.0.0              ║
╚══════════════════════════════════════════════╝

  此 SubApp 需要以下凭证:

  [1] DeepSeek API Key
      用途: AI 模型调用
      获取: https://platform.deepseek.com → API Keys
      状态: ✗ 未设置

  [2] GitHub PAT
      用途: 仓库代码读写 + PR 创建
      所需权限: repo, workflow
      状态: ✗ 未设置

  选择操作:
  (1) 逐一输入凭证
  (2) GitHub 用 Device Flow 自动获取
  (3) 从文件导入 (JSON/YAML)
  (c) 取消，稍后再配置

> 2

  ── 正在发起 GitHub Device Flow ──
  ✓ 已获取设备码

  ┌─────────────────────────────────────────────┐
  │  请访问: https://github.com/login/device    │
  │  输入代码: DSNX-XXXX                        │
  │                                             │
  │  等待确认中... (最多 5 分钟)                │
  └─────────────────────────────────────────────┘
  ... 轮询 ...
  ✓ GitHub 认证完成!

  [1] DeepSeek API Key → 还未设置
  请输入 (直接回车跳过): sk-xxxxxxxxxxxxxxxx

  ╔══════════════════════════════════════════════╗
  ║  ✓ 所有凭证已就绪                            ║
  ║  已保存到 ~/.dsn/secrets.yaml (加密)         ║
  ║  下次启动将自动读取                          ║
  ╚══════════════════════════════════════════════╝
```

---

## 八、实现优先级 & 路线

### Phase 1 — 最小闭环（2-3 天）

| 任务 | 产出 |
|------|------|
| `credentials.py` → `CredentialProvider` 基础类 | 支持 env + YAML 文件两个后端 |
| `subapp_loader.py` → `SubAppConfig.credentials` | YAML 声明解析 |
| `engine.py` → `_init_credentials()` 注入 | 引擎初始化时读取并注入 env |
| `skills/loader.py` → `Skill.requires_creds` | Skill YAML 声明 |
| `github_pr` skill → 改为读 `GITHUB_TOKEN` env | 工具类不再依赖 `gh auth` |

**Phase 1 结束后，SubApp 只需：**
```bash
export DEEPSEEK_API_KEY=sk-xxx
export GITHUB_TOKEN=ghp_xxx
python subapps/self_evolution/entry.py
```
零交互。

### Phase 2 — 加密存储 & 引导（2-3 天）

| 任务 | 产出 |
|------|------|
| `credentials.py` → AES 加密存储 | `~/.dsn/secrets.yaml` |
| `credentials.py` → `bootstrap()` 引导流程 | 交互式凭证收集 |
| `credentials.py` → `check_all()` 可用性检查 | 启动时自动校验 |
| `entry.py` 公共 `--bootstrap` 参数 | 所有 SubApp 复用 |

### Phase 3 — Headless OAuth & 容错（2-3 天）

| 任务 | 产出 |
|------|------|
| `credentials.py` → `DeviceFlowAuth` | GitHub Device Flow |
| `credentials.py` → `_on_auth_failure()` | 过期检测 + 降级 |
| `credentials.py` → `NotificationChannel` | 凭证失效通知 |
| 系统 Keyring 后端 | Windows / macOS / Linux |

---

## 九、不做的

- ~~托管凭证服务 / SaaS~~ — SubApp 本地跑，不上传凭证
- ~~OAuth2 Authorization Code Flow~~ — 需要浏览器回调，和无人值守矛盾
- ~~凭证多租户~~ — 先单用户，多用户是以后的事
- ~~分布式凭证同步~~ — 不需要，SubApp 跑在单机上

---

## 十、文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `credentials.py` | **新增** | CredentialProvider + DeviceFlowAuth + 加密存储 |
| `subapp_loader.py` | 改动 | SubAppConfig 加 credentials 字段 |
| `engine.py` | 改动 | 初始化注入凭证，加 `--bootstrap` 支持 |
| `skills/loader.py` | 改动 | Skill 加 requires_creds 字段 |
| `skills/registry.py` | 改动 | register_skill 时注入凭证 env |
| `subapps/self_evolution/entry.py` | 改动 | 支持 `--bootstrap` 参数 |
| `subapps/self_evolution/skills/github_pr/skill.yaml` | 改动 | 加 `requires_creds: [github_pat]` |
| `docs/guide-credentials.md` | 新增 | 凭证系统使用文档（实现后写） |
