# System-1 决策基座

> System 1 不是另一个模型，是**同一种说话方式**：
> 给它一个封闭选项集，它在**一次前向传播**里把答案分布直接写在下一个
> token 的概率上，不生成推理文本。
>
> System 2 让你「读一段话」，System 1 让你「读一个概率」。

本仓库挂载的 JEV-27B-VL 是双系统混合模型：System 2 走常规生成，
System 1 是训练时融合进权重的 typed-decision 头。

---

## 一、它解决什么

离散判断（是/否、选哪个、打几分、要不要检索）用常规生成来做，
代价是「生成一段话 → 解析 → 丢弃大部分内容」，慢且不稳。

System 1 把这件事变成一次前向（实测本机 **0.55~0.7s**），而且给的是
**可阈值化的置信度** —— 于是可以这么用：

```python
if gate.evaluate(text).value and gate.evaluate(text).confident:
    ...   # 高置信度才走这条分支
```

能落地的场景（本仓库已接的）：

| 场景 | 类型 | 落点 |
|---|---|---|
| 情绪读取（驱动语气与 TTS 语速） | choice | `apps/dsn_study/models/decision_service.py` |
| 危机检测（关键词预筛 + 模型确认） | yes_no | 同上 |
| 工具路由 | choice | `harness/decisions/use_cases.py` |
| 检索前置判断 | yes_no | 同上 |
| 题型 / 难度分类 | choice | 同上 |

---

## 二、怎么用（llama.cpp 上的正确姿势）

System 1 在 llama.cpp 上**没有**专用端点。正确做法是**读 logprobs**：

```
POST /v1/chat/completions
  max_tokens: 1
  temperature: 0
  logprobs: true
  top_logprobs: 32
  chat_template_kwargs: {enable_thinking: false}
→ choices[0].logprobs.content[0] 就是该位置的词表分布
```

拿到的是**同一个分布**，不是降级。三个要点：

1. **选项必须能落到单 token**（`Y`/`N`、`A`..`Z`、数字）。拿到子词碎片
   就拼不回概率。所以语义名（工具名、情绪名）要编号成字母，答完再映射回去
   —— `harness/decisions/use_cases.py:route_tool` 就是这么做的。
2. **token 变体必须归并**。llama.cpp 的 tokenizer 里 `Y`、` Y`、`Yes`、`yes`
   是不同 token，只取完全相等的那个会漏掉概率质量。
3. **关掉思维链**。`enable_thinking: false` —— 思考会污染第一步的分布。

---

## 三、生命周期（和 TTS 一样：闲置自动释放）

决策模型是**重量级本地服务**：JEV 的 Q4_K_M 权重 16.5G，加载后**占满双卡**
（实测 9.9G + 9.9G）。它挂在**外周资源池**里，与 ASR/TTS/VLM 同一套机制：

```
注册（不占显存）
   ↓ 第一次决策
按需拉起 llama-server（约 9~17s 冷启动）
   ↓ 租约期间
保活（不会被槽位压力驱逐：resident=True）
   ↓ 闲置超过 idle_timeout
IdleReaper 停掉进程 → 归还约 20GB 显存
   ↓ 下次请求
重新拉起
```

**阈值**：`DECISION_IDLE_TIMEOUT`（默认 900s）。**总开关**：
`RESOURCE_IDLE_SHUTDOWN`（不设则跟随 `VOICE_IDLE_SHUTDOWN`）。

> ⚠️ 与 VLM/Bonsai（12G）**不能**同时加载 —— 拉起前有显存预检
> （`DECISION_VRAM_REQUIRED_MB`，默认 17G），不够就跳过决策并降级，
> 而不是硬挤把别人的服务 OOM 掉。

---

## 四、代码地图

```
infra/decision/client.py          传输：logprobs 通道 + /props 身份校验 + 探针
infra/decision/jev.py             JEV 的发现/端口避让/启动配置（ngl 固定 99、mmproj 放 CPU）
infra/decision/backends.py        两种取客户端的方式：池托管 / 编排器托管
infra/resources/decision_service.py  作为外周资源托管（ResourceKind.DECISION）
harness/decisions/core.py         语义：请求/结果/提示词/分布解释/置信度
harness/decisions/service.py      门面：把传输与语义接起来
harness/decisions/use_cases.py    用例：情绪、危机、工具路由、检索闸门、分类
apps/dsn_ui/system1_api.py        HTTP 契约（/v1/decide、/v1/decide/capabilities）
apps/dsn_study/models/decision_service.py  应用侧：状态探测 + 情绪→语气
```

---

## 五、验证

```bash
# 单元测试（纯逻辑，不碰模型）
python3 -m pytest tests/test_decisions_core.py \
                 tests/test_decision_use_cases.py \
                 tests/test_decision_resource.py \
                 tests/test_dsn_ui_system1_api.py \
                 tests/test_dsn_study_decision.py -q

# 真机闭环（会真的加载 16.5G 权重，占满双卡，约 2 分钟）
python3 apps/dsn_study/scripts/verify_decision_lifecycle.py
```

真机闭环会打印：拉起耗时 → 两次真实决策的候选分布 → 情绪读数 →
空闲回收用时与显存变化 → 再拉起。

**参考读数**（本机，2×RTX 2080 Ti）：

| 指标 | 实测 |
|---|---|
| 冷启动 | 9~17s（权重进页缓存后约 9s） |
| 单次决策 | 0.55~0.7s |
| 空闲回收后显存 | 从 9.9G+9.9G 回到桌面占用 |
| 决策质量 | 邮件威胁判定 P(是)=0.946（作者原厂实测 0.968，差异来自提示词措辞） |
| 情绪读数 | 「今天真的太累了」→ 疲惫，置信度 0.997 |

---

## 六、已知边界

- **不产文本**。只能给封闭选项 + 概率。需要 JSON/自由文本的活儿
  （比如人格回写的结构化字段）用不了 —— 得先把接口从「要 JSON」
  改成「多字段决策」。
- **概率校准只对融合了决策头的模型成立**。普通模型也能返回 logprobs，
  但那些概率没校准 —— capabilities 只验证「拿得到 logprobs」。
- **选项必须单 token**。多选上限 256（双字母标签）。
- **每问一次是一次前向**。「情绪 + 是否追问 + 是否危机」就是三次前向。
  所以用例适配器都是**单问题**的，组合使用时由调用方决定要不要付这个延迟
  （危机检测用关键词预筛把 99% 的对话挡在门外）。
- **显存很贵**。它与 VLM（Bonsai 12G）不能共存。
