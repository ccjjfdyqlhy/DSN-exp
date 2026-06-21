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
扫描完成后，可以对图片进行 OCR 文字识别：

1. 调用 `document.process_scan` 执行 OCR 处理
2. 处理流程：分类 → OCR 文字识别 → 生成 Markdown → 打包为 .hmd 格式
3. 输出文件保存在 `<文档输出目录>` 中

### 读取 .hmd 文档
已处理的文档以 .hmd 格式存储（包含图片和 Markdown）：

1. 调用 `document.read_hmd` 读取文档内容
2. 返回文档的 Markdown 文本和图片列表
