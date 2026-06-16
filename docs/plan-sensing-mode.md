# 感知模式（Sensing Mode）— 策划案

## 1. 概念

感知模式是一个开关。打开后，浏览器一直接着麦克风，通过**响度筛**过滤静音，自动检测人声起止，把一段完整的语音发送到后端走 ASR → ASR_filter → chat pipeline。全程无需任何按键操作。

```
┌──────────────────────────────────────────────────┐
│                   感知模式循环                      │
│                                                    │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│   │ 一直听    │    │ 响度筛    │    │ 检测到   │    │
│   │ 麦克风    │──→ │ 过滤静音  │──→ │ 人声起   │    │
│   └──────────┘    └──────────┘    └────┬─────┘    │
│                                        │          │
│   ┌──────────┐    ┌──────────┐    ┌────▼─────┐    │
│   │ 停止录音  │    │ 恢复静音  │    │ 开始录音  │    │
│   │ 发送音频  │←── │ 检测     │←── │ 缓存 PCM  │    │
│   └────┬─────┘    └──────────┘    └──────────┘    │
│        │                                           │
│        ▼                                           │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    │
│   │ ASR →    │    │ ASR_     │    │ Pipeline │    │
│   │ 语音转文字│──→ │ filter   │──→ │ → 回复   │    │
│   └──────────┘    └──────────┘    └────┬─────┘    │
│                                        │          │
│   ┌──────────┐    ┌──────────┐         │          │
│   │ 若 TTS    │    │ 播放时    │         │          │
│   │ 开启 →    │    │ 暂停感知  │◀────────┘          │
│   │ 合成+播放 │    │ 防回授    │                    │
│   └──────────┘    └──────────┘                    │
└──────────────────────────────────────────────────┘
```

---

## 2. 前端实现

### 2.1 响度筛（Loudness Gate）

不依赖 VAD 库，仅用 Web Audio API 计算 RMS 响度。

```javascript
class LoudnessGate {
    constructor(threshold = 0.02, hold_ms = 800) {
        this.threshold = threshold;    // 响度阈值，低于此视为静音
        this.hold_ms = hold_ms;        // 静音保持时间，超过此视为句尾
        this.speaking = false;         // 当前是否在说话
        this.silence_start = null;     // 进入静音的时间戳
    }

    process(rms) {
        if (rms > this.threshold) {
            // 响度超标 → 人声
            if (!this.speaking) {
                this.speaking = true;
                this.silence_start = null;
                return { type: 'voice_start' };
            }
            this.silence_start = null;
            return { type: 'voice_continue' };
        } else {
            // 低于阈值 → 静音
            if (this.speaking) {
                if (this.silence_start === null) {
                    this.silence_start = Date.now();
                } else if (Date.now() - this.silence_start > this.hold_ms) {
                    this.speaking = false;
                    this.silence_start = null;
                    return { type: 'voice_end' };
                }
                return { type: 'voice_continue' };
            }
            return { type: 'silence' };
        }
    }
}
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `threshold` | 0.02 | RMS 阈值，低于此认为是静音 |
| `hold_ms` | 800 | 静音保持 800ms 后判定为句尾 |

threshold 可通过 UI 滑块调节（低 = 更灵敏，高 = 需要更大声）。

### 2.2 录音缓存 + 自动发送

```javascript
class SensingRecorder {
    constructor() {
        this.audioCtx = null;
        this.analyser = null;
        this.mediaStream = null;
        this.recording = false;
        this.pcmChunks = [];
        this.loudnessGate = new LoudnessGate();
    }

    async start() {
        // getUserMedia → 创建 AudioContext
        // 连接 AnalyserNode（响度分析）+ 一直监听
        // 同时创建 MediaRecorder（等 voice_start 事件再 .start()）
        this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        this.audioCtx = new AudioContext();
        const source = this.audioCtx.createMediaStreamSource(this.stream);
        this.analyser = this.audioCtx.createAnalyser();
        this.analyser.fftSize = 256;
        source.connect(this.analyser);
        this._startLoop();
    }

    _startLoop() {
        // requestAnimationFrame 循环
        const data = new Uint8Array(this.analyser.frequencyBinCount);
        this.analyser.getByteTimeDomainData(data);
        const rms = this._calcRMS(data);
        const event = this.loudnessGate.process(rms);

        if (event.type === 'voice_start') {
            this.recording = true;
            this.recorder = new MediaRecoder(this.stream); // 延迟创建
            this.recorder.start();
            this.audioChunks = [];
            this.recorder.ondataavailable = e => this.audioChunks.push(e.data);
        }

        if (event.type === 'voice_end') {
            this.recording = false;
            this.recorder.stop();
            this.recorder.onstop = () => this._send(this.audioChunks);
        }

        // 持续更新波形显示的 RMS 值
        this._updateWaveform(rms);

        requestAnimationFrame(() => this._startLoop());
    }

    _send(chunks) {
        const blob = new Blob(chunks, { type: 'audio/wav' });
        // base64 → POST /api/asr/passthrough
        // 与现有 /api/asr/passthrough 路由兼容
    }

    stop() {
        this.recording = false;
        if (this.stream) this.stream.getTracks().forEach(t => t.stop());
        if (this.audioCtx) this.audioCtx.close();
    }
}
```

### 2.3 TTS 播放时自动暂停感知

```javascript
// 在 voice.js 的 PlaybackQueue 中：
class PlaybackQueue {
    enqueue(audioB64) {
        this.queue.push(audioB64);
        if (!this.playing) this.next();
    }

    async next() {
        if (this.queue.length === 0) {
            this.playing = false;
            if (this.onDrain) this.onDrain();  // 播放完毕 → 恢复感知
            return;
        }
        this.playing = true;
        if (this.onStart) this.onStart();  // 开始播放 → 暂停感知

        const b64 = this.queue.shift();
        // 解码 → 播放
        // ...
        source.onended = () => this.next();
    }
}

// 使用：
playback.onStart = () => sensing.pause();   // 开始播放 → 暂停感知
playback.onDrain = () => sensing.resume();  // 播放完 → 恢复感知
```

感知暂停期间麦克风仍然开着，但 `LoudnessGate` 不触发 voice_start → 不产生新录音。

### 2.4 感知模式 UI

```
┌──────────────────────────────────┐
│  [感知模式 🔴] [TTS 🎵]          │
│                                  │
│        ┌──────────────┐          │
│        │  波形显示区    │          │
│        │  (实时 RMS)   │          │
│        └──────────────┘          │
│                                  │
│   "你说的话实时显示在这里"          │
│   "AI 回复也显示在这里"            │
│                                  │
│   ┌────┐  ┌────┐  ┌────────────┐│
│   │感知 │  │ TTS │  │ 灵敏: ███░░││
│   │开/关│  │开/关│  │           ││
│   └────┘  └────┘  └────────────┘│
└──────────────────────────────────┘
```

- 顶部两个开关：感知模式开关、TTS 开关
- 中央波形：实时音频 RMS 电平
- 文字区：显示 ASR 识别结果 + AI 回复
- 灵敏滑块：调节 LoudnessGate 的 threshold

---

## 3. 后端实现

### 3.1 无需新增任何核心模块

感知模式复用的全部是现有端点：

| 功能 | 端点 | 现有 |
|------|------|------|
| 语音→文字 | `POST /api/asr/passthrough` | ✅ |
| 内容过滤 | `ASR_filter.py` | ✅ |
| 对话回复 | 同上端点内部调 chat pipeline | ✅ |
| TTS 合成 | pipeline POST_PROCESS → TTS Plugin | ✅ |
| SSE 流 | 同上端点返回 SSE 事件 | ✅ |

### 3.2 ASR_filter 交互

当前 `ASR_filter.py` 已有 `LMFilterModel` 做内容过滤。感知模式下同样经过过滤。

过滤判定：
- 通过 → 正常 chat pipeline 回复
- 不通过 → SSE 返回 `filtered: true`，前端可不显示/播放
- 流式场景下已有的 `ctx.filtered` 机制完全适用

### 3.3 端点小增强

`POST /api/asr/passthrough` 目前接受 `base64` 音频 → ASR → pipeline。感知模式下同样发 base64。

可选增强：新增查询参数 `sensing=true`，后端可据此：
- 日志标记为"感知模式"来源
- 返回额外字段（如 VAD 时间戳）
- 对话上下文中标记语音轮次

```python
@app.route("/api/asr/passthrough", methods=["POST"])
def asr_passthrough():
    is_sensing = request.args.get("sensing", "false") == "true"
    # ... 现有逻辑不变 ...
```

### 3.4 感知模式专属提示词注入

感知模式下需要一条**强行注入**的对话风格提示词，叠加在现有性格提示词之上。目的是让 AI 在保持原有性格的前提下，输出适合语音播报的短句。

**注入时机**：`/api/asr/passthrough` 中检测到 `sensing=true` 时，在构建 `system_prompt` 的末尾追加以下内容：

```
[SENSING_MODE_HINT]
对话模式: 语音通话
风格要求:
- 你是真人，对方也是真人，你们在打电话
- 用词自然口语化，像人类电话聊天一样
- 每句话尽量短，一句话说不完就分成两三句说
- 不要列条目（1. 2. 3.），不要用加粗、标记符号，因为对方是用耳朵听的
- 不要解释你做了什么操作，除非对方主动问
- 对方不说话就是还在听，继续往下说就行
- 保持你原有的性格

如果你听懂了这段提示词，不必回复确认，直接按此风格正常对话即可。
```

**强制叠加机制**：

```python
SENSING_MODE_HINT = """..."""

def build_sensing_prompt(base_prompt: str) -> str:
    """感知模式下在 system_prompt 末尾追加语音风格提示"""
    return base_prompt + "\n\n" + SENSING_MODE_HINT
```

在 `app.py` 的 `/api/asr/passthrough` 路由中：

```python
if is_sensing:
    ctx.system_prompt = build_sensing_prompt(ctx.system_prompt)
```

这个提示词会在每次感知模式的 LLM 调用前注入，不影响普通文字聊天。不修改 `prompt_engine` 本身，只在管线构造 `PluginContext` 后、MODEL_INVOKE 前追加字符串。

**关键约束**：
- 不修改 PersonalitySystemV3 / V2 的提示词，只在上面叠一层
- 不永久生效，仅当前请求
- 前端关闭感知模式后，后续请求不再注入

---

## 4. 全流程示例

```
1. 用户打开感知开关
   → 浏览器请求麦克风权限
   → getUserMedia → AudioContext → AnalyserNode
   → 开始实时 RMS 计算，波形跳动

2. 用户开始说话
   → RMS > 0.02 → LoudnessGate 触发 voice_start
   → MediaRecorder.start() 开始录音
   → 波形区高亮显示"录音中"

3. 用户说话结束（停顿 >800ms）
   → RMS < 0.02 → LoudnessGate 触发 voice_end
   → MediaRecorder.stop() → Blob → base64
   → POST /api/asr/passthrough?sensing=true

4. 后端处理
   → FunASR 识别 → ASR_filter 过滤
   → chat pipeline → SSE 流返回
   → text_ready → 前端显示用户说的话
   → line (含 audio_b64) → 前端加入播放队列
   → 若 TTS 开启 → 开始播放

5. 播放 TTS 时
   → PlaybackQueue.onStart → SensingRecorder 暂停
   → 麦克风仍开但不能触发新录音
   → PlaybackQueue.onDrain → 恢复感知检测

6. 用户再次说话
   → 回到步骤 2
```

---

## 5. 文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `psychoscope/static/js/voice.js` | **新增** | LoudnessGate + SensingRecorder + PlaybackQueue |
| `psychoscope/static/js/app.js` | 小改 | 感知模式开关绑定、模式切换时启停 voice.js |
| `psychoscope/static/index.html` | 小改 | 感知模式 UI: 开关、波形、灵敏滑块 |
| `psychoscope/static/css/style.css` | 小改 | 感知模式样式 |
| `app.py` | 小改 | `asr_passthrough` 中识别 `sensing=true`，追加 `SENSING_MODE_HINT` |

后端新增内容：一段常量字符串 `SENSING_MODE_HINT` + 一个拼接函数 `build_sensing_prompt`。

---

## 6. 实现计划

| 阶段 | 内容 | 预估 |
|------|------|------|
| P1 | `voice.js`: LoudnessGate 响度筛 + 录音起停逻辑 | 1 天 |
| P2 | `voice.js`: PlaybackQueue + 感知暂停/恢复 | 0.5 天 |
| P3 | 前端 UI: 开关、波形、灵敏滑块 + app.js 模式切换 | 1 天 |
| P4 | TTS 开关 + 禁止蛇咬尾巴（播放时暂停感知） | 0.5 天 |
| P5 | 后端: `SENSING_MODE_HINT` 常量 + `sensing=true` 处理 | 0.5 天 |
| P6 | 集成联调 + 灵敏参数微调 | 0.5 天 |

**总计约 4 天**。后端新增一段常量字符串 + app.py 约 10 行改动，不新增依赖。

---

## 7. 风险

| 风险 | 说明 | 应对 |
|------|------|------|
| 响度筛误触发（环境噪音） | threshold 过低时空调/风扇声触发录音 | 默认 threshold 0.02，用户可调；加 highpass 滤波 |
| 说话快/停顿短被切句 | 800ms hold_ms 可能切掉句中正常停顿 | hold_ms 可调；用户语速快可调大 |
| 麦克风权限 | 浏览器拒绝 | 检测权限状态 → 提示 → 回退文字模式 |
| TTS 播放时外界声音 | 播放时感知暂停，外界声音不会触发 | 恢复感知后正常；若有遗失内容用户可手动再说 |
| 长段音频超时 | MediaRecorder 有 maxRecordingTime | 默认 30s，超时自动截断发送 |
