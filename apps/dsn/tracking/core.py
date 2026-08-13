# tracking/core.py
# TrackingEngine — 用户跟踪系统核心引擎（infra）。
#
# 定位：一个通过不断观察获取数据来建模用户作息规律 / 生活节奏 / 项目进度等
#       各种事项的"个人行为日记本"。支持多模态记录：
#         拍照(image) / 录像(video) / 录音(audio) / 文件(file) / 文本(text)，
#       全部按用户隔离存入统一 tracking_events，并可进一步建模作息/节奏/项目。
#
# 本引擎聚合：
#   1. 聆听  (AudioListeningMonitor)  — 闲时环境声捕捉（闲时感知音频依赖它）
#   2. 采集  (VisionCapture/MediaManager) — 拍照 / 录像 / 主动录音 / 文件
#   3. 记录  (TrackingStore)          — 多模态事件统一存取
#   4. 建模  (model_routines/progress) — 作息 / 节奏 / 项目统计

from __future__ import annotations

import logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional

from .store import TrackingStore
from .media import MediaManager
from .audio_listen import AudioListeningMonitor
from .vision_capture import VisionCapture

logger = logging.getLogger("tracking.core")


class TrackingEngine:
    """用户跟踪系统引擎 — 个人行为日记本核心。

    通过多模态记录用户行动：拍照 / 录像 / 录音 / 文件 / 文本，全部存入独立的
    加密数据库（tracking.db，payload/meta 经 MessageCipher AES-256-GCM 加密），
    并按用户隔离。聚合：
      1. 聆听  (AudioListeningMonitor)  — 闲时环境声捕捉（依赖它）
      2. 采集  (VisionCapture + MediaManager) — 拍照 / 录像 / 主动录音 / 文件
      3. 记录  (TrackingStore)          — 独立加密库，多模态事件统一存取
      4. 建模  (model_routines/progress) — 作息 / 节奏 / 进度

    :param db: 可选，旧 ChatDBManager（仅用于回写 legacy sensing_events 兼容）。
    :param is_busy: callable() -> bool，供聆听器判断麦克风是否被正式录音占用
    :param audio_transport: callable(audio: np.ndarray)，把聆听捕捉的音频交给上层上报
    :param media_root: 媒体（拍照/录像/录音/文件）保存根目录
    :param db_path: 独立加密数据库文件路径；缺省用 <media_root>/../tracking/tracking.db
    :param cipher: 可选 MessageCipher 实例
    """

    def __init__(self, db=None, is_busy=None, audio_transport=None,
                 media_root=None, db_path=None, cipher=None):
        # legacy_writer：把 audio 事件回写旧 chats.db 的 sensing_events，保持旧查询兼容
        def _legacy_writer(user_id, text, rms_level, chat_id, source):
            if db is not None and hasattr(db, "add_sensing_event"):
                db.add_sensing_event(
                    user_id=user_id, text=text, rms_level=rms_level,
                    chat_id=chat_id, source=source,
                )

        self.store = TrackingStore(
            db_path=db_path, root=media_root, cipher=cipher,
            legacy_writer=_legacy_writer,
        )
        self.media = MediaManager(root=media_root)
        self._vision = VisionCapture(root=media_root)

        # 聆听器：音频被捕捉后经 audio_transport 交给上层（客户端会上报后端）。
        # 若未提供 transport，则监听器不主动上报，仅作为可调用原语存在。
        self.listener = None
        if audio_transport is not None:
            self.listener = AudioListeningMonitor(
                transport_send=audio_transport,
                is_busy=is_busy,
            )

    # ── 聆听接入（闲时感知的音频部分）──
    def configure_listening(self, enabled: bool, cooldown: int = 60,
                            max_record_secs: float = 6.0) -> bool:
        """配置聆听器；返回是否发生变化。未启用 transport 时返回 False。"""
        if self.listener is None:
            return False
        return self.listener.configure(enabled, cooldown, max_record_secs)

    def start_listening(self):
        if self.listener is not None:
            self.listener.start()

    def stop_listening(self):
        if self.listener is not None:
            self.listener.stop()

    @property
    def listening(self) -> bool:
        return bool(self.listener and self.listener.running)

    # ── 多模态观察事件落库（个人行为日记本）──

    def record_audio(self, user_id: int, text: str = "", source: str = "sensing",
                     rms_level: float = 0.0, chat_id: Optional[int] = None,
                     audio_path: Optional[str] = None, duration: float = 0.0,
                     write_legacy: bool = True) -> int:
        """记录一条录音/聆听观察事件。

        :param text: 识别文本 / 描述
        :param audio_path: 若保存了音频文件则登记其路径（元数据）
        :param write_legacy: 兼容旧 sensing_events 表（仅 source=sensing 时回写）
        """
        meta = {"rms_level": rms_level}
        if audio_path:
            meta["media_path"] = audio_path
        if duration:
            meta["duration"] = round(duration, 2)
        return self.store.add_event(
            user_id=user_id, etype="audio", payload=text or "", source=source,
            chat_id=chat_id, meta=meta,
            write_legacy_sensing=write_legacy and source == "sensing",
        )

    def record_photo(self, user_id: int, path: str, source: str = "tracking",
                     chat_id: Optional[int] = None, note: str = "") -> int:
        """记录一次拍照观察事件。

        文本(payload)只存描述/备注，文件路径只进 meta，避免 AI 看到路径。
        """
        return self.store.add_event(
            user_id=user_id, etype="image", payload=note or "拍摄了一张照片", source=source,
            chat_id=chat_id, meta={"media_path": path},
        )

    def record_video(self, user_id: int, path: str, duration: float = 0.0,
                     frames: int = 0, source: str = "tracking",
                     chat_id: Optional[int] = None, note: str = "") -> int:
        """记录一次录像观察事件。文本(payload)只存描述/备注，路径只进 meta。"""
        return self.store.add_event(
            user_id=user_id, etype="video", payload=note or "录制了一段视频", source=source,
            chat_id=chat_id, meta={"media_path": path, "duration": duration, "frames": frames},
        )

    def record_file(self, user_id: int, path: str, source: str = "tracking",
                    chat_id: Optional[int] = None, note: str = "",
                    file_type: str = "") -> int:
        """记录一次文件事件（文档 / 代码 / 笔记等任意文件入库）。

        文本(payload)只存描述/备注，路径只进 meta，避免 AI 看到路径。
        """
        meta = {"media_path": path}
        if file_type:
            meta["file_type"] = file_type
        return self.store.add_event(
            user_id=user_id, etype="file", payload=note or "保存了一个文件", source=source,
            chat_id=chat_id, meta=meta,
        )

    def record_text(self, user_id: int, content: str, source: str = "tracking",
                    chat_id: Optional[int] = None, note: str = "") -> int:
        """记录一条纯文本观察/日记条目（最基础的存储）。"""
        return self.store.add_event(
            user_id=user_id, etype="text", payload=content, source=source,
            chat_id=chat_id, meta={"note": note or ""},
        )

    # ── 多模态采集并落库（拍照 / 录像 / 主动录音）──

    def capture_photo(self, user_id: int, note: str = "") -> dict:
        """拍照并落库。返回 {ok, ...} 或带 error 的 dict。"""
        res = self._vision.capture_photo(uid=user_id)
        if res.get("ok"):
            self.record_photo(user_id=user_id, path=res["path"], note=note)
        return res

    def capture_video(self, user_id: int, duration: float = 3.0, note: str = "") -> dict:
        """录像并落库。返回 {ok, ...} 或带 error 的 dict。"""
        res = self._vision.capture_video(duration=duration, uid=user_id)
        if res.get("ok"):
            self.record_video(
                user_id=user_id, path=res["path"],
                duration=res.get("duration", 0.0), frames=res.get("frames", 0), note=note,
            )
        return res

    def capture_audio(self, user_id: int, duration: float = 5.0,
                      note: str = "", source: str = "recording") -> dict:
        """主动用麦克风录音并落库。返回 {ok, ...} 或带 error 的 dict。"""
        res = self._vision.capture_audio(duration=duration, uid=user_id)
        if res.get("ok"):
            self.record_audio(
                user_id=user_id, text=note or "主动录音", source=source,
                audio_path=res["path"], duration=res.get("duration", 0.0),
                write_legacy=False,
            )
        return res

    # ── 文件 / 文本入库（日记本条目）──

    def add_file(self, user_id: int, data, filename: str, note: str = "",
                 source: str = "tracking", chat_id: Optional[int] = None) -> dict:
        """把一段内容（bytes/str）作为文件保存进用户媒体库并登记事件。

        返回 {ok, path, event_id} 或 {ok: False, error}。
        """
        path = self.media.save_file(data, filename, kind="file", uid=user_id)
        if not path:
            return {"ok": False, "error": "保存文件失败"}
        event_id = self.record_file(
            user_id=user_id, path=path, source=source, chat_id=chat_id, note=note,
            file_type=Path(filename).suffix.lstrip("."),
        )
        return {"ok": True, "path": path, "event_id": event_id}

    def import_file(self, user_id: int, src: str, note: str = "",
                    source: str = "tracking", chat_id: Optional[int] = None) -> dict:
        """把磁盘上的已有文件复制进用户媒体库并登记事件。"""
        path = self.media.import_file(src, kind="file", uid=user_id)
        if not path:
            return {"ok": False, "error": "导入文件失败"}
        event_id = self.record_file(
            user_id=user_id, path=path, source=source, chat_id=chat_id, note=note,
            file_type=Path(src).suffix.lstrip("."),
        )
        return {"ok": True, "path": path, "event_id": event_id}

    def add_text(self, user_id: int, content: str, note: str = "",
                 source: str = "tracking", chat_id: Optional[int] = None) -> dict:
        """记录一条文本日记条目。返回 {ok, event_id} 或 {ok: False, error}。"""
        if not content:
            return {"ok": False, "error": "内容为空"}
        event_id = self.record_text(
            user_id=user_id, content=content, source=source, chat_id=chat_id, note=note,
        )
        return {"ok": True, "event_id": event_id, "content": content}

    # ── 建模：把观察聚合成用户作息 / 生活节奏 / 项目进度等 ──
    def model_routines(self, user_id: int, days: int = 7) -> dict:
        """基于近 N 天音频观察，粗建模"作息规律/生活节奏"。

        当前为启发式统计（真实语义建模可由后续 LLM 摘要模块增强）：
        - 按小时聚合活跃度 → 推断活跃时段
        - 按活跃时段分类作息（早鸟/夜猫/规律/不稳定）
        """
        now = datetime.now()
        start = (now - __import__("datetime").timedelta(days=max(1, days)))
        events = self.store.query_events(user_id, etype="audio",
                                         since=start.strftime("%Y-%m-%d %H:%M:%S"), limit=500)

        hourly: dict[int, int] = {}
        for ev in events:
            try:
                dt = datetime.strptime(ev["created_at"][:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            hourly[dt.hour] = hourly.get(dt.hour, 0) + 1

        if not hourly:
            result = {"model_type": "rhythm", "title": "生活节奏", "summary": "暂无足够观察数据",
                      "meta": {"days": days, "events": 0}}
        else:
            peak_hour = max(hourly, key=hourly.get)
            active_hours = sorted(h for h, c in hourly.items() if c >= max(2, len(events) // 40))
            if 5 <= peak_hour <= 10:
                style = "早睡早起型"
            elif 11 <= peak_hour <= 17:
                style = "日间活跃型"
            elif 18 <= peak_hour <= 23:
                style = "夜猫型"
            else:
                style = "深夜型"
            stability = "规律" if len(active_hours) <= 8 else "不稳定"
            summary = (f"近{days}天观察 {len(events)} 条环境声，峰值活跃在 {peak_hour} 点"
                       f"（{style}），活跃时段分布较{stability}。")
            result = {
                "model_type": "rhythm", "title": "生活节奏",
                "summary": summary,
                "meta": {
                    "days": days, "events": len(events), "peak_hour": peak_hour,
                    "active_hours": active_hours, "style": style, "stability": stability,
                    "hourly": hourly,
                },
            }

        self.store.upsert_model(
            user_id, model_type=result["model_type"], title=result["title"],
            content=result["summary"], meta=result["meta"],
        )
        return result

    def model_progress(self, user_id: int, days: int = 7) -> dict:
        """基于近期观察（音频/图片/视频）粗建模"项目进度/事项"时间分布。

        真实项目进度需要对话/任务数据，这里给出观察频次的时间分布作为基础统计。
        """
        now = datetime.now()
        start = (now - __import__("datetime").timedelta(days=max(1, days)))
        events = self.store.query_events(user_id, since=start.strftime("%Y-%m-%d %H:%M:%S"),
                                         limit=500)
        by_type: dict[str, int] = {}
        for ev in events:
            by_type[ev["etype"]] = by_type.get(ev["etype"], 0) + 1
        def _fmt(k, label):
            n = by_type.get(k, 0)
            return f"{label} {n}" if n else ""

        parts = [p for p in (_fmt("audio", "音频"), _fmt("image", "图片"),
                             _fmt("video", "视频"), _fmt("file", "文件"),
                             _fmt("text", "文本")) if p]
        result = {
            "model_type": "progress", "title": "事项观察统计",
            "summary": (f"近{days}天共 {len(events)} 条记录：" +
                        ("、".join(parts) if parts else "暂无") + "。"),
            "meta": {"days": days, "total": len(events), "by_type": by_type},
        }
        self.store.upsert_model(
            user_id, model_type=result["model_type"], title=result["title"],
            content=result["summary"], meta=result["meta"],
        )
        return result

    def get_models(self, user_id: int, model_type: Optional[str] = None) -> list[dict]:
        """查询当前用户已生成的建模结果。"""
        return self.store.query_models(user_id, model_type=model_type)

    def query_observations(self, user_id: int, etype: Optional[str] = None,
                           since: str = "", until: str = "", keyword: str = "",
                           limit: int = 20) -> list[dict]:
        """查询当前用户的观察日志（供 AI 技能使用）。"""
        return self.store.query_events(
            user_id, etype=etype, since=since, until=until, keyword=keyword, limit=limit,
        )
