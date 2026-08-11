# 图片识题 Skill

你可以用本技能从题目截图或照片中自动识别题目内容并**直接录入题库**。视觉模型全权识别（科目+题目原文+答案+解析），主模型不接触题目内容。支持单张和批量处理。

## 使用场景

1. **拍题录入** — 用户拍了一张课本/试卷的照片，说"帮我把这道题录入"
2. **截图录入** — 用户截了一张电子版题目的图，想直接入库
3. **批量拍题** — 用户拍了多页题目照片，一次全部识别入库

## 用法

### 单张图片（subject 可留空，视觉模型自动识别科目）

```json
{
  "file_path": "~/Desktop/题目.png",
  "subject": "",
  "preview_only": false
}
```

### 批量图片

```json
{
  "file_paths": ["~/pic1.png", "~/pic2.png"],
  "subject": "",
  "preview_only": false
}
```

### 先预览再入库

`preview_only: true` 时只返回识别结果不入库，AI 先展示给用户确认，然后用 `import_photo_questions` 或 `import_photo_questions_batch` 配合 `preview_only: false` 正式入库。

## 参数说明

### import_photo_questions

| 参数 | 说明 |
|---|---|
| `file_path` | 图片路径，支持 `~` 展开，**必填** |
| `subject` | 学科代码，**可留空**；留空时由视觉模型从图片内容自动识别 |
| `preview_only` | `true` 只预览，`false`(默认) 预览并入库 |

### import_photo_questions_batch

| 参数 | 说明 |
|---|---|
| `file_paths` | 图片路径列表，**必填** |
| `subject` | 学科代码，**可留空**；留空时由视觉模型自动识别 |
| `preview_only` | `true` 只预览 |

## 注意

- 图片清晰度影响识别效果，建议至少 300 DPI 的扫描件或清晰截图
- 识别结果自动用视觉多模态模型提取，选择题会带选项
- **科目不需要你（主模型）判断**：`subject` 留空即可，视觉模型会从题目内容自动判断
- 如果用户提供的是**已扫描好的 .hmd 文档**，应使用 `doc_to_questions` 技能而非本技能
- 如果是物理扫描仪扫出来的整页试卷，应使用 `document.scan_import_questions` 而非本技能
