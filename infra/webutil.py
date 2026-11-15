# infra/webutil.py
# Web 层安全辅助：路径防线与文件名净化。
#
# 针对 CodeQL py/path-injection 的统一防线：请求参数拼进文件路径时，必须
# 在服务端定义的根目录内 realpath（展开 `..` 与符号链接）并做前缀守卫，
# 防止穿越出预期目录。normalize-then-check 模式（realpath + startswith）
# 是 CodeQL 认可的清除方式；守卫必须内联在使用该路径的函数里，且下游
# 只使用守卫后的同一个字符串。
#
# 注：HTTP 错误响应里不要携带任何异常派生数据（str(e)、异常类名都算），
# 细节只进服务端日志，对外回固定文案；受控的域异常文案用框架的
# exception handler（形参不构成异常污点源）渲染。

from __future__ import annotations

import os
import re
from pathlib import Path

# 文件名片段允许的字符：字母/数字/下划线/连字符。
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9_\-]+")

# 标识符（角色卡 id、技能 id 等用作文件名前缀的请求字段）允许的字符。
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,128}")


def valid_id(raw: str) -> bool:
    """校验请求提供的标识符能否安全用作文件名前缀。

    只允许字母/数字/下划线/连字符；路径分隔符与 `..` 一律不合法。用于
    拒绝（而不是改写）非法的 card_id / skill_id，防止拼路径时穿越出目录。
    """
    return bool(_SAFE_ID_RE.fullmatch(str(raw or "")))


def realpath_under(base: str | Path, user_path: str | Path) -> str:
    """把用户提供的路径按 `base` 起算做规范化（realpath），返回绝对路径字符串。

    只做规范化，**不做越界判断** —— 调用方必须紧跟着用 `root_prefix(base)`
    做 `startswith` 守卫（这是 CodeQL py/path-injection 认可的
    normalize-then-check 模式），并把守卫后的同一个字符串传给文件操作：

        p = realpath_under(base, user_path)
        if not p.startswith(root_prefix(base)):
            reject
        open(p)  # 安全

    `os.path.realpath` 会展开 `..` 与符号链接；绝对路径的 user_path 在
    os.path.join 语义下直接替换 base，最终仍由 startswith 守卫兜底。
    """
    base_real = os.path.realpath(str(base))
    return os.path.realpath(os.path.join(base_real, str(user_path)))


def root_prefix(base: str | Path) -> str:
    """`base` 规范化后的目录前缀（以路径分隔符结尾），供 startswith 守卫用。

    带分隔符结尾可拒绝兄弟目录（/base2 不会通过 /base/ 的前缀检查）。
    """
    return os.path.realpath(str(base)).rstrip(os.sep) + os.sep


def filename_component(raw: str, *, fallback: str = "item", limit: int = 64) -> str:
    """把用户输入收敛成安全的文件名片段：仅字母/数字/下划线/连字符。

    其余字符统一替换为 `_`，收尾修剪并截断到 `limit`；全非法时回退到
    `fallback`，保证结果永远非空、不含路径分隔符。
    """
    cleaned = _SAFE_COMPONENT_RE.sub("_", str(raw or "")).strip("_-")[:limit]
    cleaned = cleaned.strip("_-")
    return cleaned or fallback
