# harness/orchestrator/llamacpp.py
# 本地自部署 llama.cpp 推理引擎（GGUF 格式）支持模块。
#
# 功能：
#   1. LlamaServerConfig: llama-server 启动参数配置与指令合成器（支持双向解析与生成）。
#   2. LlamaServerLauncher: llama-server 子进程生命周期管理、就绪探针轮询与优雅停机。
#   3. LlamaCppChat: 符合 IChatClient 契约的 OpenAI 兼容对话客户端。
#   4. LlamaCppEmbeddingClient: 符合 IEmbeddingClient 契约的向量提取客户端。
#
# 进程管理与 OpenAI 兼容协议交互的公共实现已上移到
#   * local_engine.py —— LocalServerLauncher（子进程 / 就绪探针 / 停机 / 调度钩子）
#   * local_chat.py   —— OpenAICompatChat / OpenAICompatEmbeddingClient
# 本模块只保留 llama-server 特有的部分：命令行合成与二进制/模型校验。
# 另一类本地引擎（Strata）见 strata.py，两者共享同一套基类。

from __future__ import annotations

import logging
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .local_chat import OpenAICompatChat, OpenAICompatEmbeddingClient
from .local_engine import LocalServerLauncher

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
    flash_attn: Optional[str] = None
    agent: bool = False
    # 不把 KV cache 卸载到显存（等价于命令行 --no-kv-offload）。
    # 开启后 KV cache 常驻系统内存，可显著降低显存占用，
    # 代价是注意力计算需跨 PCIe 读取 KV，推理速度会下降。
    no_kv_offload: bool = False
    # 多模态投影器（mmproj GGUF）。设置后该模型具备图像理解能力，
    # 命令行会附加 --mmproj <path>，调用方可传 image_url 内容块。
    mmproj_path: Optional[str] = None
    # 把投影器放在 CPU/RAM 而非显存（--no-mmproj-offload）。
    # 显存紧张时可回收约 0.9GiB，代价是图像预处理变慢。
    mmproj_no_offload: bool = False
    # 图像视觉 token 上限（--image-max-tokens）。0 表示不限制。
    image_max_tokens: Optional[int] = None
    # llama-server 的额外环境变量（如自定义二进制所需的 LD_LIBRARY_PATH）。
    env: dict = field(default_factory=dict)
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

        if self.flash_attn:
            cmd.extend(["--flash-attn", str(self.flash_attn)])

        if self.agent:
            cmd.append("--agent")

        # 多模态：投影器文件 + 可选放在 CPU、图像 token 上限
        if self.mmproj_path:
            cmd.extend(["--mmproj", os.path.abspath(
                os.path.expanduser(os.path.expandvars(self.mmproj_path))
            )])
            if self.mmproj_no_offload:
                cmd.append("--no-mmproj-offload")
        if self.image_max_tokens is not None:
            cmd.extend(["--image-max-tokens", str(self.image_max_tokens)])

        # 显存管理：把 KV cache 留在 CPU 内存（--no-kv-offload）。
        # 放在 extra_args 之前，允许用户通过 extra_args 覆盖。
        if self.no_kv_offload:
            cmd.append("--no-kv-offload")

        if self.extra_args:
            cmd.extend(self.extra_args)

        return cmd

    def to_command_string(self) -> str:
        """合成可直接在终端中运行的命令行字符串。"""
        return " ".join(shlex.quote(arg) for arg in self.build_command())

    @classmethod
    def from_command_string(cls, cmd_str: str) -> LlamaServerConfig:
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
            elif arg == "--flash-attn" and i + 1 < n:
                config.flash_attn = tokens[i + 1]
                i += 2
            elif arg == "--agent":
                config.agent = True
                i += 1
            elif arg in ("--no-kv-offload", "--no_kv_offload"):
                config.no_kv_offload = True
                i += 1
            elif arg == "--mmproj" and i + 1 < n:
                config.mmproj_path = tokens[i + 1]
                i += 2
            elif arg in ("--no-mmproj-offload", "--no_mmproj_offload"):
                config.mmproj_no_offload = True
                i += 1
            elif arg == "--image-max-tokens" and i + 1 < n:
                config.image_max_tokens = int(tokens[i + 1])
                i += 2
            else:
                extra.append(arg)
                i += 1

        config.extra_args = extra
        return config

    @classmethod
    def from_dict(cls, data: dict) -> LlamaServerConfig:
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
            flash_attn=data.get("flash_attn"),
            agent=bool(data.get("agent", False)),
            no_kv_offload=bool(data.get("no_kv_offload", False)),
            mmproj_path=data.get("mmproj_path") or data.get("mmproj"),
            mmproj_no_offload=bool(data.get("mmproj_no_offload", False)),
            image_max_tokens=(
                int(data["image_max_tokens"])
                if data.get("image_max_tokens") is not None else None
            ),
            env=dict(data.get("env") or {}),
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
            "flash_attn": self.flash_attn,
            "agent": self.agent,
            "no_kv_offload": self.no_kv_offload,
            "mmproj_path": self.mmproj_path,
            "mmproj_no_offload": self.mmproj_no_offload,
            "image_max_tokens": self.image_max_tokens,
            "env": dict(self.env),
            "extra_args": self.extra_args,
        }


class LlamaServerLauncher(LocalServerLauncher):
    """llama-server 引擎子进程生命周期管理器。

    只负责 llama.cpp 特有的部分：二进制与 GGUF 校验、命令行合成、私有 .so
    目录注入；启动、就绪探针、停机与 ModelScheduler 钩子全部继承自
    LocalServerLauncher（与 Strata 等其它本地引擎共用一套实现）。
    """

    engine_label = "llama-server"
    ready_paths = ("/health", "/v1/models")

    def __init__(
        self,
        config: LlamaServerConfig,
        log_file: str | Path | None = None,
    ):
        super().__init__(log_file=log_file)
        self.config = config

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def build_command(self) -> list[str]:
        return self.config.build_command()

    def api_key(self) -> str | None:
        return self.config.api_key

    def child_env(self) -> dict:
        """llama-server 的额外环境变量（等价于命令行前注入 env）。"""
        return dict(self.config.env or {})

    def describe_target(self) -> str:
        return self.config.resolved_model_path() or self.base_url

    def preflight(self) -> None:
        """启动前校验 llama-server 二进制与 GGUF 模型文件是否就位。"""
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

    # llama.cpp 的私有 .so 目录由 Launcher 基类自动注入 LD_LIBRARY_PATH；
    # 这里保留一个别名，兼容旧调用方对 config.env 的直接读取。
    def resolved_env(self) -> dict:
        return dict(self.config.env or {})


class LlamaCppChat(OpenAICompatChat):
    """本地自部署 llama.cpp 聊天客户端。

    完全符合 IChatClient 契约；协议交互（invoke / stream / SSE / 思考链 /
    Tool Call / 上游错误体解析 / system 消息归一化）由 OpenAICompatChat 提供。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("label", "llama-server")
        super().__init__(*args, **kwargs)


class LlamaCppEmbeddingClient(OpenAICompatEmbeddingClient):
    """llama.cpp 向量嵌入客户端（llama-server --embeddings）。"""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
