---
name: web_search_examples
category: skills
priority: 61
---

### 搜索示例

**用户**: 帮我查一下今天的天气

你可以这样调用：
<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {"query": "今天天气", "max_results": 3}
}
</tool>

**用户**: 最近有什么科技新闻

<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {"query": "最新科技新闻 2026", "max_results": 5}
}
</tool>

**用户**: Python 最新版本是多少

<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {"query": "Python latest version 2026", "max_results": 3}
}
</tool>
