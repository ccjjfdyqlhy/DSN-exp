# harness/models/llamacpp.py
# 本地自部署 llama.cpp 推理引擎（GGUF 格式）支持模块。
#
# 功能：
#   1. LlamaServerConfig: llama-server 启动参数配置与指令合成器（支持双向解析与生成）。
#   2. LlamaServerLauncher: llama-server 子进程生命周期管理、就绪探针轮询与优雅停机。
#   3. LlamaCppChat: 符合 IChatClient 契约的 OpenAI 兼容对话客户端（支持 SSE 流式、DeepSeek 思考流、Tool Call、ModelScheduler 协同）。
#   4. LlamaCppEmbeddingClient: 符合 IEmbeddingClient 契约的向量提取客户端。

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Optional

import requests

from .base import ChatClientAdapter, ChatResponse, IEmbeddingClient, ToolCall

logger = logging.getLogger("LlamaCpp")


@dataclass
class LlamaServerConfig:
    """llama-server 启动参数配置与指令合成器。"""

    binary_path: str = "~/llama.cpp/build/bin/llama-server"
    model_path: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    n_gpu_layers: Optional[int] = None
    tensor_split: Optional[str] = None
    ctx_size: Optional[int] = None
    temp: Optional[float] = None
    jinja: bool = False
    chat_template_file: Optional[str] = None
    reasoning_format: Optional[str] = None
    threads: Optional[int] = None
    api_key: Optional[str] = None
    embeddings: bool = False
    alias: Optional[str] = None
    extra_args: list[str] = field(default_factory=list)

    def resolved_binary_path(self) -> str:
        """解析展开 ~ 及环境变量后的二进制可执行文件路径。"""
        expanded = os.path.expanduser(os.path.expandvars(self.binary_path))
        return os.path.abspath(expanded)

    def resolved_model_path(self) -> str:
        """解析展开 ~ 及环境变量后的模型文件路径。"""
        if not self.model_path:
            return ""
        expanded = os.path.expanduser(os.path.expandvars(self.model_path))
        return os.path.abspath(expanded)

    def build_command(self) -> list[str]:
        """将配置合成为标准的 llama-server 命令行参数列表。"""
        cmd = [self.resolved_binary_path()]

        if self.model_path:
            cmd.extend(["--model", self.resolved_model_path()])

        if self.host and self.host != "127.0.0.1":
            cmd.extend(["--host", str(self.host)])

        if self.port and self.port != 8080:
            cmd.extend(["--port", str(self.port)])

        if self.n_gpu_layers is not None:
            cmd.extend(["--n-gpu-layers", str(self.n_gpu_layers)])

        if self.tensor_split:
            cmd.extend(["--tensor-split", str(self.tensor_split)])

        if self.ctx_size is not None:
            cmd.extend(["--ctx-size", str(self.ctx_size)])

        if self.temp is not None:
            cmd.extend(["--temp", str(self.temp)])

        if self.jinja:
            cmd.append("--jinja")

        if self.chat_template_file:
            tpl_path = os.path.abspath(os.path.expanduser(os.path.expandvars(self.chat_template_file)))
            cmd.extend(["--chat-template-file", tpl_path])

        if self.reasoning_format:
            cmd.extend(["--reasoning-format", str(self.reasoning_format)])

        if self.threads is not None:
            cmd.extend(["--threads", str(self.threads)])

        if self.api_key:
            cmd.extend(["--api-key", str(self.api_key)])

        if self.embeddings:
            cmd.append("--embeddings")

        if self.alias:
            cmd.extend(["--alias", str(self.alias)])

        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def to_command_string(self) -> str:
        """合成可直接在终端中运行的命令行字符串。"""
        return " ".join(shlex.quote(arg) for arg in self.build_command())

    @classmethod
    def from_command_string(cls, cmd_str: str) -> "LlamaServerConfig":
        """从命令行字符串（如 ~/qwen_weights/cmd.txt 中的指令）反向解析为结构化配置。"""
        tokens = shlex.split(cmd_str.strip())
        if not tokens:
            return cls()

        binary_path = tokens[0]
        config = cls(binary_path=binary_path)

        i = 1
        n = len(tokens)
        extra: list[str] = []

        while i < n:
            arg = tokens[i]
            if arg in ("-m", "--model") and i + 1 < n:
                config.model_path = tokens[i + 1]
                i += 2
            elif arg in ("--host", "-h") and i + 1 < n:
                config.host = tokens[i + 1]
                i += 2
            elif arg in ("--port", "-p") and i + 1 < n:
                config.port = int(tokens[i + 1])
                i += 2
            elif arg in ("-ngl", "--n-gpu-layers", "--gpu-layers") and i + 1 < n:
                config.n_gpu_layers = int(tokens[i + 1])
                i += 2
            elif arg in ("-ts", "--tensor-split") and i + 1 < n:
                config.tensor_split = tokens[i + 1]
                i += 2
            elif arg in ("-c", "--ctx-size", "--ctx") and i + 1 < n:
                config.ctx_size = int(tokens[i + 1])
                i += 2
            elif arg == "--temp" and i + 1 < n:
                config.temp = float(tokens[i + 1])
                i += 2
            elif arg == "--jinja":
                config.jinja = True
                i += 1
            elif arg == "--chat-template-file" and i + 1 < n:
                config.chat_template_file = tokens[i + 1]
                i += 2
            elif arg == "--reasoning-format" and i + 1 < n:
                config.reasoning_format = tokens[i + 1]
                i += 2
            elif arg in ("-t", "--threads") and i + 1 < n:
                config.threads = int(tokens[i + 1])
                i += 2
            elif arg == "--api-key" and i + 1 < n:
                config.api_key = tokens[i + 1]
                i += 2
            elif arg == "--embeddings":
                config.embeddings = True
                i += 1
            elif arg in ("-a", "--alias") and i + 1 < n:
                config.alias = tokens[i + 1]
                i += 2
            else:
                extra.append(arg)
                i += 1

        config.extra_args = extra
        return config

    @classmethod
    def from_dict(cls, data: dict) -> "LlamaServerConfig":
        """从字典或 YAML profile 解析。"""
        return cls(
            binary_path=data.get("binary_path") or data.get("bin") or "~/llama.cpp/build/bin/llama-server",
            model_path=data.get("model_path") or data.get("model") or "",
            host=data.get("host", "127.0.0.1"),
            port=int(data.get("port", 8080)),
            n_gpu_layers=int(data["n_gpu_layers"]) if "n_gpu_layers" in data and data["n_gpu_layers"] is not None else None,
            tensor_split=data.get("tensor_split"),
            ctx_size=int(data["ctx_size"]) if "ctx_size" in data and data["ctx_size"] is not None else None,
            temp=float(data["temp"]) if "temp" in data and data["temp"] is not None else None,
            jinja=bool(data.get("jinja", False)),
            chat_template_file=data.get("chat_template_file"),
            reasoning_format=data.get("reasoning_format"),
            threads=int(data["threads"]) if "threads" in data and data["threads"] is not None else None,
            api_key=data.get("api_key"),
            embeddings=bool(data.get("embeddings", False)),
            alias=data.get("alias"),
            extra_args=list(data.get("extra_args", [])),
        )

    def to_dict(self) -> dict:
        return {
            "binary_path": self.binary_path,
            "model_path": self.model_path,
            "host": self.host,
            "port": self.port,
            "n_gpu_layers": self.n_gpu_layers,
            "tensor_split": self.tensor_split,
            "ctx_size": self.ctx_size,
            "temp": self.temp,
            "jinja": self.jinja,
            "chat_template_file": self.chat_template_file,
            "reasoning_format": self.reasoning_format,
            "threads": self.threads,
            "api_key": self.api_key,
            "embeddings": self.embeddings,
            "alias": self.alias,
            "extra_args": self.extra_args,
        }


class LlamaServerLauncher:
    """llama-server 引擎子进程生命周期管理器。

    提供：
      - 启动子进程并合成指令
      - 健康检查探测与就绪等待（/health 或 /v1/models）
      - 优雅停机与显存释放（SIGTERM -> SIGKILL）
      - 生成适用于 ModelScheduler 的 (load_fn, unload_fn) 钩子
    """

    def __init__(
        self,
        config: LlamaServerConfig,
        log_file: Optional[str | Path] = None,
    ):
        self.config = config
        self.log_file = Path(log_file) if log_file else None
        self._process: Optional[subprocess.Popen] = None
        self._log_fp = None

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def is_running(self) -> bool:
        """检查内部托管的子进程是否存活。"""
        if self._process is None:
            return False
        return self._process.poll() is None

    def is_ready(self, timeout: float = 2.0) -> bool:
        """通过 HTTP 端点探测服务是否已完全就绪提供推理服务。"""
        url = f"{self.base_url}/health"
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return True
        except Exception:
            pass

        # 备用探测 /v1/models
        try:
            resp = requests.get(f"{self.base_url}/v1/models", headers=headers, timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def start(self, wait_ready: bool = True, timeout: float = 180.0) -> bool:
        """启动 llama-server 实例。"""
        if self.is_running() and self.is_ready():
            logger.info("llama-server 已在运行并就绪: %s", self.base_url)
            return True

        binary_path = self.config.resolved_binary_path()
        if not os.path.isfile(binary_path) or not os.access(binary_path, os.X_OK):
            raise FileNotFoundError(
                f"未找到可执行的 llama.cpp 二进制文件: {binary_path}\n"
                f"接入本地 llama.cpp 推理引擎需要用户自行编译并提供可执行文件。\n"
                f"建议编译路径: ~/llama.cpp/build/bin/llama-server"
            )

        model_path = self.config.resolved_model_path()
        if model_path and not os.path.exists(model_path):
            raise FileNotFoundError(f"未找到指定的 GGUF 模型文件: {model_path}")

        cmd = self.config.build_command()
        logger.info("正在启动 llama-server: %s", " ".join(shlex.quote(c) for c in cmd))

        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL

        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_fp = open(self.log_file, "a", encoding="utf-8")
            stdout_dest = self._log_fp
            stderr_dest = self._log_fp

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=stdout_dest,
                stderr=stderr_dest,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
        except Exception as e:
            logger.error("启动 llama-server 失败: %s", e)
            if self._log_fp:
                self._log_fp.close()
                self._log_fp = None
            raise

        if not wait_ready:
            return True

        # 轮询探测直到服务就绪
        start_time = time.time()
        logger.info("等待 llama-server 服务就绪 (%s, 超时 %ds)...", self.base_url, timeout)
        while time.time() - start_time < timeout:
            if self._process.poll() is not None:
                ret = self._process.returncode
                logger.error("llama-server 进程异常退出，退出码: %d", ret)
                self.stop()
                raise RuntimeError(f"llama-server 启动后立即退出，返回码: {ret}")

            if self.is_ready(timeout=1.5):
                elapsed = time.time() - start_time
                logger.info("llama-server 启动成功并就绪 (耗时 %.1fs): %s", elapsed, self.base_url)
                return True

            time.sleep(0.5)

        self.stop()
        raise TimeoutError(f"llama-server 启动超时 ({timeout}s)，服务未在 {self.base_url} 就绪")

    def stop(self, timeout: float = 15.0) -> bool:
        """优雅关闭 llama-server 进程并释放显存。"""
        if self._process is None:
            return True

        pid = self._process.pid
        logger.info("正在停止 llama-server 进程 (PID %d)...", pid)

        try:
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, signal.SIGTERM)
                except Exception:
                    self._process.terminate()
            else:
                self._process.terminate()

            # 等待退出
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self._process.poll() is not None:
                    break
                time.sleep(0.2)

            # 强制杀死
            if self._process.poll() is None:
                logger.warning("llama-server 未在 %ds 内响应 SIGTERM，发送 SIGKILL...", timeout)
                if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                    try:
                        pgid = os.getpgid(pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception:
                        self._process.kill()
                else:
                    self._process.kill()
                self._process.wait(timeout=5.0)

        except Exception as e:
            logger.warning("停止 llama-server 时发生异常: %s", e)
        finally:
            self._process = None
            if self._log_fp:
                try:
                    self._log_fp.close()
                except Exception:
                    pass
                self._log_fp = None

        logger.info("llama-server 已完全停止")
        return True

    def create_scheduler_hooks(self, load_timeout: int = 180) -> tuple[Callable[[], bool], Callable[[], bool]]:
        """生成与 ModelScheduler 对接的 (load_fn, unload_fn) 钩子回调。"""
        def _load() -> bool:
            try:
                return self.start(wait_ready=True, timeout=float(load_timeout))
            except Exception as e:
                logger.error("ModelScheduler 调用 llama.cpp load_fn 失败: %s", e)
                return False

        def _unload() -> bool:
            try:
                return self.stop()
            except Exception as e:
                logger.error("ModelScheduler 调用 llama.cpp unload_fn 失败: %s", e)
                return False

        return _load, _unload


class LlamaCppChat(ChatClientAdapter):
    """本地自部署 llama.cpp 聊天客户端。

    完全符合 IChatClient 契约，支持：
      - OpenAI 兼容的 /v1/chat/completions 协议
      - DeepSeek reasoning 思考链提取 (<think> 标签与 reasoning_content 字段)
      - SSE 流式推送增量与 Tool Call 解析
      - ModelScheduler 显存管理联动
      - 可选关联 LlamaServerLauncher 自动拉起
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model_name: Optional[str] = None,
        timeout: float = 300.0,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        api_key: Optional[str] = None,
        scheduler: Optional[Any] = None,
        launcher: Optional[LlamaServerLauncher] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name or "llama-cpp"
        self.model: str = self.model_name
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_key = api_key
        self._scheduler = scheduler
        self._launcher = launcher
        self.last_usage = None
        self.last_model = self.model
        self._http_session = requests.Session()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _ensure_launcher_running(self) -> None:
        """如果绑定了 launcher 且未就绪，自动拉起。"""
        if self._launcher and not self._launcher.is_ready():
            logger.info("检测到 llama.cpp 引擎未就绪，通过 launcher 启动...")
            self._launcher.start(wait_ready=True, timeout=self.timeout)

    def _do_http_request(self, payload: dict) -> dict:
        url = f"{self.base_url}/v1/chat/completions"
        self._ensure_launcher_running()
        resp = self._http_session.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self.last_usage = data.get("usage")
        self.last_model = data.get("model", self.model_name)
        return data

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        msgs = self._to_message_dicts(messages)
        payload: dict[str, Any] = {
            "messages": msgs,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            "stream": False,
        }
        if self.model_name:
            payload["model"] = self.model_name
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        if timeout is not None:
            old_to = self.timeout
            self.timeout = timeout

        try:
            if self._scheduler is not None and self.model_name:
                with self._scheduler.use(self.model_name, timeout=self.timeout):
                    result = self._do_http_request(payload)
            else:
                result = self._do_http_request(payload)
        finally:
            if timeout is not None:
                self.timeout = old_to

        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        reasoning_content = message.get("reasoning_content")

        # 如果 content 中包含 <think>...</think> 且 reasoning_content 为空，自动提取
        if not reasoning_content and "<think>" in content and "</think>" in content:
            start = content.find("<think>") + len("<think>")
            end = content.find("</think>")
            if end > start:
                reasoning_content = content[start:end].strip()
                content = (content[:content.find("<think>")] + content[end + len("</think>"):].strip()).strip()

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                arguments=args,
            ))

        return ChatResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self.last_usage or {},
            model=self.last_model or self.model,
            finish_reason=choice.get("finish_reason"),
            reasoning_content=reasoning_content,
        )

    async def stream(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """SSE 流式交互生成器。"""
        msgs = self._to_message_dicts(messages)
        payload: dict[str, Any] = {
            "messages": msgs,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }
        if self.model_name:
            payload["model"] = self.model_name
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]

        self._ensure_launcher_running()

        def _request():
            url = f"{self.base_url}/v1/chat/completions"
            return self._http_session.post(
                url,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
                stream=True,
            )

        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(None, _request)
        resp.raise_for_status()

        for raw in resp.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except (TypeError, ValueError):
                continue
            if not chunk.get("choices"):
                continue

            delta = chunk["choices"][0].get("delta") or {}

            # 处理思维链增量输出
            if delta.get("reasoning_content"):
                yield {"reasoning_content": delta["reasoning_content"]}

            if delta.get("content"):
                yield delta["content"]

            tc_delta = delta.get("tool_calls")
            if tc_delta:
                emitted = []
                for tc in tc_delta:
                    fn = tc.get("function") or {}
                    emitted.append({
                        "index": tc.get("index", 0) or 0,
                        "id": tc.get("id", "") or "",
                        "name": fn.get("name", "") or "",
                        "arguments": fn.get("arguments", "") or "",
                    })
                if emitted:
                    yield {"tool_calls": emitted}

        resp.close()


class LlamaCppEmbeddingClient(IEmbeddingClient):
    """llama.cpp 向量嵌入客户端。"""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        model_name: Optional[str] = None,
        timeout: float = 60.0,
        api_key: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name or "llama-cpp-embedding"
        self.timeout = timeout
        self.api_key = api_key
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        url = f"{self.base_url}/v1/embeddings"
        payload = {"input": texts, "model": self.model_name}
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data.get("data", [])]
        return embeddings

    def embed_one(self, text: str) -> list[float]:
        res = self.embed([text])
        return res[0] if res else []
