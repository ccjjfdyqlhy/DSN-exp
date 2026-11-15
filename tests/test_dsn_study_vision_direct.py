# -*- coding: utf-8 -*-
"""AI 主动视觉「图片直发主模型」链路的回归测试。

这条新链路有三段，每段都要有回归护栏：

  1) harness 注入机制（harness/agent/adapters.py + harness/agent/loop.py）
     —— 工具把图片交出来之后：
       * 图片必须以 content parts 的形式附在一条 **user** 消息上
         （tool 消息的 content 在协议上是字符串，塞图片会被拍平/400）；
       * 图片**绝不能**以 base64 文本的形式留在 tool 消息里 ——
         一次抓帧就是几 MB 文本，留在上下文里会直接烧穿 token 预算；
       * 流式路径（run_stream）也不能把 ToolResult.data 里的 image_url 弄丢；
       * 步数耗尽后的收束轮（_finalize_after_max_steps）既不能把图片拍平成
         字符串，收束指令也要**并入**末尾那条图片 user 消息（不能另起一条
         user → user/user 连续在部分 chat_template 下是敏感序列）。

  2) 主模型图片能力判定（apps/dsn_study/vision_support.py）
     —— 判别式探测（发一张写着 4 位数字的图，答对才算「支持图片」，
        纯文本模型靠猜的命中率约万分之一）、显式配置覆盖、结果缓存、
        运行时降级（mark_image_unsupported）。

  3) look_around 的两条路（visual_perception 技能）
     —— 直发主模型（mode="direct"，画面原样进上下文，**不调用** VLM）
        / VLM 转述（mode="vlm"，主模型是纯文本模型时的老路）。

全部离线：模型调用一律用假客户端桩掉，**绝不真打 API**。

⚠ 为什么本文件必须用**测试专属**的 (base_url, model)：
  apps/dsn_study/vision_support.py 的能力判定是**进程级**的，缓存键是
  (base_url, model_name)，键相同就共用同一份结论和同一个「探测进行中」标记。
  而应用启动时（apps/dsn_study/boot.py::_start_main_model_image_probe）会起一个
  **后台线程**，拿 Config 里的**真实**模型名/网关地址去探测主模型 —— 那是一次
  真实的网络请求。若本文件也用同一组 Config 值，就会出现两件事：
    ① 本文件的判定可能直接命中别人（开机预探测）写下的结论，
       假客户端根本不会被调用，断言就会随启动时序忽绿忽红；
    ② 更糟的是开机预探测还在跑时，本文件的「探测」会被当成同一次探测，
       既测不到东西，又可能把请求打到真实网关上。
  所以本文件的夹具把 Config.MAIN_MODEL_NAME / OPENAI_API_BASE 换成测试专属值
  （见 _isolate_vision_config），让判定键与其它进程内参与者彻底不重叠。
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from harness.agent.loop import AgentLoop
from harness.agent.adapters import NativeToolCallAdapter
from harness.tools import ToolRegistry, ToolResult
from infra.models.base import ChatMessage, ChatResponse
from infra.orchestrator.base import count_image_parts

from apps.dsn_study.config import Config
from apps.dsn_study.vision_support import (
    PROBE_DIGITS,
    direct_to_main_enabled,
    main_model_supports_images,
    mark_image_unsupported,
    probe_image_data_url,
    reset_image_support_cache,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# ── 测试用的假图片 ──

#: 假 PNG 负载：真 PNG 头 + 一段填充。base64 后约 1.4KB ——
#: 刻意**小于** AgentLoop 默认的 max_output_chars(6000)，
#: 这样「tool 消息里没有 base64」就一定是「被摘掉了」而不是「被截断了」，
#: 断言才有意义。
_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024
_B64_BODY = base64.b64encode(_FAKE_PNG_BYTES).decode("ascii")
DATA_URL = "data:image/png;base64," + _B64_BODY

#: 1x1 合法 PNG（用作「客户端回传的帧」，与既有视觉测试保持一致）
PNG_DATA_URL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


# ── 通用小工具 ──

def _roles(messages) -> list[str]:
    """取消息角色序列（断言用）。"""
    return [m.role for m in messages]


def _has_image_part(messages) -> bool:
    """消息里是否带 image_url 内容块。"""
    for m in messages or []:
        content = getattr(m, "content", None)
        if isinstance(content, (list, tuple)):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


# ── 假客户端 ──

class _ScriptedChatClient:
    """按剧本返回 ChatResponse 的假主模型；记录每次调用收到的消息。

    用途：harness 注入机制的测试 —— 第一轮返回「带 tool_calls 的回复」，
    第二轮返回普通回复，于是第二次调用收到的消息就是「回喂后」的上下文。
    """

    model = "fake-main-model"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        if not self._responses:
            return ChatResponse(content="（剧本已空）")
        return self._responses.pop(0)


class _StreamingFakeClient:
    """实现 stream() 的假主模型：每轮吐一组 chunk。

    chunk 形态与 provider 的 SSE 增量一致：
      * 文本增量：str
      * 工具调用增量：{"tool_calls": [{"index", "id", "name", "arguments"}]}
    """

    model = "fake-main-model"

    def __init__(self, script):
        self._script = list(script)
        self.calls: list[list] = []

    def stream(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        chunks = self._script.pop(0) if self._script else []

        async def _agen():
            for c in chunks:
                yield c

        return _agen()


class _VisionCapableClient:
    """「看得见图」的假主模型。

    只有真的收到 image_url 内容块时才答出图里的 4 位数字；
    没收到图就答「我没收到图片」。
    判定必须能区分「看图的模型」和「纯文本模型」，否则探测就失去意义。
    """

    model = "fake-vision-main"

    def __init__(self, digits: str = PROBE_DIGITS):
        self._digits = digits
        self.calls: list[list] = []

    def invoke(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        if _has_image_part(messages):
            return ChatResponse(content=self._digits)
        return ChatResponse(content="我没有收到图片，无法作答。")


class _TextOnlyClient:
    """纯文本假主模型：无论有没有图都只回固定字符串（答不对探测题）。"""

    model = "fake-text-main"

    def __init__(self, reply: str = "抱歉，我无法查看图片，请用文字描述画面。"):
        self._reply = reply
        self.calls: list[list] = []

    def invoke(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        return ChatResponse(content=self._reply)


class _ExplodingModels:
    """一被调用就炸的 VLM 桩 —— 用来证明「直发时根本没调用 VLM」。"""

    def __init__(self):
        self.calls: list[tuple] = []

    def describe_image(self, image, prompt):
        self.calls.append((image, prompt))
        raise AssertionError("直发模式下不应该调用 VLM describe_image")


class _StubLLM:
    """VLM 转述桩：返回固定描述。"""

    def __init__(self, description: str = "一张数学卷子"):
        self._description = description
        self.calls: list[tuple] = []

    def describe_image(self, image, prompt):
        self.calls.append((image, prompt))
        return self._description


# ── 夹具 ──

@pytest.fixture(autouse=True)
def _reset_vision_support_cache():
    """每个用例前后都清空能力判定缓存。

    为什么必须清：vision_support 的缓存是**模块级**的，键是
    (base_url, model_name)。look_around 的用例用的是 Config 里的真实
    模型名/网关地址，若上一个用例把同一键判成「不支持图片」，
    后一个用例会直接命中缓存走 VLM 老路 —— 用例之间会互相污染。
    """
    reset_image_support_cache()
    yield
    reset_image_support_cache()


@pytest.fixture(autouse=True)
def _isolate_vision_config(monkeypatch):
    """把判定相关的配置钉死成「自动」，不受本机 .env 影响。

    - MAIN_MODEL_SUPPORTS_IMAGE="auto"：走探测（而不是读机器上的显式覆盖）；
    - VISION_DIRECT_TO_MAIN="auto"：允许直发，但具体走哪条由能力判定决定；
    - VISION_LOOK_AROUND_DEDUP=0：关掉去重窗口，避免用例之间/之内
      命中缓存导致「看起来没调用 VLM/图片路径」的假象。

    为什么要改 MAIN_MODEL_NAME / OPENAI_API_BASE：
      vision_support 的判定缓存键是 (base_url, model_name)，且是**进程级**的。
      应用启动时会起一个后台探测线程（boot._start_main_model_image_probe），
      用的正是 Config 里的真实模型名/网关地址，还会**真发一次网络请求**。
      本文件若沿用同一组值，就会与那个后台探测共用同一个键：
        * 后台探测已把结论写进缓存 → 本文件的假客户端根本不会被调用
          （「判定确实发生过」这类断言会随机失败）；
        * 后台探测还在跑 → 本文件的判定被并到同一次探测上，
          look_around 可能误走 VLM 老路。
      换成测试专属的模型名/地址即可彻底隔离：本文件的判定键与其它进程内
      参与者不重叠，且本文件所有模型调用都是桩，不会打到任何真实网关。
      （详见文件头说明。）
    """
    monkeypatch.setattr(Config, "MAIN_MODEL_SUPPORTS_IMAGE", "auto")
    monkeypatch.setattr(Config, "VISION_DIRECT_TO_MAIN", "auto")
    monkeypatch.setattr(Config, "MAIN_MODEL_IMAGE_PROBE", True)
    monkeypatch.setattr(Config, "VISION_LOOK_AROUND_DEDUP", 0)
    monkeypatch.setattr(Config, "MAIN_MODEL_NAME", "vision-test-main-model")
    monkeypatch.setattr(Config, "OPENAI_API_BASE", "http://vision-test.invalid/v1")


@pytest.fixture()
def coordinator():
    """真实的 VisionCoordinator（不接 db —— 只用请求生命周期那一段）。

    刻意用真协调器而不是手搓假对象：look_around 的
    create_request → wait_with_error → submit_frame 契约必须被真的跑一遍，
    否则测的就不是线上那条链路了。
    """
    from apps.dsn_study.api.vision import VisionCoordinator
    return VisionCoordinator(db=None, request_timeout=5)


@pytest.fixture()
def visual_tools_module():
    """按文件路径加载技能工具模块（技能目录不是 python 包，线上也是这么加载的）。"""
    path = (REPO_ROOT / "apps/dsn_study/skills/builtin/visual_perception"
            / "tools/visual_tools.py")
    spec = importlib.util.spec_from_file_location(
        "skill_tools_visual_perception_direct", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spawn_frame_responder(coord, frames: dict, uid: int = 1):
    """模拟边缘客户端：轮询待下发的请求 → 回传帧。

    对应真实链路：look_around 建请求 → /api/heartbeat 把请求下发给 CLI
    → CLI 抓帧 → POST /api/vision/frame 回传 → 唤醒 look_around。
    """
    def _run():
        for _ in range(200):
            vr = coord.pending_for_uid(uid)
            if vr:
                coord.submit_frame(vr["request_id"], frames)
                return
            time.sleep(0.02)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ══════════════════════════════════════════════════════════════════
# 1) harness 注入机制
# ══════════════════════════════════════════════════════════════════

def _registry_with(handler) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tool("vision.snap", "抓一帧并把画面交出来", handler)
    return reg


def _tool_call_response() -> ChatResponse:
    """第一轮：模型请求调用 vision.snap（wire 名是 vision__snap）。"""
    from infra.models.base import ToolCall
    return ChatResponse(
        content="我先看看客厅。",
        tool_calls=[ToolCall(id="call_1", name="vision__snap", arguments={})],
    )


def test_agent_loop_attaches_image_as_user_message_and_keeps_base64_out_of_tool_msg():
    """图片走 user 消息进上下文；tool 消息里**不能**留下 base64 原文。

    断言意图：
      * count_image_parts == 1 —— 图片确实以 content parts 的形式进了上下文
        （若被拍平成文本，这里会是 0，模型就「看不见」图了）；
      * 角色序列 user → assistant → tool → user —— 图片挂在 tool 结果之后的
        user 消息上（tool 消息的 content 在协议上是字符串，不能塞图片）；
      * tool 消息里不含 base64 —— 这是**关键回归点**：一旦摘图逻辑坏掉，
        几 MB 的 base64 会以文本形式灌进上下文，直接烧穿 token 预算。
    """
    def _handler():
        # 工具把图放在**结果顶层**（ToolResult.data 会被 AgentLoop 展开到
        # 结果 payload 顶层 —— 这正是 look_around 直发时的形态）。
        return ToolResult.ok("已抓帧", image_url=DATA_URL, note="客厅摄像头")

    client = _ScriptedChatClient([
        _tool_call_response(),
        ChatResponse(content="我看到客厅里有一张桌子。"),
    ])
    loop = AgentLoop(client=client, tools=_registry_with(_handler),
                     adapter=NativeToolCallAdapter(), max_steps=4)

    result = loop.run([ChatMessage.user("看看客厅")])

    assert result.reply == "我看到客厅里有一张桌子。"
    assert len(client.calls) == 2, "应当有「请求工具」+「回喂后」两次模型调用"

    msgs = client.calls[1]

    # ① 图片以 content parts 的形式进上下文，数量正好 1
    assert count_image_parts(msgs) == 1

    # ② 角色序列：user → assistant → tool → user（图片那条是末尾的 user）
    assert _roles(msgs) == ["user", "assistant", "tool", "user"]

    # ③ tool 消息里绝不能有 base64 原文
    tool_msgs = [m for m in msgs if m.role == "tool"]
    assert len(tool_msgs) == 1
    tool_content = tool_msgs[0].content
    assert isinstance(tool_content, str), "tool 消息的 content 必须是字符串"
    assert _B64_BODY not in tool_content, "tool 消息里残留了 base64 原文"
    assert DATA_URL not in tool_content, "tool 消息里残留了 data URL"
    assert "base64" not in tool_content, "tool 消息里出现了 base64 字样"
    # 上下文体积没有被图片撑大（base64 若漏进来，这里会是几 MB）
    assert len(tool_content) < 2000

    # ④ 但工具的其它信息必须还在（证明是「摘掉图片」而不是「整个 payload 丢了」）
    assert "客厅摄像头" in tool_content

    # ⑤ 图片那条 user 消息的内容形态：text + image_url 两个 part
    image_msg = msgs[-1]
    assert image_msg.role == "user"
    assert isinstance(image_msg.content, list)
    types = [p.get("type") for p in image_msg.content]
    assert types == ["text", "image_url"]
    assert image_msg.content[1]["image_url"]["url"] == DATA_URL


def test_agent_loop_extracts_image_from_output_dict():
    """图放在工具结果的 output dict 里（{"output": {"image_url": ...}}）也能提取。

    断言意图：这是另一条常见约定 —— 工具把整块产物放在 output 里
    （而不是放 data）。摘图逻辑若只认顶层 key，这类工具的图就会**静默丢失**，
    模型永远看不到画面。
    """
    def _handler():
        # 工具直接返回一个 dict → 被包成 ToolResult.ok(dict) → 落在 output 里
        return {"image_url": DATA_URL, "note": "客厅摄像头"}

    client = _ScriptedChatClient([
        _tool_call_response(),
        ChatResponse(content="看到了。"),
    ])
    loop = AgentLoop(client=client, tools=_registry_with(_handler),
                     adapter=NativeToolCallAdapter(), max_steps=4)

    loop.run([ChatMessage.user("看看客厅")])

    msgs = client.calls[1]
    assert count_image_parts(msgs) == 1, "output 里的图没有被摘出来"
    assert _roles(msgs) == ["user", "assistant", "tool", "user"]

    tool_content = [m for m in msgs if m.role == "tool"][0].content
    assert _B64_BODY not in tool_content, "tool 消息里残留了 base64 原文"
    assert "客厅摄像头" in tool_content


def test_run_stream_keeps_image_url_from_tool_result_data():
    """流式路径（run_stream）下，ToolResult.data 里的 image_url 不能丢。

    断言意图：run_stream 自己拼 results payload —— 一旦漏了
    `payload.update(result.data)`，图片连 results 都进不去，
    build_round 自然也摘不到，流式链路就会**静默**变成「模型看不见图」。
    """
    def _handler():
        return ToolResult.ok("已抓帧", image_url=DATA_URL)

    client = _StreamingFakeClient([
        # 第一轮：流式吐工具调用增量
        [{"tool_calls": [{"index": 0, "id": "call_1",
                          "name": "vision__snap", "arguments": "{}"}]}],
        # 第二轮：流式吐普通文本
        ["我", "看到一张桌子"],
    ])
    loop = AgentLoop(client=client, tools=_registry_with(_handler),
                     adapter=NativeToolCallAdapter(), max_steps=4)

    async def _collect():
        return [ev async for ev in loop.run_stream([ChatMessage.user("看看客厅")])]

    events = asyncio.run(_collect())

    # ① 工具结果事件里能看到 image_url（data 没被丢）
    tool_events = [ev for ev in events if ev.kind == "tool_result"]
    assert len(tool_events) == 1
    assert tool_events[0].tool_result["image_url"] == DATA_URL

    # ② 第二轮（回喂后）的消息里，图片以 content parts 的形式在
    assert len(client.calls) == 2
    msgs = client.calls[1]
    assert count_image_parts(msgs) == 1
    assert _roles(msgs) == ["user", "assistant", "tool", "user"]

    # ③ tool 消息里没有 base64 原文
    tool_content = [m for m in msgs if m.role == "tool"][0].content
    assert _B64_BODY not in tool_content
    assert DATA_URL not in tool_content

    # ④ 最终回复正常产出（流式链路没被图片打断）
    done = [ev for ev in events if ev.kind == "done"]
    assert done and done[0].reply == "我看到一张桌子"


def test_finalize_after_max_steps_merges_instruction_into_image_user_message():
    """步数耗尽后的收束轮：收束指令必须**并入**末尾那条图片 user 消息。

    断言意图：
      * 图片 part 还在（count_image_parts == 1）—— 收束轮不能把 list content
        拍平成字符串，否则模型在写最后一段总结时反而「看不见」刚拿到的画面
        （收束轮恰恰是模型最需要看图的那一轮）；
      * 收束指令是**同一条** user 消息里的另一个 text part —— 若另起一条 user
        消息，消息序列会变成 …→user→user，部分 chat_template 对连续 user
        是敏感序列；
      * 图片本体（data URL）没有被改动。
    """
    def _handler():
        return ToolResult.ok("已抓帧", image_url=DATA_URL)

    client = _ScriptedChatClient([
        _tool_call_response(),                                # 第 1 轮：请求工具
        ChatResponse(content="收束答复：客厅里有一张桌子。"),   # 第 2 轮：收束轮
    ])
    loop = AgentLoop(client=client, tools=_registry_with(_handler),
                     adapter=NativeToolCallAdapter(), max_steps=1)

    result = loop.run([ChatMessage.user("看看客厅")])

    assert result.hit_max_steps is True
    assert len(client.calls) == 2, "应当是「请求工具」+「收束轮」两次调用"
    finalize_msgs = client.calls[1]

    # ① 图片 part 还在（没被拍平成字符串）
    assert count_image_parts(finalize_msgs) == 1

    # ② 收束指令并入末尾那条 user 消息（没有多出一条 user）
    assert _roles(finalize_msgs) == ["user", "assistant", "tool", "user"]
    last = finalize_msgs[-1]
    assert last.role == "user"
    assert isinstance(last.content, list), "图片消息的 content 必须仍是 parts 列表"
    types = [p.get("type") for p in last.content]
    assert types == ["text", "image_url", "text"], \
        "收束指令应当是同一条 user 消息里追加的 text part"
    assert "步数上限" in last.content[-1]["text"]
    # 图片本体没被动过
    assert last.content[1]["image_url"]["url"] == DATA_URL

    # ③ 收束轮的答复正常产出
    assert "收束答复" in result.reply


def test_finalize_after_max_steps_keeps_image_in_stream_path():
    """流式路径的收束轮同样不能丢图、也不能多出一条 user 消息。

    断言意图：run_stream 与 run_async 是两条独立的入口，
    各自调用 _finalize_after_max_steps，两边都得守住。
    """
    def _handler():
        return ToolResult.ok("已抓帧", image_url=DATA_URL)

    client = _StreamingFakeClient([
        [{"tool_calls": [{"index": 0, "id": "call_1",
                          "name": "vision__snap", "arguments": "{}"}]}],
        ["收束答复：客厅里有一张桌子。"],
    ])
    loop = AgentLoop(client=client, tools=_registry_with(_handler),
                     adapter=NativeToolCallAdapter(), max_steps=1)

    async def _collect():
        return [ev async for ev in loop.run_stream([ChatMessage.user("看看客厅")])]

    events = asyncio.run(_collect())

    assert len(client.calls) == 2
    finalize_msgs = client.calls[1]
    assert count_image_parts(finalize_msgs) == 1
    assert _roles(finalize_msgs) == ["user", "assistant", "tool", "user"]
    last = finalize_msgs[-1]
    assert isinstance(last.content, list)
    assert [p.get("type") for p in last.content] == ["text", "image_url", "text"]
    assert last.content[1]["image_url"]["url"] == DATA_URL

    done = [ev for ev in events if ev.kind == "done"]
    assert done and done[0].hit_max is True


# ══════════════════════════════════════════════════════════════════
# 2) 主模型图片能力判定（apps/dsn_study/vision_support.py）
# ══════════════════════════════════════════════════════════════════

def test_probe_detects_vision_capable_model():
    """会看图的模型 → 判定为「支持图片」。

    断言意图：探测走的是「发一张写着 4 位数字的图、问数字是多少」，
    所以必须断言**探测请求里真的带了图片**，否则「答对了」可能只是巧合。
    """
    client = _VisionCapableClient()
    assert main_model_supports_images(client, model_name="m-vision",
                                      base_url="b1") is True
    assert len(client.calls) == 1
    assert count_image_parts(client.calls[0]) == 1, "探测请求里必须带图片"


def test_probe_rejects_text_only_model():
    """纯文本模型 → 判定为「不支持图片」。

    断言意图：纯文本模型对「图里的数字是多少」只能瞎猜/答非所问，
    判不出来就必须保守地按「不支持」处理 —— 否则会把图发给看不见图的模型，
    换回一段**幻觉描述**（比报错更糟）。
    """
    client = _TextOnlyClient()
    assert main_model_supports_images(client, model_name="m-text",
                                      base_url="b1") is False
    assert len(client.calls) == 1


def test_explicit_true_overrides_probe(monkeypatch):
    """MAIN_MODEL_SUPPORTS_IMAGE="true" → 覆盖探测结果，且不再发探测请求。"""
    monkeypatch.setattr(Config, "MAIN_MODEL_SUPPORTS_IMAGE", "true")
    client = _TextOnlyClient()
    assert main_model_supports_images(client, model_name="m-ovr",
                                      base_url="b1") is True
    assert client.calls == [], "显式覆盖时不该再发探测请求"


def test_explicit_false_overrides_probe(monkeypatch):
    """MAIN_MODEL_SUPPORTS_IMAGE="false" → 覆盖探测结果（即使模型其实看得见图）。"""
    monkeypatch.setattr(Config, "MAIN_MODEL_SUPPORTS_IMAGE", "false")
    client = _VisionCapableClient()
    assert main_model_supports_images(client, model_name="m-ovr2",
                                      base_url="b1") is False
    assert client.calls == [], "显式覆盖时不该再发探测请求"


def test_probe_result_is_cached():
    """同一 key 调两次 → 只探测一次（第二次命中缓存）。

    断言意图：探测是一次真实的模型调用（要发图、要等回答），
    每帧都探一次会把延迟和费用翻倍。
    """
    client = _VisionCapableClient()
    assert main_model_supports_images(client, model_name="m-cache",
                                      base_url="b1") is True
    assert main_model_supports_images(client, model_name="m-cache",
                                      base_url="b1") is True
    assert len(client.calls) == 1, "第二次应当命中缓存，不该再发探测请求"


def test_mark_image_unsupported_downgrades_to_false():
    """运行时降级：mark_image_unsupported() 之后一律按「不支持」处理。

    断言意图：用于「探测说支持、实际调用却报错」的情况（换了网关/模型名）。
    降级后不该**重新探测**（那会把同一个坏网关又打一遍）。
    """
    client = _VisionCapableClient()
    assert main_model_supports_images(client, model_name="m-degrade",
                                      base_url="b1") is True
    mark_image_unsupported(model_name="m-degrade", base_url="b1")
    assert main_model_supports_images(client, model_name="m-degrade",
                                      base_url="b1") is False
    assert len(client.calls) == 1, "降级后不该重新探测"


def test_probe_image_data_url_is_valid_png():
    """探测图必须是合法 PNG（否则「图片探测」根本不成立）。"""
    url = probe_image_data_url()
    assert url.startswith("data:image/png;base64,")
    raw = base64.b64decode(url.split(",", 1)[1])
    assert raw.startswith(b"\x89PNG"), "PNG 魔数不对"
    assert b"IHDR" in raw and b"IEND" in raw, "缺少 PNG 必需块"


def test_direct_to_main_switch(monkeypatch):
    """VISION_DIRECT_TO_MAIN 的 on/off 开关。"""
    monkeypatch.setattr(Config, "VISION_DIRECT_TO_MAIN", "off")
    assert direct_to_main_enabled() is False
    monkeypatch.setattr(Config, "VISION_DIRECT_TO_MAIN", "on")
    assert direct_to_main_enabled() is True
    monkeypatch.setattr(Config, "VISION_DIRECT_TO_MAIN", "auto")
    assert direct_to_main_enabled() is True


# ══════════════════════════════════════════════════════════════════
# 3) look_around 的两条路
# ══════════════════════════════════════════════════════════════════

def _make_tool(visual_tools_module, coord):
    tool = visual_tools_module.VisualPerceptionTool()
    tool._coordinator = coord
    tool._uid = 1
    return tool


def test_look_around_direct_mode_attaches_image_without_calling_vlm(
        visual_tools_module, coordinator):
    """直发模式：画面直接进上下文，**VLM 一次都不许被调用**。

    断言意图：
      * mode == "direct" 且顶层有 images —— harness 会把 images 里的
        data URL 转成 image_url 内容块；
      * observations[i]["description"] 为空 —— 没有文字转述，
        模型看到的是**原图**；
      * describe_image 一次都没被调用 —— 这是「直发」与「VLM 转述」
        的分水岭：直发的价值就是省掉一次调用、不让别人的转述失真。
    """
    tool = _make_tool(visual_tools_module, coordinator)
    client = _VisionCapableClient()
    tool._chat_client = client
    tool._models = _ExplodingModels()

    t = _spawn_frame_responder(coordinator, {"cam0": PNG_DATA_URL})
    result = tool.look_around(camera="", focus="桌上的卷子")
    t.join(timeout=3)

    assert result["success"] is True, result
    assert result["mode"] == "direct"
    assert result["images"] == [PNG_DATA_URL], "直发时必须把 data URL 交给 harness"
    obs = result["observations"][0]
    assert obs["logical_name"] == "cam0"
    assert obs["image_attached"] is True
    assert obs["description"] == "", "直发模式不该有文字转述"

    # 关键断言：VLM 根本没被调用
    assert tool._models.calls == [], "直发模式不应该调用 VLM"

    # 能力判定确实发生过：主模型收到过一张探测图
    assert len(client.calls) == 1
    assert count_image_parts(client.calls[0]) == 1


def test_look_around_falls_back_to_vlm_without_chat_client(
        visual_tools_module, coordinator):
    """没有主模型 client → 走 VLM 转述（老路）。

    断言意图：主模型 client 拿不到就无从判定，此时**只能**走 VLM 转述，
    并且结果里必须有文字描述（模型靠这段文字「看」画面）。
    """
    tool = _make_tool(visual_tools_module, coordinator)
    tool._chat_client = None
    stub = _StubLLM("一张数学卷子")
    tool._models = stub

    t = _spawn_frame_responder(coordinator, {"cam0": PNG_DATA_URL})
    result = tool.look_around(camera="", focus="桌上的卷子")
    t.join(timeout=3)

    assert result["success"] is True, result
    assert result["mode"] == "vlm"
    assert result["observations"][0]["description"] == "一张数学卷子"
    assert "images" not in result, "VLM 模式不该把原图交给主模型"
    assert len(stub.calls) == 1
    assert stub.calls[0][0] == PNG_DATA_URL


def test_look_around_falls_back_to_vlm_when_main_model_is_text_only(
        visual_tools_module, coordinator):
    """主模型是纯文本模型（探测判为不支持）→ 走 VLM 转述。

    断言意图：这是最关键的安全闸 —— 纯文本模型对着图片只会**幻觉**，
    把幻觉当画面写进上下文比拿不到画面糟糕得多。
    """
    tool = _make_tool(visual_tools_module, coordinator)
    client = _TextOnlyClient()
    tool._chat_client = client
    stub = _StubLLM("一张数学卷子")
    tool._models = stub

    t = _spawn_frame_responder(coordinator, {"cam0": PNG_DATA_URL})
    result = tool.look_around(camera="", focus="桌上的卷子")
    t.join(timeout=3)

    assert result["success"] is True, result
    assert result["mode"] == "vlm"
    assert result["observations"][0]["description"] == "一张数学卷子"
    assert "images" not in result
    # 判定确实发过一次探测（带图），并且没能答对
    assert len(client.calls) == 1
    assert count_image_parts(client.calls[0]) == 1
    assert len(stub.calls) == 1
