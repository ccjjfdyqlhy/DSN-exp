# documentation index

these documents are for maintainers. the goal is to build a correct mental model
of the library in half a day.

## reading paths

### first day

```text
README.md                -> what the library is in 30 seconds
docs/architecture.md     -> module map and dependency rules
docs/getting-started.md  -> install and run it
docs/apps.md             -> the web console repository
```

### before changing code

```text
docs/maintenance.md      -> invariants and a checklist by change location
docs/technical-debt.md   -> what is already broken, so you do not own it
docs/testing.md          -> how to run tests and read a failure
```

### deeper into one layer

```text
docs/infra.md            -> model orchestration, resources, policy
docs/harness.md          -> agent loop, tools, context, pipeline
docs/skills.md           -> skill plugins, dependency injection, validation
docs/configuration.md    -> where configuration comes from
docs/sdk_guide.md        -> embed the framework in another project
docs/app-development.md  -> write a new application
```

## document list

| document | contents | read it when |
|---|---|---|
| [architecture.md](architecture.md) | layers, dependency direction, module map, request path, global singletons, quality baseline | always first |
| [harness.md](harness.md) | agent loop control flow and events, `AgentSpec`, tools, context trimming, hooks, learning subsystem | changing agent behavior |
| [skills.md](skills.md) | skill directory layout, `skill.yaml`, capability injection, load-time validation, `skill.env`, runtime api | writing a skill |
| [infra.md](infra.md) | orchestrator layers, scheduler, providers, resource pool, policy, store, finetune subsystem, device gate | changing models, resources or storage |
| [apps.md](apps.md) | the `aicf-ui` repository and how it relates to core | finding product code |
| [app-development.md](app-development.md) | assembly options, minimum application, tools, skills, web application | adding a feature or starting an application |
| [getting-started.md](getting-started.md) | environment, dependencies, configuration, startup, ports, troubleshooting | first run |
| [configuration.md](configuration.md) | configuration sources, key variables, precedence, credentials | changing configuration |
| [testing.md](testing.md) | how to run tests, the current baseline, tests that need external services | running or judging tests |
| [maintenance.md](maintenance.md) | placement rules, invariants, checklists, repository hygiene | before touching code |
| [technical-debt.md](technical-debt.md) | known debt by priority, verified bugs, fix order | planning work |
| [sdk_guide.md](sdk_guide.md) | using aicf as a python sdk | embedding the framework |
| [split_migration.md](split_migration.md) | old paths to new paths, configuration changes | migrating from the monorepo |

## conventions

### only verified facts

every statement here was checked against the source or a real run.
when something is uncertain, the document says so instead of presenting a guess.

old documentation claimed several things that turned out to be false:

| old claim | reality |
|---|---|
| `AgentLoop` passes through 5 hook points | it has 8 hook points, and `AgentLoop` does not go through the pipeline at all |
| there are 16 or 17 standard tools | there are 18 |
| the token economy loop is closed | it is assembled but not connected |
| `SpeculativePrefetch` is on the main path | no caller exists |
| `batch.run` is a placeholder | it is implemented |

### cite `file:line`

when a document needs a location, it gives `file:line`. the code comments carry
the history; the documents carry the current structure.

### separate design from reality

for every capability, the document states whether it is connected, optional,
written but not connected, or declared but inactive. this keeps the next
maintainer from trusting a name.

### docs ship with the repository

`docs/` is tracked. commit documentation changes with the code they describe.
