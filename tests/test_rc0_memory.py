# tests/test_rc0_memory.py
# enable_memory has to do something.
#
# The flag created a store, registered it in the runtime and stopped there:
# nothing was written to it and nothing read from it, so the flag was a
# no-op that looked like a feature.

from __future__ import annotations

import json

from aicf.harness import create_agent
from aicf.harness.memory.in_memory import InMemoryStore, keywords
from aicf.infra.models.base import ChatResponse
from aicf.infra.models.stub import StubChatClient


def _agent(responses):
    stub = StubChatClient(responses=responses)
    agent = create_agent(client=stub, enable_memory=True)
    return agent, stub


def test_memory_stores_the_turn():
    agent, _stub = _agent([ChatResponse(content="the codeword is banana"),
                           ChatResponse(content="banana")])

    agent.chat("remember the codeword banana")

    store = agent._memory_store()
    assert store is not None
    assert store.count() == 2


def test_memory_recalls_the_previous_turn():
    agent, stub = _agent([ChatResponse(content="the codeword is banana"),
                          ChatResponse(content="banana")])

    agent.chat("remember the codeword banana")
    agent.chat("what is the codeword")

    messages = stub.calls[1]["messages"]
    assert any("Relevant memory" in str(m.get("content", ""))
               for m in messages), "the second turn got no memory block"
    assert "banana" in json.dumps(messages, ensure_ascii=False)


def test_memory_block_does_not_join_the_conversation():
    """The recall block belongs to the request, not to the history.

    Otherwise every turn would carry the previous recalls forever.
    """
    agent, _stub = _agent([ChatResponse(content="one"),
                           ChatResponse(content="two")])

    agent.chat("first question")
    agent.chat("second question")

    stored = agent.conversation.messages
    assert not any("Relevant memory" in str(getattr(m, "content", ""))
                   for m in stored)


def test_memory_off_keeps_no_store():
    stub = StubChatClient(responses=[ChatResponse(content="hi")])
    agent = create_agent(client=stub)

    assert agent._memory_store() is None


def test_keyword_search_matches_a_question_about_an_old_fact():
    store = InMemoryStore()
    store.add_text("记住密码是香蕉", role="user")

    hits = store.search("密码是什么")

    assert [hit.text for hit in hits] == ["记住密码是香蕉"]


def test_keywords_splits_cjk_runs():
    assert "密码" in keywords("密码是什么")
    assert "banana" in keywords("what is the Banana")


def test_keyword_search_ranks_the_better_match_first():
    store = InMemoryStore()
    store.add_text("the weather is fine", role="user")
    store.add_text("the codeword is banana", role="user")

    hits = store.search("what is the codeword")

    assert hits[0].text == "the codeword is banana"
