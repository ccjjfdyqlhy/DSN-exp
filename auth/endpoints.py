# auth/endpoints.py
# Flask 认证端点 — 全部 /api/auth/* 路由

from __future__ import annotations

import logging

from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger("AuthEndpoints")

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_auth() -> "AuthManager":
    return current_app.config["AUTH_MANAGER"]


def _get_ip() -> str:
    from .network import NetworkDetector
    return NetworkDetector.get_client_ip(request)


# ═══════════ 状态 ═══════════

@auth_bp.route("/status", methods=["GET"])
def auth_status():
    """返回服务器认证状态"""
    auth = _get_auth()
    users = auth.list_users()
    return jsonify({
        "need_pairing": len(users) == 0,
        "users_count": len(users),
        "methods": {
            "pairing": auth.pairing.is_active(),
            "session": True,
            "webauthn": auth.webauthn is not None and auth.webauthn.available if auth.webauthn else False,
            "totp": auth.totp is not None and auth.totp.available if auth.totp else False,
            "api_key": True,
        },
    })


@auth_bp.route("/users", methods=["GET"])
def auth_users():
    """返回用户列表（仅 ID + display_name，不含敏感信息）"""
    auth = _get_auth()
    return jsonify({"users": auth.list_users()})


# ═══════════ L0 配对码 ═══════════

@auth_bp.route("/pairing/status", methods=["GET"])
def pairing_status():
    """当前配对码状态"""
    auth = _get_auth()
    return jsonify(auth.pairing.get_status())


@auth_bp.route("/pairing/verify", methods=["POST"])
def pairing_verify():
    """提交配对码 + 名字 → 创建用户 → 返回 uid"""
    auth = _get_auth()
    data = request.get_json()
    if not data or "code" not in data:
        return jsonify({"error": "Missing code"}), 400

    code = str(data["code"]).strip()
    display_name = str(data.get("display_name", "")).strip()
    is_admin = bool(data.get("is_admin", True))

    network_level = auth.network.get_network_level(_get_ip())
    if network_level == "external":
        return jsonify({"error": "配对码仅在内网可用"}), 403

    uid = auth.pairing.verify(code)
    if uid is None:
        return jsonify({"error": "配对码无效或已过期"}), 401

    if display_name:
        auth._update_user_name(uid, display_name)

    session_id, device_token, expires = auth.session.create_session(
        uid, device_name="initial-setup", ip_address=_get_ip(), trust_device=True,
    )

    response = jsonify({
        "uid": uid,
        "display_name": display_name,
        "session_id": session_id,
        "device_token": device_token,
        "expires_at": expires,
        "need_webauthn": auth.webauthn is not None and auth.webauthn.available if auth.webauthn else False,
    })
    response.set_cookie(
        "dsn_device", device_token,
        max_age=86400 * 30, httponly=True, samesite="Lax", secure=False,
    )
    return response


# ═══════════ L1 会话 + 信任设备 ═══════════

@auth_bp.route("/session/recover", methods=["POST"])
def session_recover():
    """信任设备恢复登录。body: uid 或 display_name + device_token"""
    auth = _get_auth()
    data = request.get_json() or {}
    client_ip = _get_ip()

    device_token = request.cookies.get("dsn_device", "") or str(data.get("device_token", "")).strip()

    logger.info("session_recover: ip=%s cookies_keys=%s body_keys=%s dsn_device=%s",
                client_ip,
                list(request.cookies.keys()),
                list(data.keys()),
                device_token[:16] + "..." if device_token else "<absent>")
    if not device_token:
        logger.warning("session_recover: no device token from ip=%s", client_ip)
        return jsonify({"error": "No device token"}), 401

    uid = 0
    uid_raw = data.get("uid")
    if uid_raw is not None:
        uid = int(uid_raw)
    if not uid:
        display_name = str(data.get("display_name", "")).strip()
        if display_name:
            uid = auth._get_uid_by_name(display_name)
            logger.info("session_recover: looked up uid=%d for display_name='%s'", uid, display_name)
    if not uid:
        logger.warning("session_recover: could not determine uid from body (raw_uid=%s)", uid_raw)
        return jsonify({"error": "Missing uid or display_name"}), 400

    logger.info("session_recover: attempting recovery for uid=%d", uid)
    result = auth.session.recover(uid, device_token, client_ip)
    if result is None:
        logger.warning("session_recover: recovery FAILED for uid=%d", uid)
        return jsonify({"error": "Device not trusted or expired"}), 401

    logger.info("session_recover: OK uid=%d new_session=%.12s...", uid, result["session_id"])
    return jsonify({
        "session_id": result["session_id"],
        "uid": result["uid"],
        "expires_at": result.get("expires_at", ""),
    })


@auth_bp.route("/session", methods=["DELETE"])
def session_revoke():
    """退出当前会话"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    session_id = request.headers.get("Authorization", "").replace("Session ", "")
    auth._get_auth_instance().session.revoke_session(session_id)
    return jsonify({"success": True})


@auth_bp.route("/sessions", methods=["GET"])
def session_list():
    """列出当前用户的所有活跃会话"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    sessions = _get_auth().session.list_sessions(auth["uid"])
    return jsonify({"sessions": sessions})


# ═══════════ L2 WebAuthn ═══════════

@auth_bp.route("/webauthn/register/begin", methods=["POST"])
def webauthn_register_begin():
    """开始注册通行密钥"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    mgr = _get_auth().webauthn
    if mgr is None or not mgr.available:
        return jsonify({"error": "WebAuthn not available"}), 503
    display_name = auth.get("display_name", auth.get("nickname", "user"))
    options = mgr.register_begin(auth["uid"], display_name)
    if options is None:
        return jsonify({"error": "WebAuthn registration failed"}), 500
    return jsonify(options)


@auth_bp.route("/webauthn/register/complete", methods=["POST"])
def webauthn_register_complete():
    """完成注册"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    mgr = _get_auth().webauthn
    if mgr is None:
        return jsonify({"error": "WebAuthn not available"}), 503
    ok = mgr.register_complete(auth["uid"], request.get_json() or {})
    return jsonify({"success": ok})


@auth_bp.route("/webauthn/login/begin", methods=["POST"])
def webauthn_login_begin():
    """开始通行密钥登录"""
    data = request.get_json() or {}
    uid = int(data.get("uid", 0))
    mgr = _get_auth().webauthn
    if mgr is None or not mgr.available:
        return jsonify({"error": "WebAuthn not available"}), 503
    options = mgr.login_begin(uid)
    if options is None:
        return jsonify({"error": "WebAuthn login failed"}), 500
    return jsonify(options)


@auth_bp.route("/webauthn/login/complete", methods=["POST"])
def webauthn_login_complete():
    """完成通行密钥登录→返回 session"""
    data = request.get_json() or {}
    uid = int(data.get("uid", 0))
    mgr = _get_auth().webauthn
    if mgr is None:
        return jsonify({"error": "WebAuthn not available"}), 503
    result_uid = mgr.login_complete(uid, data)
    if result_uid is None:
        return jsonify({"error": "WebAuthn verification failed"}), 401
    session_id, device_token, expires = _get_auth().session.create_session(
        result_uid, device_name="webauthn", ip_address=_get_ip(),
        trust_device=data.get("trust_device", True),
    )
    response = jsonify({"session_id": session_id, "uid": result_uid, "expires_at": expires})
    response.set_cookie(
        "dsn_device", device_token, max_age=86400 * 30,
        httponly=True, samesite="Lax", secure=False,
    )
    return response


# ═══════════ L3 TOTP ═══════════

@auth_bp.route("/totp/setup", methods=["POST"])
def totp_setup():
    """生成 TOTP 种子"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    mgr = _get_auth().totp
    if mgr is None or not mgr.available:
        return jsonify({"error": "TOTP not available"}), 503
    result = mgr.setup(auth["uid"], auth.get("display_name", auth.get("nickname", "user")))
    if result is None:
        return jsonify({"error": "TOTP setup failed"}), 500
    return jsonify(result)


@auth_bp.route("/totp/activate", methods=["POST"])
def totp_activate():
    """激活 TOTP"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    code = str(data.get("code", "")).strip()
    mgr = _get_auth().totp
    if mgr is None:
        return jsonify({"error": "TOTP not available"}), 503
    ok = mgr.activate(auth["uid"], code)
    return jsonify({"success": ok})


@auth_bp.route("/totp/verify", methods=["POST"])
def totp_verify():
    """TOTP 登录验证"""
    data = request.get_json() or {}
    uid = int(data.get("uid", 0))
    code = str(data.get("code", "")).strip()
    if not uid or not code:
        return jsonify({"error": "Missing uid or code"}), 400
    mgr = _get_auth().totp
    if mgr is None or not mgr.available:
        return jsonify({"error": "TOTP not available"}), 503
    ok = mgr.verify(uid, code)
    if not ok:
        return jsonify({"error": "Invalid TOTP code"}), 401
    session_id, device_token, expires = _get_auth().session.create_session(
        uid, device_name="totp-login", ip_address=_get_ip(), trust_device=True,
    )
    response = jsonify({"session_id": session_id, "uid": uid, "expires_at": expires})
    response.set_cookie("dsn_device", device_token, max_age=86400 * 30,
                        httponly=True, samesite="Lax", secure=False)
    return response


# ═══════════ L4 API Key ═══════════

@auth_bp.route("/api-key/create", methods=["POST"])
def api_key_create():
    """创建 API Key"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json() or {}
    raw, key_hash = _get_auth().api_key.create_key(
        auth["uid"],
        name=str(data.get("name", "unnamed")),
        scopes=str(data.get("scopes", "read")),
    )
    return jsonify({"key": raw, "key_hash": key_hash, "warning": "此密钥仅显示一次，请立即复制保存"})


@auth_bp.route("/api-key/list", methods=["GET"])
def api_key_list():
    """列出 API Key"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    keys = _get_auth().api_key.list_keys(auth["uid"])
    return jsonify({"keys": keys})


@auth_bp.route("/api-key/<key_hash>", methods=["DELETE"])
def api_key_revoke(key_hash: str):
    """撤销 API Key"""
    auth = authenticate_from_request()
    if not auth:
        return jsonify({"error": "Unauthorized"}), 401
    ok = _get_auth().api_key.revoke(key_hash)
    return jsonify({"success": ok})


# ═══════════ 内部辅助 ═══════════

def authenticate_from_request() -> dict | None:
    """从当前 request 认证用户"""
    auth_mgr = _get_auth()
    return auth_mgr.authenticate(request)


def _get_auth():
    return current_app.config["AUTH_MANAGER"]
