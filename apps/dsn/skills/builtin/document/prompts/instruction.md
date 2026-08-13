---
name: document_instruction
category: skills
priority: 65
---

## 文档处理技能

你可以通过 `<tool>` 标签控制物理扫描仪和打印机。

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
- **扫描后一键处理**（推荐）：`scan` → `process_last_scan`（零参数，自动处理）
- 用户说扫描：先 `list_scanners` → 引导放文档 → `scan` → `process_last_scan` 或 `process_scan`
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
