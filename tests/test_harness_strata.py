# tests/test_harness_strata.py
# Strata 本地推理引擎（run config JSON + serve/server.py）支持的完整单元测试。
#
# 与 llama.cpp 的关系：两者都是「一条命令行 → 一个 OpenAI 兼容 HTTP 服务」的
# 本地引擎，共用 LocalServerLauncher（子进程/就绪探针/停机）与
# OpenAICompatChat（协议交互）；差异只在命令行合成与预检。

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.orchestrator import (
    ChatMessage,
    IChatClient,
    IEmbeddingClient,
    LlamaServerConfig,
    LlamaServerLauncher,
    LocalServerLauncher,
    ModelOrchestrator,
    ModelSourceType,
    OpenAICompatChat,
    StrataChat,
    StrataEmbeddingClient,
    StrataEngineConfig,
    StrataServerLauncher,
    build_engine_config,
    default_python_for_script,
    discover_runs,
    find_strata_root,
)


@pytest.fixture(autouse=True)
def clean_orchestrator():
    ModelOrchestrator.reset_instance()
    yield
    ModelOrchestrator.reset_instance()


# ════════════════════════════════════════════════════════════════════════════
# 1. run config 解析与命令行合成（对齐官方 run-<model>.sh）
# ════════════════════════════════════════════════════════════════════════════

def make_run_config(root: Path) -> dict:
    """一份贴近真实的 run config（路径全部落在测试目录内，便于预检通过）。

    字段与 ~/Strata/strata-coder-iq1_m.json 一一对应；layer_split / gpus_asked
    这类 harness 不认识的键必须原样保留（用户自己的设置不能被吞掉）。
    """
    return {
        "exe": str(root / "engine" / "strata"),
        "args": ["--pack", str(root / "data" / "packs" / "coder"),
                 "--native", str(root / "data" / "models" / "x-00001.gguf"),
                 "--spec", "4", "--max-context", "262144", "--kv", "int8"],
        "cwd": str(root),
        "tokenizer": str(root / "data" / "packs" / "coder" / "tokenizer"),
        "model_name": "qwen-coder-iq1_m",
        "log": str(root / "strata-coder.log"),
        "lib_dirs": [str(root / "cuda" / "lib64")],
        "port": 8080,
        "gpu": [0, 1],
        "layer_split": "auto",
        "gpus_asked": True,
    }



def tmp_exe(root: Path) -> Path:
    """造一个真实存在且可执行的“引擎二进制”（预检只要求 file + X_OK）。"""
    exe = root / "engine" / "strata"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def strata_tree(tmp_path: Path) -> Path:
    """构造一个最小可用的 Strata 检出：serve/server.py + run config + .venv + 引擎。"""
    root = tmp_path / "Strata"
    (root / "serve").mkdir(parents=True)
    (root / "serve" / "server.py").write_text("# stub\n", encoding="utf-8")
    (root / ".venv" / "bin").mkdir(parents=True)
    python = root / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    tmp_exe(root)                                  # 引擎二进制（预检要求 file + X_OK）
    (root / "data" / "packs" / "coder" / "tokenizer").mkdir(parents=True)
    (root / "strata-coder-iq1_m.json").write_text(
        json.dumps(make_run_config(root), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (root / "run-coder-iq1_m.sh").write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    return root

def test_run_config_roundtrip(strata_tree: Path):
    """run config 读到内存再写回，已知键被规范化、未知键一个不丢。"""
    cfg_path = strata_tree / "strata-coder-iq1_m.json"
    cfg = StrataEngineConfig.load(cfg_path)

    assert cfg.model_name == "qwen-coder-iq1_m"
    assert cfg.port == 8080
    assert cfg.gpu_list() == [0, 1]
    assert cfg.resolved_ctx_size() == 262144   # 上下文长度从 args 的 --max-context 推导
    assert cfg.extra == {"layer_split": "auto", "gpus_asked": True}

    out = cfg.effective_config_dict()
    for key in ("exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "gpu", "port"):
        assert key in out
    assert out["layer_split"] == "auto" and out["gpus_asked"] is True


def test_build_command_matches_run_script_semantics(strata_tree: Path):
    """命令行 = 「<venv python> serve/server.py --engine strata --config <json> ...」。"""
    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.server_script = str(strata_tree / "serve" / "server.py")

    cmd = cfg.build_command()
    assert cmd[0] == str(strata_tree / ".venv" / "bin" / "python")
    assert cmd[1] == str(strata_tree / "serve" / "server.py")
    assert cmd[2:4] == ["--engine", "strata"]
    assert "--config" in cmd and str(strata_tree / "strata-coder-iq1_m.json") in cmd
    assert "--port" in cmd and "8080" in cmd
    assert "--gpu" in cmd and "0,1" in cmd
    assert "--tokenizer" in cmd and str(strata_tree / "data" / "packs" / "coder" / "tokenizer") in cmd

    # 与官方脚本同构：cd <run config 的 cwd> + exec <命令行>
    script = cfg.run_script_text()
    assert script.startswith("#!/bin/sh\n")
    assert f'cd "{strata_tree}"' in script
    assert script.rstrip().endswith(cfg.to_command_string())


def test_engine_args_are_forwarded_verbatim():
    """引擎参数（--pack/--spec/--mtp/MTP 相关开关）必须原样透传，不做解释。"""
    args = ["--pack", "/p", "--spec", "4", "--mtp", "/m"]
    cfg = StrataEngineConfig(exe="/e/strata", args=list(args))
    assert cfg.engine_args() == args


def test_discover_runs_and_root(strata_tree: Path):
    """目录探测：找到 serve/server.py 与 strata-*.json，并带上 run-*.sh。"""
    root = find_strata_root(strata_tree)
    assert root == strata_tree.resolve()

    runs = discover_runs(strata_tree)
    assert len(runs) == 1
    run = runs[0]
    assert run.name == "strata:qwen-coder-iq1_m"
    assert Path(run.config_path).name == "strata-coder-iq1_m.json"
    assert run.script_name and Path(run.script_name).name == "run-coder-iq1_m.sh"

    cfg = build_engine_config(run)
    assert cfg.model_name == "qwen-coder-iq1_m"
    assert cfg.python_path == str(strata_tree / ".venv" / "bin" / "python")


def test_discover_runs_empty_when_no_config(tmp_path: Path):
    """只有 serve/server.py、没有 run config 时不应报错，返回空列表。"""
    root = tmp_path / "Strata"
    (root / "serve").mkdir(parents=True)
    (root / "serve" / "server.py").write_text("# stub\n", encoding="utf-8")
    assert find_strata_root(root) == root.resolve()
    assert discover_runs(root) == []


def test_default_python_prefers_venv(strata_tree: Path):
    """解释器推断：优先同目录 .venv（与官方脚本一致）。"""
    assert default_python_for_script(strata_tree / "serve" / "server.py") == str(
        strata_tree / ".venv" / "bin" / "python"
    )


def test_gpu_list_accepts_common_shapes():
    """gpu 字段兼容 2 / "2" / [0,1] / "0,1" / false 等写法。"""
    assert StrataEngineConfig(gpu=1).gpu_list() == [1]
    assert StrataEngineConfig(gpu="1").gpu_list() == [1]
    assert StrataEngineConfig(gpu=[0, 2]).gpu_list() == [0, 2]
    assert StrataEngineConfig(gpu="0,2").gpu_list() == [0, 2]
    assert StrataEngineConfig(gpu=False).gpu_list() == []
    assert StrataEngineConfig(gpu=None).gpu_list() == []


def test_save_config_writes_backup(strata_tree: Path):
    """保存 run config：原子替换 + 保留一份 .bak，未知键仍在。"""
    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.port = 8099
    cfg.server_script = str(strata_tree / "serve" / "server.py")
    target = cfg.save_config()

    assert target == strata_tree / "strata-coder-iq1_m.json"
    assert (strata_tree / "strata-coder-iq1_m.json.bak").exists()
    written = json.loads(target.read_text(encoding="utf-8"))
    assert written["port"] == 8099
    assert written["gpus_asked"] is True       # 未知键保留
    assert written["exe"] == str(strata_tree / "engine" / "strata")


# ════════════════════════════════════════════════════════════════════════════
# 2. Launcher：与 llama.cpp 共用基类，预检报错可操作
# ════════════════════════════════════════════════════════════════════════════

def test_strata_launcher_shares_base(strata_tree: Path):
    """Strata 与 llama.cpp 的 launcher 都派生自 LocalServerLauncher。"""
    assert issubclass(StrataServerLauncher, LocalServerLauncher)
    assert issubclass(LlamaServerLauncher, LocalServerLauncher)


def test_strata_launcher_base_url_and_target(strata_tree: Path):
    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.server_script = str(strata_tree / "serve" / "server.py")
    launcher = StrataServerLauncher(cfg)
    assert launcher.base_url == "http://127.0.0.1:8080"
    assert "Strata" in launcher.describe_target()
    assert launcher.command_string() is None      # 还没 start 过


def test_strata_preflight_requires_files(tmp_path: Path):
    """预检失败要给出可操作的中文提示，而不是启动后才炸。"""
    cfg = StrataEngineConfig(exe=str(tmp_path / "missing-engine"))
    launcher = StrataServerLauncher(cfg)
    with pytest.raises(FileNotFoundError) as e:
        launcher.preflight()
    assert "serve/server.py" in str(e.value)


def test_strata_preflight_checks_run_config(tmp_path: Path):
    """run config 缺失时明确报错（而不是让 serve/server.py 自己崩）。"""
    root = tmp_path / "Strata"
    (root / "serve").mkdir(parents=True)
    (root / "serve" / "server.py").write_text("# stub\n", encoding="utf-8")
    cfg = StrataEngineConfig(
        server_script=str(root / "serve" / "server.py"),
        config_path=str(root / "strata-nope.json"),
        exe="/bin/echo",
    )
    with pytest.raises(FileNotFoundError) as e:
        StrataServerLauncher(cfg).preflight()
    assert "run config" in str(e.value)


def test_strata_preflight_ok_with_real_tree(strata_tree: Path):
    """齐全的检出应通过预检（exe 用 /bin/sh 代替真实引擎二进制）。"""
    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.server_script = str(strata_tree / "serve" / "server.py")
    cfg.exe = "/bin/sh"
    StrataServerLauncher(cfg).preflight()          # 不抛异常即通过


@patch("subprocess.Popen")
def test_strata_launcher_start_and_stop(mock_popen, strata_tree: Path):
    """启动 → 就绪探测 → 停机，与 llama.cpp 走同一套基类逻辑。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 4321
    mock_popen.return_value = mock_proc

    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.server_script = str(strata_tree / "serve" / "server.py")
    launcher = StrataServerLauncher(cfg)

    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert launcher.start(wait_ready=True, timeout=5.0) is True

    assert launcher.is_running() is True
    assert launcher.is_ready() is True
    assert launcher.command_string() and "--engine strata" in launcher.command_string()

    mock_proc.poll.side_effect = [None, 0]
    launcher.stop(timeout=1.0)
    assert launcher._process is None


@patch("os.path.isfile", return_value=True)
@patch("os.access", return_value=True)
@patch("os.path.exists", return_value=True)
@patch("subprocess.Popen")
def test_llama_launcher_still_works(mock_popen, mock_exists, mock_access, mock_isfile):
    """抽基类后 llama.cpp 的行为不变（回归保护）。"""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    mock_proc.pid = 99
    mock_popen.return_value = mock_proc

    cfg = LlamaServerConfig(binary_path="/mock/llama-server", model_path="/mock/m.gguf", port=8090)
    launcher = LlamaServerLauncher(cfg)
    with patch("requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        assert launcher.start(wait_ready=True, timeout=5.0) is True
    assert launcher.base_url == "http://127.0.0.1:8090"
    assert mock_popen.call_args[0][0][0] == "/mock/llama-server"


# ════════════════════════════════════════════════════════════════════════════
# 3. 客户端：OpenAICompatChat 基类 + Strata 特化
# ════════════════════════════════════════════════════════════════════════════

def test_strata_chat_conforms_ichatclient():
    chat = StrataChat(base_url="http://127.0.0.1:8080", model_name="qwen-coder-iq1_m")
    assert isinstance(chat, IChatClient)
    assert isinstance(chat, OpenAICompatChat)
    assert chat.model == "qwen-coder-iq1_m"


def test_strata_chat_reasoning_only_answer():
    """Strata 只生成思考时 content 为 null：思考在 reasoning_content 里，不能丢。"""
    chat = StrataChat(base_url="http://127.0.0.1:8080", model_name="qwen-coder")
    fake = {
        "choices": [{
            "message": {"role": "assistant", "content": None,
                        "reasoning_content": "We need to answer the user."},
            "finish_reason": "length",
        }],
        "usage": {"prompt_tokens": 56, "completion_tokens": 8},
        "timings": {"predicted_per_second": 18.0},
        "model": "qwen-coder",
    }
    with patch.object(chat._http_session, "post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200, json=MagicMock(return_value=fake))
        resp = chat.invoke([ChatMessage.user("hi")])

    assert resp.content == ""
    assert resp.reasoning_content == "We need to answer the user."
    assert resp.usage["completion_tokens"] == 8
    assert chat.last_timings["predicted_per_second"] == 18.0


@pytest.mark.asyncio
async def test_strata_stream_skips_keepalive_and_reads_timings():
    """Strata 的 SSE 带 `: keep-alive` 注释帧；timings 在收尾 chunk 里。"""
    chat = StrataChat(base_url="http://127.0.0.1:8080", model_name="qwen-coder")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = [
        'data: {"choices":[{"delta":{"role":"assistant","content":""}}]}',
        ': keep-alive',
        'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}',
        'data: {"choices":[{"delta":{"content":"答案"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
        '"usage":{"prompt_tokens":10,"completion_tokens":5},'
        '"timings":{"predicted_per_second":20.0}}',
        'data: [DONE]',
    ]
    with patch.object(chat._http_session, "post", return_value=mock_resp):
        chunks = [c async for c in chat.stream([ChatMessage.user("hi")])]

    assert {"reasoning_content": "思考"} in chunks
    assert "答案" in chunks
    usage = next(c for c in chunks if isinstance(c, dict) and "usage" in c)
    assert usage["usage"]["completion_tokens"] == 5
    assert any(isinstance(c, dict) and c.get("timings") for c in chunks)


def test_strata_error_body_is_reported():
    """上游错误体（Strata 的 400/503 报文）必须拼进异常，便于定位。"""
    chat = StrataChat(base_url="http://127.0.0.1:8080", model_name="qwen-coder")
    resp = MagicMock()
    resp.status_code = 503
    resp.text = '{"error": {"type": "server_error", "message": "the engine is not running"}}'
    resp.request = MagicMock(url="http://127.0.0.1:8080/v1/chat/completions")
    with pytest.raises(RuntimeError) as e:
        chat._raise_for_status(resp)
    assert "the engine is not running" in str(e.value)


def test_strata_embedding_client_shape():
    """Strata 没有 /v1/embeddings：接口形状保留，但调用会走真实 HTTP（明确失败）。"""
    client = StrataEmbeddingClient(base_url="http://127.0.0.1:8080")
    assert isinstance(client, IEmbeddingClient)


def test_system_message_normalization_applies_to_both_engines():
    """严格的 Jinja 模板不接受多条/非头部 system —— 两个引擎共用归一化。"""
    chat = StrataChat(base_url="http://127.0.0.1:9999", model_name="m")
    msgs = [
        {"role": "system", "content": "A"},
        {"role": "user", "content": "q"},
        {"role": "system", "content": "B"},
    ]
    out = chat._normalize_system_messages(msgs)
    assert [m["role"] for m in out] == ["system", "user"]
    assert out[0]["content"] == "A\n\nB"


# ════════════════════════════════════════════════════════════════════════════
# 4. Orchestrator：注册、状态、启动参数
# ════════════════════════════════════════════════════════════════════════════

def _strata_cfg(strata_tree: Path, port: int = 8080) -> StrataEngineConfig:
    cfg = StrataEngineConfig.load(strata_tree / "strata-coder-iq1_m.json")
    cfg.server_script = str(strata_tree / "serve" / "server.py")
    cfg.port = port
    return cfg


def test_orchestrator_registers_strata_engine(strata_tree: Path):
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree), priority=35)

    status = orch.status()
    info = next(m for m in status["models"] if m["name"] == "strata:coder")
    assert info["source_type"] == ModelSourceType.LOCAL_STRATA.value
    assert info["is_local"] is True
    assert info["engine"] == "strata"
    assert info["is_scheduled"] is True
    assert "--engine strata" in info["command"]

    # 与 llama.cpp 同在本地轨道：调度器里也注册了
    assert "strata:coder" in orch._scheduler.snapshot()


def test_orchestrator_launch_params_are_engine_aware(strata_tree: Path):
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree))
    orch.register_local_llamacpp(
        "llama:x", LlamaServerConfig(binary_path="/mock/llama-server", model_path="/m.gguf")
    )

    s = orch.get_launch_params("strata:coder")
    assert s["engine"] == "strata"
    assert s["gpu"] == [0, 1]
    assert "--pack" in s["args"]
    assert "run_script_preview" in s
    assert "run-<model>" not in s["command_preview"]        # 只是提示串

    llama_params = orch.get_launch_params("llama:x")
    assert llama_params["engine"] == "llama_cpp"
    assert llama_params["n_gpu_layers"] is None


def test_orchestrator_applies_strata_params(strata_tree: Path):
    """UI 提交的参数要能改到 run config（含多行文本 → 列表的归一化）。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree))

    changed = orch.apply_launch_params("strata:coder", {
        "port": "8099",
        "gpu": "0",
        "args": ["--pack", "/a", "--spec", "2"],       # 列表
        "lib_dirs": "/x/lib\n/y/lib",                  # 多行文本
        "idle_unload_s": "120",
        "lazy": True,
        "unknown_field": "ignored",
    })
    assert set(changed) == {"port", "gpu", "args", "lib_dirs", "idle_unload_s", "lazy"}
    assert "unknown_field" not in changed

    s = orch.get_launch_params("strata:coder")
    assert s["port"] == 8099
    assert s["gpu"] == "0"
    assert s["ctx_size"] is None                    # args 换掉后就没有 --max-context（动态推导）
    # 改写上下文长度等价于改写引擎参数，且不残留旧的 --max-context
    orch.apply_launch_params("strata:coder", {"ctx_size": 32768})
    after = orch.get_launch_params("strata:coder")
    assert after["ctx_size"] == 32768
    assert after["args"].count("--max-context") == 1
    assert s["lib_dirs"] == ["/x/lib", "/y/lib"]
    assert s["lazy"] is True


def test_orchestrator_preview_matches_applied_config(strata_tree: Path):
    """预览（不落地）与实际配置应当一致，且预览不改动运行中配置。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree))

    preview = orch.preview_launch_params("strata:coder", {"port": "8111"})
    assert "--port 8111" in preview["command"]
    assert preview["engine"] == "strata"
    assert preview["run_script"].startswith("#!/bin/sh")
    assert orch.get_launch_params("strata:coder")["port"] == 8080     # 未被改动


def test_orchestrator_save_strata_config(strata_tree: Path):
    """「保存」直接回写 run config（用户调好的参数脱离 harness 也可复现）。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree))
    orch.apply_launch_params("strata:coder", {"port": "8123"})

    written = orch.save_launch_params("strata:coder", {})
    assert Path(written["config_path"]) == strata_tree / "strata-coder-iq1_m.json"
    on_disk = json.loads((strata_tree / "strata-coder-iq1_m.json").read_text(encoding="utf-8"))
    assert on_disk["port"] == 8123
    assert on_disk["layer_split"] == "auto"


def test_launch_params_reject_non_local_model():
    """远程 API 模型没有可编辑的启动参数：明确报错而不是静默返回空。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_api_openai("api:x", api_key="sk-test")
    with pytest.raises(ValueError):
        orch.get_launch_params("api:x")


def test_kv_offload_switch_only_touches_llamacpp(strata_tree: Path):
    """KV offload 开关是 llama.cpp 专有：不能误改 Strata 的 run config。"""
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    orch.register_local_llamacpp("llama:x", LlamaServerConfig(binary_path="/b", model_path="/m.gguf"))
    orch.register_local_strata("strata:coder", _strata_cfg(strata_tree))

    assert orch.set_kv_offload_disabled(True) == 1
    assert orch._specs["llama:x"].llama_config.no_kv_offload is True
    assert orch._specs["strata:coder"].strata_config.extra.get("no_kv_offload") is None


# ════════════════════════════════════════════════════════════════════════════
# 5. dsn_ui 集成：发现 → 注册 → 端口避让
# ════════════════════════════════════════════════════════════════════════════

def test_dsn_ui_strata_registration(strata_tree: Path, monkeypatch):
    from apps.dsn_ui import strata_integration

    monkeypatch.setenv("DSN_STRATA_DIR", str(strata_tree))
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=1)
    names = strata_integration.register_strata_models(orch, priority=35)

    assert names == ["strata:qwen-coder-iq1_m"]
    spec = orch._specs["strata:qwen-coder-iq1_m"]
    assert spec.source_type is ModelSourceType.LOCAL_STRATA
    assert spec.strata_config.python_path == str(strata_tree / ".venv" / "bin" / "python")


def test_dsn_ui_port_avoidance(strata_tree: Path, monkeypatch):
    """端口被其它已注册本地模型占用时自动让开（避免静默错配）。"""
    from apps.dsn_ui import strata_integration

    monkeypatch.setenv("DSN_STRATA_DIR", str(strata_tree))
    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    orch.register_local_llamacpp(
        "llama:occupier",
        LlamaServerConfig(binary_path="/b", model_path="/m.gguf", port=8080),
    )
    names = strata_integration.register_strata_models(orch)
    assert names
    assert orch._specs[names[0]].strata_config.port != 8080


def test_dsn_ui_strata_status(strata_tree: Path, monkeypatch):
    from apps.dsn_ui import strata_integration

    monkeypatch.setenv("DSN_STRATA_DIR", str(strata_tree))
    st = strata_integration.strata_status()
    assert st["available"] is True
    assert st["runs"][0]["model_name"] == "qwen-coder-iq1_m"
    assert "--engine strata" in st["runs"][0]["command_preview"]


def test_dsn_ui_strata_status_absent(tmp_path: Path, monkeypatch):
    from apps.dsn_ui import strata_integration

    monkeypatch.setenv("DSN_STRATA_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(strata_integration, "find_strata_root", lambda root=None: None)
    st = strata_integration.strata_status()
    assert st["available"] is False
    assert st["runs"] == []


# ════════════════════════════════════════════════════════════════════════════
# 6. dsn_ui HTTP 层：launch-params 端点对两种引擎都成立
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def ui_client(strata_tree: Path, monkeypatch):
    """构造 dsn_ui 的 FastAPI 测试客户端（不启动任何真实引擎）。"""
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from apps.dsn_ui import server as ui_server

    orch = ModelOrchestrator.get_instance(max_concurrent_slots=2)
    cfg = _strata_cfg(strata_tree)
    orch.register_local_strata("strata:coder", cfg)
    orch.register_local_llamacpp(
        "llama:mock", LlamaServerConfig(binary_path="/b", model_path="/m.gguf", port=8091)
    )

    # 只测路由层：用最小替身引擎（不触碰真实 orchestrator 之外的东西）。
    engine = MagicMock()
    engine.orchestrator = orch
    engine.load_launch_overrides.return_value = {"llama:mock": {"ctx_size": 8192}}
    engine.save_launch_override.return_value = {"ctx_size": 8192}
    engine.clear_launch_override.return_value = True

    app = ui_server.create_app(engine)
    return fastapi_testclient.TestClient(app)


def test_ui_launch_params_endpoints_engine_aware(ui_client):
    r = ui_client.get("/api/models/launch-params", params={"model": "strata:coder"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "strata"
    assert "--engine strata" in body["command_preview"]

    r = ui_client.get("/api/models/launch-params", params={"model": "llama:mock"})
    assert r.status_code == 200
    assert r.json()["engine"] == "llama_cpp"

    # 预览：两种引擎都给命令行，Strata 额外给 run 脚本
    r = ui_client.post("/api/models/launch-params/preview",
                       json={"model": "strata:coder", "params": {"port": "8200"}})
    assert r.status_code == 200
    assert "--port 8200" in r.json()["command"]
    assert r.json()["run_script"].startswith("#!/bin/sh")

    # 非本地引擎模型：明确 404/400
    r = ui_client.get("/api/models/launch-params", params={"model": "nope"})
    assert r.status_code == 404


def test_ui_models_list_exposes_engine(ui_client):
    r = ui_client.get("/v1/models")
    assert r.status_code == 200
    data = {m["id"]: m for m in r.json()["data"]}
    assert data["strata:coder"]["owned_by"] == "strata"
    assert data["strata:coder"]["meta"]["engine"] == "strata"
    assert data["llama:mock"]["owned_by"] == "llama_cpp"


def test_ui_save_launch_params_writes_strata_config(ui_client, strata_tree: Path):
    r = ui_client.post("/api/models/launch-params/save",
                       json={"model": "strata:coder", "params": {"port": "8300"}})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "strata"
    assert body["status"] == "ok"
    on_disk = json.loads((strata_tree / "strata-coder-iq1_m.json").read_text(encoding="utf-8"))
    assert on_disk["port"] == 8300


def test_ui_strata_integration_endpoint(ui_client, strata_tree: Path, monkeypatch):
    monkeypatch.setenv("DSN_STRATA_DIR", str(strata_tree))
    r = ui_client.get("/api/integration/strata")
    assert r.status_code == 200
    assert r.json()["strata_dir"] == str(strata_tree)
