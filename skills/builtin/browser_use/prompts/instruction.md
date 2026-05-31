---
name: browser_use_instruction
category: skills
priority: 65
---

## 浏览器操控技能

你具备浏览器操控能力。当用户需要浏览网页、查找在线信息、填写表单、截取网页截图时使用。

### 工具列表

| 工具 | 说明 | 参数 |
|------|------|------|
| `navigate` | 打开 URL | `url`(必填), `timeout`(默认30s) |
| `click` | 点击元素 | `selector`(CSS选择器/按钮文本), `timeout` |
| `type` | 输入文本 | `selector`, `text`, `press_enter`(可选) |
| `get_content` | 提取页面文本 | `selector`(可选，不填取全文) |
| `get_title` | 获取页面标题 | 无 |
| `get_url` | 获取当前地址 | 无 |
| `screenshot` | 页面截图 | `filename`(可选), `full_page`(默认false) |
| `execute_js` | 执行 JavaScript | `code`(JS代码) |
| `wait_for` | 等待元素出现 | `selector`, `timeout`(默认10s) |
| `scroll` | 滚动页面 | `direction`(down/up/top/bottom), `amount`(像素) |

### 使用方式

```
<tool>
{"skill": "browser_use", "tool": "navigate", "params": {"url": "https://example.com"}}
</tool>
```

### 使用原则

1. 先 `navigate` 到目标网站，再进行其他操作
2. `click` 的 selector 可以是 CSS 选择器(`#id`、`.class`、`button`)或按钮文本
3. 导航后应 `wait_for` 关键元素，确保页面加载完成
4. 优先用 `get_content` 提取文本，而非截图（你无法看图）
5. 如果需要视觉判断，用 `screenshot` 截图
6. 浏览器会话持久化——cookies 和登录态在会话中保持
7. 复杂交互（如滚动到底部、等待异步加载）用 `execute_js`
8. 提取内容太多时，用 `selector` 缩小范围
