# tests/test_dsn_ui_multimodal_passthrough.py
# 回归测试：通过 dsn_ui 上传的图片必须一路保留到发往推理引擎的 payload。
#
# 现场问题：用户给 bonsai:bonsai2:27B（带 mmproj 视觉投影器）上传图片，
# 模型回复"没有提供图片"。链路逐层排查：
#   1. 前端 chat.service.ts 正确构造了 image_url content part；
#   2. /v1/chat/completions 也保留了数组结构；
#   3. apps/dsn_ui/agent.py 只取 content 里的 text 字段 → 图像被丢；
#   4. topic_manager.assemble_context_messages 把整轮上下文拍平成纯文本，
#      最后 assembled.append(ChatMessage.user(new_user_message)) 只带文本。
# 于是图像在进入 AgentLoop 之前就没了。

from __future__ import annotations

from apps.dsn_ui.agent import extract_last_user_turn
from apps.dsn_ui.integration_api import openai_content_to_parts
from apps.dsn_ui.topic_manager import DSNUITopicContextManager
from infra.orchestrator.base import count_image_parts
from infra.orchestrator.local_chat import OpenAICompatChat

IMG = "data:image/png;base64," + "A" * 512


def _inbound() -> list[dict]:
    """模拟前端实际发出的请求体（图片 + 文字）。"""
    return [
        {"role": "system", "content": "你是助手"},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": IMG}},
                {"type": "text", "text": "这张图里有什么？"},
            ],
        },
    ]


def test_extract_last_user_turn_keeps_image_parts():
    """agent 层的抽取必须保留 image_url，而不是只取 text。"""
    text, parts = extract_last_user_turn(_inbound())

    assert text == "这张图里有什么？"
    assert parts is not None
    assert count_image_parts([{"content": parts}]) == 1


def test_extract_last_user_turn_plain_text():
    """纯文本消息不应被强行包成 parts。"""
    text, parts = extract_last_user_turn([{"role": "user", "content": "你好"}])

    assert text == "你好"
    assert parts is None


def test_topic_assembly_preserves_image():
    """上下文装配必须把 image_url 带到最终那条 user 消息上。"""
    mgr = DSNUITopicContextManager()
    _, parts = extract_last_user_turn(_inbound())

    msgs = mgr.assemble_context_messages(
        new_user_message="这张图里有什么？",
        system_prefix="你是助手",
        new_user_parts=parts,
    )

    assert count_image_parts(msgs) == 1, (
        "图像在上下文装配层丢失；"
        f"实际形状={[type(m.content).__name__ for m in msgs]}"
    )
    # 最后一条必须是 user 且携带 parts
    assert msgs[-1].role == "user"
    assert isinstance(msgs[-1].content, list)


def test_topic_assembly_without_parts_is_text_only():
    """不传 parts 时保持旧行为（纯文本），确保向后兼容。"""
    mgr = DSNUITopicContextManager()

    msgs = mgr.assemble_context_messages(
        new_user_message="你好", system_prefix="你是助手"
    )

    assert count_image_parts(msgs) == 0
    assert isinstance(msgs[-1].content, str)


def test_image_reaches_outgoing_payload():
    """端到端：入站请求 → 抽取 → 上下文装配 → 发往引擎的 payload。"""
    # 1) 服务端入口的归一化
    raw = _inbound()
    for m in raw:
        if isinstance(m.get("content"), list):
            m["content"] = openai_content_to_parts(m["content"])

    # 2) agent 抽取
    text, parts = extract_last_user_turn(raw)
    assert parts is not None

    # 3) 上下文装配
    mgr = DSNUITopicContextManager()
    context_msgs = mgr.assemble_context_messages(
        new_user_message=text, system_prefix="你是助手", new_user_parts=parts
    )

    # 4) 最后一站：发往引擎的 payload
    client = OpenAICompatChat(base_url="http://127.0.0.1:9", model_name="bonsai:bonsai2:27B")
    payload = client._build_payload(
        context_msgs, None, temperature=None, max_tokens=None, stream=True
    )

    assert count_image_parts(payload["messages"]) == 1, (
        "图像没有到达上行 payload，模型自然看不到图片"
    )
    user_msgs = [m for m in payload["messages"] if m["role"] == "user"]
    assert len(user_msgs) == 1
    assert any(p.get("type") == "image_url" for p in user_msgs[0]["content"])


def test_text_only_request_is_not_wrapped_in_parts():
    """纯文本请求的 payload 保持字符串 content（不引入回归）。"""
    client = OpenAICompatChat(base_url="http://127.0.0.1:9", model_name="m")
    payload = client._build_payload(
        [{"role": "user", "content": "你好"}], None,
        temperature=None, max_tokens=None, stream=True,
    )

    assert isinstance(payload["messages"][0]["content"], str)
