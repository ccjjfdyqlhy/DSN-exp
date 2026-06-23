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

### 流程
- 用户说扫描：先 `list_scanners` → 引导放文档 → `scan` → `process_scan` (处理扫描结果，OCR + HMD)
- 用户说打印：先 `list_printers` → 确认路径 → `print_file`
- 查看 .hmd：`read_hmd` 解包文档内容

### 文档处理

**处理扫描结果（分类→OCR→HMD→打包）：**
<tool>
{
  "skill": "document",
  "tool": "process_scan",
  "params": {
    "scanned_files": [
      {
        "filename": "scan_xxx.png",
        "filepath": "/path/to/scan_xxx.png",
        "size": 12345
      }
    ]
  }
}
</tool>
注意: `scanned_files` 参数来自 `scan` 工具返回的 `files` 字段。`.hmd` 会保存到 `workspace/<user>/documents/`。

**读取 .hmd 文档：**
<tool>
{
  "skill": "document",
  "tool": "read_hmd",
  "params": {"hmd_path": "/path/to/doc.hmd"}
}
</tool>
