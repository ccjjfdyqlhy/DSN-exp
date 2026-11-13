# apps/dsn_study/gating.py
"""运行时可求值的开关层（Feature Gate）。
#
# 为什么需要它：仓库里**没有**任何 feature flag / 灰度 / 双写 / 蓝绿机制，
# 而 `Config` 是 import 期快照（`config.py:14-22`）—— 运行时改环境变量不生效，
# 面板的 `/config/set` 恒返回 501。
#
# 这意味着"换一整套上下文与人格实现"这种大改，**上线只能靠回滚 commit**，
# 没有中间态。本模块补上这一层：
#
#   * **运行时求值** —— 改文件即生效，不用重启；
#   * **有保守默认** —— 求值失败一律回退默认值（默认 v1 = 旧路径）；
#   * **优先级明确** —— 环境变量 > 文件 > 默认值；
#   * **可观测** —— 每次求值都能看出当时跑的是哪套。
#
# 用法：
#     from apps.dsn_study import gating
#     if gating.enabled("persona_llm_judge", False):
#         ...
#     gating.flag("context_engine", "v1")
#
# 面板可写：`.dsn/feature_flags.json`，格式 `{"context_engine": "v2"}`。
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("StudyGating")

#: 仓库根（.dsn/ 在它下面）
REPO_ROOT = Path(__file__).resolve().parents[2]
#: 开关文件
FLAGS_FILE = REPO_ROOT / ".dsn" / "feature_flags.json"

#: 环境变量前缀
ENV_PREFIX = "DSN_FLAG_"

#: 布尔真值
_TRUTHY = {"1", "true", "yes", "on", "y"}
_FALSY = {"0", "false", "no", "off", "n", ""}

_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_mtime: Optional[float] = None


def _read_file() -> dict[str, str]:
    """读开关文件。文件不存在或坏了 → 返回空 dict（不抛）。"""
    try:
        if not FLAGS_FILE.exists():
            return {}
        mtime = FLAGS_FILE.stat().st_mtime
    except OSError as exc:
        logger.warning("开关文件不可访问（已忽略）: %s", exc)
        return {}
    with _lock:
        if _cache_mtime == mtime:
            return dict(_cache)
    try:
        raw = FLAGS_FILE.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
        if not isinstance(data, dict):
            logger.warning("开关文件格式不对（应为对象），已忽略")
            data = {}
        out = {str(k): str(v) for k, v in data.items()}
    except Exception as exc:
        logger.warning("开关文件解析失败（已忽略）: %s", exc)
        return {}
    with _lock:
        _cache.clear()
        _cache.update(out)
        _cache_mtime = mtime
    return dict(out)


def flag(name: str, default: Optional[str] = "") -> Optional[str]:
    """取开关值。

    优先级：环境变量 ``DSN_FLAG_<NAME>`` > ``.dsn/feature_flags.json`` > 默认值。
    """
    env_key = ENV_PREFIX + str(name).upper()
    env_val = os.environ.get(env_key)
    if env_val is not None:
        return env_val
    try:
        values = _read_file()
    except Exception:
        values = {}
    val = values.get(str(name))
    if val is None:
        return default
    return val


def enabled(name: str, default: bool = False) -> bool:
    """取布尔开关。

    - **未设置** → 返回 ``default``（区分"没配"与"配成空串"）；
    - 取值无法识别 → 回退 ``default``（保守）。
    """
    raw = flag(name, None)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in _TRUTHY:
        return True
    if text in _FALSY:
        return False
    logger.warning("开关 %s 的值 %r 无法识别，回退默认 %s", name, raw, default)
    return default


def snapshot() -> dict[str, str]:
    """当前生效的全部开关（文件里的 + 环境变量覆盖后的）。"""
    values = dict(_read_file())
    for key in list(values):
        env_val = os.environ.get(ENV_PREFIX + str(key).upper())
        if env_val is not None:
            values[key] = env_val
    return values


def set_flag(name: str, value: str) -> bool:
    """写开关（面板用）。成功返回 True。"""
    try:
        FLAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if FLAGS_FILE.exists():
            raw = FLAGS_FILE.read_text(encoding="utf-8")
            loaded = json.loads(raw) if raw.strip() else {}
            if isinstance(loaded, dict):
                data = loaded
        data[str(name)] = str(value)
        FLAGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception as exc:
        logger.warning("开关写入失败: %s", exc)
        return False
    with _lock:
        _cache.clear()
        _cache_mtime = None
    return True


def reload() -> None:
    """丢弃缓存（改了文件但 mtime 没变时用）。"""
    with _lock:
        _cache.clear()
        _cache_mtime = None
