# dual/instant_service.py
# Instant 模型服务 — 即时回复 / 进度概括 / 插话处理 / 完成通知

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from config import Config
from .instant_registry import InstantContextRegistry

logger = logging.getLogger("InstantService")

# Instant 模型控制标签
_SUMMON_RE = re.compile(r"<summon>\s*(.*?)\s*</summon>", re.DOTALL | re.IGNORECASE)
_CONTROL_RE = re.compile(r"<control>\s*(stop|cancel)\s*</control>", re.IGNORECASE)
_TARGET_RE = re.compile(r"<target>\s*(.*?)\s*</target>", re.IGNORECASE)

# Instant 指令模板
_INSTANT_INSTRUCTIONS = """\
## 你的角色
你是用户消息的第一接收者。你没有工具调用能力，但可以：
1. 用你的语气自然、简短地回复用户（一两句话即可）
2. 如果用户的请求需要执行操作（搜索、文件处理、系统操作、代码执行等），在回复末尾添加 <summon>简述需要主模型做什么</summon>
3. 如果用户要求停止正在进行的任务，回复后添加 <control>stop</control>，并在下一行添加 <target>任务ID前8位</target>
4. 如果用户只是闲聊或提问，直接回复即可，不需要 <summon>
5. 如果用户询问你正在做什么，参考下方的任务列表回答

## 进度概括规则
当收到主模型步骤通知时，用你自己的语气一句话告诉用户你正在做什么。
要求：口语化、自然，不要提及任务ID、步骤号、工具名称、插件名称或任何系统内部细节。
例如：可以说"我正在帮你搜索资料"，不要说"[进度] 任务 dual_34b 第2/5步 工具: web_search"。
当收到主模型完成通知时，简短告知用户结果。
"""


@dataclass
class InstantResult:
    """Instant 模型处理结果"""
    text: str = ""                          # 回复文本 (去掉控制标签后的纯文本)
    audio_b64: str = ""                     # 首行 TTS 音频
    summons: list[str] = field(default_factory=list)  # <summon> 内容列表
    controls: list[dict] = field(default_factory=list)  # [{action, target}]


class InstantModelService:
    """Instant 模型服务 — 管理持久上下文 + 模型调用 + TTS"""

    def __init__(
        self,
        prompt_engine=None,
        memory_system=None,
        tts_synth=None,
        request_pool=None,
        instant_registry=None,
        db=None,
    ):
        self._prompt_engine = prompt_engine
        self._memory = memory_system
        self._tts = tts_synth
        self._pool = request_pool
        self._registry = instant_registry or InstantContextRegistry.get_instance()
        self._db = db

    def _get_context(self, user_id: int, chat_id: int):
        return self._registry.get_or_create(
            user_id, chat_id,
            model_name=Config.INSTANT_MODEL,
            base_url=Config.INSTANT_MODEL_URL,
            summary_model=self._memory.summary_model if self._memory else None,
        )

    def _build_system_prompt(self, user_id: int, nickname: str = "用户") -> str:
        """构建 Instant 模型的 system prompt (人格 + 记忆 + 请求池 + 指令)"""
        sections = []

        # 1. 人格描述 (轻量 — 只取人格段，不取完整 system prompt)
        if self._prompt_engine:
            try:
                pe = self._prompt_engine
                if pe.personality_v3 and pe.personality_v3.enabled:
                    persona = pe.personality_v3.generate_personality_prompt(user_id)
                    if persona:
                        sections.append(persona)
                elif pe.personality_v2:
                    sections.append(pe.personality_v2.build_prompt(user_id))
            except Exception:
                logger.warning("人格生成失败", exc_info=True)

        # 2. 记忆摘要
        if self._memory:
            try:
                mem_msgs = self._memory.assemble_context(user_id, history=[])
                mem_text = "\n".join(m["content"] for m in mem_msgs if m.get("content"))
                if mem_text:
                    sections.append(f"## 相关记忆\n{mem_text}")
            except Exception:
                logger.warning("记忆组装失败", exc_info=True)

        # 3. 请求池状态
        if self._pool:
            pool_text = self._pool.summarize_for_prompt(user_id)
            sections.append(f"## 当前任务状态\n{pool_text}")

        # 4. 用户上下文
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sections.append(f"当前用户：{nickname}\n当前时间：{now}")

        # 5. 指令
        sections.append(_INSTANT_INSTRUCTIONS)

        return "\n\n".join(s for s in sections if s.strip())

    def _parse_output(self, reply: str) -> InstantResult:
        """解析 Instant 模型输出，提取控制标签"""
        summons = _SUMMON_RE.findall(reply)
        controls = []
        for m in _CONTROL_RE.finditer(reply):
            action = m.group(1).lower()
            target_match = _TARGET_RE.search(reply[m.end():])
            target = target_match.group(1).strip() if target_match else ""
            controls.append({"action": action, "target": target})

        # 清理文本 (去掉控制标签)
        text = _SUMMON_RE.sub("", reply)
        text = _CONTROL_RE.sub("", text)
        text = _TARGET_RE.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return InstantResult(text=text, summons=summons, controls=controls)

    def _synthesize_tts(self, text: str) -> str:
        """合成首行 TTS，返回 base64"""
        if not self._tts or not self._tts.available:
            return ""
        return self._tts.synthesize_first_line_b64(text) or ""

    def handle_request(
        self, user_id: int, chat_id: int, message: str,
        nickname: str = "用户",
    ) -> InstantResult:
        """处理用户消息 (step 0 或插话)"""
        ctx = self._get_context(user_id, chat_id)

        # 刷新 system prompt
        system_prompt = self._build_system_prompt(user_id, nickname)
        ctx.refresh_system_prompt(system_prompt)

        # 调用 Instant 模型 (自动追加 user + assistant 到 messages)
        reply = ctx.call(message)

        # 解析输出
        result = self._parse_output(reply)

        # TTS
        result.audio_b64 = self._synthesize_tts(result.text)

        # 持久化到 B2 (type='instant')
        if self._db:
            try:
                self._db.append_messages(
                    user_id, chat_id,
                    [
                        {"role": "user", "content": message, "msg_type": "instant"},
                        {"role": "assistant", "content": result.text, "msg_type": "instant"},
                    ],
                    skip_ownership_check=True,
                )
            except Exception:
                logger.warning("Instant 消息持久化失败", exc_info=True)

        logger.info("Instant handle_request: msg=%s summons=%d controls=%d",
                    message[:50], len(result.summons), len(result.controls))
        return result

    def summarize_progress(
        self, user_id: int, chat_id: int,
        task_id: str, step_info: dict,
    ) -> InstantResult:
        """为主模型步骤生成进度概括 (使用持久 Instant 上下文)"""
        ctx = self._get_context(user_id, chat_id)

        # 注入进度信息 — 不暴露任务ID/工具名/步骤号等技术细节
        intermediate = step_info.get("reply", "")
        progress_msg = "主模型刚刚完成了一步操作。"
        if intermediate:
            progress_msg += f" 产生的结果摘要: {intermediate[:150]}"

        ctx.append_system(progress_msg)

        # 刷新 system prompt (更新请求池状态)
        system_prompt = self._build_system_prompt(user_id)
        ctx.refresh_system_prompt(system_prompt)

        # 调用 Instant 模型生成概括 — 要求自然语言，不涉及技术细节
        reply = ctx.call(
            "用你的语气，一句话告诉用户你正在做什么。"
            "不要提及任务ID、步骤号、工具名称或系统内部细节。"
        )

        # TTS
        audio = self._synthesize_tts(reply)

        logger.info("Instant summarize_progress: task=%s → %s",
                    task_id[:8], reply[:60])
        return InstantResult(text=reply, audio_b64=audio)

    def notify_completion(
        self, user_id: int, chat_id: int,
        task_id: str, final_reply: str,
    ) -> None:
        """主模型完成通知，注入摘要到 Instant 上下文"""
        ctx = self._get_context(user_id, chat_id)
        summary = final_reply[:200] if final_reply else "任务已完成"
        ctx.append_system(f"主模型已完成任务。结果: {summary}")
        logger.info("Instant notify_completion: task=%s", task_id[:8])
