---
name: document_instruction
category: skills
priority: 65
---

## 文档处理技能

你可以通过 `<tool>` 标签控制物理扫描仪和打印机。

### 扫描

**列出扫描仪：**
```json
{"skill": "document", "tool": "list_scanners", "params": {}}
```

**执行扫描：**
```json
{"skill": "document", "tool": "scan", "params": {}}
```
高分辨率: `{"skill": "document", "tool": "scan", "params": {"resolution": 600, "mode": "Color"}}`

### 打印

**列出打印机：**
```json
{"skill": "document", "tool": "list_printers", "params": {}}
```

**打印文件：**
```json
{"skill": "document", "tool": "print_file", "params": {"file_path": "/path/to/doc.pdf"}}
```
指定页码: `{"skill": "document", "tool": "print_file", "params": {"file_path": "/path/to/doc.pdf", "page_range": "1", "copies": 2}}`

### 流程
- 用户说扫描：先 `list_scanners` → 引导放文档 → `scan` → `process_scan` (处理扫描结果，OCR + HMD)
- 用户说打印：先 `list_printers` → 确认路径 → `print_file`
- 查看 .hmd：`read_hmd` 解包文档内容

### 文档处理

**处理扫描结果（分类→OCR→HMD→打包）：**
```json
{"skill": "document", "tool": "process_scan", "params": {"scanned_files": [{"filename": "scan_xxx.png", "filepath": "/path/to/scan_xxx.png", "size": 12345}]}}
```
注意: `scanned_files` 参数来自 `scan` 工具返回的 `files` 字段。`.hmd` 会保存到 `workspace/<user>/documents/`。

**读取 .hmd 文档：**
```json
{"skill": "document", "tool": "read_hmd", "params": {"hmd_path": "/path/to/doc.hmd"}}
```
