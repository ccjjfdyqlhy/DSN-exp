---
name: document_scanning
category: capabilities
version: "2.0"
description: "文档扫描/OCR/HMD 处理能力。AI 可以通过 document 技能调用物理扫描仪和打印机，以及 OCR/HMD 文档处理管线。"
priority: 65
enabled: true
tags:
  - 扫描
  - 打印
  - OCR
  - 文档
---

## 文档处理能力

你有控制物理扫描仪和打印机的能力。

### 扫描文档
当用户需要录入纸质文档（试卷、合同、笔记本等）时：

1. 调用 `document.list_scanners` 确认扫描仪可用
2. 引导用户把文档放在扫描台上
3. 用户确认后调用 `document.scan` 执行扫描
4. 扫描文件保存在 `<扫描文件存放目录>` 中

### 打印文档
当用户需要打印文件时：

1. 调用 `document.list_printers` 确认打印机可用
2. 确认用户要打印的文件路径和页码范围
3. 调用 `document.print_file` 发送打印任务

### OCR 文档处理
扫描完成后，可以对图片进行 OCR 文字识别。推荐流程：

1. `document.scan` 执行扫描
2. **`document.process_last_scan`**（零参数，自动找最新扫描文件处理）或 `document.process_scan`（手动传路径）
3. 处理流程：分类 → OCR 文字识别 → 生成 Markdown → 打包
4. 输出文件保存在 `<文档输出目录>` 中，格式为 `.hmd`（含图片和 Markdown）
5. `process_scan` / `process_last_scan` 返回的 `feedback_text` 已包含完整文档 Markdown 内容，可直接阅读
6. 如果启用了 VISION_OVERRIDE，还会额外保存独立 `.md` 文件到同一目录

### 读取文档内容
处理后的文档内容可通过以下方式读取：

1. **直接读取**：`process_scan` 返回的 `feedback_text` 已含完整文字，AI 可直接引用
2. **读取 .hmd**：调用 `document.read_hmd` 解包读取（返回 mdA + mdB + 图片列表）
3. **读取 .md**（VISION_OVERRIDE 模式下）：用 `workspace_file` 的 `read_file` 读取 `md_path` 指向的独立 Markdown 文件
4. **查找文件**：用 `workspace_file` 的 `find` 子命令递归搜索工作区文件

### 扫描文件管理
- `document.process_last_scan` — 零参数，自动处理最近一次扫描（推荐）
- `document.process_scan` — 手动指定文件路径列表：`["/path/to/a.png", ...]`
- `file_manager.workspace_file` 的 `find` 子命令 — 递归搜索文件：`{"tool": "find", "path": "*.png"}`
