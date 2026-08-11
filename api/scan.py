# api/scan.py
# 快速扫题 API — 批量拍照 → 后端逐个异步 VLM 提取题目(JSON)入库 → 全部完成后
# 一次性把整批处理结果发给主模型，由主模型总结并简洁反馈用户。
#
# 流程:
#   1. POST /api/scan/select_camera
#        客户端首次扫题时枚举+回传多台摄像头画面，后端用 VLM 逐台描述，
#        再由主AI判定哪台摄像头正对着桌面文档，返回该摄像头逻辑名（客户端持久化）。
#   2. POST /api/scan/quick   （可连续多次调用，构成一批照片）
#        客户端用已选定的摄像头立刻拍照回传 → 后端给该照片分配 photo_id 并入当前批次，
#        后台 worker 串行执行 VLM 提取 → QuestionStore 入库，结果写回批次状态。
#   3. POST /api/scan/finish  （客户端停止拍照后调用）
#        标记批次结束 → 后台 worker 等待该批所有照片识别入库完毕 → 汇总整批结果
#        → 只调用一次主模型总结反馈（task_id 经 AsyncTaskPoller 轮询播放）。

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid

from flask import Blueprint, request, jsonify, g, current_app

from plugins.base import PluginContext

logger = logging.getLogger("Scan")

scan_bp = Blueprint("scan_api", __name__)

_auth_manager = None

# 批量扫题等待所有照片入库的兜底超时（秒）
QUICK_SCAN_BATCH_WAIT = float(os.environ.get("QUICK_SCAN_BATCH_WAIT", "600"))

# 扫题总结调用主模型的超时兜底（秒）：超过则用统计文案回复，避免模型繁忙时卡住任务
QUICK_SCAN_SUMMARY_TIMEOUT = float(os.environ.get("QUICK_SCAN_SUMMARY_TIMEOUT", "45"))

# ── 批次状态（内存，按用户隔离） ──
_batch_lock = threading.Lock()
_batches: dict[int, dict] = {}          # user_id -> batch
_photo_worker_locks: dict[int, threading.Lock] = {}   # 每用户串行处理照片，避免并发打爆模型/写库
_photo_worker_locks_guard = threading.Lock()

# 摄像头选择结果缓存（user_id -> logical_name），会话内复用，避免反复跑 VLM/网络
_select_camera_cache: dict[int, str] = {}
_select_camera_cache_lock = threading.Lock()


def _user_photo_lock(user_id: int) -> threading.Lock:
    with _photo_worker_locks_guard:
        lock = _photo_worker_locks.setdefault(user_id, threading.Lock())
    return lock


def init_scan_api(auth_manager=None):
    """注入依赖（boot.py 启动时调用）。"""
    global _auth_manager
    _auth_manager = auth_manager


@scan_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


# ── 依赖获取 ──

def _get_engine():
    return current_app.config.get("ENGINE")


def _get_question_store(engine):
    if engine and engine.question_store:
        return engine.question_store
    from config import Config
    from db.question_bank import QuestionBankDBManager
    from question_bank.store import QuestionStore
    return QuestionStore(db=QuestionBankDBManager(db_path=Config.QUESTION_BANK_DB_PATH))


def _get_template_manager(engine):
    if engine and engine.template_manager:
        return engine.template_manager
    from config import Config
    from db.question_bank import QuestionBankDBManager
    from question_bank.template_manager import SubjectTemplateManager
    return SubjectTemplateManager(db=QuestionBankDBManager(db_path=Config.QUESTION_BANK_DB_PATH))


# ── 摄像头选择：首次询问主AI ──

@scan_bp.route("/api/scan/select_camera", methods=["POST"])
def select_camera():
    """body: {frames: [{logical_name, image_data}, ...]} → {logical_name}"""
    data = request.get_json(silent=True) or {}
    frames = data.get("frames") or []
    if not frames:
        return jsonify({"error": "缺少 frames"}), 400

    user_id = g.user.get("uid", 0)

    with _select_camera_cache_lock:
        cached = _select_camera_cache.get(user_id)
    if cached:
        return jsonify({"success": True, "logical_name": cached})

    try:
        logical_name = _choose_document_camera(frames, user_id)
    except Exception as e:
        logger.error("选择扫描摄像头失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": f"选择失败: {e}"}), 500

    if not logical_name:
        return jsonify({"success": False, "error": "未能确定面向文档的摄像头，已回退到默认机位"}), 200
    return jsonify({"success": True, "logical_name": logical_name})


def _choose_document_camera(frames: list, user_id: int = 0) -> str:
    """逐台 VLM 判定哪台正对桌面文档，返回逻辑名；无法确定返回空串。

    只调用视觉模型（glm-4.6v 等，毫秒级），不再调用主模型判定——
    修复此前“主模型选择摄像头失败: 无法在 300s 内获取模型使用权”导致的
    扫题长时间卡死。结果按用户缓存，后续扫题直接复用。
    """
    named = [f.get("logical_name", "").strip() for f in frames if f.get("logical_name")]
    if not named:
        return ""

    # 只有一台摄像头：直接使用，省去一轮 VLM 判定
    if len(named) == 1:
        chosen = named[0]
    else:
        from models.clients import VisionModel
        vm = VisionModel()
        prompt = (
            "请判断这张摄像头拍摄的画面：画面里是否有桌面上的纸质文档"
            "（试卷/习题册/笔记/书本页面）？"
            "只回答\"是文档\"或\"不是文档\"，再简短说明你看到的物体。"
        )
        matches = []
        for f in frames:
            name = (f.get("logical_name") or "").strip()
            img = f.get("image_data") or ""
            if not name or not img:
                continue
            try:
                desc = vm.ask(data_url=img, prompt=prompt, max_tokens=100, temperature=0.0)
            except Exception as e:
                logger.warning("摄像头 %s 画面分析失败: %s", name, e)
                desc = ""
            logger.info("摄像头 %s 文档判定: %r", name, (desc or "")[:80])
            if desc and "是文档" in desc and "不是文档" not in desc:
                matches.append(name)
        chosen = matches[0] if matches else ""

    if chosen and user_id:
        with _select_camera_cache_lock:
            _select_camera_cache[user_id] = chosen
    return chosen


# ── 批量拍照 ──

def _open_batch(user_id: int) -> dict:
    """取当前批次；无/已结束则新开一批。"""
    with _batch_lock:
        b = _batches.get(user_id)
        if b is None or b["finalized"]:
            b = {
                "batch_id": uuid.uuid4().hex[:12],
                "user_id": user_id,
                "photos": {},          # photo_id -> {status, result}
                "finalized": False,
                "created_at": time.time(),
            }
            _batches[user_id] = b
        return b


@scan_bp.route("/api/scan/quick", methods=["POST"])
def quick_scan():
    """body: {image_data, camera?, chat_id?, subject_code?} → {photo_id, batch_id}。

    客户端连续按扫题键即可向当前批次追加照片；后台异步 VLM 提取+入库，不阻塞响应。
    """
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    image_data = data.get("image_data", "")
    if not image_data:
        return jsonify({"error": "缺少 image_data"}), 400

    user_id = g.user.get("uid", 0)
    chat_id = data.get("chat_id", 0) or 0
    camera = data.get("camera", "") or ""
    subject_code = data.get("subject_code", "") or _guess_subject_code(engine)

    batch = _open_batch(user_id)
    photo_id = f"p_{uuid.uuid4().hex[:8]}"
    with _batch_lock:
        batch["photos"][photo_id] = {"status": "running", "result": None}

    threading.Thread(
        target=_photo_worker,
        args=(engine, user_id, photo_id, image_data, subject_code),
        daemon=True, name=f"scan-photo-{user_id}",
    ).start()

    logger.info("扫题照片入队: user=%d photo=%s batch=%s", user_id, photo_id, batch["batch_id"])
    return jsonify({
        "success": True,
        "photo_id": photo_id,
        "batch_id": batch["batch_id"],
        "count": len(batch["photos"]),
    })


def _photo_worker(engine, user_id: int, photo_id: str, image_data: str,
                  subject_code: str) -> None:
    """单张照片：VLM 提取 → 入库 → 写回批次状态（同用户串行）。"""
    batch = _batches.get(user_id)
    try:
        with _user_photo_lock(user_id):
            result = _extract_and_store(engine, image_data, subject_code)
        with _batch_lock:
            if batch is not None and not batch["finalized"]:
                batch["photos"][photo_id]["status"] = "done"
                batch["photos"][photo_id]["result"] = result
        logger.info("扫题照片完成: user=%d photo=%s 识别=%d 入库=%d",
                    user_id, photo_id, result.get("questions_found", 0),
                    result.get("questions_added", 0))
    except Exception as e:
        logger.error("扫题照片失败 %s: %s", photo_id, e, exc_info=True)
        with _batch_lock:
            if batch is not None and not batch["finalized"]:
                batch["photos"][photo_id]["status"] = "error"
                batch["photos"][photo_id]["result"] = {"error": str(e)}


@scan_bp.route("/api/scan/finish", methods=["POST"])
def finish_scan():
    """body: {chat_id?} → {task_id, count}。

    标记当前批次结束 → 等待该批所有照片识别入库完毕 → 一次性调用主模型总结反馈。
    """
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    user_id = g.user.get("uid", 0)
    chat_id = data.get("chat_id", 0) or 0

    with _batch_lock:
        b = _batches.get(user_id)
        if b is None or b["finalized"] or not b["photos"]:
            return jsonify({"success": False, "error": "没有待汇总的扫题批次"}), 400
        b["finalized"] = True
        count = len(b["photos"])

    task_id = f"scan_{uuid.uuid4().hex[:16]}"
    store = engine.async_task_store
    store.create(task_id, user_id, chat_id)

    threading.Thread(
        target=_finalize_worker,
        args=(engine, task_id, user_id, chat_id, b),
        daemon=True, name=f"scan-finalize-{user_id}",
    ).start()

    logger.info("扫题批次结束: user=%d batch=%s photos=%d task=%s",
                user_id, b["batch_id"], count, task_id)
    return jsonify({"success": True, "task_id": task_id, "count": count})


def _finalize_worker(engine, task_id: str, user_id: int, chat_id, batch: dict) -> None:
    """等待整批照片识别入库完毕 → 汇总 → 一次性调用主模型总结反馈。"""
    store = engine.async_task_store

    deadline = time.time() + QUICK_SCAN_BATCH_WAIT
    while time.time() < deadline:
        with _batch_lock:
            if all(p["status"] in ("done", "error") for p in batch["photos"].values()):
                break
        time.sleep(0.3)

    with _batch_lock:
        results = [dict(p.get("result") or {}) for p in batch["photos"].values()
                   if p["status"] == "done"]
        errors = [str(p["result"].get("error", "")) for p in batch["photos"].values()
                  if p["status"] == "error"]
    # 未在时限内完成的照片按失败计入
    pending = sum(1 for p in batch["photos"].values() if p["status"] == "running")
    if pending:
        errors.append(f"{pending} 张照片识别超时未完成")
    if not results and not errors:
        store.complete(task_id, reply="", error="批次中没有有效照片")
        return

    message = _build_batch_message(results, errors)

    ctx = PluginContext(
        user_id=user_id,
        message=message,
        chat_id=chat_id,
        history=[],
        full_history=[],
    )
    ctx.extra["_scan_batch_task_id"] = task_id
    ctx.tts_enabled = True

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result_ctx = loop.run_until_complete(
            asyncio.wait_for(engine.pipeline.process(ctx), timeout=QUICK_SCAN_SUMMARY_TIMEOUT))
        reply = result_ctx.reply or ""
        audio_b64 = result_ctx.audio_b64 or ""
        if not reply:
            store.complete(task_id, reply="扫题完成，题目已全部入库。", error="")
        else:
            store.complete(task_id, reply=reply, audio_b64=audio_b64)
    except asyncio.TimeoutError:
        logger.warning("扫题总结超时（>%ss），改用统计兜底回复", QUICK_SCAN_SUMMARY_TIMEOUT)
        store.complete(task_id, reply=_build_fallback_reply(results, errors), error="")
    except Exception as e:
        logger.error("扫题总结任务失败 %s: %s", task_id, e, exc_info=True)
        store.complete(task_id, reply="", error=str(e))
    finally:
        loop.close()

    total_found = sum(r.get("questions_found", 0) for r in results)
    total_added = sum(r.get("questions_added", 0) for r in results)
    logger.info("扫题批次完成: user=%d batch=%s 照片=%d 识别=%d 入库=%d",
                user_id, batch["batch_id"], len(results), total_found, total_added)


def _build_batch_message(results: list, errors: list) -> str:
    """把整批照片的处理结果拼成一条主模型消息。"""
    total_found = sum(r.get("questions_found", 0) for r in results)
    total_added = sum(r.get("questions_added", 0) for r in results)

    lines = []
    for i, r in enumerate(results, 1):
        subjects = r.get("subjects") or []
        subj_txt = "/".join(subjects) if subjects else r.get("subject_code", "")
        line = (f"- 第{i}张照片: 识别 {r.get('questions_found', 0)} 题, "
                f"入库 {r.get('questions_added', 0)} 题 (科目: {subj_txt or '未知'})")
        added = r.get("added", [])
        if added:
            previews = "；".join(f"[#{q['id']}] {q['content'][:60]}" for q in added[:5])
            line += f"\n    已入库题目: {previews}"
        lines.append(line)
    if errors:
        lines.append(f"- 失败照片: {len(errors)} 张（{'；'.join(errors[:3])}）")

    return (
        f"【系统消息】用户刚通过摄像头一口气拍了 {len(results) + len(errors)} 张照片，"
        f"全部完成识别并入库。整批结果如下:\n"
        + "\n".join(lines) +
        f"\n\n共计识别 {total_found} 题，成功入库 {total_added} 题。"
        "请向用户简洁汇报本次批量扫题结果（扫了几张、共识别/入库多少题、涉及哪些科目、有无失败照片），"
        "不要逐题罗列。"
    )


def _build_fallback_reply(results: list, errors: list) -> str:
    """主模型总结超时/失败时的统计兜底回复（不含 TTS 音频，客户端仍会收到提示音）。"""
    total_found = sum(r.get("questions_found", 0) for r in results)
    total_added = sum(r.get("questions_added", 0) for r in results)
    subjects = set()
    for r in results:
        for s in r.get("subjects") or []:
            subjects.add(s)
    subj_txt = "/".join(sorted(subjects)) if subjects else ""
    fail_txt = f"，{len(errors)} 张失败" if errors else ""
    return (
        f"本次共扫 {len(results) + len(errors)} 张照片{fail_txt}，"
        f"识别 {total_found} 题，成功入库 {total_added} 题"
        + (f"（科目：{subj_txt}）" if subj_txt else "")
        + "。"
    )


# ── 识别入库 ──

def _subject_id_by_code(subjects: list, code: str) -> int:
    for s in subjects:
        if s.get("code") == code:
            return s["subject_id"]
    return subjects[0]["subject_id"] if subjects else 1


def _match_subject(subjects: list, raw: str, fallback_code: str) -> int:
    """把 VLM 判定的科目名称/代码匹配到题库科目；无法匹配则回退到 fallback_code。"""
    fallback = _subject_id_by_code(subjects, fallback_code)
    raw = (raw or "").strip().lower()
    if not raw:
        return fallback
    for s in subjects:
        name = str(s.get("name") or "").lower()
        code = str(s.get("code") or "").lower()
        if raw == name or raw == code:
            return s["subject_id"]
        if name and name in raw:  # 容忍 "高中数学" 这类带前缀的表述
            return s["subject_id"]
    return fallback


def _extract_and_store(engine, image_data: str, subject_code: str) -> dict:
    """VLM 从图片提取题目 JSON（含自动标签/科目/题图描述）→ 逐题入库。返回统计。"""
    from models.clients import VisionModel
    vm = VisionModel()
    prompt = (
        "请仔细识别这张图片中的所有题目，返回 JSON 数组。\n"
        "每道题包含以下字段:\n"
        "- content: 题目内容\n"
        "- answer: 参考答案\n"
        "- type_name: 题型(选择题/填空题/解答题/判断题)\n"
        "- subtype: 子类型(单选/多选/填空/计算/证明/简答/判断)\n"
        "- difficulty: 难度 1-5\n"
        "- options: 选项列表(选择题才有)\n"
        "- explanation: 题目解析(选填)\n"
        "- subject: 科目(如 数学/语文/英语/物理/化学/生物，无法判断可省略)\n"
        "- tags: 标签数组，2-5个，概括本题涉及的知识点/主题(如 \"一元二次方程\"、\"电路\"、\"文言文\")。"
        "若题目属于学科综合题可给多个学科标签\n"
        "- knowledge_points: 知识点列表(选填)\n"
        "- figure_description: 该题配图/图表/图形的文字描述；若题目没有配图则为空字符串\n"
        "只返回纯 JSON 数组，不要包含其他内容。"
    )
    raw = vm.ask(data_url=image_data, prompt=prompt, max_tokens=4096, temperature=0.1)
    questions = _parse_questions(raw)

    store = _get_question_store(engine)
    tm = _get_template_manager(engine)
    subjects = tm.get_active_subjects() or []
    fallback_subject_id = _subject_id_by_code(subjects, subject_code)

    added = []
    errors = []
    subjects_used = set()
    for q in questions:
        try:
            type_name = q.get("type_name", "解答题")
            subtype = q.get("subtype", "")
            type_id = tm.get_type_id(type_name, subtype) or tm.get_type_id(type_name) or 1
            subject_id = _match_subject(subjects, q.get("subject", ""), subject_code)

            metadata = {}
            fig = q.get("figure_description")
            if isinstance(fig, str) and fig.strip():
                metadata["figure_description"] = fig.strip()
            elif isinstance(fig, list):
                metadata["figure_description"] = fig

            qid = store.create_question({
                "subject_id": subject_id,
                "type_id": type_id,
                "source": "quick_scan",
                "difficulty": q.get("difficulty", 3),
                "content": q.get("content", ""),
                "options": q.get("options", []),
                "answer": q.get("answer", ""),
                "explanation": q.get("explanation", ""),
                "tags": q.get("tags", []) or [],
                "knowledge_points": q.get("knowledge_points", []),
                "metadata": metadata,
            })
            added.append({"id": qid, "content": (q.get("content") or "")[:200]})
            for s in subjects:
                if s["subject_id"] == subject_id:
                    subjects_used.add(s.get("name") or s.get("code") or "")
                    break
        except Exception as e:
            logger.error("题目入库失败: %s", e)
            errors.append(str(e))

    if not subjects_used and fallback_subject_id:
        for s in subjects:
            if s["subject_id"] == fallback_subject_id:
                subjects_used.add(s.get("name") or s.get("code") or "")
                break

    return {
        "questions_found": len(questions),
        "questions_added": len(added),
        "added": added,
        "added_ids": [a["id"] for a in added],
        "subject_code": subject_code,
        "subjects": sorted(subjects_used),
        "errors": errors,
    }


def _guess_subject_code(engine) -> str:
    """默认科目：取第一个启用的科目，否则 math。"""
    try:
        tm = _get_template_manager(engine)
        subjects = tm.get_active_subjects()
        if subjects:
            return subjects[0].get("code", "")
    except Exception:
        pass
    return "math"


def _parse_questions(text: str) -> list:
    """解析 VLM 返回的 JSON 数组（容忍 ``` 围栏）。"""
    text = (text or "").strip()
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("识别题目 JSON 解析失败: %s", text[:200])
        return []
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) else []


# ════════════════════════════════════════════════════════════════
# 扫题打印：物理扫描仪 → VisionModel → 题库入库 → 生成可打印文档 → 打印
# 全程不调用主模型：扫描由 SANE 直接完成，题目/科目/题图描述/标准答案解析
# 全部由 VisionModel 一次输出 JSON，主模型完全不接触题目内容。
# ════════════════════════════════════════════════════════════════

_SCANPRINT_VISION_PROMPT = (
    "你是一个试卷题目提取专家。你看到的是刚从物理扫描仪扫出的一页试卷图片。\n"
    "请综合图片内容直接输出一个 JSON 对象：\n"
    "{\n"
    '  "subject": 科目代码（从 math/physics/chemistry/english/chinese/biology 中自动判断；无法判断填 "unknown"）,\n'
    '  "page_description": 整页图片的文字描述（表格/图形/实验装置等）,\n'
    '  "questions": [每道题的 JSON 对象数组]\n'
    "}\n"
    "每道题字段：\n"
    "- content: 题目原文\n"
    "- options: 选项列表，如[\"A. xxx\", \"B. xxx\"]；非选择题填 []\n"
    "- answer: 标准答案\n"
    "- explanation: 标准解析（解题步骤与思路，尽量详细）\n"
    "- type_name: \"选择题\"/\"填空题\"/\"解答题\"/\"判断题\"\n"
    "- subtype: \"单选\"/\"多选\"/\"填空\"/\"计算\"/\"证明\"/\"简答\"/\"判断\"\n"
    "- difficulty: 1-5 整数\n"
    "- tags: 字符串数组，如[\"氧化还原\",\"化学计算\"]\n"
    "- knowledge_points: 知识点字符串数组\n"
    "- figure_description: 该题配图/图表的文字描述；无配图则填\"\"\n"
    "- notes: 图片中的手写备注（无则填\"\"）\n"
    "只返回这一个 JSON 对象，不要包含其他任何内容。"
)

_SCANPRINT_CJK_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


@scan_bp.route("/api/scan/scanprint", methods=["POST"])
def scan_print():
    """body: {chat_id?} → {task_id}

    不依赖主模型：物理扫描仪第一台 → 扫描 → VisionModel 生成题库结构化
    JSON（科目/题图描述/题目原文/标准答案解析）→ 入库 → 生成可打印文档 → 打印。
    后台异步执行，客户端通过 AsyncTaskPoller 轮询 task_id 获取结果。
    """
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    user_id = g.user.get("uid", 0)
    chat_id = data.get("chat_id", 0) or 0

    task_id = f"scanprint_{uuid.uuid4().hex[:16]}"
    store = engine.async_task_store
    store.create(task_id, user_id, chat_id)

    threading.Thread(
        target=_scanprint_worker,
        args=(engine, task_id, user_id, chat_id),
        daemon=True, name=f"scanprint-{user_id}",
    ).start()

    logger.info("扫题打印任务已启动: user=%d task=%s", user_id, task_id)
    return jsonify({"success": True, "task_id": task_id})


def _scanprint_worker(engine, task_id: str, user_id: int, chat_id) -> None:
    """后台线程：扫描 → VisionModel → 入库 → 打印 → 写回异步任务结果。"""
    store = engine.async_task_store
    try:
        result = _scanprint_run(engine, user_id)
        if result.get("success"):
            store.complete(task_id, reply=result["feedback_text"])
        else:
            store.complete(task_id, reply="", error=result.get("error", "扫描打印失败"))
    except Exception as e:
        logger.error("扫题打印任务失败 %s: %s", task_id, e, exc_info=True)
        store.complete(task_id, reply="", error=str(e))


def _scanprint_run(engine, user_id: int) -> dict:
    """主流程：第一台扫描仪扫描 → VisionModel 直接结构化 → 入库 → 可打印文档 → 打印。"""
    from document.scanner import ScannerTool
    from document.printer import PrinterTool
    from models.clients import VisionModel
    from utils.workspace import get_workspace_manager

    # 1. 扫描（最前面一台扫描仪，300 DPI）
    scanners = ScannerTool.list_scanners()
    if not scanners:
        return {"success": False, "error": "未找到扫描仪（请检查连接/驱动/接口）"}
    device = scanners[0]["device"]

    wm = get_workspace_manager()
    uploads = str(wm.user_uploads_dir(uid=user_id or 1))
    scanned = ScannerTool.scan(device=device, output_dir=uploads,
                               resolution=300, mode="Color")
    if not scanned:
        return {"success": False, "error": "扫描未产出文件"}
    png_path = scanned[0]["filepath"]
    logger.info("扫题打印: 扫描完成 %s (device=%s)", png_path, device)

    # 2. VisionModel 直接生成结构化 JSON（不经主模型）
    data_url = VisionModel.encode_image(png_path)
    vm = VisionModel()
    raw = vm.ask(data_url, _SCANPRINT_VISION_PROMPT, max_tokens=8192, temperature=0.1)
    questions, subject, page_desc = _parse_scanprint(raw)
    if not questions:
        return {"success": False, "error": "视觉模型未能从扫描件中识别出题目",
                "scan_file": png_path}

    # 3. 入库（科目以 VisionModel 识别结果为准）
    store = _get_question_store(engine)
    tm = _get_template_manager(engine)
    subjects = tm.get_active_subjects() or []
    imported = []
    import_errors = []
    subjects_used = set()
    for q in questions:
        try:
            type_name = q.get("type_name", "解答题")
            subtype = q.get("subtype", "")
            type_id = tm.get_type_id(type_name, subtype) or tm.get_type_id(type_name) or 1
            subject_id = _match_subject(subjects, q.get("subject", ""), subject)

            metadata = {"source": "scan_print"}
            fig = q.get("figure_description")
            if isinstance(fig, str) and fig.strip():
                metadata["figure_description"] = fig.strip()
            notes = q.get("notes")
            if isinstance(notes, str) and notes.strip():
                metadata["handwritten_notes"] = notes.strip()

            qid = store.create_question({
                "subject_id": subject_id,
                "type_id": type_id,
                "source": "scan_print",
                "difficulty": q.get("difficulty", 3),
                "content": q.get("content", ""),
                "options": q.get("options", []),
                "answer": q.get("answer", ""),
                "explanation": q.get("explanation", ""),
                "tags": q.get("tags", []) or [],
                "knowledge_points": q.get("knowledge_points", []),
                "metadata": metadata,
            })
            imported.append({"id": qid, "content": (q.get("content") or "")[:60]})
            for s in subjects:
                if s["subject_id"] == subject_id:
                    subjects_used.add(s.get("name") or s.get("code") or "")
                    break
        except Exception as e:
            logger.error("扫题打印入库失败: %s", e)
            import_errors.append(str(e))
    if not subjects_used and subject:
        for s in subjects:
            if s.get("code") == subject:
                subjects_used.add(s.get("name") or subject)
                break

    # 4. 生成可打印文档（优先 PDF，回退 TXT）
    doc = _build_printable_doc(questions, subject, page_desc, user_id)

    # 5. 打印
    print_result = PrinterTool.print_file(doc["path"])

    # 6. 反馈
    subj_txt = "/".join(sorted(subjects_used)) if subjects_used else (subject or "未知")
    feedback = (
        f"扫描打印完成：扫描件 {os.path.basename(png_path)}，"
        f"识别 {len(questions)} 道题，入库 {len(imported)} 道"
        f"（科目：{subj_txt}）"
    )
    if print_result.get("success"):
        feedback += f"，打印任务已提交（job #{print_result.get('job_id')}）"
    else:
        feedback += f"，但打印失败：{print_result.get('error', '未知错误')}"
    if import_errors:
        feedback += f"。入库失败 {len(import_errors)} 道"
    feedback += f"。可打印文档：{doc['path']}"

    logger.info("扫题打印完成: 识别 %d 题, 入库 %d 题, 打印=%s",
                len(questions), len(imported), print_result.get("success"))

    return {
        "success": True,
        "questions_found": len(questions),
        "questions_added": len(imported),
        "subjects": sorted(subjects_used),
        "scan_file": png_path,
        "doc_path": doc["path"],
        "print": print_result,
        "feedback_text": feedback,
    }


def _parse_scanprint(text: str) -> tuple:
    """解析 VisionModel 回复（包裹对象或纯数组）。返回 (questions, subject, page_desc)。"""
    text = (text or "").strip()
    if "```" in text:
        lines = text.split("\n")
        json_lines = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_block:
                    break
                in_block = True
                continue
            if in_block:
                json_lines.append(line)
        text = "\n".join(json_lines)
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("扫描打印 JSON 解析失败: %s", text[:200])
        return [], "", ""
    if isinstance(data, dict):
        qs = data.get("questions") or data.get("items") or []
        if isinstance(qs, dict):
            qs = [qs]
        return (qs if isinstance(qs, list) else []), \
               str(data.get("subject", "") or "").strip(), \
               str(data.get("page_description", "") or "").strip()
    if isinstance(data, list):
        return data, "", ""
    return [], "", ""


def _build_printable_doc(questions: list, subject: str, page_desc: str,
                         user_id: int) -> dict:
    """生成可打印文档（优先 PDF，回退 TXT），返回 {path, fmt}。"""
    from utils.workspace import get_workspace_manager
    wm = get_workspace_manager()
    doc_dir = str(wm.user_documents_dir(uid=user_id or 1))
    os.makedirs(doc_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    stem = f"scanprint_{ts}"

    subject_name = {
        "math": "数学", "physics": "物理", "chemistry": "化学",
        "english": "英语", "chinese": "语文", "biology": "生物",
    }.get(subject, subject or "未知")

    lines = []
    lines.append("扫描试卷 · 题目与标准答案解析")
    lines.append(f"科目: {subject_name}    时间: {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append("=" * 40)
    if page_desc:
        lines.append(f"[整页图片描述] {page_desc}")
        lines.append("")
    for i, q in enumerate(questions, 1):
        lines.append(f"第 {i} 题 【{q.get('type_name', '解答题')}】")
        lines.append(q.get("content", ""))
        for o in (q.get("options") or []):
            lines.append(f"    {o}")
        lines.append(f"答案: {q.get('answer', '')}")
        if q.get("explanation"):
            lines.append(f"解析: {q.get('explanation', '')}")
        if q.get("figure_description"):
            lines.append(f"题图: {q.get('figure_description', '')}")
        lines.append("-" * 40)

    # 优先 PDF（fpdf2 + 系统 CJK 字体），失败回退纯文本
    try:
        from fpdf import FPDF
        from fpdf.enums import XPos, YPos
        font_path = None
        for cand in _SCANPRINT_CJK_FONTS:
            if os.path.isfile(cand):
                font_path = cand
                break
        pdf = FPDF()
        pdf.add_page()
        if font_path:
            pdf.add_font("CJK", "", font_path)
            pdf.set_font("CJK", size=12)
        else:
            pdf.set_font("Helvetica", size=12)
        for ln in lines:
            # new_x=LMARGIN 保证每行从左边距开始，避免下一行可用宽度被吃掉
            pdf.multi_cell(0, 6, ln, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        path = os.path.join(doc_dir, f"{stem}.pdf")
        pdf.output(path)
        return {"path": path, "fmt": "pdf"}
    except Exception as e:
        logger.warning("生成 PDF 失败，回退 TXT: %s", e)
        path = os.path.join(doc_dir, f"{stem}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return {"path": path, "fmt": "txt"}
