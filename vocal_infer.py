
# DSN-exp/vocal_infer.py
# UPD v1_260214

import requests
import logging
from typing import Optional, Any, Dict, Union, List, Generator

logger = logging.getLogger(__name__)


class TTSRequestError(Exception):
    """自定义异常，用于API请求失败时抛出"""
    pass


class VocalExp:
    """
    提供TTS推理、模型切换、服务控制等功能。
    需要提供API的base_url。
    """

    def __init__(self, base_url: str, logger: Optional[logging.Logger] = None):
        """
        :param base_url: API服务的基础地址，如 "http://127.0.0.1:9880"
        :param logger: 可选的日志记录器，若不提供则使用模块级logger
        """
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.logger = logger or logging.getLogger(__name__)

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        底层请求方法，统一处理URL拼接和异常。
        返回requests.Response对象，由上层方法解析。
        支持流式请求：当kwargs中包含'stream'且为True时，不会自动读取内容。
        """
        url = f"{self.base_url}{endpoint}"
        self.logger.debug(f"发起{method}请求: {url}, 参数: {kwargs.get('params')}, JSON: {kwargs.get('json')}")
        try:
            response = self.session.request(method, url, **kwargs)
            # 注意：如果stream=True，此时不会抛出HTTPError，需手动检查状态码
            if not kwargs.get('stream'):
                response.raise_for_status()
            else:
                if response.status_code >= 400:
                    # 对于流式请求，尝试读取错误信息
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('message', '')
                    except:
                        error_msg = response.text[:200]
                    raise requests.exceptions.HTTPError(
                        f"{response.status_code} Error: {error_msg}",
                        response=response
                    )
            self.logger.debug(f"请求成功: {response.status_code}")
            return response
        except requests.exceptions.RequestException as e:
            error_msg = f"API请求失败: {e}"
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_data = e.response.json()
                    error_msg += f" - {error_data.get('message', '')}"
                except:
                    pass
            self.logger.error(error_msg)
            raise TTSRequestError(error_msg) from e

    def tts(self, **params) -> bytes:
        """
        文本合成语音（TTS），非流式模式，返回完整音频二进制数据。
        所有参数与API文档中的POST /tts一致，以关键字参数形式传入。
        成功时返回音频二进制数据（bytes），失败时抛出TTSRequestError。

        常用参数:
            text (str): 待合成文本，必须
            text_lang (str): 文本语言，必须
            ref_audio_path (str): 参考音频路径，必须
            prompt_lang (str): 提示文本语言，必须
            prompt_text (str): 提示文本，可选，默认为""
            aux_ref_audio_paths (List[str]): 辅助参考音频列表，可选
            top_k (int): 默认15
            top_p (float): 默认1.0
            temperature (float): 默认1.0
            text_split_method (str): 默认"cut5"
            batch_size (int): 默认1
            batch_threshold (float): 默认0.75
            split_bucket (bool): 默认True
            speed_factor (float): 默认1.0
            fragment_interval (float): 默认0.3
            seed (int): 默认-1
            media_type (str): 返回音频格式，"wav","raw","ogg","aac"之一，默认"wav"
            streaming_mode (Union[bool,int]): 流式模式，默认False（非流式模式也可设为False/0）
            parallel_infer (bool): 默认True
            repetition_penalty (float): 默认1.35
            sample_steps (int): 默认32
            super_sampling (bool): 默认False
            overlap_length (int): 默认2
            min_chunk_length (int): 默认16

        注意：如果streaming_mode设为True，服务端会返回流式音频，但本方法会等待全部数据接收完毕再返回，
             因此仍然返回完整的音频bytes。若需实时处理流式数据，请使用tts_stream方法。
        """
        # 确保必填参数存在
        required = ['text', 'text_lang', 'ref_audio_path', 'prompt_lang']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        # 默认prompt_text为空字符串
        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        # 发送POST请求
        resp = self._request('POST', '/tts', json=params)
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
        # 确保必填参数存在
        required = ['text', 'text_lang', 'ref_audio_path', 'prompt_lang']
        for r in required:
            if r not in params or params[r] is None:
                raise ValueError(f"缺少必填参数: {r}")

        # 默认prompt_text为空字符串
        if 'prompt_text' not in params:
            params['prompt_text'] = ""

        # 强制启用流式模式（服务端必须返回分块数据）
        # 如果用户传入的streaming_mode已经是True或数字，我们保留；否则设为True
        # 但若streaming_mode为False/0，则服务端不会分块，流式接收将失去意义，因此我们覆盖为True
        streaming_mode = params.get('streaming_mode', False)
        if streaming_mode in (False, 0):
            self.logger.info("tts_stream: 将streaming_mode从False/0强制改为True，以启用服务端流式输出")
            params['streaming_mode'] = True

        # 发送流式POST请求
        resp = self._request('POST', '/tts', json=params, stream=True)

        # 逐块yield数据
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                yield chunk

        self.logger.debug("流式TTS完成")

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