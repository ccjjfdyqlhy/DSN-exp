# 高考在线抓取 Skill

从 **高考在线（gaokzx.com）** 搜索、解析并下载「试题图片」和「答案图片」。
这是第三方站点，请按下面的顺序调用，别一上来就下载。

## 什么时候用这个技能

- 用户要「抓/下载某套试卷的题目图片或答案」
- 用户给了 gaokzx.com 的文章链接，想把里面的扫描件存到本地
- 用户要「北京某某中学 某年级 期中/期末 数学 试题和答案」
- 想把下载下来的试卷图片接着做 OCR / 录入题库（配合 `quest_from_image`、`scan_import_questions`）

## 典型调用流程（先搜 → 再解析 → 最后下载）

### 第 1 步：`search_papers` —— 找文章

```json
{"keyword": "一七一中 初一 数学 期中", "page": 1, "page_size": 20}
```

返回 `papers[]`，每条含 `id` / `title` / `url` / `release_time` / `has_answer_hint`。

**注意**：站内搜索是模糊匹配，会混进不相关的文章。**必须看标题挑**，
标题形如「2026-2027学年北京一七一中初一上学期期中数学试题及答案」的才是目标。
`has_answer_hint=true` 只说明标题里有「答案」两个字，不代表答案单独成篇。

### 第 2 步：`inspect_paper` —— 看清这篇文章里有什么（不下载）

```json
{"paper_id": 161882}
// 或 {"url": "https://www.gaokzx.com/gk/shitiku/161882.html"}
```

返回 `page_count` / `images[]` / `pdfs[]` / `summary` /
`question_count` / `answer_count` / `scan_set`（`with_answers` / `without_answers`）。
每张图都带 `kind`（`question` 试题图 / `answer` 答案图 / `unknown`）、
`kind_reason`（判别依据）、`confidence` 和 `page`（在第几页）。
每个附件 PDF 带 `file_name` / `url` / `kind`（`question` / `answer` / `unknown`）。

### 第 3 步：`download_images` —— 按需下载

```json
{"paper_id": 161882, "kind": "question", "user_id": 1, "max_images": 0}
```

- 落盘目录：`<工作区>/users/<user_id>/gaokzx/<paper_id>/`
- 文件名：`question_01.png` / `answer_01.png`
- 重复调用会自动跳过已下载且大小一致的文件（幂等，可以放心重跑）
- `kind="all"` 时试题图和答案图都下
- 本文是「有答案」套卷时（试题页和答案页在**同一套**扫描件里），`kind="question"`
  会回退成下载整套扫描件，返回里 `kind_fallback=true`、`note` 会写清楚

### 第 4 步（可选）：`find_answer_paper` —— 找配套答案文章

```json
{"paper_id": 161882}
```

**试题图和答案图常常分散在两处**，这是本技能最容易踩的坑：

## ⚠️ 试题图和答案图常常分散在两处

这是本技能最容易踩的坑，务必按下面的判断走：

1. **扫描件文件名带「无答案」** → 正文的扫描件只给了试题。
   **但附件 PDF 可能是「有答案」版**（很常见），所以一定要看 `inspect_paper`
   返回的 `pdfs[]`：`pdfs` 里 `kind="answer"` 的就是答案，直接下它的 URL。
2. **扫描件文件名带「有答案」** → 这套卷把答案一起扫进来了，答案一般在**扫描集的后半部分**。
   这时 `kind="answer"` 的图片就是这套卷的全部扫描件（含试题页），
   想要纯试题图要找同系列的「无答案」文章。
3. **答案是另一篇独立文章** → 标题形如「2027届北京各区高三上学期期中试题答案」，
   与试题文章分开发布。此时用 `find_answer_paper` 去找：

```json
{"paper_id": 161882}
```

它会先看本文档自己有没有答案材料（有就直接告诉你「答案就在本文内」），
没有再用标题派生的关键词去站内搜，按标题相似度排序给候选。
**`best` 为 null 时不要硬猜** —— 说明站内确实没有可确认的独立答案文章，
把候选列表（`candidates`）给用户看，让用户自己挑。

## 注意事项

- 站内文章 id 在两个站点（高考在线 / 自主选拔在线）**含义不同**，本技能已强制带
  `sourceType: GAOKZX` 请求头，不要绕过。
- 请求已做限速（默认 0.8s 一次，`GAOKZX_DELAY` 可调）、失败重试与退避，
  别在同一个会话里并发狂刷。
- `inspect_paper` **只解析元数据不下载**，先看清楚再下载，避免白下几百 MB 扫描件。
- 老文章（2019 年前后）的真实路径在 `/c/YYYYMM/` 下，正文里主要是链接表格，
  没有扫描图；这类文章建议直接用链接里的 PDF。
