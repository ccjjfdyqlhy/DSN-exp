---
name: document_instruction
category: skills
priority: 65
---

## 文档处理技能

你可以通过 `<tool>` 标签控制物理扫描仪和打印机。

### 题库入库扫描（强制流程：scan → scan_import_questions，禁止拆步）

当用户要把纸质试卷/题目录入题库（"录入题库""存入题库""扫描试卷入库""导入题库"等）时，**必须且只能**走下面这条原子管线：

1. `document.list_scanners` 确认扫描仪可用
2. 引导用户把试卷放上扫描台
3. `document.scan`（默认 300 DPI，返回 PNG 文件列表 `files`）
4. `document.scan_import_questions`（参数：`scanned_files`=上一步返回的 `files`；`subject` **留空即可**）——此工具**内部由视觉模型全权处理**：OCR → 视觉模型自动识别科目+题目原文+图片描述+答案解析（输出完整 JSON）→ 批量入库，一步到位，**主模型不接触题目内容**

**科目不需要你判断**：`subject` 参数可空，视觉模型会从图片内容自动识别科目。

**严禁手动拆步 / 绕圈子**：
- ❌ 不要先调 `describe_image` 去"确认科目/看内容"——科目由 `scan_import_questions` 内部的视觉模型自动识别
- ❌ 不要手动切换/加载 OCR 模型——OCR 由 `scan_import_questions` 内部的 OCRModel 完成
- ❌ 不要把 OCR 文本单独丢给视觉模型做结构化——`scan_import_questions` 内部会把图片+OCR 一起合成 JSON
- ❌ 不要用 `process_scan` / `process_last_scan` / `read_hmd` 走通用文档 OCR 路径来入库（那是阅读文档用的，不是题库入库）
- ❌ 不要在 `scan_import_questions` 之外再叠加任何"确认题目"的步骤

**失败处理**：
- `scan_import_questions` 返回的 `page_errors` / `import_errors` 是正常的逐页容错结果，把失败项报告给用户即可，**不要因此重扫**
- 若 `scan_import_questions` 调用超时/失败，**先重试该工具本身**，不要重扫
- 已生成的 PNG 保存在 uploads 目录，文件不会因模型超时而损坏；只有确认 uploads 中确实没有 PNG 时才重新 `scan`

### 扫描

**列出扫描仪：**
<tool>
{
  "skill": "document",
  "tool": "list_scanners",
  "params": {}
}
</tool>

**执行扫描：**
<tool>
{
  "skill": "document",
  "tool": "scan",
  "params": {}
}
</tool>

高分辨率：
<tool>
{
  "skill": "document",
  "tool": "scan",
  "params": {"resolution": 600, "mode": "Color"}
}
</tool>

### 打印

**列出打印机：**
<tool>
{
  "skill": "document",
  "tool": "list_printers",
  "params": {}
}
</tool>

**打印文件：**
<tool>
{
  "skill": "document",
  "tool": "print_file",
  "params": {"file_path": "/path/to/doc.pdf"}
}
</tool>

指定页码：
<tool>
{
  "skill": "document",
  "tool": "print_file",
  "params": {"file_path": "/path/to/doc.pdf", "page_range": "1", "copies": 2}
}
</tool>

### 图片分析
你可以分析本地图片的内容（截图、照片、扫描件等）。

**分析图片：**
<tool>
{
  "skill": "document",
  "tool": "describe_image",
  "params": {
    "file_path": "~/Desktop/图片3.png"
  }
}
</tool>

### 流程
- **扫描后一键入库**（强制）：`list_scanners` → `scan` → `scan_import_questions`（见上方「题库入库扫描」）
- **通用文档 OCR**（阅读用途，非入库）：`scan` → `process_last_scan` / `process_scan`（生成 .hmd 供阅读）
- 用户说扫描：先 `list_scanners` → 引导放文档 → 按用户目的分流：录入题库走 `scan_import_questions`，仅阅读走 `process_last_scan`
- 用户说打印：先 `list_printers` → 确认路径 → `print_file`
- 用户说"看看这张图""分析这张图片"：用 `describe_image` 分析图片内容
- 查看文档：`process_scan` 返回的 `feedback_text` 包含完整文字；也可用 `workspace_file` 读取 `.md` 文件
- 找文件：用 `workspace_file` 的 `find` 子命令递归搜索，如 `{"tool": "find", "path": "*.png"}`

### 文档处理

**方式一（推荐）——自动处理最近一次扫描：**
<tool>
{
  "skill": "document",
  "tool": "process_last_scan",
  "params": {}
}
</tool>
自动查找 uploads 目录中最新的 PNG 文件，零参数直接调用。

**方式二——手动指定文件路径列表（支持简单字符串路径）：**
<tool>
{
  "skill": "document",
  "tool": "process_scan",
  "params": {
    "scanned_files": ["/path/to/scan_1.png", "/path/to/scan_2.png"]
  }
}
</tool>
`scanned_files` 也支持完整对象格式：`[{"filename": "a.png", "filepath": "/path/a.png", "size": 123}]`。

返回的 `feedback_text` 已包含完整文档 Markdown 内容，可直接阅读。开启 VisionModel 接管时还会额外保存 `.md` 文件。

**查找扫描文件：**
<tool>
{
  "skill": "file_manager",
  "tool": "workspace_file",
  "params": {"tool": "find", "path": "*.png"}
}
</tool>

**读取 .hmd 文档（备选）：**
<tool>
{
  "skill": "document",
  "tool": "read_hmd",
  "params": {"hmd_path": "/path/to/doc.hmd"}
}
</tool>
