---
name: browser_use_examples
category: skills
priority: 66
---

### 典型场景

**搜索信息：**
```
navigate → "https://www.google.com"
type → selector="input[name='q']", text="搜索关键词", press_enter=true
wait_for → selector="#search"
get_content → selector="#search"
```

**填写表单：**
```
navigate → "https://example.com/form"
wait_for → selector="form"
type → selector="#name", text="用户名"
type → selector="#email", text="email@example.com"
click → selector="button[type='submit']"
wait_for → selector=".success-message"
get_content → selector=".success-message"
```

**登录网站：**
```
navigate → "https://example.com/login"
type → selector="#username", text="myuser"
type → selector="#password", text="pass123", press_enter=true
wait_for → selector=".dashboard"
get_title
```
