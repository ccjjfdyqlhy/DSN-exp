# harness/tools/sandbox/paths.py
# 路径边界判定：先 resolve 再判前缀（策划案 §4.4.6「文件」行）。
#
# 为什么单独一个模块：路径判定是沙箱里**唯一**能防「../ 穿越」与
# 「符号链接逃逸」的逻辑，restricted / namespaced 两个后端都要用。
# 放在一处是为了避免两个后端各写一份、各漏一种绕过方式。
#
# 判定顺序（顺序本身就是安全语义，不能换）：
#   1. 词法归一（normpath）：把 `a/../../b` 这种**穿越**先折叠掉。
#   2. 真实解析（realpath）：把符号链接**展开**成它真正指向的位置。
#   3. 前缀判定：解析结果必须落在允许根目录之内。
#
# 为什么必须先 realpath 再判前缀：
#   工作区里放一个 `link -> /etc/passwd` 的软链，命令写 `cat link`。
#   词法路径是 `<workspace>/link`（在允许根内），真实路径是 `/etc/passwd`
#   （在允许根外）。只做词法判定 → 放行 → 逃逸成功。
#   这就是「符号链接逃逸」，必须靠 realpath 兜住。
#
# 设计取舍（注释即缺陷数据库）：
#   - 判定是**词法级**的：命令可以写成 `cat $(printf '/etc/passwd')` 绕过
#     静态扫描。restricted 档本来就没有 mount namespace，只能做到这一步；
#     真正的隔离在 namespaced.py（bubblewrap 把 /etc 根本不 bind 进去）。
#   - 因此 restricted 档的 degraded 永远是 True —— 它是「检查」不是「隔离」。

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

#: 默认允许**读**的系统目录。
#:
#: 为什么只放这一小撮：命令要能执行就得能读解释器和动态库；但 /etc、/home、
#: /root、/var 这些地方装着凭据与别的租户的数据，默认不放行。
#: 「未声明 = 不允许」—— 跟策略层「默认拒绝」是同一条原则。
#:
#: 修复说明（lead review）：/opt 已从默认里去掉。
#: /opt 不属于「跑命令必需」这一类（绝大多数 /opt 下的二进制依赖库在
#: /usr/lib），而 /opt 经常放第三方软件**和业务数据** —— 默认放行等于
#: 默认把业务数据敞开。需要的人显式传 `system_read_paths=('/opt',)`。
DEFAULT_SYSTEM_READ_PATHS: tuple[str, ...] = (
    '/usr', '/bin', '/sbin', '/lib', '/lib32', '/lib64',
)

#: 违规类型
#:
#: traversal       `../` 穿越出了允许根
#: symlink_escape  软链指向允许根之外
#: outside_root    直接引用了允许根之外的路径（绝对路径等）
#: write_denied    往只读区域写
#: cwd_denied      工作目录本身在允许根之外
ViolationKind = str


@dataclass(frozen=True)
class PathViolation:
    """一次路径违规。"""

    kind: ViolationKind
    path: str
    detail: str = ''

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return f'{self.kind}:{self.path}' + (f' ({self.detail})' if self.detail else '')


@dataclass(frozen=True)
class PathPolicy:
    """路径白名单。

    readonly  允许读、**不允许写**的根
    writable  允许读写的根（工作区一般在这里）
    system_read 允许读的系统目录（解释器、动态库…），永远只读
    """

    readonly: tuple[str, ...] = ()
    writable: tuple[str, ...] = ()
    system_read: tuple[str, ...] = DEFAULT_SYSTEM_READ_PATHS

    # ── 派生 ───────────────────────────────────────────
    def read_roots(self, base: str = '', cwd: str = '') -> tuple[str, ...]:
        """允许读的根（已解析成真实路径）。

        cwd 额外算一个可读根：工作目录就是这一轮的工作区，
        模型读自己的工作区是正常操作，不该拦。
        （修复说明：漏了 cwd 会把「在工作区里 cat 自己的文件」也拒掉。）
        """
        roots = [real_path(p, base) for p in self.readonly]
        roots += [real_path(p, base) for p in self.writable]
        roots += [real_path(p, base) for p in self.system_read]
        if cwd:
            roots.append(real_path(cwd, base))
        return tuple(_dedupe(roots))

    def write_roots(self, base: str = '', cwd: str = '') -> tuple[str, ...]:
        """允许写的根（已解析成真实路径）。

        cwd 额外算一个可写根：工作目录就是这一轮的工作区，
        模型往自己的工作区里写文件是正常操作，不该拦。
        """
        roots = [real_path(p, base) for p in self.writable]
        if cwd:
            roots.append(real_path(cwd, base))
        return tuple(_dedupe(roots))

    def allows_read(self, path: str, base: str = '', cwd: str = '') -> bool:
        target = real_path(path, base)
        return any(is_within(root, target)
                   for root in self.read_roots(base, cwd))

    def allows_write(self, path: str, base: str = '', cwd: str = '') -> bool:
        target = real_path(path, base)
        return any(is_within(root, target)
                   for root in self.write_roots(base, cwd))


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def real_path(path: str, base: str = '') -> str:
    """展开 ~ / 相对路径 / 符号链接，得到**真实**绝对路径。

    realpath 对不存在的末段也能解析（把已存在的父目录解析完），
    所以「即将被创建的文件」也能判定前缀。
    """
    expanded = os.path.expanduser(str(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(base or os.getcwd(), expanded)
    return os.path.realpath(expanded)


def lexical_path(path: str, base: str = '') -> str:
    """词法归一（不展开符号链接）。"""
    expanded = os.path.expanduser(str(path))
    if not os.path.isabs(expanded):
        expanded = os.path.join(base or os.getcwd(), expanded)
    return os.path.normpath(expanded)


def is_within(root: str, path: str) -> bool:
    """path 是否在 root 之内。

    用 commonpath 而不是 startswith：
    `/usr/local` 在 `/usr` 内，但 `/usrlocal` **不在** `/usr` 内 ——
    前缀字符串比较会把后者误判成放行。
    """
    try:
        root_abs = os.path.normpath(os.path.abspath(root))
        path_abs = os.path.normpath(os.path.abspath(path))
        return os.path.commonpath([root_abs, path_abs]) == root_abs
    except ValueError:
        # Windows 上跨盘符；或者路径不可比较 —— 一律判为「不在里面」。
        return False


def tokenize(command: str) -> list[str]:
    """把 shell 命令行切成 token。

    用 shlex 而不是 str.split：引号里的空格不该被当成参数分隔，
    否则 `cat "a b"` 会被误判成两个路径。
    引号不配对时退回朴素切分 —— 解析失败不等于放行，
    后续的路径扫描仍会按能切出来的 token 判定。
    """
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _is_redirect(token: str) -> bool:
    """token 是不是重定向符号（含 `2>`、`>>` 这类带前缀的写法）。"""
    return '>' in token


#: 需要剥掉的引号字符（单引号与双引号）。
#:
#: 用常量而不是在调用点写转义：转义写在字符串里很容易被 heredoc /
#: 格式化工具吃掉，引号一丢就是语法错误。
_QUOTE_CHARS = chr(39) + chr(34)


def extract_write_targets(tokens: list[str]) -> list[str]:
    """从 token 流里抽出**写入目标**。

    覆盖四种写法：
      `> file`   `>> file`   `2> file`   `>file`
    以及**嵌在引号里**的一整段脚本（`sh -c 'echo x > /etc/evil'`）——
    那种情况下重定向符和目标在同一个 token 里，必须拆开。

    `>&1` / `2>&1` 这种「重定向到 fd」不是路径，跳过。

    修复说明：早期版本直接取 `>` 之后的整段文本，不去空白，
    于是 `sh -c 'echo x > /etc/evil'` 抽出来的是 ' /etc/evil'（带前导空格），
    realpath 之后落在工作区**里面** → 判定成「可写」→ 写入逃逸漏网。
    """
    targets: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if _is_redirect(token):
            tail = token.rsplit('>', 1)[1].strip()
            # 目标后面可能还跟着别的内容（`> /etc/evil; rm -rf /`），
            # 只取第一个词 —— 那才是重定向的目标。
            if tail:
                target = tail.split()[0].strip(_QUOTE_CHARS)
                # 目标后面可能跟着 shell 分隔符（`> /etc/evil; rm -rf /`），
                # 那些字符不是路径的一部分，要去掉。
                target = target.rstrip(';|&')
                if target and not target.startswith('&'):
                    targets.append(target)
            elif index + 1 < len(tokens):
                nxt = tokens[index + 1].strip(_QUOTE_CHARS)
                if nxt and not nxt.startswith('&'):
                    targets.append(nxt)
                    index += 1
        index += 1
    return targets


def _is_path_candidate(token: str, base: str) -> bool:
    """token 是不是「看起来像路径」。

    三条：
      1. 带路径分隔符 / 以 ~ . 开头 —— 一定是路径。
      2. 不带分隔符，但在 base 下**确实存在** —— 也可能是路径。
         这一条是软链逃逸的入口：`cat link`（link 是指向 /etc/passwd 的软链）
         没有斜杠，靠第 1 条抓不到，只能靠「它存在」抓。
      3. 带 scheme:// 的一律**不算**路径 —— 那是 URL，交给网络策略判。
         （修复说明：否则 `curl http://x/y` 会被当成路径，
         在 cwd 下拼出「cwd/http:/x/y」并误报成路径越界。）
    """
    if not token or token.startswith('-'):
        return False
    if '://' in token:
        return False
    if token.startswith(('/', '~', './', '../')) or '/' in token:
        return True
    try:
        return os.path.lexists(os.path.join(base or os.getcwd(), token))
    except OSError:
        return False


def scan_path_violations(tokens: list[str], policy: PathPolicy, *,
                         base: str = '', cwd: str = '') -> list[PathViolation]:
    """扫描命令里的路径参数，返回违规列表。

    base  相对路径的基准目录（通常是 cwd）
    cwd   本轮工作目录（额外算一个可写根）
    """
    violations: list[PathViolation] = []
    base = base or cwd or os.getcwd()
    write_targets = set(extract_write_targets(tokens))

    for token in tokens:
        if not _is_path_candidate(token, base):
            continue
        if token in write_targets:
            continue    # 写入目标单独按「写」判定
        resolved = real_path(token, base)
        if policy.allows_read(resolved, base, cwd):
            continue
        lexical = lexical_path(token, real_path(base))
        if '..' in token.replace('\\', '/').split('/'):
            kind = 'traversal'
        elif resolved != lexical:
            kind = 'symlink_escape'
        else:
            kind = 'outside_root'
        violations.append(PathViolation(
            kind, token, f'resolved={resolved}'))

    for target in extract_write_targets(tokens):
        resolved = real_path(target, base)
        if policy.allows_write(resolved, base, cwd):
            continue
        violations.append(PathViolation(
            'write_denied', target, f'resolved={resolved}'))

    if cwd:
        resolved_cwd = real_path(cwd, base)
        if not any(is_within(root, resolved_cwd)
                   for root in policy.read_roots(base, cwd)):
            violations.append(PathViolation(
                'cwd_denied', cwd, f'resolved={resolved_cwd}'))

    return violations


__all__ = [
    'DEFAULT_SYSTEM_READ_PATHS',
    'PathPolicy',
    'PathViolation',
    'ViolationKind',
    'extract_write_targets',
    'is_within',
    'lexical_path',
    'real_path',
    'scan_path_violations',
    'tokenize',
]
