# DSN-exp 视觉感知系统 — 策划案 v2.0

> Phase 1 最后一块：OpenCV 轻量监控 + 模态模型场景描述，双模协同。

---

## 1. 设计思路

| 模式 | 引擎 | 频率 | 成本 | 产出 |
|------|------|------|------|------|
| **结构感知** | OpenCV 帧处理 | 持续（30s~5min） | 几乎零 | 结构化状态: 有人在吗、亮度、是否在动 |
| **语义描述** | LMStudio 多模态模型 | 事件触发 + 定期 | LLM 推理 | 自然语言: "用户在写代码，桌面有咖啡" |

**协同方式**：

```
OpenCV 每 30s 抓帧
  ├─ 结构化数据 → 立即写入 EnvironmentState → 每次对话注入 system_prompt
  └─ 事件检测 → 触发模态描述 → 语义描述也写入 EnvironmentState → 一并注入
```

对话时 AI 收到：
```
[环境感知]
用户状态: 在屏幕前，正在打字
环境光线: 明亮（185 lux）
连续时长: 78 分钟
场景描述: 用户坐在书桌前，屏幕亮着，桌面上有一杯水。窗外阳光射入。
```

---

## 2. 配置项

```python
CAMERA_ENABLED = _env("CAMERA_ENABLED", "true").lower() == "true"
CAMERA_DEVICE_ID = int(_env("CAMERA_DEVICE_ID", "0"))
CAMERA_INTERVAL_ACTIVE = int(_env("CAMERA_INTERVAL_ACTIVE", "30"))
CAMERA_INTERVAL_IDLE = int(_env("CAMERA_INTERVAL_IDLE", "300"))
CAMERA_MOTION_THRESHOLD = float(_env("CAMERA_MOTION_THRESHOLD", "0.02"))
CAMERA_DESCRIBE_EVERY = int(_env("CAMERA_DESCRIBE_EVERY", "600"))  # 秒，定期模态描述间隔
```

说明：`CAMERA_DESCRIBE_EVERY` 控制每多少秒调用一次多模态模型生成场景描述（默认 10min）。
事件触发（用户回来/光线突变）时立即调用，不受此间隔限制。

---

## 3. 架构

```
┌──────────────────────────────────────────────────────────────────┐
│                      CameraWatcher (后台线程)                      │
│                                                                  │
│  OpenCV VideoCapture                                              │
│       │                                                          │
│       ├──▶ 帧差法运动检测 ──→ motion_flag                         │
│       ├──▶ Haar Cascade 人脸检测 ──→ face_count                    │
│       ├──▶ 帧平均亮度 ──→ lux_value → bright/normal/dim/dark     │
│       └──▶ 判断是否需要模态描述 ──┐                                │
│                                   │                              │
└───────────────────────────────────┼──────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │ 事件判断                        │
                    │  - 用户首次出现                 │
                    │  - 用户离开后回来               │
                    │  - 光线突变                     │
                    │  - 距上次描述 > CAMERA_...     │
                    └───────────────┬───────────────┘
                                    ▼
                    ┌───────────────────────────────┐
                    │ 模态描述 (异步)                │
                    │  LMStudio.describe_image()     │
                    │  → "用户正在编程..."           │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │     EnvironmentState          │
                    │  user_present: True           │
                    │  user_active: True            │
                    │  ambient_light: "bright"      │
                    │  lux_value: 185.0             │
                    │  scene_description: "..."     │
                    │  session_duration_min: 78     │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │  VisualPerceptionPlugin       │
                    │  PRE_PROCESS (priority=27)     │
                    │  → 注入 [环境感知] 到 system   │
                    └───────────────────────────────┘
```

---

## 4. 核心代码

### 4.1 EnvironmentState

```python
@dataclass
class EnvironmentState:
    user_present: bool = False
    user_active: bool = False
    face_count: int = 0
    ambient_light: str = "normal"
    lux_value: float = 0.0
    scene_description: str = ""         # 模态模型生成的语义描述
    last_description_time: float = 0    # 上次描述时间戳
    session_duration_min: int = 0
    mode: str = "idle"

    def to_dict(self) -> dict:
        return {
            "user_present": self.user_present,
            "user_active": self.user_active,
            "face_count": self.face_count,
            "ambient_light": self.ambient_light,
            "lux_value": round(self.lux_value, 1),
            "session_duration_min": self.session_duration_min,
            "mode": self.mode,
            "scene_description": self.scene_description,
        }
```

### 4.2 CameraWatcher

```python
class CameraWatcher(threading.Thread):
    """后台摄像头抓帧线程。双模：OpenCV 结构感知 + 模态描述。"""

    class Mode(Enum):
        ACTIVE = "active"
        IDLE = "idle"
        EVENT = "event"

    def __init__(self, camera_id: int = 0):
        self._cap: cv2.VideoCapture | None = None
        self._mode = self.Mode.IDLE
        self._state = EnvironmentState()
        self._prev_frame: np.ndarray | None = None
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._running = False
        self._lock = threading.Lock()
        self._last_describe_ts = 0.0

    def run(self):
        self._cap = cv2.VideoCapture(self._camera_id)
        self._running = True
        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(1)
                continue
            self._process_frame(frame)
            time.sleep(self._get_interval())

    def _process_frame(self, frame: np.ndarray):
        motion = self._detect_motion(frame)
        faces = self._detect_faces(frame)
        lux = self._estimate_lux(frame)

        now = time.time()
        user_here = len(faces) > 0 or motion
        light_label = self._lux_to_label(lux)
        duration = self._calc_session_duration(now)

        with self._lock:
            prev_present = self._state.user_present
            prev_light = self._state.ambient_light

            self._state.user_present = user_here
            self._state.user_active = motion
            self._state.face_count = len(faces)
            self._state.ambient_light = light_label
            self._state.lux_value = lux
            self._state.session_duration_min = duration

        # 判断是否需要调用模态描述
        if self._should_describe(now, prev_present, prev_light, user_here):
            threading.Thread(
                target=self._describe_scene, args=(frame,), daemon=True
            ).start()

    def _should_describe(self, now, prev_present, prev_light, user_here) -> bool:
        """触发条件：用户首次出现 / 回来 / 光线突变 / 定期"""
        if not user_here:
            return False
        if not prev_present and user_here:
            return True
        if prev_light != self._lux_to_label(self._state.lux_value):
            return True
        return (now - self._last_describe_ts) > Config.CAMERA_DESCRIBE_EVERY

    def _describe_scene(self, frame: np.ndarray):
        """调 LMStudio 多模态模型生成场景描述"""
        try:
            from models import LMStudioChat
            chat = LMStudioChat(
                base_url=Config.LMSTUDIO_BASE_URL,
                model_name=Config.MEMORY_MODEL,
                timeout=60,
            )
            import cv2, base64
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
            data_url = f"data:image/jpeg;base64,{base64.b64encode(buf).decode()}"
            description = chat.describe_image(
                data_url,
                prompt="请简短描述这张图片里的场景：用户在做什么、环境怎么样。20字以内。",
                max_tokens=80,
            )
            with self._lock:
                self._state.scene_description = description
                self._last_describe_ts = time.time()
            logger.info("场景描述: %s", description)
        except Exception as e:
            logger.error("场景描述失败: %s", e)
```

### 4.3 VisualPerceptionPlugin

```python
class VisualPerceptionPlugin(Plugin):
    name = "visual_perception"
    description = "环境感知 — 摄像头 + 模态双模感知"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 27

    def __init__(self, watcher=None):
        self._watcher = watcher or CameraWatcher()

    def on_load(self):
        if Config.CAMERA_ENABLED:
            self._watcher.start()
            logger.info("CameraWatcher 已启动 (device=%d)", Config.CAMERA_DEVICE_ID)

    def on_unload(self):
        self._watcher.stop()

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if not Config.CAMERA_ENABLED:
            return ctx
        if hook == HookPoint.PRE_PROCESS:
            self._watcher.set_active()
            state = self._watcher.get_state()
            if state.get("user_present"):
                ctx.system_prompt += "\n\n" + self._build_prompt(state)
        return ctx

    @staticmethod
    def _build_prompt(state: dict) -> str:
        lines = ["[环境感知]"]
        if state.get("user_present"):
            activity = "正在活动" if state.get("user_active") else "静止"
            lines.append(f"用户状态: 在屏幕前，{activity}")
        else:
            lines.append("用户状态: 不在屏幕前")
        lines.append(f"环境光线: {state.get('ambient_light', 'normal')}（{state.get('lux_value', 0):.0f} lux）")
        dur = state.get("session_duration_min", 0)
        if dur > 0:
            lines.append(f"连续时长: {dur} 分钟")
            if dur > 120:
                lines.append("⚠️ 已连续工作超过 2 小时")
        desc = state.get("scene_description", "")
        if desc:
            lines.append(f"场景描述: {desc}")
        return "\n".join(lines)
```

---

## 5. 注入效果

AI 每次对话看到：

```
[环境感知]
用户状态: 在屏幕前，正在活动
环境光线: 明亮（185 lux）
连续时长: 78 分钟
场景描述: 用户在电脑前写代码，桌面放着一杯咖啡
```

或者光线暗时：

```
[环境感知]
用户状态: 在屏幕前，静坐
环境光线: 昏暗（8 lux）
连续时长: 125 分钟
⚠️ 已连续工作超过 2 小时
场景描述: 用户在屏幕前，房间光线暗，只有屏幕光
```

---

## 6. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `config.py` | 修改 +6 行 | 5 个 Camera 配置项 |
| `.env.example` | 修改 +5 行 | 注释 |
| `plugins/builtin/visual_perception_plugin.py` | **新建** | CameraWatcher + VisualPerceptionPlugin |
| `engine.py` | 修改 +1 行 | 注册插件 |

---

## 7. 依赖

```
opencv-python>=4.8.0
```

无摄像头时 `CAMERA_ENABLED=false` 即可跳过。
