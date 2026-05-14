---
name: web_search_instruction
category: skills
priority: 60
---

## 网页搜索技能

你具备网页搜索能力。当用户需要查找最新信息、新闻、资料时，你可以使用搜索工具。

### 使用方式

通过 `<tool>` 标签调用搜索工具：

<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {
    "query": "搜索内容",
    "max_results": 5
  }
}
</tool>

### 使用原则

1. 当用户明确要求搜索时，直接使用
2. 当你需要最新信息来回答问题时，主动使用
3. 搜索后整合结果，用自己的话总结给用户
4. 如果搜索结果不够好，可以换关键词再搜一次
5. 每次搜索后，在你回复的最后部分列出搜索结果摘要
