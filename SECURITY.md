# security policy

## supported versions

only the default branch (`main`) receives security fixes.
released `aicf-core` packages on pypi are supported for one minor version back.

| branch / version | supported |
|---|---|
| `main` (default) | yes |
| pypi `aicf-core` latest | yes |
| pypi `aicf-core` older minors | no |
| other branches | no |

## reporting a vulnerability

do **not** open a public issue for anything you believe is exploitable.

use github's private vulnerability reporting: repository page ->
Security -> Report a vulnerability. if that is unavailable, email
`ccjjfdyqlhy@outlook.com` with `[security]` in the subject.

please include:

- the affected package/branch and commit (or pypi version)
- a minimal reproduction (script, request, or sequence)
- the impact you believe it has
- any mitigation you have already found

you will get an acknowledgment within a few days, a fix timeline once the
issue is confirmed, and credit in the fixing commit or advisory unless you
prefer to stay anonymous.

## scope

in scope:

- the `aicf-core` distribution itself: the `aicf.harness` and `aicf.infra`
  packages (agent engine, tool execution, session storage, model clients)
- the published pypi artifacts

out of scope:

- vulnerabilities in dependencies (report upstream, but you may still
  open a private report if a dependency is mishandled here)
- the `aicf-ui` web console repository (separate project)
- anything requiring a compromised local machine or shell access to the
  operator's account

## posture notes

what this package does protect:

- every tool call goes through the deny-by-default policy gate, and a tool
  that declares no contract is treated as the strictest one
- effectful and destructive tools need a human approval; an approval
  timeout counts as a denial, not a pass
- a tool that starts a process is checked before it starts: the path scope
  the tool declared (`readonly` keeps the working directory read-only,
  `workspace` makes it writable), the network target, and `ulimit`s; the
  child gets an environment whitelist instead of `os.environ`
- every call leaves a record in the undeletable audit store - it is on by
  default and can only be dropped explicitly (`security_audit=False`, which
  keeps the trace face alone)

what it does not protect:

- **tools run with the operator's privileges by design: there is no
  OS-level sandbox** - no container, no micro vm, no dropped privileges.
  the shipped backend tier is `restricted` (subprocess + ulimits + a
  pre-flight path check); it reports `degraded` because it checks, it does
  not contain. the `isolated` tier (container / micro vm) is not built yet
- the path check is lexical - it reads the command line before the process
  starts, it does not confine the process afterwards
- do not point the agent at untrusted workloads without understanding that
  `proc.run`, `file.write` and `file.edit` act on real files
- provider api keys are not stored by this package: there is no key store
  and no encrypted config file. the key comes from the environment
  (`OPENAI_API_KEY`) or from the caller (`create_agent(api_key=...)`), and
  anything written to a trace, an event or the audit log goes through the
  single redaction gate first
- session databases and image stores live under the user data directory
  (`$AICF_HOME`, else `~/.aicf`) and are never committed; `local/` is
  machine-local by policy
