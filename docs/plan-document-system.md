# DSN-exp Document 子系统 — 策划案

> 文档录入 & OCR & HMD 处理系统。两部分：打印机/扫描仪控制 + 文档理解管线。

---

## 1. 总体架构

```
document/
├── __init__.py               # 导出
├── printer.py                # PrinterTool（CUPS 打印）
├── scanner.py                # ScannerTool（scanimage 扫描）
├── hmd.py                    # HmdClient（2md API 客户端 + .hmd 读写）
└── doc_processor.py          # 文档处理管线（分类→OCR→HMD合包）

skills/builtin/document/
├── skill.yaml                # 统一 document 技能定义
├── prompts/instruction.md    # AI 使用说明
└── tools/
    ├── scanner.py            # ScannerTool 技能 wrapper
    ├── printer.py            # PrinterTool 技能 wrapper
    └── doc_tools.py          # process_scan / read_hmd 技能 wrapper
```

### 依赖关系

```
document skill (skills/builtin/document/)
  ├── scanner.py      → scanimage (SANE)
  ├── printer.py      → CUPS
  ├── doc_tools.py    → DocProcessor + HmdClient
  └── doc_processor.py → 分类→OCR→2md→HMD → workspace/<user>/documents/
```

---

## 2. 基础设施变更

### 2.1 配置新增 (`config.py`)

```python
# ==================== OCR 文档处理 ====================
OCR_MODEL = _env("OCR_MODEL", "deepseek-ocr")           # OCR 模型名
OCR_BASE_URL = _env("OCR_BASE_URL", "http://localhost:4502")  # OCR 专用 LMStudio 实例
OCR_UNLOAD_AFTER_USE = _env("OCR_UNLOAD_AFTER_USE", "true").lower() == "true"

# ==================== 2md 文档解析 API ====================
TWO_MD_API = _env("TWO_MD_API", "http://localhost:8000")  # 2md 转换服务地址
```

### 2.2 OCRModel (`models.py` 新增类)

```python
class OCRModel:
    """
    deepseek-ocr 客户端。纯视觉→markdown 模型。

    行为:
    - 初始化时自动连接 LMStudio 实例
    - 若模型未加载 → 自动加载
    - 输入: 图片 base64 (data_url)，无文本提示
    - 输出: 图片对应的 markdown 文本
    - 支持 OCR_UNLOAD_AFTER_USE 自动卸载
    """

    def __init__(self, base_url: str = None, model_name: str = None):
        self.base_url = base_url or Config.OCR_BASE_URL
        self.model_name = model_name or Config.OCR_MODEL
        self._http_session = requests.Session()
        self._load_lock = threading.Lock()
        self._model_ready = threading.Event()

    def ocr(self, data_url: str) -> str:
        """对单张图片执行 OCR，返回 markdown 文本"""

    def ocr_batch(self, images: list[dict]) -> list[dict]:
        """批量 OCR，每条: {filename, data_url} → {filename, markdown}"""

    def _ensure_loaded(self) -> bool:
        """自动加载模型"""

    def unload(self) -> bool:
        """卸载模型"""

    @staticmethod
    def unload_model(base_url: str, model_name: str) -> bool:
        """静态方法：向 LMStudio 发送 unload 请求"""
        # POST {base_url}/api/v1/models/unload
        # Body: {"instance_id": "model_name"}
        # Response: 模型名即成功
```

### 2.3 unload 通用方法 (`models.py`)

```python
def _unload_lmstudio_model(base_url: str, model_name: str) -> bool:
    """卸载 LMStudio 模型，成功返回 True"""
    try:
        resp = requests.post(
            f"{base_url}/api/v1/models/unload",
            json={"instance_id": model_name},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            # LMStudio 返回模型名表示卸载成功
            if data.get("instance_id") == model_name or data.get("model") == model_name:
                return True
        return False
    except Exception:
        return False
```

### 2.4 LMStudioChat.describe_images — 多图支持

```python
class LMStudioChat:
    def describe_images(self, images: list[dict], prompt: str = None) -> str:
        """
        一次传入多张图片，返回合并描述表。

        :param images: [{"filename": "page1.png", "data_url": "data:image/png;base64,..."}, ...]
        :param prompt: 描述提示词
        :return: 格式化表格文本，包含原始文件名和描述
        """
        # 将多张图片打包到单次请求的 content 数组中
        # 回复格式:
        # | 文件名 | 描述 |
        # |--------|------|
        # | page1.png | 描述... |
        # | page2.png | 描述... |
```

### 2.5 LMStudioChat.describe_image 增强

原有方法仅返回纯描述文本，现需增加 **分类判断** 能力 —— 区分纯文档 vs 非文档图片（风景、照片等）。

```python
class LMStudioChat:
    def classify_image(self, data_url: str) -> str:
        """
        判断图片类型。返回:
        - "document" — 纯文档（试卷、论文、合同等印刷/手写文本）
        - "photo" — 非文档图片（风景、人物、实物照片等）
        - "mixed"  — 混合（文档含嵌入图片）
        """
```

---

## 3. document 子系统模块

### 3.1 `document/scanner.py` — ScannerTool

基于 `tests/test_printer.py:18-51` 的 `get_scanner_device()` 和 `scan_to_file()` 改造。

```python
class ScannerTool:
    """扫描仪控制工具。底层调用 scanimage (SANE)。"""

    @staticmethod
    def list_scanners() -> list[dict]:
        """返回 [{device, description}]"""

    @staticmethod
    def scan(
        device: str = None,          # 自动发现第一个
        output_dir: str = None,      # 默认 workspace/<user>/uploads/
        resolution: int = 300,
        mode: str = "Color",
        format: str = "png",
        page_count: int = 1,         # 多页扫描
    ) -> list[dict]:
        """返回 [{filename, filepath, size, width, height}]"""
```

### 3.2 `document/printer.py` — PrinterTool

基于 `tests/test_printer.py:79-98` 的 `print_file()` 改造。

```python
class PrinterTool:
    """打印机控制工具。底层调用 pycups (CUPS API)。"""

    @staticmethod
    def list_printers() -> list[dict]:
        """返回 [{name, state, description}]"""

    @staticmethod
    def print_file(
        file_path: str,
        printer_name: str = None,    # 默认第一台
        copies: int = 1,
        page_range: str = None,      # "1" / "1-3" / "1,3,5"
        options: dict = None,
    ) -> dict:
        """返回 {success, job_id, printer}"""
```

### 3.3 OCRModel — 直接使用 (`models.py`)

OCR 处理由 `models.py:OCRModel` 直接提供，`ocr_batch()` 内置 `OCR_UNLOAD_AFTER_USE` 判断。

### 3.4 `document/hmd.py` — HmdClient

基于 `temp/2hmd.py` 改造，封装 2md API 调用。

```python
class HmdClient:
    """HMD 文档客户端。调用 2md API 将 PDF/PNG 转为结构化 HMD 包。"""

    def __init__(self, server_url: str = None):
        self.server_url = server_url or Config.TWO_MD_API

    def convert(self, file_path: str, dpi: int = 200, pages: str = None) -> dict:
        """
        同步调用 /convert 接口。
        返回: {
            basename: str,
            markdown: str,        # 即 mdB — 布局版
            pages: [dict],        # page_info + layout_dets
            images: {fname: b64}, # 裁剪出的图表 PNG
        }
        """

    def save_hmd(self, api_result: dict, mdA_list: list[dict],
                  output_dir: str) -> str:
        """
        合并 OCR 输出 (mdA) 与 2md 输出 (mdB/json/images) → 生成 .hmd zip 包。

        .hmd 文件结构:
          1.hmd (zip)
          ├── 1.mdA       ← deepseek-ocr 纯文本输出（合并所有页）
          ├── 1.mdB       ← 2md API 布局 markdown
          ├── 1.json      ← 2md API 页面布局元数据（不含 images base64）
          ├── img_001.png ← 2md 裁剪出的图表
          ├── img_002.png ← ...
          └── ...
        """

    @staticmethod
    def read_hmd(hmd_path: str) -> dict:
        """
        解包 .hmd 文件，返回结构化数据供 AI 读取。
        返回: {
            mda: str,           # OCR 文本
            mdb: str,           # 布局 markdown
            json: dict,         # 页面元数据
            images: [{filename, filepath}],  # 图片引用
        }
        """
```

### 3.5 `document/doc_processor.py` — 文档处理管线

核心管线，串联扫描→分类→OCR→HMD→合并。

```python
class DocProcessor:
    """
    文档处理管线。

    流程:
      Step 0: 扫描 → 获取 PNG 列表
      Step 1: 对每张图用 vision 分类 (document / photo / mixed)
      Step 2: 纯文档 → deepseek-ocr → mdA
              非文档 → vision describe → 直接给 AI
      Step 3: 调用 2md API → 获取 mdB + json + 关联图表
      Step 4: 合并 mdA + mdB + json + 图表 → 打包 .hmd
      Step 5: .hmd 存入 workspace/<user>/documents/
      Step 6: 生成 AI 可读的反馈文本
    """

    def __init__(self, vision_plugin=None, ocr_model=None, hmd_client=None):
        ...

    def process_scan(self, user_id: int, scanned_images: list[dict]) -> dict:
        """
        完整处理一趟扫描。
        :param scanned_images: [{filename, filepath, data_url}, ...]
        :return: {hmd_path, feedback_text, documents: [...], photos: [...]}
        """
```

#### 详细流程

```
用户说"帮我录入文档"
  ↓
1. AI 检测到"扫描"关键词 → 调用 `document.list_scanners`
2. AI 引导: "把文档放在扫描台上"
3. 用户确认 → AI 调用 `document.scan` → 获取 [page_001.png, ...]
4. AI 调用 `document.process_scan` → 分类→OCR→2md→打包 .hmd → 返回反馈文本
5. 反馈文本注入主模型上下文 → AI 理解文档内容
  ↓
━━━━━━━━━━ Step 0: 分类判断 ━━━━━━━━━━
对每张图调用 vision_model.classify_image(page_n.png):
  - 纯文档 → 进入 Step 1
  - 照片 → 记录到 photos 列表（直接给 vision describe）
  - 混合 → 既做 OCR 也存原始描述
  ↓
━━━━━━━━━━ Step 1: deepseek-ocr ━━━━━━━━
OCRModel.ocr_batch(document_images)
  → [{filename: "page_001.png", markdown: "## 第一章\n..."}, ...]
  OCR 完成后检查 OCR_UNLOAD_AFTER_USE，若 true 则 unload
  ↓
━━━━━━━━━━ Step 2: 2md API ━━━━━━━━━━━
HmdClient.convert(scanned_file_path)
  → {basename, markdown (mdB), pages, images}
  ↓
━━━━━━━━━━ Step 3: 合并 & 打包 ━━━━━━━━
HmdClient.save_hmd(api_result, mdA_results, output_dir)
  → workspace/Darkstar/documents/20260620_143021.hmd
  ↓
━━━━━━━━━━ Step 4: 反馈 AI ━━━━━━━━━━━
生成结构化反馈文本:
  合并 mdA (文本) + mdB (布局) + json (元数据)
  如果有照片 → 附加 vision 描述
  注入到 ctx.message 供主模型理解
```

### 3.6 `document/document_plugin.py` — 管线插件

```python
class DocumentPlugin(Plugin):
    """
    文档录入插件。

    PRE_PROCESS (priority=24):
    - 检测用户消息是否含"扫描"/"录入"/"文档"/"试卷"等关键词
    - 若有：接管流程，引导用户扫描→分类→OCR→HMD→存储
    - 将处理结果注入 ctx.message

    配置:
    - 依赖 ScannerTool + DocProcessor
    """
    name = "document"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 24
```

---

## 4. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `config.py` | 修改 +8 行 | `OCR_MODEL`, `OCR_BASE_URL`, `OCR_UNLOAD_AFTER_USE`, `TWO_MD_API` |
| `.env.example` | 修改 +4 行 | 同上注释 |
| `models.py` | 修改 +120 行 | `OCRModel` 类, `_unload_lmstudio_model()`, `LMStudioChat.describe_images()`, `LMStudioChat.classify_image()` |
| `tests/test_printer.py` | 修改 | 恢复正确的 test 路径（之前被改） |
| `document/__init__.py` | **新建** | |
| `document/scanner.py` | **新建** | ScannerTool |
| `document/printer.py` | **新建** | PrinterTool |
| `document/hmd.py` | **新建** | HmdClient + .hmd 读写 |
| `document/doc_processor.py` | **新建** | 文档处理管线 |
| `skills/builtin/document/skill.yaml` | **新建** | 统一 document 技能 |
| `skills/builtin/document/tools/scanner.py` | **新建** | 扫描仪技能 wrapper |
| `skills/builtin/document/tools/printer.py` | **新建** | 打印机技能 wrapper |
| `skills/builtin/document/tools/doc_tools.py` | **新建** | process_scan + read_hmd wrapper |
| `skills/builtin/document/prompts/instruction.md` | **新建** | AI 使用说明 |
| `prompt/prompts/capabilities/document_scanning.md` | **新建** | 系统能力描述 |
| `workspace.py` | 修改 +2 行 | `user_documents_dir()` 便捷方法 |
| `engine.py` | 无修改 | 已删除 DocumentPlugin 注册 |

---

## 5. 实施顺序

### Phase A: 基础设施 (先改 models.py + config.py)
1. `config.py`: 新增 4 个配置项
2. `models.py`: 新增 `_unload_lmstudio_model()`
3. `models.py`: 新增 `OCRModel` 类
4. `models.py`: `LMStudioChat.describe_images()` 多图支持
5. `models.py`: `LMStudioChat.classify_image()` 分类能力

### Phase B: document 子模块 (平行构建)
6. `document/scanner.py`: ScannerTool
7. `document/printer.py`: PrinterTool
8. `document/hmd.py`: HmdClient
9. `document/doc_processor.py`: 文档处理管线
10. `workspace.py`: 新增 `user_documents_dir()`

### Phase C: 技能注册
11. `skills/builtin/document/skill.yaml`: 统一 document 技能
12. `skills/builtin/document/tools/`: scanner/printer/doc_tools wrapper
13. `prompt/prompts/capabilities/document_scanning.md`: 能力描述

---

## 6. .hmd 格式规格

```
<basename>.hmd  → zip 压缩包
├── <basename>.mdA   ← 所有页 OCR 文本合并 (Markdown)
├── <basename>.mdB   ← 2md API 布局版 (Markdown，含图片占位)
├── <basename>.json  ← 页面元数据 (不含 images base64)
├── img_001.png      ← 2md 裁剪出的图/表
├── img_002.png
└── ...
```

### AI 读取 .hmd 时的处理

1. 解压 zip
2. 所有 PNG → vision describe → 描述表（文件名 + 描述）
3. 合并: `.mdA` (OCR纯文) + `.mdB` (布局md) + 描述表 + `.json` (元数据)
4. 拼接后注入 system prompt 或作为上下文发送给主模型

---

*策划案 v1.0*
