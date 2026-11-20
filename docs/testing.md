# testing guide

for people running tests, adding tests, or deciding whether a failure belongs to
their change.

## running tests

### prerequisites

`pytest` is not a runtime dependency. install it separately:

```bash
pip install pytest pytest-asyncio
```

### commands

the repository configures pytest in `pyproject.toml`:

```bash
python -m pytest                # full suite, known_broken excluded
python -m pytest -q             # quiet
python -m pytest tests/test_harness_*.py -q
python -m pytest -m known_broken
python -m pytest -x             # stop at the first failure
python -m pytest --collect-only -q
```

`tests/conftest.py` provides the `stub_client` fixture and global singleton
resets. do not use `os.chdir` to isolate directories.

## baseline

on 2026-11-18, python 3.12, the tracked suite reports:

```text
1117 passed, 16 skipped
```

the skips break down as 13 from the mutation-testing layer
(`tests/fault/mutation/`, off by default, turn it on with
`RUN_MUTATION=1 pytest -q tests/fault/mutation/`) plus three single cases: one
needs `python-vlc`, one needs `funasr`, and one is skipped because `socksio` *is*
installed (it asserts the failure path of a missing SOCKS transport).

a local-only file, `tests/test_dsn_existence_loop.py` (38 cases), joins the run
when `apps/` exists. it is listed in `.git/local-only-policy.txt` and never
leaves this machine, so it is not part of the baseline.

CI runs the tracked suite on python 3.10 through 3.13. the `test` job collects
`tests/fault/` as well (about 2s), and a separate nightly `fault` job re-runs
that layer as its own gate.

the config does three things:

| setting | effect |
|---|---|
| `testpaths = ["tests"]` | a bare `pytest` never scans `temp/`, where old scripts call external apis at import |
| `addopts = "--continue-on-collection-errors"` | one broken import does not stop the whole run |
| `-m 'not known_broken'` | asset-drift cases stay out of the default run |

the `known_broken` marker is still registered, but no test currently uses it.

## tests that need external conditions

these files exited pytest collection or skip themselves because they are manual
scripts or need hardware:

| file | why it cannot run in ci |
|---|---|
| `scripts_littleskin_login.py` | browser oauth callback and `input()` |
| `scripts_printer.py` | `python-cups` and a configured printer |
| `test_funasr.py` | downloads a model and needs a microphone |
| `test_vlc.py` | needs `python-vlc`; skips when it is missing |
| `test_lmstudio.py` | needs a server on `localhost:4501` |

camera tests use a fake `cv2` object and do run.

## test layout

### `aicf/harness/`

| file | coverage |
|---|---|
| `test_harness_agent.py` | `AgentLoop` basics |
| `test_harness_agent_runtime.py` | `AgentRuntime` facade |
| `test_harness_sdk.py`, `test_sdk_dx.py` | `create_agent`, `@tool`, sdk ergonomics |
| `test_harness_tools.py`, `test_harness_standard_tools.py` | tool registry and standard tools |
| `test_harness_toolbox.py` | two-phase toolbox activation |
| `test_harness_context_assembly.py` | segmented budget trimming |
| `test_harness_stream.py` | streaming events |
| `test_harness_v2_innovations.py` | declarative assembly |
| `test_agent_engine.py` | stateful `ConversationEngine` |
| `test_agent_collab.py`, `test_collab_types.py` | sub-agent mailboxes and delegation |
| `test_harness_personality_migration.py` | personality data migration |
| `test_harness_learning.py`, `test_harness_selfplay.py`, `test_harness_probes.py` | learning loop |
| `test_harness_utilities.py` | filediff, images, usage and transcript helpers |

### `aicf/infra/`

| file | coverage |
|---|---|
| `test_orchestrator.py`, `test_harness_infra.py` | orchestration contracts |
| `test_harness_scheduler.py`, `test_orchestrator_gaps.py` | slots and scheduling |
| `test_harness_llamacpp.py`, `test_lmstudio.py` | local backends |
| `test_infra_openai_client.py`, `test_wire_message_translation.py` | openai and anthropic wires |
| `test_harness_policy.py`, `test_harness_retry.py` | policy and retries |
| `test_harness_runtime.py`, `test_harness_settings.py` | dependency injection and settings |
| `test_local_engine_cancel.py`, `test_orchestrator_load_cancel.py` | cancellation races |
| `test_infra_finetune.py` | finetune contracts and device gate |
| `test_killpg_guard.py` | process-group kill guards |

### application tests

application tests live with the application. this repository has no tests that
import `aicf_ui`.

## adding tests

- name framework tests `test_harness_<module>.py` or `test_<module>.py`
- use `StubChatClient` and `StreamingClient` instead of real providers
- mark network or device tests with `@pytest.mark.integration`
- use `Runtime.activate(rt)` to isolate global singletons:

```python
rt = Runtime(name="test")
with Runtime.activate(rt):
    ...
```

- run the suite before and after your change; a regression is a lower pass count
- fix a bug with a regression test in the same commit

## infrastructure

| item | status |
|---|---|
| `tests/conftest.py` | present: stub client, singleton reset, data directory isolation |
| pytest config in `pyproject.toml` | present |
| markers | `slow`, `integration`, `known_broken`, `script_not_test` |
| CI | `.github/workflows/ci.yml` runs the suite on python 3.10-3.13 |
| release smoke tests | `.github/workflows/release.yml` runs tests before publishing |
| assertion style | a few old tests still return a value; pytest warns about them |

### data isolation

`conftest.py` points `DSN_UI_DATA_DIR` at a temporary directory and removes it
afterwards, so tests do not write a real database. `MagicMock/` output is gone:
the cache only accepts `str` or `os.PathLike` as its data directory.

`conftest.py` does not change the working directory. several tests use relative
paths, and changing cwd turns those into `FileNotFoundError`.

## remaining work

1. rewrite the few tests that return `True` or `False` instead of asserting;
2. keep the python 3.10-3.13 matrix green when adding a version-specific
   dependency.
