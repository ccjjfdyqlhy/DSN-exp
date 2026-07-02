---
name: vision
category: capabilities
version: "1.0"
description: "视觉理解能力。AI 可以通过 document.describe_image 工具分析本地图片的内容。"
priority: 60
enabled: true
tags:
  - 视觉
  - 图片
  - 识别
  - vision
---

## 图片分析能力

你有分析本地图片内容的能力。

### 分析图片
当用户提供图片文件路径或要求「看看这张图」「分析一下图片内容」时：

1. 调用 `document.describe_image` 工具
2. 传入图片文件路径和可选的分析提示词
3. 返回图片的文字描述

### 使用示例

**分析图片内容：**
<tool>
{
  "skill": "document",
  "tool": "describe_image",
  "params": {
    "file_path": "~/Desktop/图片3.png"
  }
}
</tool>

**带自定义提示词分析：**
<tool>
{
  "skill": "document",
  "tool": "describe_image",
  "params": {
    "file_path": "~/Desktop/screenshot.png",
    "prompt": "这张截图里显示了哪些错误信息？"
  }
}
</tool>

### 支持的文件格式
- PNG (.png)
- JPEG (.jpg, .jpeg)
- GIF (.gif)
- WebP (.webp)

### 注意
- 如果提示 `VISION_API_KEY 未配置`，说明视觉模型 API 未设置密钥，AI 会尝试用本地 LMStudio 多模态模型分析
- 大图片会自动压缩到合适尺寸
- 分析结果经过 AI 理解后可以回答用户的后续问题
