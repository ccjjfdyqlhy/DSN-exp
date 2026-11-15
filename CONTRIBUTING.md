# contributing

thanks for looking at the project. this document covers setup, the rules
that keep the repository coherent, and how to land a change.

## what lives where

- `harness/` - the scenario-agnostic agent core: turn engine, tool
  abstractions, conversation state, sessions, collaboration. this is the
  part published to pypi as `aicf`
- `infra/` - the layer under the core: model clients (openai compatible,
  responses, anthropic), storage, settings, networking
- `apps/` - scenario layers built on the core (they are **not** part of
  the pypi package)
- `tests/` - the pytest suite
- `bench/` - (adcode repo only; not this one)

the layering rule that matters: `harness` never imports an application.
if your change needs an app concept inside `harness`, it belongs in the
app or needs to be designed as a generic mechanism first.

## setup

python >= 3.10. `uv` is the recommended tool, plain pip works too.

```bash
uv venv
uv pip install -e ".[full,mcp,anthropic,socks]"
uv pip install pytest
python -m pytest -q
```

the full suite runs offline: model calls in tests hit scripted stubs or
the local gateway, never a real provider.

## the local-only policy

some paths are machine-local and must never be committed. they are
gitignored and hook-enforced (`.git/local-only-policy.txt`):

- `apps/dsn_existence/**`
- `tests/test_dsn_existence*`
- `local/**`

if `git status` shows them, leave them alone. do not remove the ignore
entries, and do not `git add -f` past the pre-commit hook.

## branch and commit conventions

- the default branch is `harness-refactor`; feature branches cut from it
  and PR against it
- commit messages are exactly one line: `type(scope): description` -
  imperative, lowercase, no trailing period (`feat(engine): ...`,
  `fix(infra): ...`). if it needs a paragraph, that is the PR
  description's job
- one commit is one coherent change; mixed refactor + feature commits
  get split
- commits are not gpg-signed in this repository

## code conventions

- plain english for comments, docstrings, log messages and commit
  messages; no mixed-language sentences
- comments explain why and business rules, not the next token; target
  sparse (under ~10% of lines)
- 4-space indent, `snake_case` functions, `PascalCase` classes,
  `UPPER_SNAKE_CASE` constants
- type hints on public functions; one-line docstrings plus `Args: /
  Returns:` when the signature is not self-evident
- f-strings, not `%` or `.format()`
- no bare `except:`; catch the narrowest exception that can be handled;
  let errors propagate when there is nothing to do
- no secrets in the diff, ever. provider keys live in the encrypted
  local config, never in code or tests

## layering rules for the engine

changes under `harness/` are the sensitive ones:

- `harness` imports `infra` and itself, never `apps.*`
- new capabilities are mechanisms, not application features: if a name
  only makes sense for one scenario (coding, study, chat), it belongs in
  that app, not the core
- every added parameter must keep the old behavior when omitted; the
  apps in this repository are the regression net
- public surface additions land in the package `__init__` exports and
  need tests beside them (`tests/`)

## testing

- run `python -m pytest -q` before pushing; the suite must stay green
  (the single known-broken pdf test is excluded by marker)
- engine behavior gets scripted-stub tests (`StubChatClient`,
  `StreamingClient` in `tests/`); network-dependent tests are marked
  `integration` and skipped by default
- if your change fixes a bug, add the regression test in the same commit

## pull requests

- PR against `harness-refactor`, one coherent change per PR
- the description covers what / why / how to test, in that order; test
  steps are exact commands a reviewer can paste
- CI and the maintainer review; keep the diff reviewable - a 3k-line
  drive-by will sit unread

## releases

maintainer-only. `uv build`, verify the wheel contains only `harness`
and `infra`, then publish (twine with an api token, or the tag-driven
trusted publishing flow). bump the version in `pyproject.toml` in the
release commit.
