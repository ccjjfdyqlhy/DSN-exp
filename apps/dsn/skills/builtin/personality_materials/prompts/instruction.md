---
name: personality_materials_instruction
category: capabilities
priority: 70
---

## 性格素材管理

你可以通过下载歌词、文章、对话记录等文本，导入为 AI 的性格蒸馏素材。

### 工作流：歌词 → 素材库

1. 使用 ncm_music.get_lyrics 下载歌词：
<tool>
{
  "skill": "ncm_music",
  "tool": "get_lyrics",
  "params": {"song_id": "xxx", "save": true}
}
</tool>
   - 工具返回结果中 `data.plain` 是纯文本歌词
   - 工具返回结果中 `saved_to.txt_path` 是保存的文件路径
2. 把歌词展示给用户，询问是否要加入性格素材库
3. 用户确认后，使用 personality_materials.import_experience 导入：
<tool>
{
  "skill": "personality_materials",
  "tool": "import_experience",
  "params": {
    "source_path": "ncm 工具返回的 txt_path（如 skills/builtin/ncm_music/music/186016.txt）",
    "source_label": "网易云: 晴天 - 周杰伦",
    "card_id": "exa"
  }
}
</tool>
4. 工具会自动把文件复制到 `character_cards/materials/{card_id}/` 并触发蒸馏

### 素材目录

```
character_cards/materials/exa/    ← EXA（默认角色卡）的素材
```

不同角色卡有各自子目录。

### 查看已导入素材

<tool>
{
  "skill": "personality_materials",
  "tool": "list_experiences",
  "params": {"card_id": "exa"}
}
</tool>

### 注意事项

- 导入前务必确认用户同意
- source_label 应包含来源信息（歌名、歌手等）
- 不用手动复制文件 — import_experience 会自动处理
