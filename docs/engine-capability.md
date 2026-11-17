# the conversation engine: capability and sdk assessment

Where the stateful conversation engine stands after the capability work, and
what the existing sdk (harness/sdk.py) can and cannot drive yet.

## what was added, layer by layer

The harness stays scenario-agnostic. Every addition below is a mechanism, not
an application; application tools remain in 应用仓（aicf-ui / aicf-dsn / aicf-study / aicf-code）.

| capability | where it lives | state |
|---|---|---|
| effort dial + per-wire reasoning params | `infra/orchestrator/base.py` (`resolve_effort`, `effort_stream_params`) | done |
| stream-creation retry with visible retry events | `infra/orchestrator/base.py` (`retrying_stream`) | done |
| finish events (stop / length / incomplete) on all three wires | `openai.py`, `anthropic.py` | done |
| proxy-aware http clients, SOCKS included | `infra/net.py`, `http_client` kwargs on both clients | done |
| prompt cache key passthrough (responses wire) | `openai.py` | done |
| token estimation, usage normalization, budget math | `harness/usage.py` | done |
| image references: `[image: path]` markers, files-api id cache, stores | `harness/images.py` | done |
| file snapshots, unified diffs, work-tree diff | `harness/filediff.py` | done |
| per-turn tool context (cwd, interrupt, live sink) | `harness/tools/context.py` | done |
| registry ownership tracking + snapshot-diff execution | `harness/tools/registry.py` (`ManagedToolRegistry`) | done |
| persistent shell sessions as a tool | `harness/tools/shell.py` (`ShellSessions`) | done |
| draft-commit history, stable prefix fingerprints, compaction | `harness/conversation.py` (`ManagedConversation`) | done |
| deterministic summary fallback when streamed compaction fails | `harness/conversation.py` (`structured_summary`) | done |
| session persistence: transcript items, atomic JSON, rewind, fork | `harness/transcript.py` | done |
| stateful engine: turn queue, status machine, 29 event kinds | `harness/agent/engine.py` (`ConversationEngine`) | done |
| side questions that never touch main history | `engine.py` (`_run_aside`) | done |
| auto compaction mid-turn + manual compaction mode | `engine.py` (`_run_compact`) | done |
| continuation on `length` with a bounded retry of the answer | `engine.py` (`max_continuations`) | done |
| partial commit of interrupted turns (tool results kept, repaired) | `engine.py` (`_commit_partial`) | done |
| 30s session checkpoints + `__last__` resume | `engine.py` + `transcript.py` | done |
| mailboxes, delegation, wait/interrupt for sub-agent teams | `harness/agent/collab.py` (`AgentManager`) | done |
| coding app tool suite (read/write/edit/bash/grep/...) | `aicf-code 仓的 aicf_code/core_tools.py` | done, app layer |

Test coverage lives beside each layer: `tests/test_orchestrator_gaps.py`,
`test_harness_utilities.py`, `test_tools_runtime.py`,
`test_conversation_state.py`, `test_transcript_store.py`,
`test_agent_engine.py`, `test_agent_collab.py`,
`test_coding_agent_tools.py`.

## conventions the engine commits to

- Tool failures are model-facing text: the result starts with `Error: ` and
  the model recovers. `ToolResult.success=False` from an exception is
  normalized to the same shape by `ManagedToolRegistry.execute`.
- Tool results are staged as plain `role=tool` text messages (normalized and
  truncated), not as a JSON envelope. Images travel as `[image: path]`
  markers collected into a `<tool_images>` user block.
- Sub-agent outcomes are `<subagent_update agent status>` blocks in the
  parent's mailbox; the parent stages its mailbox as one
  `<subagent_updates>` user message before the next model round.
- The engine is asyncio-native. Control-plane methods are loop-affine; a
  thread-bound UI either drains the EventSink from its own thread (events
  are queue-backed) or wraps the engine in a thin thread bridge.

## sdk reachability

What `create_agent` / `AgentSpec` / `AgentRuntime` can drive today:

- any `IChatClient` (injection point exists and is honored)
- tool registration, toolbox two-phase activation, memory, budget caps
- mcp servers via config, standard harness tools
- a stateless agent: `chat` / `run` / `chat_stream` with a flat `Conversation`

What the sdk cannot express yet:

1. No engine. `ConversationEngine` is the stateful stack (turn queue, aside,
   compaction modes, sessions, transcript, collab), but `sdk.py` exposes only
   the short-lived `AgentLoop` stack. `AgentRuntime` even rebuilds the loop
   per run, which is the opposite of stateful.
2. `AgentSpec` has no fields for `EngineConfig`, an `EventSink`, a session
   store, `allowed_tools`, an agent name, or a fork of history - the exact
   wiring an application does by hand today.
3. No effort dial. `effort_stream_params` is engine-level knowledge; a bare
   `create_agent` cannot say "high effort on the responses wire".
4. No prompt cache key. The stable-prefix fingerprint lives in
   `ManagedConversation`; the sdk never computes or sends one.
5. Event vocabulary mismatch. `StreamEvent` (the loop's output) has 9 kinds;
   the engine emits the 29-kind vocabulary a session UI needs. Consumers of
   `sdk.py` cannot observe compaction, aside, queueing or tool output.
6. No collaboration. `AgentManager` is usable directly but invisible to the
   sdk surface.

## minimal sdk extension

Smallest change that closes the gap without disturbing the stateless path:

- `AgentSpec` grows optional fields: `engine_config`, `event_sink`,
  `session_store`, `allowed_tools`, `agent_name`, `effort`.
- `sdk.py` gains `create_engine(...)` beside `create_agent(...)`: same
  argument shape, returns a started `ConversationEngine` wired to the
  assembled registry, mcp manager and system prompt builder. `chat_stream`
  style consumers keep working; stateful consumers get the full event
  vocabulary and sessions.
- `AgentRuntime` stays as-is, documented for stateless one-shot use.

Nothing else in the sdk needs to move: clients, tools, mcp and budget are
already injection points the engine reuses directly.

## how an application wires it today

```python
import asyncio

from harness.agent import ConversationEngine, EngineConfig, ManagedToolRegistry
from harness.transcript import SessionStore
from infra.orchestrator.openai import OpenAICompatClient


async def main():
    client = OpenAICompatClient(api_key="...", base_url="...", model="...")
    registry = ManagedToolRegistry()
    engine = ConversationEngine(
        client=client, registry=registry,
        store=SessionStore("sessions"),
        system_provider=lambda: "you are a helpful agent",
        cwd=".", model=my_model_info, config=EngineConfig())
    engine.start()
    engine.submit("inspect the repo and summarize")
    async for kind, payload in poll(engine):     # application's frame loop
        render(kind, payload)
    await engine.shutdown()
```

The tool suite an application installs is its own choice; the engine only
needs a `ManagedToolRegistry`.
