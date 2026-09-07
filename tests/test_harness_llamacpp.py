# tests/test_harness_llamacpp.py
# 本地自部署 llama.cpp 推理引擎（GGUF 格式）支持与指令合成完整单元测试。

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import requests

from harness.models import (
    IChatClient,
    IEmbeddingClient,
    ChatMessage,
    ChatResponse,
    ToolCall,
    ModelProviderRegistry,
)
from harness.models.llamacpp import (
    LlamaServerConfig,
    LlamaServerLauncher,
    LlamaCppChat,
    LlamaCppEmbeddingClient,
)
from harness.models.scheduler import ModelScheduler


# ════════════════════════════════════════════════════════════════════════════
# 1. 指令合成器与双向解析测试（针对 ~/qwen_weights/cmd.txt 中指令）
# ════════════════════════════════════════════════════════════════════════════

def test_command_synthesis_qwen_flash():
    """测试 Qwen 3.8 Flash Next 分片模型与 Jinja、Reasoning 指令合成。"""
    cfg = LlamaServerConfig(
        binary_path="~/llama.cpp/build/bin/llama-server",
        model_path="/home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/UD-IQ1_M/Qwen3.8-Flash-Next-UD-IQ1_M-00001-of-00003.gguf",
        n_gpu_layers=17,
        tensor_split="11,11",
        ctx_size=128000,
        temp=1.0,
        jinja=True,
        chat_template_file="/home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/chat_template.jinja",
        reasoning_format="deepseek",
    )
    cmd = cfg.build_command()

    assert cmd[0].endswith("llama-server")
    assert "--model" in cmd
    assert "/home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/UD-IQ1_M/Qwen3.8-Flash-Next-UD-IQ1_M-00001-of-00003.gguf" in cmd
    assert "--n-gpu-layers" in cmd and "17" in cmd
    assert "--tensor-split" in cmd and "11,11" in cmd
    assert "--ctx-size" in cmd and "128000" in cmd
    assert "--temp" in cmd and "1.0" in cmd
    assert "--jinja" in cmd
    assert "--chat-template-file" in cmd
    assert "--reasoning-format" in cmd and "deepseek" in cmd


def test_command_from_cmd_txt_line1_roundtrip():
    """测试解析 cmd.txt 第一行并还原配置。"""
    cmd_line = (
        "~/llama.cpp/build/bin/llama-server --model /home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/UD-IQ1_M/Qwen3.8-Flash-Next-UD-IQ1_M-00001-of-00003.gguf "
        "--n-gpu-layers 17 --tensor-split 11,11 --ctx-size 128000 --temp 1.0 --jinja "
        "--chat-template-file /home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/chat_template.jinja --reasoning-format deepseek"
    )
    parsed = LlamaServerConfig.from_command_string(cmd_line)
    assert parsed.n_gpu_layers == 17
    assert parsed.tensor_split == "11,11"
    assert parsed.ctx_size == 128000
    assert parsed.temp == 1.0
    assert parsed.jinja is True
    assert parsed.reasoning_format == "deepseek"
    assert parsed.chat_template_file == "/home/darkstar/qwen_weights/Qwen3.8-Flash-Next-GGUF/chat_template.jinja"


def test_command_from_cmd_txt_line3_and_5():
    """测试解析 cmd.txt 中 Gemma 与 DeepSeek-V4-Pro 指令。"""
    cmd_gemma = "~/llama.cpp/build/bin/llama-server --model /home/darkstar/.lmstudio/models/lmstudio-community/gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf"
    p_gemma = LlamaServerConfig.from_command_string(cmd_gemma)
    assert p_gemma.model_path == "/home/darkstar/.lmstudio/models/lmstudio-community/gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf"

    cmd_ds = "~/llama.cpp/build/bin/llama-server --model /home/darkstar/qwen_weights/Qwen3.5/DeepSeek-V4-Pro-Qwen3.5-4B-MTP-Q8_0.gguf --reasoning-format deepseek"
    p_ds = LlamaServerConfig.from_command_string(cmd_ds)
    assert p_ds.reasoning_format == "deepseek"
    assert p_ds.model_path == "/home/darkstar/qwen_weights/Qwen3.5/DeepSeek-V4-Pro-Qwen3.5-4B-MTP-Q8_0.gguf"


def test_dict_serialization():
    """测试 dict/YAML 互转。"""
    d = {
        "binary_path": "/usr/bin/llama-server",
        "model_path": "/tmp/test.gguf",
        "port": 9090,
        "n_gpu_layers": 32,
        "ctx_size": 4096,
        "jinja": True,
        "reasoning_format": "deepseek",
    }
    cfg = LlamaServerConfig.from_dict(d)
    assert cfg.port == 9090
    assert cfg.n_gpu_layers == 32
    assert cfg.jinja is True
    assert cfg.reasoning_format == "deepseek"
    assert cfg.to_dict()["port"] == 9090


# ════════════════════════════════════════════════════════════════════════════
# 2. 进程管理与健康检查测试
# ════════════════════════════════════════════════════════════════════════════

@patch("os.path.isfile", return_value=True)
@patch("os.access", return_value=True)
@patch("os.path.exists", return_value=True)
@patch("subprocess.Popen")
def test_launcher_start_and_ready(mock_popen, mock_exists, mock_access, mock_isfile):
    """测试 Launcher 启动与就绪探测。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 12345
    mock_popen.return_value = mock_proc

    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
        port=8088,
    )
    launcher = LlamaServerLauncher(cfg)

    # 模拟 health 返回 200
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        ok = launcher.start(wait_ready=True, timeout=5.0)
        assert ok is True
        assert launcher.is_running() is True
        assert launcher.is_ready() is True


@patch("os.path.isfile", return_value=True)
@patch("os.access", return_value=True)
@patch("os.path.exists", return_value=True)
@patch("subprocess.Popen")
def test_launcher_stop(mock_popen, mock_exists, mock_access, mock_isfile):
    """测试 Launcher 优雅停止。"""
    mock_proc = MagicMock()
    mock_proc.poll.side_effect = [None, 0]
    mock_proc.pid = 12345
    mock_popen.return_value = mock_proc

    cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
    )
    launcher = LlamaServerLauncher(cfg)
    launcher._process = mock_proc

    launcher.stop(timeout=2.0)
    assert launcher._process is None


def test_launcher_missing_binary_raises():
    """测试二进制文件缺失时的明确报错。"""
    cfg = LlamaServerConfig(binary_path="/non_existent_binary/llama-server")
    launcher = LlamaServerLauncher(cfg)
    with pytest.raises(FileNotFoundError) as excinfo:
        launcher.start(wait_ready=False)
    assert "未找到可执行的 llama.cpp 二进制文件" in str(excinfo.value)


# ════════════════════════════════════════════════════════════════════════════
# 3. 客户端接口契约与流式交互测试
# ════════════════════════════════════════════════════════════════════════════

def test_llamacpp_chat_conforms_ichatclient():
    """验证 LlamaCppChat 实现了 IChatClient 协议。"""
    chat = LlamaCppChat(base_url="http://127.0.0.1:8080", model_name="qwen-gguf")
    assert isinstance(chat, IChatClient)
    assert chat.model == "qwen-gguf"


def test_llamacpp_chat_invoke_with_reasoning_and_tools():
    """验证 invoke 请求响应包含 content, reasoning_content, tool_calls。"""
    chat = LlamaCppChat(base_url="http://127.0.0.1:8080", model_name="qwen-gguf")

    fake_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "答案是 42",
                "reasoning_content": "思考：计算 6 * 7 = 42",
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": "{\"expr\": \"6*7\"}"}
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        "model": "qwen-gguf"
    }

    with patch.object(chat._http_session, "post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response
        mock_post.return_value = mock_resp

        resp = chat.invoke([ChatMessage.user("计算 6*7")])
        assert isinstance(resp, ChatResponse)
        assert resp.content == "答案是 42"
        assert resp.reasoning_content == "思考：计算 6 * 7 = 42"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "calculator"
        assert resp.tool_calls[0].arguments == {"expr": "6*7"}


def test_llamacpp_chat_extracts_think_tags():
    """验证当 reasoning_content 未单独提供但 content 包含 <think> 标签时的自动提取。"""
    chat = LlamaCppChat(base_url="http://127.0.0.1:8080", model_name="qwen-gguf")

    fake_response = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "<think>让我想想，1+1等于2</think>结果是2",
            }
        }]
    }

    with patch.object(chat._http_session, "post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_response
        mock_post.return_value = mock_resp

        resp = chat.invoke([ChatMessage.user("1+1")])
        assert resp.content == "结果是2"
        assert resp.reasoning_content == "让我想想，1+1等于2"


@pytest.mark.asyncio
async def test_llamacpp_chat_stream():
    """验证流式输出解析（文本增量、reasoning 增量与 tool_calls 增量）。"""
    chat = LlamaCppChat(base_url="http://127.0.0.1:8080", model_name="qwen-gguf")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"reasoning_content":"思考中..."}}]}',
        'data: {"choices":[{"delta":{"content":"你好"}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"search","arguments":"{\\"q\\""}}]}}]}',
        'data: [DONE]',
    ]

    with patch.object(chat._http_session, "post", return_value=mock_resp):
        chunks = []
        async for chunk in chat.stream([ChatMessage.user("hi")]):
            chunks.append(chunk)

        assert chunks[0] == {"reasoning_content": "思考中..."}
        assert chunks[1] == "你好"
        assert chunks[2] == {"tool_calls": [{"index": 0, "id": "c1", "name": "search", "arguments": '{"q"'}]}


def test_llamacpp_embedding_client():
    """验证向量客户端 IEmbeddingClient 契约与接口。"""
    client = LlamaCppEmbeddingClient(base_url="http://127.0.0.1:8080")
    assert isinstance(client, IEmbeddingClient)

    fake_data = {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}
    with patch.object(client._session, "post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_data
        mock_post.return_value = mock_resp

        res = client.embed(["hello", "world"])
        assert len(res) == 2
        assert res[0] == [0.1, 0.2, 0.3]

        one = client.embed_one("hello")
        assert one == [0.1, 0.2, 0.3]


# ════════════════════════════════════════════════════════════════════════════
# 4. ModelScheduler 与 Provider 注册集成测试
# ════════════════════════════════════════════════════════════════════════════

def test_model_provider_registry_llamacpp():
    """验证 ModelProviderRegistry 注册 llamacpp。"""
    reg = ModelProviderRegistry()
    reg.register_chat("llamacpp", lambda: LlamaCppChat(base_url="http://127.0.0.1:8080"))
    reg.register_embedding("llamacpp_embedding", lambda: LlamaCppEmbeddingClient(base_url="http://127.0.0.1:8080"))

    chat = reg.get_chat_client("llamacpp")
    assert isinstance(chat, IChatClient)
    emb = reg.get_embedding_client("llamacpp_embedding")
    assert isinstance(emb, IEmbeddingClient)


def test_scheduler_llama_lifecycle_hooks():
    """测试 ModelScheduler 驱动 llama_cpp 引擎模型的生命周期钩子。"""
    scheduler = ModelScheduler(max_concurrent=1)
    events = []

    launcher_cfg = LlamaServerConfig(
        binary_path="/mock/bin/llama-server",
        model_path="/mock/model.gguf",
    )
    launcher = LlamaServerLauncher(launcher_cfg)

    # 模拟 launcher start 和 stop
    with patch.object(launcher, "start", side_effect=lambda **kw: events.append("start") or True):
        with patch.object(launcher, "stop", side_effect=lambda **kw: events.append("stop") or True):
            load_fn, unload_fn = launcher.create_scheduler_hooks()
            scheduler.register(
                model_name="llama-test",
                base_url=launcher.base_url,
                load_fn=load_fn,
                unload_fn=unload_fn,
                priority=60,
                engine="llama_cpp",
            )

            with scheduler.use("llama-test", timeout=1):
                assert scheduler.snapshot()["llama-test"]["loaded"] is True

            assert "start" in events
