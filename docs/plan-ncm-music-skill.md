# NCM 音乐技能 — 策划案

> 策划案 | 版本: v1.0 | 日期: 2026-06-14
> 类型: 技能 (Skill)，非插件
> API: vkeys.cn 网易云音乐接口
> 存放: `skills/builtin/ncm_music/`

---

## 一、概述

通过 `api.vkeys.cn` 提供的网易云音乐 API，让 AI 获得以下能力：

1. **点歌** — 根据关键词搜索歌曲，返回歌曲信息 + 播放链接
2. **查歌词** — 根据歌曲 ID 获取 LRC 歌词
3. **歌词蒸馏**（后续）— 从歌词中分析语言风格特征，注入人格蒸馏系统

核心价值：让 AI 可以和用户一起听音乐、分享歌曲、讨论歌词。

---

## 二、API 摘要

### 2.1 歌曲搜索/获取播放链接
```
GET https://api.vkeys.cn/v2/music/netease
参数: word(歌名/歌手), id(歌曲ID), page, num(每页数), choose(选第几首), quality(1-9)
```

**quality 音质等级：**

| 值 | 音质 | 比特率 |
|----|------|--------|
| 1 | 标准 | 64k |
| 2 | 标准 | 128k |
| 3 | HQ | 192k |
| 4 | HQ | 320k |
| 5 | SQ 无损 | — |
| 6 | Hi-Res 高解析 | — |
| 7 | 高清臻音 Spatial | — |
| 8 | 沉浸环绕声 | — |
| 9 | 超清母带 Master | — |

### 2.2 歌词获取
```
GET https://api.vkeys.cn/v2/music/netease/lyric
参数: id(歌曲ID)
返回: lrc(时间轴歌词), yrc(逐字歌词)
```

---

## 三、技能文件结构

```
skills/builtin/ncm_music/
├── skill.yaml              # 技能元数据 + 工具定义
├── prompts/
│   ├── instruction.md      # AI 使用指引
│   └── examples.md         # 使用示例
└── tools/
    ├── __init__.py
    └── ncm_api.py           # NCMApi 工具类
```

---

## 四、skill.yaml 设计

```yaml
name: ncm_music
display_name: "网易云音乐"
description: "搜索网易云音乐歌曲、获取播放链接和歌词"
version: "1.0"
author: "system"
source: "builtin"
enabled: true
status: "active"
prompt_category: "capabilities"
prompt_priority: 55

tags:
  - 音乐
  - 点歌
  - 网易云
  - 歌词
  - entertainment

# 激活条件：当用户提到这些词时，AI 应考虑使用此技能
activation:
  keywords:
    - 点歌
    - 放歌
    - 音乐
    - 歌单
    - 歌词
    - 网易云
    - 唱首歌
    - 来一首
    - 搜首歌
    - 播放
    - 听歌
    - 我想听

# 工具定义
tools:
  - name: search_song
    display_name: "搜索歌曲"
    description: "根据关键词搜索网易云音乐的歌曲，返回歌曲列表（包含歌曲名、歌手、专辑、封面、播放链接等）"
    module: "tools.ncm_api"
    class_name: "NCMApi"
    methods:
      - search_song

  - name: get_song_by_id
    display_name: "获取歌曲信息"
    description: "通过歌曲 ID 获取歌曲详细信息（包含不同音质的播放链接）"
    module: "tools.ncm_api"
    class_name: "NCMApi"
    methods:
      - get_song_by_id

  - name: get_lyrics
    display_name: "获取歌词"
    description: "根据歌曲 ID 获取歌词文本（LRC 格式，含时间轴）"
    module: "tools.ncm_api"
    class_name: "NCMApi"
    methods:
      - get_lyrics
```

---

## 五、工具类设计 (tools/ncm_api.py)

```python
import requests
import logging
from typing import Optional

logger = logging.getLogger("NCMApi")

API_BASE = "https://api.vkeys.cn"


class NCMApi:
    """网易云音乐 API 封装"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.base_url = self.config.get("api_base", API_BASE)
        self.timeout = self.config.get("timeout", 15)
        self.default_quality = self.config.get("default_quality", 4)  # 320k

    def search_song(
        self,
        keyword: str,
        page: int = 1,
        num: int = 5,
        quality: int = None,
    ) -> dict:
        """
        搜索歌曲。

        :param keyword: 搜索关键词（歌名/歌手/专辑）
        :param page: 页数，默认 1
        :param num: 每页数量，默认 5
        :param quality: 音质 1-9，默认使用配置值 (4 = HQ 320k)
        :return: {"success": bool, "data": [...], "total": int, "error": str}
        """
        ...

    def get_song_by_id(
        self,
        song_id: int,
        quality: int = None,
    ) -> dict:
        """
        通过 ID 获取歌曲详情和播放链接。

        :param song_id: 网易云音乐歌曲 ID
        :param quality: 音质 1-9
        :return: {"success": bool, "data": {...}, "error": str}
        """
        ...

    def get_lyrics(self, song_id: int) -> dict:
        """
        获取歌曲歌词。

        :param song_id: 网易云音乐歌曲 ID
        :return: {"success": bool, "data": {"lrc": "...", "song_info": {...}}, "error": str}
        """
        ...

    # ---- 内部方法 ----

    def _search(self, word: str, page: int, num: int, quality: int) -> dict:
        ...

    def _get_by_id(self, song_id: int, quality: int) -> dict:
        ...

    def _get_lyrics(self, song_id: int) -> dict:
        ...

    @staticmethod
    def _parse_lrc(lrc_text: str) -> str:
        """将 LRC 文本转为纯歌词文本（去时间戳）"""
        ...
```

### 返回结构

**search_song 返回：**
```json
{
  "success": true,
  "data": [
    {
      "id": 1345872140,
      "name": "勾指起誓",
      "singer": "洛天依Official/ilem",
      "album": "2:3",
      "duration": "3分3秒",
      "cover": "http://...",
      "quality": "HQ极高（320k）",
      "size": "12.3MB",
      "url": "http://..."
    }
  ],
  "total": 1,
  "page": 1
}
```

**get_song_by_id 返回：**
```json
{
  "success": true,
  "data": {
    "id": 1345872140,
    "name": "勾指起誓",
    "singer": "洛天依Official/ilem",
    "album": "2:3",
    "duration": "3分3秒",
    "cover": "http://...",
    "quality": "HQ极高（320k）",
    "url": "http://..."
  }
}
```

**get_lyrics 返回：**
```json
{
  "success": true,
  "data": {
    "song_id": 2078368206,
    "song_name": "...",
    "singer": "...",
    "lrc": "[00:12.42]ya la hu la\n[00:15.84]任天地之间 吟游四方\n...",
    "plain": "ya la hu la\n任天地之间 吟游四方\n偶尔有风浪\n..."
  }
}
```

---

## 六、提示词设计 (prompts/)

### 6.1 instruction.md

```markdown
---
name: ncm_music_instruction
category: capabilities
priority: 55
---

## 网易云音乐能力

你可以使用网易云音乐 API 帮助用户搜索音乐、获取播放链接和查看歌词。

### 可用工具

- `<tool>ncm_music.search_song</tool>` — 搜索歌曲
  - keyword: 搜索关键词（必填）
  - page: 页数（可选，默认1）
  - num: 每页数量（可选，默认5）
  - quality: 音质 1-9（可选，默认4=HQ 320k）

- `<tool>ncm_music.get_song_by_id</tool>` — 通过 ID 获取歌曲详情+播放链接
  - song_id: 歌曲ID（必填）
  - quality: 音质 1-9（可选）

- `<tool>ncm_music.get_lyrics</tool>` — 获取歌词
  - song_id: 歌曲ID（必填）

### 使用原则

1. 当用户说"点歌""来一首""搜首歌""放歌"等时，使用 search_song
2. 搜索到歌曲后，告诉用户歌曲信息（歌名、歌手、时长、文件大小）
3. 如果用户想听特定音质，在参数中指定 quality（如 quality=5 表示无损）
4. 当用户讨论歌词时，使用 get_lyrics
5. 不要同时返回太多歌曲（最多 5 首），让用户选择
6. 如果用户没有特别说明，默认使用 HQ 320k (quality=4)
```

### 6.2 examples.md

```markdown
---
name: ncm_music_examples
category: capabilities
priority: 55
---

## 音乐搜索示例

用户: "点一首勾指起誓"
→ 使用 `<tool>ncm_music.search_song</tool>` keyword="勾指起誓"
→ 回复: "找到了《勾指起誓》- 洛天依Official/ilem，3分3秒，HQ 320k。已为你准备好播放链接。"

用户: "搜周杰伦的歌"
→ 使用 `<tool>ncm_music.search_song</tool>` keyword="周杰伦" num=5
→ 回复: "搜到以下几首周杰伦的歌：1. 晴天 2. 七里香 ... 你想听哪首？"

用户: "无损的月亮之上"
→ 使用 `<tool>ncm_music.search_song</tool>` keyword="月亮之上" quality=5
→ 回复: "找到了《月亮之上》- 凤凰传奇，SQ 无损品质。"

用户: "这首歌的歌词是什么"
→ 根据上下文获取当前歌曲 ID
→ 使用 `<tool>ncm_music.get_lyrics</tool>` song_id=xxx
→ 回复歌词内容并可以讨论歌词意境
```

---

## 七、实现要点

### 7.1 API 响应处理

API 返回的数据结构不完全一致——`/v2/music/netease` 用关键词搜索时，如果没指定 `id` 且没指定 `choose`，返回的可能是一个列表而非单个对象。需要处理两种响应模式：

- **搜索模式**（word + page + num）：返回 `data.list[]` 或 `data` 是数组
- **ID 模式**（id 参数）：返回 `data` 是单个歌曲对象

```python
def _search(self, word: str, page: int, num: int, quality: int) -> dict:
    params = {"word": word, "page": page, "num": num}
    if quality:
        params["quality"] = quality
    resp = requests.get(f"{self.base_url}/v2/music/netease", params=params, timeout=self.timeout)
    data = resp.json()
    if data.get("code") != 200:
        return {"success": False, "error": data.get("message", "未知错误")}
    # 处理响应（可能是单曲或列表）
    ...

def _get_by_id(self, song_id: int, quality: int) -> dict:
    params = {"id": song_id}
    if quality:
        params["quality"] = quality
    resp = requests.get(f"{self.base_url}/v2/music/netease", params=params, timeout=self.timeout)
    ...
```

### 7.2 歌词解析

LRC 格式：`[mm:ss.xx]歌词文本`，需要提供纯文本版本（去除时间戳）方便 AI 阅读和讨论。

```python
@staticmethod
def _parse_lrc(lrc_text: str) -> str:
    lines = []
    for line in lrc_text.strip().split("\n"):
        # 去掉时间标签 [mm:ss.xx] 或 [mm:ss]
        clean = re.sub(r'\[\d{2}:\d{2}(?:\.\d{2,3})?\]', '', line).strip()
        if clean and not clean.startswith("作词") and not clean.startswith("作曲"):
            lines.append(clean)
    return "\n".join(lines)
```

### 7.3 错误处理

- API 不可用 → 返回错误信息，AI 应告知用户"音乐服务暂时不可用"
- 歌曲不存在 → 返回空结果，AI 应建议换关键词
- 歌词不存在 → 返回错误信息，AI 应说明"这首歌暂无歌词"
- 超时 → 捕获异常，返回错误信息

### 7.4 音质默认值

默认 `quality=4`（HQ 320k），因为这是性价比最高的选择——音质好、文件不太大。用户可以说"无损"来请求 `quality=5`。

---

## 八、与系统的交互

### 8.1 AI 发现和使用技能

1. AI 在 system prompt 中看到技能提示词（§六），了解自己可以用 `ncm_music.xxx` 工具
2. 当用户的消息匹配技能关键字（activation.keywords），AI 考虑使用该技能
3. AI 通过 `<tool>` 标签调用工具
4. 工具执行结果通过 `<tool_result>` 返回给 AI
5. AI 将结果转换成自然语言回复用户

### 8.2 与其他系统的关系

| 系统 | 关系 |
|------|------|
| **技能注册中心** (`SkillRegistry`) | NCM 技能在此注册，工具被索引 |
| **Agent 循环** | AI 在 Agent 循环中通过 `<tool>` 调用 NCM 工具 |
| **插件管线** | 不需要管道介入，纯技能 |
| **蒸馏引擎**（未来） | 可从歌词中提取语言风格特征 |
| **TTS** | 获得播放链接后，可考虑本地播放/AI 哼唱 |

### 8.3 后续扩展

- **歌词蒸馏**：从用户常听歌曲的歌词中提取语言习惯和情感特征，注入人格蒸馏引擎
- **歌单管理**：保存用户的常听歌曲，AI 可以推荐或创建歌单
- **音乐讨论**：AI 结合歌词和歌曲信息与用户讨论音乐
- **日推/推荐**：基于用户听歌历史，AI 用自己的理解推荐音乐

---

## 九、实现清单

| # | 任务 | 文件 |
|---|------|------|
| 1 | 创建目录 | `skills/builtin/ncm_music/` |
| 2 | skill.yaml | `skills/builtin/ncm_music/skill.yaml` |
| 3 | instruction.md | `skills/builtin/ncm_music/prompts/instruction.md` |
| 4 | examples.md | `skills/builtin/ncm_music/prompts/examples.md` |
| 5 | NCMApi 工具类 | `skills/builtin/ncm_music/tools/ncm_api.py` |
| 6 | tools/__init__.py | `skills/builtin/ncm_music/tools/__init__.py` |
| 7 | 测试 | `tests/test_ncm_music.py` |

### 验收标准

1. AI 能在用户说"点一首XXX"时自动搜索并返回歌曲信息
2. AI 能根据歌曲 ID 获取播放链接
3. AI 能获取并展示歌词（含纯文本版本）
4. API 不可用时优雅降级（返回明确错误信息而非崩溃）
5. 搜索结果限制在合理数量（默认 5 首）
