---
name: personality_materials_examples
category: capabilities
priority: 71
---

## 性格素材管理 — 使用示例

### 示例 1: 导入歌词到蒸馏素材

用户: 帮我下载《晴天》的歌词
AI: [使用 ncm_music.search_song 找到歌曲 ID=186016]
    [使用 ncm_music.get_lyrics(song_id=186016, save=true) 下载歌词]
    返回: saved_to={"txt_path": "skills/builtin/ncm_music/music/186016.txt"}
    "歌词已下载。要我把它加到我的性格素材库吗？后面我可以融入这种审美风格。"
用户: 好
AI: [使用 file_manager.write_file 或读+写的方式，把歌词复制到素材目录]
    目标路径: character_cards/materials/exa/186016_晴天.txt
    "已添加到素材库。下次对话时系统会自动蒸馏，把这种文化背景融入我的性格。"

### 示例 2: 查看素材库

用户: 你现在有哪些性格素材
AI: [使用 personality_materials.list_experiences]
    显示已导入的素材列表

### 示例 3: 手动导入文本

如果没有文件，也可以直接传文本：
AI: [使用 personality_materials.import_experience(text="...", source_label="来源描述")]
