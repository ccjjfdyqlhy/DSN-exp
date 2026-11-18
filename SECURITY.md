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

- the `aicf-core` distribution itself: the `harness` and `infra` packages
  (agent engine, tool execution, session storage, model clients)
- the published pypi artifacts

out of scope:

- vulnerabilities in dependencies (report upstream, but you may still
  open a private report if a dependency is mishandled here)
- the adcode client repository (separate project)
- anything requiring a compromised local machine or shell access to the
  operator's account

## posture notes

- provider api keys are stored encrypted (`~/.adcode/config.json`,
  keyring-backed) and are never logged or sent anywhere except the
  configured provider endpoint
- session databases and image stores live under the user data directory
  and are never committed; `local/` is machine-local by policy
- tools run with the operator's privileges by design: there is no
  sandbox. do not point the agent at untrusted workloads without
  understanding that `bash`, `write` and `edit` act on real files
