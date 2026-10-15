# apps/dsn_ui/thought_cache.py
"""思考链缓存（thought-chain cache）——「思路模板」的存储、蒸馏、排队与检索。

问题：面对相似任务（例如「查一下今天北京的天气」），模型每次都要重新探索
一遍推理路径，重复调用工具、浪费步数。

方案：一轮任务完成后，把「用户请求 + 推理/工具调用链 + 最终回复」交给
蒸馏模型（可以是同一个模型，也可以是配置里专门指定的 cache 模型），让它
输出一个**最短路径**的 JSON 思路模板，落库为可复用的 思路模板（thought
template）。之后的相似任务通过 cache.recall 工具取回模板，直接照着最短
路径执行。

设计要点
--------
* 存储：专用 sqlite 库 apps/dsn_ui/data/thought_cache.db（stdlib sqlite3，
  每次操作一个短连接，天然线程安全；按 task_signature 去重，同签名覆盖为
  最新流程而不是新增一行）。
* 签名：低成本、无需 embedding 的归一化规则（见 normalize_signature）。
* 蒸馏：**单后台守护线程串行消费队列**。enqueue_distill() 只入队并立即
  返回，绝不阻塞 HTTP 响应；前一个任务没跑完时新任务在队列里排队。
* 模型调用：在工作线程里通过 orchestrator.invoke 完成（同步阻塞，因此
  不能跑在事件循环线程上）。

任务签名规则（normalize_signature）
----------------------------------
1. 转小写；
2. 把所有非 [0-9a-z] 与 CJK 的字符（标点/空白/符号）替换为空格；
3. 删除常见功能词短语（查一下 / 帮我 / 怎么样 / 如何 / 是什么 …）；
4. 按「ASCII 单词 + 单个 CJK 汉字」切分 token，丢弃单字停用词
   （的/了/吗/是/在/我/你/想/要/帮/查/问/怎/么…）；
5. 去重后按字典序排序，用空格连接。

例：「查一下今天北京的天气」与「北京今天天气怎么样」都归一化为
「京 北 天 今 气」（sorted set），因此命中同一模板。
这是刻意的轻量近似：签名相同即“同一类任务”，签名不同时 recall 还会退化为
token 重叠度（Jaccard）排序，不会因为一个功能词差异就完全找不到。
"""

from __future__ import annotations

import json
import logging
import queue
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("DSNUIThoughtCache")


# ────────────────────────── 配置 ──────────────────────────

DEFAULT_CONFIG: dict = {
    "enabled": True,
    "model": None,          # None = 沿用当轮对话模型
    "top_k": 3,
    "min_tool_calls": 1,    # 至少有这么多次工具调用的轮次才值得蒸馏
    "max_context_chars": 6000,
}

#: 在 agent_settings.json 里占用的键（复用 Agent 设置文件的持久化模式）。
SETTINGS_KEY = "thought_cache"
#: 侧车文件：agent.py 的 _save_settings() 会整文件覆盖 agent_settings.json，
#: 因此额外写一份，保证思考链缓存配置不会被 Agent 设置改写冲掉。
SIDECAR_FILE = "thought_cache_config.json"


def _clamp_int(val: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _validate_config(raw: dict) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(raw, dict):
        if "enabled" in raw:
            cfg["enabled"] = bool(raw.get("enabled"))
        if "model" in raw:
            m = raw.get("model")
            m = str(m).strip() if m else ""
            cfg["model"] = m or None
        if "top_k" in raw:
            cfg["top_k"] = _clamp_int(raw.get("top_k"), 1, 20, DEFAULT_CONFIG["top_k"])
        if "min_tool_calls" in raw:
            cfg["min_tool_calls"] = _clamp_int(raw.get("min_tool_calls"), 0, 50, DEFAULT_CONFIG["min_tool_calls"])
        if "max_context_chars" in raw:
            cfg["max_context_chars"] = _clamp_int(raw.get("max_context_chars"), 500, 200000, DEFAULT_CONFIG["max_context_chars"])
    return cfg


# ────────────────────────── 任务签名 ──────────────────────────

#: 先按短语删除的功能词（多字，优先于单字停用词）。
_STOP_PHRASES = (
    "查一下", "查一查", "帮我查", "帮我", "请问", "帮我看看",
    "怎么样", "怎么样呢", "是什么", "有没有", "能不能", "可不可以",
    "如何", "为什么", "怎么", "什么",
)

#: 单 token 停用词（CJK 单字 + 英文功能词）。
_STOP_TOKENS = set(
    "的 了 吗 呢 吧 啊 呀 哦 嗯 是 在 有 我 你 他 她 它 们 想 要 会 能 可 以 "
    "请 帮 查 问 看 给 和 与 或 就 都 也 很 个 这 那 些 什 么 怎 样 为 下 一 "
    "上 中 对 把 被 到 从 让 说 做 用 好 来 去 那 里 地 得 着 过 还 只 又".split()
)
_STOP_TOKENS |= {
    "the", "a", "an", "of", "to", "for", "in", "on", "at", "is", "are", "be",
    "and", "or", "with", "how", "what", "please", "help", "me", "my", "i",
}

#: 非「数字/字母/CJK」一律视为标点/空白。
_PUNCT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
#: 工具调用标记：server 侧把每个 tool call 格式化为 "[tool] name(args)" 一行。
_TOOL_MARKER_RE = re.compile(r"^\s*\[tool\]", re.MULTILINE)

#: 兜底（非精确签名）匹配的最低 token 重叠度（Jaccard）。
#: 低于它视为不相关 —— 否则两个任务只要共享一个常用字（如「天」）就会互相命中。
_MIN_OVERLAP = 0.2


def normalize_signature(text: str) -> str:
    """把任务文本归一化为稳定的签名串（见模块 docstring 的规则）。"""
    s = (text or "").lower()
    s = _PUNCT_RE.sub(" ", s)
    for phrase in _STOP_PHRASES:
        if phrase in s:
            s = s.replace(phrase, " ")
    tokens = [t for t in _TOKEN_RE.findall(s) if t not in _STOP_TOKENS]
    return " ".join(sorted(set(tokens)))


def signature_tokens(signature: str) -> set:
    """把签名串拆成 token 集合；空签名返回空集。"""
    return {t for t in (signature or "").split() if t}


def count_tool_calls(chain: str) -> int:
    """统计链条里 [tool] 标记的数量（= 本轮真实工具调用次数）。"""
    return len(_TOOL_MARKER_RE.findall(chain or ""))


def truncate_middle(text: str, max_chars: int) -> str:
    """超长文本保留首尾、截断中间（比只留头部更不容易丢结论）。"""
    text = text or ""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars < 200:
        return text[:max_chars]
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + "\n...[上下文过长，已截断中间部分]...\n" + text[-tail:]


# ────────────────────────── 存储 ──────────────────────────

_COLUMNS = (
    "id", "task_signature", "intent", "steps", "tools", "model",
    "created_at", "updated_at", "hits", "success_count",
    "source_conv_id", "source_message_id", "notes",
)


class ThoughtCacheStore:
    """思路模板的 sqlite 持久化（每次操作一个短连接，线程安全）。"""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    # ── 连接 ──

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _cursor(self):
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        """建表（幂等）。"""
        with self._cursor() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS thought_templates (
                    id TEXT PRIMARY KEY,
                    task_signature TEXT UNIQUE,
                    intent TEXT DEFAULT '',
                    steps TEXT DEFAULT '[]',
                    tools TEXT DEFAULT '[]',
                    model TEXT DEFAULT '',
                    created_at REAL DEFAULT 0,
                    updated_at REAL DEFAULT 0,
                    hits INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    source_conv_id TEXT DEFAULT '',
                    source_message_id TEXT DEFAULT '',
                    notes TEXT DEFAULT ''
                )
                """
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_thought_sig "
                "ON thought_templates(task_signature)"
            )
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_thought_updated "
                "ON thought_templates(updated_at DESC)"
            )

    # ── 行转换 ──

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = {k: row[k] for k in _COLUMNS if k in row.keys()}
        for key, default in (("steps", []), ("tools", [])):
            try:
                parsed = json.loads(d.get(key) or "null")
                d[key] = parsed if isinstance(parsed, list) else list(default)
            except Exception:  # noqa: BLE001
                d[key] = list(default)
        d["hits"] = int(d.get("hits") or 0)
        d["success_count"] = int(d.get("success_count") or 0)
        return d

    # ── CRUD ──

    def upsert(
        self,
        task_signature: str,
        *,
        intent: str = "",
        steps: Optional[list] = None,
        tools: Optional[list] = None,
        model: str = "",
        source_conv_id: str = "",
        source_message_id: str = "",
        notes: str = "",
    ) -> tuple[dict, bool]:
        """按 task_signature 去重写入；返回 (record, created)。"""
        signature = task_signature or ""
        steps = steps if isinstance(steps, list) else []
        tools = tools if isinstance(tools, list) else []
        now = time.time()
        existing = self.get_by_signature(signature)
        if existing:
            with self._cursor() as c:
                c.execute(
                    "UPDATE thought_templates SET intent=?, steps=?, tools=?, model=?, "
                    "updated_at=?, source_conv_id=?, source_message_id=?, notes=? "
                    "WHERE id=?",
                    (
                        intent, json.dumps(steps, ensure_ascii=False),
                        json.dumps(tools, ensure_ascii=False), model, now,
                        source_conv_id, source_message_id, notes, existing["id"],
                    ),
                )
            return self.get(existing["id"]), False
        record_id = uuid.uuid4().hex
        with self._cursor() as c:
            c.execute(
                "INSERT INTO thought_templates "
                "(id, task_signature, intent, steps, tools, model, created_at, "
                " updated_at, hits, success_count, source_conv_id, source_message_id, notes) "
                "VALUES (?,?,?,?,?,?,?,?,0,0,?,?,?)",
                (
                    record_id, signature, intent,
                    json.dumps(steps, ensure_ascii=False),
                    json.dumps(tools, ensure_ascii=False), model,
                    now, now, source_conv_id, source_message_id, notes,
                ),
            )
        return self.get(record_id), True

    def get(self, template_id: str) -> Optional[dict]:
        with self._cursor() as c:
            row = c.execute(
                "SELECT * FROM thought_templates WHERE id=?", (template_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_by_signature(self, signature: str) -> Optional[dict]:
        with self._cursor() as c:
            row = c.execute(
                "SELECT * FROM thought_templates WHERE task_signature=?", (signature,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def all(self) -> list[dict]:
        with self._cursor() as c:
            rows = c.execute(
                "SELECT * FROM thought_templates ORDER BY updated_at DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list(self, limit: int = 50, offset: int = 0, query: Optional[str] = None) -> tuple[int, list[dict]]:
        limit = max(1, min(500, int(limit or 50)))
        offset = max(0, int(offset or 0))
        where, params = "", []
        if query:
            like = f"%{query}%"
            where = "WHERE intent LIKE ? OR task_signature LIKE ?"
            params = [like, like]
        with self._cursor() as c:
            total = c.execute(
                f"SELECT COUNT(*) FROM thought_templates {where}", params
            ).fetchone()[0]
            rows = c.execute(
                f"SELECT * FROM thought_templates {where} "
                "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        return int(total), [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        with self._cursor() as c:
            return int(c.execute("SELECT COUNT(*) FROM thought_templates").fetchone()[0])

    def delete(self, template_id: str) -> bool:
        with self._cursor() as c:
            cur = c.execute("DELETE FROM thought_templates WHERE id=?", (template_id,))
            return cur.rowcount > 0

    def bump_hits(self, ids: list[str]) -> int:
        ids = [i for i in (ids or []) if i]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._cursor() as c:
            cur = c.execute(
                f"UPDATE thought_templates SET hits = hits + 1 WHERE id IN ({placeholders})",
                ids,
            )
            return int(cur.rowcount or 0)


# ────────────────────────── 蒸馏输出解析 ──────────────────────────

_DISTILL_SYSTEM = (
    "你是「思路模板」蒸馏器。阅读一次已经完成的任务（用户请求、推理与工具"
    "调用链、最终回复），写出下次遇到相似任务时的**最短路径**。"
    "只输出 JSON，不要输出任何解释或客套话。"
)


def parse_distill_output(raw: str) -> dict:
    """稳健解析蒸馏模型的输出。

    支持 fenced JSON、裸 JSON、以及前后夹带文字的情况；
    解析失败时**不抛异常**：把原文放进 notes、steps=[]，保证仍可落库。
    """
    text = (raw or "").strip()
    candidate = text
    fenced = re.search(r"(\x60\x60\x60)(?:json)?\s*(.*?)\1", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(2).strip()
    obj = None
    try:
        obj = json.loads(candidate)
    except Exception:  # noqa: BLE001
        brace = re.search(r"\{.*\}", candidate, re.DOTALL)
        if brace:
            try:
                obj = json.loads(brace.group(0))
            except Exception:  # noqa: BLE001
                obj = None
    if not isinstance(obj, dict):
        return {
            "intent": "", "task_signature_hint": "", "steps": [],
            "notes": text, "parse_ok": False,
        }
    raw_steps = obj.get("steps")
    steps: list[dict] = []
    if isinstance(raw_steps, list):
        for s in raw_steps:
            if isinstance(s, dict):
                steps.append({
                    "tool": str(s.get("tool") or ""),
                    "why": str(s.get("why") or ""),
                })
            elif isinstance(s, str):
                steps.append({"tool": s, "why": ""})
    return {
        "intent": str(obj.get("intent") or ""),
        "task_signature_hint": str(obj.get("task_signature_hint") or ""),
        "steps": steps,
        "notes": str(obj.get("notes") or ""),
        "parse_ok": True,
    }


# ────────────────────────── 服务 ──────────────────────────

class ThoughtCacheService:
    """思路模板服务：配置 + 串行蒸馏队列 + 检索。"""

    def __init__(self, orchestrator: Any = None, store: Any = None,
                 settings: Any = None, data_dir: Optional[Path | str] = None):
        self.orchestrator = orchestrator
        self._settings = settings
        if data_dir is None:
            if store is not None and getattr(store, "db_path", None):
                data_dir = Path(store.db_path).parent
            elif settings is not None and getattr(settings, "data_dir", None):
                data_dir = Path(settings.data_dir)
            else:
                data_dir = Path(__file__).resolve().parent / "data"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = store or ThoughtCacheStore(self.data_dir / "thought_cache.db")

        self._config_lock = threading.Lock()
        self._config = self._load_config()

        self._queue: "queue.Queue[Optional[dict]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._current: Optional[dict] = None
        self._last_error: Optional[str] = None
        self._emitter: Optional[Callable[[dict], None]] = None
        logger.info(
            "思考链缓存服务初始化: db=%s enabled=%s model=%s top_k=%s",
            getattr(self.store, "db_path", "?"), self._config["enabled"],
            self._config["model"] or "(沿用当轮模型)", self._config["top_k"],
        )

    # ── 配置持久化 ──

    def _settings_file(self) -> Path:
        return self.data_dir / "agent_settings.json"

    def _sidecar_file(self) -> Path:
        return self.data_dir / SIDECAR_FILE

    def _load_config(self) -> dict:
        raw_cfg: dict = {}
        # 先读侧车（抗覆盖），再读 agent_settings.json（更权威、可被设置页编辑）。
        for f in (self._sidecar_file(), self._settings_file()):
            try:
                if f.exists():
                    payload = json.loads(f.read_text(encoding="utf-8"))
                    sub = payload.get(SETTINGS_KEY) if isinstance(payload, dict) else None
                    if isinstance(sub, dict):
                        raw_cfg.update(sub)
            except Exception as e:  # noqa: BLE001
                logger.debug("读取思考链缓存配置失败 %s: %s", f, e)
        return _validate_config(raw_cfg)

    def _persist_config(self, cfg: dict) -> None:
        blob = json.dumps(cfg, ensure_ascii=False, indent=2)
        try:
            self._sidecar_file().write_text(blob, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("写入思考链缓存侧车配置失败: %s", e)
        try:
            f = self._settings_file()
            raw: dict = {}
            if f.exists():
                loaded = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
            raw[SETTINGS_KEY] = cfg
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            logger.warning("写入 agent_settings.json 的 thought_cache 配置失败: %s", e)

    def get_config(self) -> dict:
        with self._config_lock:
            return dict(self._config)

    def update_config(self, **kwargs) -> dict:
        """更新配置字段并持久化，返回最新配置。非法值会被钳制/忽略。"""
        with self._config_lock:
            merged = dict(self._config)
            merged.update({k: v for k, v in kwargs.items() if k in DEFAULT_CONFIG})
            self._config = _validate_config(merged)
            cfg = dict(self._config)
        self._persist_config(cfg)
        logger.info("思考链缓存配置已更新: %s", cfg)
        return cfg

    # ── SSE 事件 ──

    def set_emitter(self, fn: Optional[Callable[[dict], None]]) -> None:
        """注册事件回调（在工作线程/调用线程被调用，必须自身线程安全）。"""
        self._emitter = fn

    def _emit(self, state: str, job: dict) -> None:
        fn = self._emitter
        if fn is None:
            return
        payload = {
            "state": state,
            "message_id": job.get("message_id", ""),
            "conv_id": job.get("conv_id", ""),
            "count": self.store.count(),
            "queue_depth": self._queue.qsize(),
        }
        try:
            fn(payload)
        except Exception as e:  # noqa: BLE001 - 事件推送失败不得影响蒸馏
            logger.debug("思考链缓存事件推送失败: %s", e)

    # ── 状态 ──

    def status(self) -> dict:
        with self._state_lock:
            current = dict(self._current) if self._current else None
        cfg = self.get_config()
        return {
            "enabled": bool(cfg.get("enabled")),
            "model": cfg.get("model"),
            "running": current is not None,
            "queue_depth": self._queue.qsize(),
            "current": current,
            "total_templates": self.store.count(),
            "last_error": self._last_error,
        }

    # ── 入队 ──

    def enqueue_distill(self, conv_id: str, message_id: str, context: str,
                        chain: str, model: Optional[str] = None,
                        force: bool = False) -> Optional[str]:
        """把一轮完成的任务入队蒸馏；立即返回 job id（disabled/不值得缓存时 None）。

        本方法**绝不阻塞**：只做 O(1) 入队与一次事件推送。
        chain 中每个工具调用一行、以 "[tool]" 开头（见 count_tool_calls）。
        force=True 时跳过 min_tool_calls 门槛（供手动触发接口使用）。
        """
        if not self.get_config().get("enabled", True):
            return None
        if not force and count_tool_calls(chain) < int(self.get_config().get("min_tool_calls", 1)):
            return None
        if not (context or "").strip() and not (chain or "").strip():
            return None
        job = {
            "id": uuid.uuid4().hex,
            "conv_id": str(conv_id or ""),
            "message_id": str(message_id or ""),
            "context": context or "",
            "chain": chain or "",
            "model": model or None,
            "enqueued_at": time.time(),
        }
        self._queue.put(job)
        self._emit("queued", job)
        return job["id"]

    # ── 工作线程 ──

    def start(self) -> None:
        """启动单后台守护线程（重复调用无副作用）。"""
        with self._state_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop.clear()
            self._worker = threading.Thread(
                target=self._worker_loop, name="dsnui-thought-cache", daemon=True
            )
            self._worker.start()
        logger.info("思考链缓存工作线程已启动")

    def shutdown(self, timeout: float = 5.0) -> None:
        """请求停止并等待工作线程退出。"""
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except Exception:  # noqa: BLE001
            pass
        with self._state_lock:
            worker = self._worker
            self._worker = None
        if worker is not None and worker.is_alive():
            worker.join(timeout=timeout)
        logger.info("思考链缓存工作线程已停止")

    def _worker_loop(self) -> None:
        """唯一消费者：串行蒸馏，前一个跑完才轮到下一个（下一个排队执行）。"""
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue
            if job is None:
                break
            with self._state_lock:
                self._current = {
                    "id": job.get("id"),
                    "conv_id": job.get("conv_id", ""),
                    "message_id": job.get("message_id", ""),
                    "state": "running",
                    "started_at": time.time(),
                }
            self._emit("running", job)
            try:
                record = self._distill_job(job)
                with self._state_lock:
                    self._last_error = None
                self._emit("done", job)
                logger.info(
                    "思路蒸馏完成: conv=%s sig=%r steps=%d",
                    job.get("conv_id"), (record or {}).get("task_signature"),
                    len((record or {}).get("steps") or []),
                )
            except Exception as e:  # noqa: BLE001 - 单个任务失败不能拖垮 worker
                with self._state_lock:
                    self._last_error = str(e)
                logger.exception("思路蒸馏失败: %s", e)
                self._emit("error", job)
            finally:
                with self._state_lock:
                    self._current = None
                self._queue.task_done()

    # ── 蒸馏 ──

    @staticmethod
    def _task_text(job: dict) -> str:
        """从 context 的首个非空行取任务文本（容忍 用户请求: 前缀）。"""
        for line in (job.get("context") or "").splitlines():
            line = line.strip()
            if line:
                return re.sub(r"^(用户请求|user|task)\s*[:：]\s*", "", line, flags=re.I)
        return ""

    def _build_prompt(self, job: dict) -> str:
        max_chars = int(self.get_config().get("max_context_chars", 6000))
        task = self._task_text(job) or "(未提供任务文本)"
        context = truncate_middle(job.get("context") or "", max_chars)
        chain = truncate_middle(job.get("chain") or "", max_chars)
        return (
            f"任务：{task}\n\n"
            f"上下文与最终回复：\n{context}\n\n"
            f"工具调用链（[tool] = 调用，[result] = 结果）：\n{chain}\n\n"
            "请输出严格 JSON（不要输出代码块之外的任何文字）：\n"
            '{"intent": "一句话任务描述", "task_signature_hint": "稳定短关键词", '
            '"steps": [{"tool": "工具名", "why": "为什么这一步是必要的"}], '
            '"notes": "注意事项"}\n'
            "要求：\n"
            "- steps 只保留最短路径上真正必要的步骤，复用上面出现过的工具名；\n"
            "- 不要发明新工具；如果不需要工具，steps 输出空数组 [].\n"
        )

    def _call_model(self, prompt: str, model: str) -> str:
        """在工作线程里同步调用蒸馏模型。"""
        if self.orchestrator is None:
            raise RuntimeError("orchestrator 不可用，无法运行思路蒸馏")
        from infra.orchestrator import ChatMessage

        messages = [ChatMessage.system(_DISTILL_SYSTEM), ChatMessage.user(prompt)]
        resp = self.orchestrator.invoke(
            messages, model_name=model, temperature=0.2, max_tokens=800,
        )
        return str(getattr(resp, "content", None) or "")

    def _distill_job(self, job: dict) -> dict:
        """执行一次蒸馏并落库（由工作线程串行调用）。"""
        model = (self.get_config().get("model") or job.get("model") or "").strip()
        if not model:
            raise RuntimeError("未指定蒸馏模型（config.model 为空且本轮模型未知）")
        prompt = self._build_prompt(job)
        raw = self._call_model(prompt, model)
        parsed = parse_distill_output(raw)
        task = self._task_text(job)
        signature = normalize_signature(task)
        if not signature:
            # 任务文本缺失时退而求其次：用模型给的 hint，再不行用工具链。
            signature = normalize_signature(parsed.get("task_signature_hint") or "")
        if not signature:
            signature = normalize_signature(job.get("chain") or "")
        steps = parsed.get("steps") or []
        tools = [s.get("tool") for s in steps if isinstance(s, dict) and s.get("tool")]
        notes = parsed.get("notes") or ""
        if not parsed.get("parse_ok") and raw:
            logger.warning("蒸馏输出不是合法 JSON，已把原文存入 notes")
        record, created = self.store.upsert(
            signature,
            intent=parsed.get("intent") or task,
            steps=steps,
            tools=tools,
            model=model,
            source_conv_id=job.get("conv_id", ""),
            source_message_id=job.get("message_id", ""),
            notes=notes,
        )
        record["created"] = created
        return record

    # ── 检索 ──

    def recall(self, query: str, limit: Optional[int] = None) -> list[dict]:
        """检索最匹配的思路模板并累加 hits。

        先精确匹配 task_signature，再按 token 重叠度（Jaccard）排序兜底。
        """
        query = (query or "").strip()
        if not query:
            return []
        qsig = normalize_signature(query)
        q_tokens = signature_tokens(qsig)
        rows = self.store.all()
        if not rows:
            return []

        scored: list[tuple[float, float, float, dict]] = []
        for row in rows:
            sig = row.get("task_signature") or ""
            if qsig and sig == qsig:
                score = 2.0
            else:
                t_tokens = signature_tokens(sig)
                if q_tokens and t_tokens:
                    inter = len(q_tokens & t_tokens)
                    score = inter / len(q_tokens | t_tokens) if inter else 0.0
                else:
                    score = 0.0
                if score < _MIN_OVERLAP:
                    score = 0.0
            if score <= 0:
                continue
            scored.append((score, float(row.get("hits") or 0), float(row.get("updated_at") or 0), row))

        if not scored:
            return []
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        top_k = max(1, int(self.get_config().get("top_k", 3)))
        take = max(1, int(limit)) if limit else top_k
        matched = [row for _, _, _, row in scored[:take]]
        try:
            self.store.bump_hits([r.get("id") for r in matched])
            for r in matched:
                r["hits"] = int(r.get("hits") or 0) + 1
        except Exception as e:  # noqa: BLE001 - 计数失败不影响检索结果
            logger.warning("更新思路模板 hits 失败: %s", e)
        return matched

    # ── 管理 ──

    def list_templates(self, limit: int = 50, offset: int = 0,
                       query: Optional[str] = None) -> tuple[int, list[dict]]:
        return self.store.list(limit=limit, offset=offset, query=query)

    def delete_template(self, template_id: str) -> bool:
        return self.store.delete(template_id)
