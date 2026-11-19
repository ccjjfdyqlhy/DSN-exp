# split migration: monorepo to library plus web console

effective 2026-11-18. this document answers two questions: where did the old
paths go, and how should existing code change.

## why the split

the old `DSN-exp` repository held both the library and every product. that
caused four problems:

- library code hardcoded application paths such as a character card directory;
- a single commit could touch tens of thousands of lines, so review stopped;
- the published package could not state what it contained;
- shared changes had to be copied across products.

the split leaves one library and one web console. dependencies point one way:
the console depends on the library, and the library depends on nothing above it.

## repositories

| repository | contents | install | internal dependency |
|---|---|---|---|
| [`aicf-core`](https://github.com/ccjjfdyqlhy/aicf-core) | `harness/` and `infra/` | `pip install aicf-core` | none |
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | web console | `pip install -e .` | aicf-core |

`aicf-core` 1.0.0rc0 is the current release. while a version is unpublished, install
from git:

```bash
pip install "aicf-core @ git+https://github.com/ccjjfdyqlhy/aicf-core.git"
```

## old paths to new paths

### python module paths

| old | new | repository |
|---|---|---|
| `apps.dsn_ui.*` | `aicf_ui.*` | aicf-ui |
| `harness.*` / `infra.*` | unchanged | aicf-core |

### root-level glue

`main.py`, `launcher.py`, `installer.py`, `onboarding.py` and `apps.yaml`
belonged to the application suite launcher. they moved with `aicf-ui`.
the launcher probes entry modules: installed products appear, missing products
show as unavailable instead of crashing.

## configuration and path changes

after the split there is no repository root to anchor writable data. data goes
to the user home directory or to a path from the environment:

| old | new | note |
|---|---|---|
| `<repo>/apps/dsn_ui/data/` | `~/.aicf/ui/data/` or `DSN_UI_DATA_DIR` | console data |
| `<repo>/.env` | `AICF_ENV_FILE`, then `./.env`, then `~/.aicf/ui/.env` | searched in order |

`harness/personality` used to hardcode an application card directory. it now
looks in `AICF_CHARACTER_CARDS_DIR`, then next to the package, then at the
repository root.

## how to change existing code

### using the product

```bash
git clone https://github.com/ccjjfdyqlhy/aicf-ui.git && cd aicf-ui
pip install -e .
python -m aicf_ui.server --port 8888
```

### using the sdk

```python
from harness import Agent
```

the import is unchanged. only the install source changed.

the public `harness` and `infra` api is frozen at 0.6. breaking changes get a
minor version bump.

### changing application code

1. work in the `aicf-ui` repository;
2. rewrite imports using the module table above;
3. replace path assumptions with package-relative paths or environment variables;
4. declare `aicf-core>=0.6,<0.7`.

## old repository status

`DSN-exp` was renamed to `aicf-core`. github redirects the old links.
the old `main` and `harness-refactor` branches were collapsed into a linear
history, and feature work now goes through pull requests.
