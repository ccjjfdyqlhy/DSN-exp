# apps/dsn_study/api/skills.py
# 技能管理 API —— 让"技能可插拔"这件事不用改代码、不用重启就能生效。
#
#   GET  /api/skills                 技能清单 + 工具索引 + 能力清单 + 加载期诊断
#   POST /api/skills/install         运行时安装（从目录）
#   POST /api/skills/reload          全量重扫技能目录
#   POST /api/skills/<name>/enable   启用
#   POST /api/skills/<name>/disable  禁用
#   POST /api/skills/<name>/reload   重载单个技能
#   POST /api/skills/<name>/uninstall 卸载
#
# 为什么需要它（2026-11）：
#   以前 SkillManager.install() 存在，但**没有任何 HTTP 入口**，
#   写完技能包只能重启应用；而且技能写错了（方法名/参数名对不上）
#   要等到用户真的调那个工具才会暴露。现在：
#     * 装完技能 → 调 install / reload 立即生效；
#     * 写错了 → GET /api/skills 的 issues 字段直接告诉你哪一行不对。

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, jsonify, request, g

from infra.webutil import realpath_under, root_prefix

logger = logging.getLogger("SkillsAPI")

skills_bp = Blueprint("skills_api", __name__)

_manager = None
_registry = None
_auth_manager = None


def init_skills_api(skill_manager, skill_registry, auth_manager):
    global _manager, _registry, _auth_manager
    _manager = skill_manager
    _registry = skill_registry
    _auth_manager = auth_manager


@skills_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@skills_bp.route("/api/skills", methods=["GET"])
def list_skills():
    """技能清单 + 工具索引 + 能力清单 + 诊断。"""
    if _manager is None or _registry is None:
        return jsonify({"error": "技能系统未初始化"}), 503

    skills = _manager.list_skills()
    for s in skills:
        try:
            s["tools"] = [k for k in _registry.list_active_tools()
                          if k.startswith(f"{s['name']}.")]
        except Exception:
            s["tools"] = []

    # 无法派发的工具（注册成功但调用必挂）—— 阶段 0 的护栏。
    # 装配期已打 ERROR 日志，这里再暴露一份，便于运维/CI 直接断言。
    try:
        undispatchable = _registry.undispatchable_tools()
    except Exception:
        undispatchable = []

    payload = {
        "skills": skills,
        "tools": _registry.get_tools_index(),
        "capabilities": _registry.capability_names(),
        "diagnostics": _manager.diagnostics(),
        "undispatchable_tools": undispatchable,
        "undispatchable_count": len(undispatchable),
    }
    return jsonify(payload)


def _allowed_skill_roots() -> list:
    """运行时安装技能允许的根目录：已配置的技能扫描目录 + 环境变量扩展。

    技能安装会把 tools/*.py 导入进程（任意代码执行），因此不允许把任意
    请求提供的路径直接喂给安装器；默认只接受启动时扫描的那些技能目录，
    开发者可用 DSN_SKILL_INSTALL_ROOT 显式放开额外目录。
    """
    roots: list = []
    if _manager is not None:
        for d in _manager.diagnostics().get("skill_dirs") or []:
            try:
                roots.append(Path(d).resolve())
            except OSError:
                continue
    extra = os.environ.get("DSN_SKILL_INSTALL_ROOT", "")
    if extra:
        roots.append(Path(extra).expanduser().resolve())
    return roots


@skills_bp.route("/api/skills/install", methods=["POST"])
def install_skill():
    """运行时安装一个技能（从目录）。不需要重启。"""
    if _manager is None:
        return jsonify({"error": "技能系统未初始化"}), 503
    data = request.get_json(silent=True) or {}
    skill_dir = (data.get("skill_dir") or data.get("dir") or "").strip()
    if not skill_dir:
        return jsonify({"error": "缺少 skill_dir 参数"}), 400
    # 防路径注入：请求提供的目录必须落在允许的技能根目录内。realpath 展开
    # ../ 与符号链接后做前缀守卫（带分隔符结尾，兄弟目录同样拒绝），
    # 后续文件操作与安装只使用守卫后的 resolved_dir。
    resolved_dir = None
    for root in _allowed_skill_roots():
        cand = realpath_under(root, skill_dir)
        if cand.startswith(root_prefix(root)):
            resolved_dir = cand
            break
    if resolved_dir is None:
        return jsonify({"error": "仅允许安装已配置技能目录内的技能"
                                    "（可用 DSN_SKILL_INSTALL_ROOT 扩展）"}), 403
    if not os.path.isdir(resolved_dir):
        return jsonify({"error": "目录不存在"}), 400

    ok = _manager.install(resolved_dir)
    return jsonify({"success": bool(ok), "skill_dir": resolved_dir,
                    "skills": [s["name"] for s in _manager.list_skills()]}), \
        (200 if ok else 400)


@skills_bp.route("/api/skills/reload", methods=["POST"])
def reload_all():
    """全量重扫技能目录（改动 skill.yaml / tools/*.py 后调用）。"""
    if _manager is None:
        return jsonify({"error": "技能系统未初始化"}), 503
    count = _manager.scan_and_load()
    return jsonify({"success": True, "loaded": count,
                    "diagnostics": _manager.diagnostics()})


@skills_bp.route("/api/skills/<name>/<action>", methods=["POST"])
def skill_action(name, action):
    """单个技能的 enable / disable / reload / uninstall。"""
    if _manager is None:
        return jsonify({"error": "技能系统未初始化"}), 503
    actions = {
        "enable": _manager.enable,
        "disable": _manager.disable,
        "reload": _manager.reload,
        "uninstall": _manager.uninstall,
    }
    fn = actions.get(action)
    if fn is None:
        return jsonify({"error": f"未知操作: {action}",
                        "allowed": list(actions.keys())}), 400
    ok = fn(name)
    if not ok:
        return jsonify({"success": False, "error": f"技能不存在或操作失败: {name}",
                        "skill": name}), 404
    return jsonify({"success": True, "skill": name, "action": action})
