
# DSN-exp/vocal_infer.py
# UPD v1_260214

import os
import time
import hashlib
import requests
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict, Union, List, Generator

# 硬编码DEBUG标签: 设为True时，每次TTS合成的音频都会保存到 logs/tts_history/
_DEBUG_SAVE_AUDIO = True

# 模块级日志记录器，不再单独配置处理器
logger = logging.getLogger(__name__)


class TTSRequestError(Exception):
    """自定义异常，用于API请求失败时抛出"""
    pass


class VocalExp:
    """
    提供TTS推理、模型切换、服务控制等功能。
    需要提供API的base_url。
    """

    # 可重试的网络异常类型
    _RETRYABLE_ERRORS = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        ConnectionRefusedError,
        ConnectionResetError,
        ConnectionAbortedError,
        BrokenPipeError,
        OSError,
    )

    def __init__(self, base_url: str, logger: Optional[logging.Logger] = None, architecture: str = "parallel",
                 max_retries: int = 3, retry_backoff: float = 2.0, retry_max_wait: float = 10.0):
        """
        :param base_url: API服务的基础地址，如 "http://127.0.0.1:9880"
        :param logger: 可选的日志记录器，若不提供则使用模块级logger
        :param architecture: 推理架构，"parallel"（并行/默认）或 "serial"（串行）
        :param max_retries: 最大重试次数，默认3
        :param retry_backoff: 退避基数（秒），实际等待 = backoff * 2^attempt，默认2.0
        :param retry_max_wait: 单次重试最大等待时间上限（秒），默认10.0
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.logger = logger or logging.getLogger(__name__)
        self.architecture = architecture
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.retry_max_wait = retry_max_wait
        self._save_dir = None
        if _DEBUG_SAVE_AUDIO:
            self._debug_init_save_dir()

    def _debug_init_save_dir(self):
        self._save_dir = Path(__file__).resolve().parent.parent / "logs" / "tts_history"
        self._save_dir.mkdir(parents=True, exist_ok=True)
        self.logger.debug("TTS DEBUG: 音频保存目录=%s", self._save_dir)

    def _debug_save_audio(self, audio_data: bytes, text: str, ext: str, mode: str = "sync"):
        if not _DEBUG_SAVE_AUDIO or not audio_data:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        text_slug = text[:40].strip()
        text_hash = hashlib.md5(text.encode()).hexdigest()[:8]
        filename = f"{ts}_{text_hash}_{mode}.{ext.lstrip('.')}"
        filepath = self._save_dir / filename
        try:
            filepath.write_bytes(audio_data)
            self.logger.debug("TTS DEBUG: 已保存音频 (%dB) → %s", len(audio_data), filepath)
        except Exception as e:
            self.logger.warning("TTS DEBUG: 保存音频失败 %s: %s", filepath, e)

    def _is_retryable(self, exc: Exception) -> bool:
        """判断异常是否可重试（仅网络层错误，不重试 HTTP 4xx 等业务错误）。"""
        if isinstance(exc, self._RETRYABLE_ERRORS):
            return True
        if isinstance(exc, requests.exceptions.RequestException):
            # 连接类错误（无响应）可重试，有 HTTP 响应的不重试
            if exc.response is not None:
                return False
            return True
        return False

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        底层请求方法，统一处理URL拼接和异常。
        支持自动重试：网络层错误（连接拒绝、超时等）按指数退避重试。
        返回requests.Response对象，由上层方法解析。
        支持流式请求：当kwargs中包含'stream'且为True时，不会自动读取内容。
        """
        url = f"{self.base_url}{endpoint}"
        self.logger.debug("发起%s请求: %s, 参数: %s, JSON: %s", method, url, kwargs.get('params'), kwargs.get('json'))

        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                # 注意：如果stream=True，此时不会抛出HTTPError，需手动检查状态码
                if not kwargs.get('stream'):
                    response.raise_for_status()
                else:
                    if response.status_code >= 400:
                        try:
                            error_data = response.json()
                            error_msg = error_data.get('message', '')
                        except Exception:
                            error_msg = response.text[:200]
                        raise requests.exceptions.HTTPError(
                            f"{response.status_code} Error: {error_msg}",
                            response=response
                        )
                self.logger.debug("请求成功: %s", response.status_code)
                return response
            except Exception as e:
                last_exc = e
                if self._is_retryable(e) and attempt < self.max_retries:
                    wait = min(self.retry_backoff * (2 ** attempt), self.retry_max_wait)
                    self.logger.warning("请求失败，将在 %.1fs 后重试 (%d/%d): %s",
                                        wait, attempt + 1, self.max_retries, e)
                    time.sleep(wait)
                    continue
                break

        # 所有重试用尽或遇到不可重试的错误
        e = last_exc
        error_msg = f"API请求失败: {e}"
        if hasattr(e, 'response') and e.response is not None:
            resp = e.response
            status_code = resp.status_code
            try:
                error_data = resp.json()
                detail = error_data.get('message') or error_data.get('detail') or error_data.get('error') or ''
                body_str = str(error_data)[:600]
            except Exception:
                body_str = resp.text[:600]
            error_msg += f" [HTTP {status_code}]"
            if detail:
                error_msg += f" detail={detail}"
            error_msg += f" response_body={body_str}"
        else:
            error_msg += " [无响应]"
        error_msg += f" url={url}"
        if kwargs.get('json'):
            json_info = kwargs['json'].copy()
            if 'text' in json_info and len(str(json_info['text'])) > 60:
                json_info['text'] = json_info['text'][:60] + '...'
            error_msg += f" body_params={json_info}"
        self.logger.error(error_msg, exc_info=True)
        raise TTSRequestError(error_msg) from e

    def _detect_architecture(self, params: Dict[str, Any]) -> str:
        """根据参数字段名自动推断推理架构，用于兼容旧调用方未显式传入 architecture 的场景。"""
        if "refer_wav_path" in params or "text_language" in params:
            return "serial"
        return "parallel"

    def _resolve_endpoint(self, architecture: str) -> str:
        if architecture == "serial":
            return "/"
        return "/tts"

    def tts(self, **params) -> bytes:
        """
        文本合成语音（TTS），非流式模式，返回完整音频二进制数据。
        所有参数与API文档一致，以关键字参数形式传入。
        成功时返回音频二进制数据（bytes），失败时抛出TTSRequestError。

        常用参数 (parallel 架构):
            text (str): 待合成文本，必须
            text_lang (str): 文本语言，必须
            ref_audio_path (str): 参考音频路径，必须
            prompt_lang (str): 提示文本语言，必须
            prompt_text (str): 提示文本，可选，默认为""
            aux_ref_audio_paths (List[str]): 辅助参考音频列表，可选
            top_k (int): 默认15
            top_p (float): 默认1.0
            temperature (float): 默认1.0
            speed_factor (float): 默认1.0
            fragment_interval (float): 默认0.3
            repetition_penalty (float): 默认1.35
            sample_steps (int): 默认32
            media_type (str): 返回音频格式，"wav","raw","ogg","aac"之一，默认"wav"
            streaming_mode (Union[bool,int]): 流式模式，默认False
            parallel_infer (bool): 默认True

        常用参数 (serial 架构):
            text (str): 待合成文本，必须
            text_language (str): 文本语言，必须
            refer_wav_path (str): 参考音频路径，必须
            prompt_language (str): 提示文本语言，必须
            prompt_text (str): 提示文本，可选，默认为""
            inp_refs (List[str]): 辅助参考音频列表，可选
            top_k (int): 默认20
            top_p (float): 默认0.6
            temperature (float): 默认0.6
            speed (int): 语速，默认1
            media_type (str): 返回音频格式，默认"wav"
            streaming_mode (Union[bool,int]): 流式模式，默认False

        注意：如果streaming_mode设为True，服务端会返回流式音频，但本方法会等待全部数据接收完毕再返回，
             因此仍然返回完整的音频bytes。若需实时处理流式数据，请使用tts_stream方法。
        """
        architecture = self.architecture
        if architecture == "parallel" and self._detect_architecture(params) == "serial":
            architecture = "serial"

        if architecture == "serial":
            return self._tts_serial(**params)

        # ---- parallel 架构 ----
        required = ['text', 'text_lang', 'ref_audio_path', 'prompt_lang']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        text_preview = params.get('text', '')[:80]
        self.logger.info("TTS开始 | text=%s... | ref_audio=%s | text_lang=%s | prompt_lang=%s",
                         text_preview, params.get('ref_audio_path'), params.get('text_lang'), params.get('prompt_lang'))
        t0 = time.perf_counter()
        endpoint = self._resolve_endpoint("parallel")
        resp = self._request('POST', endpoint, json=params)
        elapsed = time.perf_counter() - t0
        audio_len = len(resp.content)
        self.logger.info("TTS完成 | 耗时=%.2fs | 音频大小=%.1fKB", elapsed, audio_len / 1024)
        media_type = params.get('media_type', 'wav')
        self._debug_save_audio(resp.content, params.get('text', ''), media_type, mode="sync")
        return resp.content

    def _tts_serial(self, **params) -> bytes:
        required = ['text', 'text_language', 'refer_wav_path', 'prompt_language']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        text_preview = params.get('text', '')[:80]
        self.logger.info("串行TTS开始 | text=%s... | refer_wav=%s | text_language=%s | prompt_language=%s",
                         text_preview, params.get('refer_wav_path'), params.get('text_language'), params.get('prompt_language'))
        t0 = time.perf_counter()
        endpoint = self._resolve_endpoint("serial")
        resp = self._request('POST', endpoint, json=params)
        elapsed = time.perf_counter() - t0
        audio_len = len(resp.content)
        self.logger.info("串行TTS完成 | 耗时=%.2fs | 音频大小=%.1fKB", elapsed, audio_len / 1024)
        media_type = params.get('media_type', 'wav')
        self._debug_save_audio(resp.content, params.get('text', ''), media_type, mode="sync")
        return resp.content

    def tts_stream(self, chunk_size: int = 1024, **params) -> Generator[bytes, None, None]:
        """
        流式文本合成语音（TTS）。
        参数与tts方法相同，但会强制将streaming_mode设为True（或至少非False），以便服务端返回分块音频。
        返回一个生成器，按块产生音频二进制数据（bytes），适用于实时播放或处理。

        :param chunk_size: 每次yield的数据块大小（字节），默认1024。
        :param params: 其他TTS参数，同tts方法。
        :yield: 音频数据块（bytes）
        """
        architecture = self.architecture
        if architecture == "parallel" and self._detect_architecture(params) == "serial":
            architecture = "serial"

        if architecture == "serial":
            yield from self._tts_serial_stream(chunk_size, **params)
            return

        # ---- parallel 流式 ----
        required = ['text', 'text_lang', 'ref_audio_path', 'prompt_lang']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        streaming_mode = params.get('streaming_mode', False)
        if streaming_mode in (False, 0):
            self.logger.info("tts_stream: 将streaming_mode从False/0强制改为True，以启用服务端流式输出")
            params['streaming_mode'] = True

        text_preview = params.get('text', '')[:80]
        self.logger.info("流式TTS开始 | text=%s... | ref_audio=%s | text_lang=%s | prompt_lang=%s",
                         text_preview, params.get('ref_audio_path'), params.get('text_lang'), params.get('prompt_lang'))
        t0 = time.perf_counter()
        endpoint = self._resolve_endpoint("parallel")
        resp = self._request('POST', endpoint, json=params, stream=True)

        chunk_count = 0
        total_bytes = 0
        chunks: list[bytes] = []
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                chunk_count += 1
                total_bytes += len(chunk)
                chunks.append(chunk)
                if chunk_count <= 3 or chunk_count % 10 == 0:
                    self.logger.debug("流式TTS #%d: %d bytes (累计 %.1fKB)", chunk_count, len(chunk), total_bytes / 1024)
                yield chunk

        elapsed = time.perf_counter() - t0
        self.logger.info("流式TTS完成 | 共%d个chunk | 总大小=%.1fKB | 耗时=%.2fs", chunk_count, total_bytes / 1024, elapsed)
        if chunks:
            media_type = params.get('media_type', 'wav')
            self._debug_save_audio(b''.join(chunks), params.get('text', ''), media_type, mode="stream")

    def _tts_serial_stream(self, chunk_size: int, **params) -> Generator[bytes, None, None]:
        required = ['text', 'text_language', 'refer_wav_path', 'prompt_language']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        streaming_mode = params.get('streaming_mode', False)
        if streaming_mode in (False, 0):
            self.logger.info("_tts_serial_stream: 将streaming_mode从False/0强制改为True")
            params['streaming_mode'] = True

        text_preview = params.get('text', '')[:80]
        self.logger.info("串行流式TTS开始 | text=%s... | refer_wav=%s | text_language=%s | prompt_language=%s",
                         text_preview, params.get('refer_wav_path'), params.get('text_language'), params.get('prompt_language'))
        t0 = time.perf_counter()
        endpoint = self._resolve_endpoint("serial")
        resp = self._request('POST', endpoint, json=params, stream=True)

        chunk_count = 0
        total_bytes = 0
        chunks: list[bytes] = []
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                chunk_count += 1
                total_bytes += len(chunk)
                chunks.append(chunk)
                if chunk_count <= 3 or chunk_count % 10 == 0:
                    self.logger.debug("串行流式TTS #%d: %d bytes (累计 %.1fKB)", chunk_count, len(chunk), total_bytes / 1024)
                yield chunk

        elapsed = time.perf_counter() - t0
        self.logger.info("串行流式TTS完成 | 共%d个chunk | 总大小=%.1fKB | 耗时=%.2fs", chunk_count, total_bytes / 1024, elapsed)
        if chunks:
            media_type = params.get('media_type', 'wav')
            self._debug_save_audio(b''.join(chunks), params.get('text', ''), media_type, mode="stream")

    def probe(self, timeout: float = 3.0) -> bool:
        """
        探测 TTS 服务是否可达。用于启动时健康检查。
        :param timeout: 连接超时时间（秒），默认3.0
        :return: 服务可达返回 True，否则返回 False
        """
        url = f"{self.base_url}/"
        try:
            resp = self.session.get(url, timeout=timeout)
            return resp.status_code < 500
        except Exception:
            return False

    def control(self, command: str) -> Dict[str, Any]:
        """
        发送控制命令，如重启或退出服务。
        :param command: "restart" 或 "exit"
        :return: 成功时通常无返回内容，但为统一解析返回JSON（可能为空字典）
        """
        if command not in ['restart', 'exit']:
            raise ValueError("command 必须是 'restart' 或 'exit'")
        resp = self._request('GET', '/control', params={'command': command})
        return resp.json() if resp.content else {}

    def set_gpt_weights(self, weights_path: str) -> Dict[str, Any]:
        """
        切换GPT模型权重。
        :param weights_path: 权重文件路径
        :return: 成功时返回 {"message": "success"} 字典
        """
        resp = self._request('GET', '/set_gpt_weights', params={'weights_path': weights_path})
        return resp.json()

    def set_sovits_weights(self, weights_path: str) -> Dict[str, Any]:
        """
        切换SoVITS模型权重。
        :param weights_path: 权重文件路径
        :return: 成功时返回 {"message": "success"} 字典
        """
        resp = self._request('GET', '/set_sovits_weights', params={'weights_path': weights_path})
        return resp.json()