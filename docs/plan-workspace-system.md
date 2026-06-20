# DSN-exp 工作区系统 — 策划案

> 将分散的 `~/dsn_workspace` 提升为全局工作区系统，作为 AI 的专属沙盒空间，
> 也是未来文档系统（图书馆）和 Obsidian 星图笔记系统的基础设施。

---

## 1. 动机

### 1.1 现状问题

| # | 问题 | 说明 |
|---|------|------|
| 1 | 工作区路径分散 | `git_tool.py` 硬编码 `~/dsn_workspace`，`tasks.py` 的 shell cwd 为 `~`，`file_ops.py` 以项目根为 base，三者互不统一 |
| 2 | 无用户隔离 | 多用户场景下所有 AI 操作混在同一目录，无法区分用户数据 |
| 3 | 无配置入口 | 没有 `WORKSPACE_DIR` 这样的配置键，改路径只能改代码 |
| 4 | 非系统组件 | 工作区只是一个路径常量，没有对应的管理对象，各模块各自为政 |
| 5 | 阻碍上层建设 | 文档系统、Obsidian 笔记系统都需要一个"AI 专属空间"作为锚点 |

### 1.2 目标

- 统一工作区位置：`.dsn/workspace/`
- 按用户隔离：`.dsn/workspace/<显示名>/`
- 同一用户跨聊天共享文件夹
- 新增可配置的 `WORKSPACE_DIR` 配置键
- 插件/技能/任务执行默认以此为工作目录
- AI 笔记保存至 `workspace/notebook/`
- **不限制** AI 对全局文件系统的访问（工作区是默认位置，不是沙盒）

---

## 2. 总体设计

### 2.1 架构

```
.dsn/workspace/                          ← 工作区根目录 (可配置)
├── 张三/                                ← 用户隔离目录 (display_name)
│   ├── repos/                           ← GitHub 克隆仓库
│   │   ├── DSN-exp/
│   │   └── some-other-repo/
│   ├── notebook/                        ← AI 笔记 (观察日记/学习笔记)
│   │   ├── 2026-06-20.md
│   │   └── ...
│   ├── uploads/                         ← 用户上传/扫描的文件
│   └── projects/                        ← AI 自主创建的项目文件
├── 李四/
│   └── ...

全局文件系统 (不受限):
  ~/Desktop/
  ~/Documents/
  /mnt/data/
  ...  ← AI 仍然可以读写这些路径
```

### 2.2 新增模块

```
workspace.py              ← WorkspaceManager 单例
├── resolve_workspace_root()     ← 从 Config 获取工作区根路径
├── user_dir(uid)           ← 获取指定用户的目录
├── user_repos_dir(uid)     ← repos/ 子目录
├── user_notebook_dir(uid)  ← notebook/ 子目录
└── ensure_user_dir(uid)    ← 确保用户目录存在
```

### 2.3 配置变更 (`config.py`)

```python
# ==================== 工作区系统 ====================
WORKSPACE_DIR = _env("WORKSPACE_DIR", ".dsn/workspace")  # 相对项目根 or 绝对路径
```

### 2.4 依赖关系

```
WorkspaceManager
  ├── 被 GitTool 引用 → 替代 ~/dsn_workspace
  ├── 被 FileOpsTool 引用 → 作为默认 base_dir
  ├── 被 TaskManager 引用 → shell/python 默认 cwd
  ├── 被 NotebookPlugin 引用 → 笔记存储位置
  ├── 被 PrinterScannerPlugin 引用 → 扫描输出位置
  └── 被未来文档系统/星图笔记系统引用
```

---

## 3. 详细设计

### 3.1 WorkspaceManager

```python
# workspace.py — 工作区管理器

class WorkspaceManager:
    """
    全局工作区管理器。单例模式，通过 get_workspace_manager() 获取。

    职责:
    - 解析工作区根路径（从 Config.WORKSPACE_DIR）
    - 为每个用户创建并管理隔离目录
    - 提供子目录 helper（repos, notebook, uploads, projects）
    - 与 Config 联动，支持运行时重载
    """

    def __init__(self, db=None):
        self._db = db
        self._root: Path | None = None

    # ── 初始化 ──

    def init(self, db=None) -> None:
        """初始化工作区根目录（启动时调用）"""
        if db:
            self._db = db
        raw = Config.WORKSPACE_DIR
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        self._root = p.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("工作区根目录: %s", self._root)

    # ── 目录解析 ──

    def user_dir(self, uid: int, display_name: str = "") -> Path:
        """
        返回用户工作区目录 (.dsn/workspace/<display_name>/)。
        优先使用 display_name，若为空则查数据库回退到 uid。
        """
        name = self._resolve_username(uid, display_name)
        d = self._root / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def user_repos_dir(self, uid: int, display_name: str = "") -> Path:
        """返回用户仓库目录 (.dsn/workspace/<name>/repos/)"""
        d = self.user_dir(uid, display_name) / "repos"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def user_notebook_dir(self, uid: int, display_name: str = "") -> Path:
        """返回用户笔记目录 (.dsn/workspace/<name>/notebook/)"""
        d = self.user_dir(uid, display_name) / "notebook"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def user_uploads_dir(self, uid: int, display_name: str = "") -> Path:
        """返回用户上传目录 (.dsn/workspace/<name>/uploads/)"""
        d = self.user_dir(uid, display_name) / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 辅助 ──

    def resolve(self, subpath: str, uid: int = 0) -> Path:
        """
        将相对路径解析为绝对路径。
        如果 subpath 是绝对路径，原样返回（不限制全局访问）。
        如果是相对路径，锚定到 user_dir(uid)。
        """
        p = Path(subpath)
        if p.is_absolute():
            return p
        if uid:
            return self.user_dir(uid) / subpath
        return self._root / subpath

    def _resolve_username(self, uid: int, display_name: str) -> str:
        if display_name:
            return self._sanitize_name(display_name)
        if self._db:
            from auth.auth_manager import AuthManager  # lazy import
            user = AuthManager(self._db).get_user(uid)
            name = user.get("display_name") or user.get("nickname", "")
            if name:
                return self._sanitize_name(name)
        return f"user_{uid}"

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """清理目录名：只保留字母数字中文下划线"""
        import re
        name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name)
        return name or "default"


# ── 全局单例访问 ──

_workspace_manager: WorkspaceManager | None = None

def get_workspace_manager() -> WorkspaceManager:
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager

def init_workspace_manager(db=None) -> WorkspaceManager:
    wm = get_workspace_manager()
    wm.init(db=db)
    return wm
```

### 3.2 配置变更

**`config.py`** — 新增工作区配置段：

```python
# ==================== 工作区系统 ====================
WORKSPACE_DIR = _env("WORKSPACE_DIR", ".dsn/workspace")
```

**`.env.example`** — 新增说明：

```bash
# 工作区目录 (相对项目根 或 绝对路径)
WORKSPACE_DIR=.dsn/workspace
```

### 3.3 启动流程变更

在 `boot.py` 或 `main.py` 的初始化阶段，新增：

```python
# 初始化工作区管理器
from workspace import init_workspace_manager
init_workspace_manager(db=chatdb)
```

### 3.4 各子系统集成

#### 3.4.1 GitTool (GitHub Skill)

**当前** (`skills/builtin/github/tools/git_tool.py`):

```python
DEFAULT_WORK_DIR = os.path.join(os.path.expanduser("~"), "dsn_workspace")
```

**改为**：

```python
from workspace import get_workspace_manager

class GitTool:
    def __init__(self, work_dir: str | None = None, uid: int = 0, display_name: str = ""):
        if work_dir:
            self._work_dir = work_dir
        else:
            wm = get_workspace_manager()
            self._work_dir = str(wm.user_repos_dir(uid, display_name))
        os.makedirs(self._work_dir, exist_ok=True)
```

`skill.yaml` 中的 clone 工具需新增 `uid` 和 `display_name` 参数传递。

#### 3.4.2 SubApp self_evolution GitHub PR Tool

**当前** (`subapps/self_evolution/skills/github_pr/tools/pr_tool.py`):

```python
self._work_dir = work_dir or os.path.join(os.path.expanduser("~"), "dsn_workspace")
```

**改为**：同上，引入 `WorkspaceManager`。

#### 3.4.3 TaskManager — Shell 执行

**当前** (`tasks.py:_action_shell`):

```python
cwd=os.path.expanduser("~"),
```

**改为**：

```python
from workspace import get_workspace_manager
wm = get_workspace_manager()
cwd = str(wm.user_dir(uid))  # uid 从 task 上下文获取
```

需要 Task 对象携带 uid 信息（目前 Task 的 params 中可能有 user_id，需规范化）。

#### 3.4.4 TaskManager — Python 执行

**当前** (`tasks.py:_action_python`):

```python
cwd=os.path.dirname(temp_file),
```

**改为**：

```python
from workspace import get_workspace_manager
wm = get_workspace_manager()
cwd = str(wm.user_dir(uid))
```

#### 3.4.5 TaskManager — 文件写入/编辑

**当前** (`tasks.py:_action_write_file`, `_action_edit_file`):

```python
if not os.path.isabs(file_path):
    file_path = os.path.join(os.path.expanduser("~"), file_path)
```

**改为**：

```python
if not os.path.isabs(file_path):
    wm = get_workspace_manager()
    file_path = str(wm.resolve(file_path, uid))
```

#### 3.4.6 FileOpsTool (file_manager Skill)

**当前** (`skills/builtin/file_manager/tools/file_ops.py`):

```python
_BASE_DIR = Path(__file__).parent.parent.parent.parent.parent  # 项目根目录

class FileOpsTool:
    def __init__(self, config=None):
        self.base_dir = Path(self.config.get("base_dir", str(_BASE_DIR)))
```

**改为**：`base_dir` 默认走工作区，但在 skill 调用时可通过参数覆盖。

不过注意：用户说"不限制AI对全局文件系统的访问"，所以 FileOpsTool 应保留允许绝对路径的能力。修改为：

```python
class FileOpsTool:
    def __init__(self, config=None):
        self.config = config or {}
        # 如果没有显式指定 base_dir，默认走工作区
        default_base = str(get_workspace_manager().user_dir(uid)) if uid else None
        self.base_dir = Path(self.config.get("base_dir", default_base or str(_BASE_DIR)))

    def _safe_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p  # 绝对路径不做限制
        return (self.base_dir / path).resolve()
```

#### 3.4.7 Notebook 笔记系统

**当前**：`NOTEBOOK_FREQUENCY` 配置项存在，但笔记存储位置未与工作区关联。

**改为**：笔记文件存储到 `workspace/<user>/notebook/`。在 `notebook/` 插件中引用 `WorkspaceManager.user_notebook_dir(uid)`。

#### 3.4.8 打印机/扫描仪

扫描输出文件默认写到 `workspace/<user>/uploads/`。

---

## 4. 实施步骤

### Step 1: 创建 WorkspaceManager <!-- 核心基础设施 -->

**文件**: `workspace.py`（新建）
**内容**: WorkspaceManager 类 + 全局单例访问函数

**涉及文件**:
- `workspace.py` — 新建

---

### Step 2: 注册配置项 <!-- 可配置化 -->

**文件**: `config.py`
**修改**: 新增 `WORKSPACE_DIR` 配置项

**涉及文件**:
- `config.py` — +3 行
- `.env.example` — +2 行

---

### Step 3: 启动时初始化 <!-- 生命周期集成 -->

**文件**: `boot.py` 或 `main.py`
**修改**: 在启动流程中加入 `init_workspace_manager(db)`

**涉及文件**:
- `main.py` / `boot.py` — +3 行

---

### Step 4: GitTool 集成 <!-- 替代 ~/dsn_workspace -->

**文件**: `skills/builtin/github/tools/git_tool.py`
**修改**: 引入 WorkspaceManager，默认克隆到 `repos/`

**涉及文件**:
- `git_tool.py` — 修改 `DEFAULT_WORK_DIR` 逻辑
- `subapps/self_evolution/skills/github_pr/tools/pr_tool.py` — 同样修改

---

### Step 5: TaskManager 集成 <!-- 默认 cwd 改到工作区 -->

**文件**: `tasks.py`
**修改**: `_action_shell`, `_action_python`, `_action_write_file`, `_action_edit_file` 的默认 cwd/path

**涉及文件**:
- `tasks.py` — 修改 4 处

---

### Step 6: FileOpsTool 集成 <!-- 默认 base_dir -->

**文件**: `skills/builtin/file_manager/tools/file_ops.py`
**修改**: 默认 base_dir 指向工作区，保留绝对路径通行

**涉及文件**:
- `file_ops.py` — 修改 `_BASE_DIR` 和 `_safe_path`

---

### Step 7: Notebook 路径对齐 <!-- 笔记存储统一 -->

**文件**: `notebook/` 相关插件
**修改**: 笔记存储路径改为 `workspace/<user>/notebook/`

**涉及文件**:
- 待定（需查看 notebook 插件的具体实现）

---

## 5. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `workspace.py` | **新建** | WorkspaceManager 单例 |
| `config.py` | 修改 +3 行 | 新增 `WORKSPACE_DIR` |
| `.env.example` | 修改 +2 行 | 注释说明 |
| `main.py` / `boot.py` | 修改 +3 行 | 启动初始化 |
| `skills/builtin/github/tools/git_tool.py` | 修改 ~10 行 | 默认工作区改为 repos/ |
| `subapps/self_evolution/skills/github_pr/tools/pr_tool.py` | 修改 ~5 行 | 同上 |
| `tasks.py` | 修改 ~8 行 | 4 处 action handler 的 cwd/path |
| `skills/builtin/file_manager/tools/file_ops.py` | 修改 ~10 行 | 默认 base_dir 可配置 |
| `plugins/builtin/notebook/` | 修改 ~5 行 | 笔记路径对齐 |

---

## 6. 注意事项

### 6.1 向后兼容

- 已有 `~/dsn_workspace` 中的仓库不会自动迁移。GitTool 第一次在新位置 clone 时才使用新路径。
- `WORKSPACE_DIR` 默认值为 `.dsn/workspace`，若不配置则自动使用此值。
- Task 的 `_action_write_file` 和 `_action_edit_file` 改变默认路径后，存量代码指定的绝对路径不受影响。

### 6.2 用户目录名变更

用户显示名改变时，旧目录不会自动清理或迁移。初次建立时以当时的 display_name 为准。

### 6.3 安全性

工作区不是沙盒。AI 仍然可以通过绝对路径访问 `/etc/passwd`、`~/Desktop` 等任意位置。工作区仅仅是一个"默认位置"。

### 6.4 与未来系统的关系

```
工作区 (workspace)
  ├── repos/        ← GitHub 克隆仓库
  ├── notebook/     ← AI 笔记
  ├── uploads/      ← 扫描/上传
  ├── projects/     ← AI 项目
  ├── documents/    ← (未来) 文档系统 / 图书馆
  └── obsidian/     ← (未来) Obsidian 星图笔记
```

---

*策划案 v1.0*
