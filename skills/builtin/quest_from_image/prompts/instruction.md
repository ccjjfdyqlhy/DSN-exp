# 图片识题 Skill

你可以用本技能从题目截图或照片中自动识别题目内容并录入题库。支持单张和批量处理。

## 使用场景

1. **拍题录入** — 用户拍了一张课本/试卷的照片，说"帮我把这道题录入"
2. **截图录入** — 用户截了一张电子版题目的图，想直接入库
3. **批量拍题** — 用户拍了多页题目照片，一次全部识别入库

## 用法

### 单张图片

```json
{
  "file_path": "~/Desktop/题目.png",
  "subject": "math",
  "preview_only": false
}
```

### 批量图片

```json
{
  "file_paths": ["~/pic1.png", "~/pic2.png"],
  "subject": "physics",
  "preview_only": false
}
```

### 先预览再入库

`preview_only: true` 时只返回识别结果不入库，AI 先展示给用户确认，然后用 `snap_question` 或 `snap_batch` 配合 `preview_only: false` 正式入库。

## 参数说明

### snap_question

| 参数 | 说明 |
|---|---|
| `file_path` | 图片路径，支持 `~` 展开，**必填** |
| `subject` | 学科代码，**必填** |
| `preview_only` | `true` 只预览，`false`(默认) 预览并入库 |

### snap_batch

| 参数 | 说明 |
|---|---|
| `file_paths` | 图片路径列表，**必填** |
| `subject` | 学科代码，**必填** |
| `preview_only` | `true` 只预览 |

## 注意

- 图片清晰度影响识别效果，建议至少 300 DPI 的扫描件或清晰截图
- 识别结果自动用视觉多模态模型提取，选择题会带选项
- 如果用户提供的是**已扫描好的 .hmd 文档**，应使用 `doc_to_questions` 技能而非本技能
- 如果图片中包含大量文字（如整页试卷），本技能也能处理，但如果需要布局分析，建议用 document + doc_to_questions 流程
