# the application layer

the core repository ships no application code.
the web console lives in its own repository and depends on `aicf-core`.

## repositories

the only product is [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui), a web
console for models, chat, resources and system-1 decisions. run it with
`python -m aicf_ui.server`; the default port is `8888`.

`aicf-ui` is the only application this documentation covers.
it installs `aicf-core` and nothing else from this project.

## why the split

| before | after |
|---|---|
| one repository held the library and every product | the library and the console ship separately |
| library code hardcoded application paths | core knows no application; the console uses its own paths and environment variables |
| the published package contents were unclear | `aicf-core` installs `harness` and `infra` only |
| shared changes were copied across products | shared mechanisms live in core, product semantics stay in the console |

## how the console is assembled

the console uses the standard web shape:

- `Runtime` and `Settings` for dependency injection
- `ModelProviderRegistry` for model clients
- `AgentRuntime` for the conversation loop
- an HTTP layer on top of `harness` and `infra`

it predates the framework facade in places, so it also carries its own routing
and context code. treat it as a working product, not as a minimal template.

## starting a new application

create a separate repository that depends on `aicf-core`:

```bash
mkdir my-app && cd my-app
git init
```

declare the dependency in `pyproject.toml`:

```toml
dependencies = ["aicf-core>=0.6,<0.7"]
```

then follow [app-development.md](app-development.md) for the assembly options.

## cross-application calls

not supported. the core has no knowledge of applications, and `aicf-ui` does not
import another product repository.

## migration details

see [split_migration.md](split_migration.md) for the old paths and the new
environment variables.
