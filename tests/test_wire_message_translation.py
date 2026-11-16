# tests/test_wire_message_translation.py
# The Responses and Anthropic wires must understand chat-shaped dicts the
# same way they understand ChatMessage objects: a tool round travels as
# function_call / function_call_output items, and a turn that carries only
# reasoning keeps it as its text instead of vanishing.

from __future__ import annotations

from infra.models.base import ChatMessage
from infra.orchestrator.anthropic import AnthropicCompatClient
from infra.orchestrator.openai import OpenAICompatClient


# ── responses wire ──────────────────────────────────────────
def test_a_dict_tool_result_becomes_a_function_call_output():
    items = OpenAICompatClient._dict_to_responses_items({
        'role': 'tool', 'tool_call_id': 'call_1', 'content': 'the file is read'})
    assert items == [{'type': 'function_call_output', 'call_id': 'call_1',
                      'output': 'the file is read'}]


def test_a_dict_assistant_tool_call_becomes_a_function_call_item():
    items = OpenAICompatClient._dict_to_responses_items({
        'role': 'assistant', 'content': None,
        'tool_calls': [{'id': 'call_9', 'type': 'function',
                        'function': {'name': 'file__read',
                                     'arguments': '{"path": "a.py"}'}}]})
    # a turn that produced only tool calls carries no empty output_text block
    assert items == [{'type': 'function_call', 'call_id': 'call_9',
                      'name': 'file__read', 'arguments': '{"path": "a.py"}'}]


def test_a_dict_turn_with_only_reasoning_carries_it_as_text():
    items = OpenAICompatClient._dict_to_responses_items({
        'role': 'assistant', 'content': None,
        'reasoning_content': 'the plan is to move the caret'})
    assert items == [{'role': 'assistant',
                      'content': [{'type': 'output_text',
                                   'text': 'the plan is to move the caret'}]}]


def test_a_chatmessage_turn_with_only_reasoning_carries_it_as_text():
    message = ChatMessage(role='assistant', content='',
                          reasoning_content='the plan is to move the caret')
    items = OpenAICompatClient._messages_to_responses_input([message])
    assert items == [{'role': 'assistant',
                      'content': [{'type': 'output_text',
                                   'text': 'the plan is to move the caret'}]}]


def test_an_assistant_turn_with_text_keeps_its_text():
    items = OpenAICompatClient._dict_to_responses_items({
        'role': 'assistant', 'content': 'the answer',
        'reasoning_content': 'the plan'})
    assert items[0]['content'] == [{'type': 'output_text',
                                    'text': 'the answer'}]


# ── anthropic wire ──────────────────────────────────────────
def test_an_anthropic_turn_with_only_reasoning_keeps_it():
    _, messages = AnthropicCompatClient._split_system([
        {'role': 'user', 'content': 'go'},
        {'role': 'assistant', 'content': None,
         'reasoning_content': 'the plan is to move the caret'},
    ])
    assistant = [m for m in messages if m['role'] == 'assistant']
    assert assistant and assistant[0]['content'] == 'the plan is to move the caret'


def test_an_anthropic_tool_call_keeps_the_reasoning_next_to_it():
    _, messages = AnthropicCompatClient._split_system([
        {'role': 'assistant', 'content': None,
         'reasoning_content': 'the plan is to read the file first',
         'tool_calls': [{'id': 'call_1', 'type': 'function',
                         'function': {'name': 'file__read',
                                      'arguments': '{"path": "a.py"}'}}]},
    ])
    assert len(messages) == 1
    blocks = messages[0]['content']
    assert blocks[0] == {'type': 'text',
                         'text': 'the plan is to read the file first'}
    assert blocks[1]['type'] == 'tool_use'


def test_an_anthropic_turn_with_text_is_unchanged():
    _, messages = AnthropicCompatClient._split_system([
        {'role': 'assistant', 'content': 'the answer',
         'reasoning_content': 'the plan'},
    ])
    assert messages[0]['content'] == 'the answer'
