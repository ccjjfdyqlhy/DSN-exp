# usermgr.py
# 服务端用户认证模块（使用 Flask + PyJWT）

import os
import json
import logging
import urllib.parse
import urllib.request
from typing import Optional, Dict, Any

import jwt
from flask import Blueprint, request, redirect, jsonify, current_app, url_for

logger = logging.getLogger(__name__)

try:
    from config import Config
except ImportError:
    pass # Warning 已在 app.py 中处理，此处不再重复提示，继续执行

DEFAULT_BASE_URL = "https://littleskin.cn"
JWT_ALGORITHM = "HS256"


class UserManager:
    """
    LittleSkin OAuth2 服务端核心类，处理授权码交换、用户信息获取、JWT 签发。
    """

    def __init__(
        self,
        client_id: int,
        client_secret: str,
        base_url: str = DEFAULT_BASE_URL,
        jwt_secret: str = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.jwt_secret = jwt_secret or os.environ.get("JWT_SECRET", "dev-secret-change-me")

        # 构建 OAuth 端点
        self.authorize_url = f"{self.base_url}/oauth/authorize"
        self.token_url = f"{self.base_url}/oauth/token"
        self.user_api_url = f"{self.base_url}/api/user"

        # 日志
        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger("UserManager")
            if not self.logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                ))
                self.logger.addHandler(handler)
                self.logger.setLevel(logging.INFO)

    def generate_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        """生成跳转到 LittleSkin 授权页的 URL"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "",
            "state": state,
        }
        return f"{self.authorize_url}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str) -> Optional[str]:
        """用授权码换取 access_token"""
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        req = urllib.request.Request(
            self.token_url,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return resp_data.get("access_token")
        except Exception as e:
            self.logger.error("换取 access_token 失败: %s", e)
            return None

    def get_user_info(self, access_token: str) -> Optional[Dict[str, Any]]:
        """用 access_token 获取用户信息"""
        req = urllib.request.Request(self.user_api_url)
        req.add_header("Authorization", f"Bearer {access_token}")
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            self.logger.error("获取用户信息失败: %s", e)
            return None

    def generate_jwt(self, user_info: Dict[str, Any]) -> str:
        """签发 JWT，包含用户基本信息"""
        payload = {
            "uid": user_info["uid"],
            "nickname": user_info["nickname"],
            "email": user_info.get("email", ""),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=JWT_ALGORITHM)

    def verify_jwt(self, token: str) -> Optional[Dict[str, Any]]:
        """验证 JWT，返回用户信息"""
        try:
            return jwt.decode(token, self.jwt_secret, algorithms=[JWT_ALGORITHM])
        except jwt.InvalidTokenError as e:
            self.logger.warning("JWT 验证失败: %s", e)
            return None


# ---------- Flask 蓝图 ----------
auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.route("/start", methods=["GET"])
def login_start():
    """客户端请求登录：接收 client_redirect 参数，返回 LittleSkin 授权 URL"""
    client_redirect = request.args.get("redirect_uri")
    if not client_redirect:
        return jsonify({"error": "Missing redirect_uri"}), 400

    # 生成 state 用于后续验证（简单示例，实际应使用随机字符串）
    state = client_redirect  # 此处直接将回调地址作为 state，后续验证使用

    um: UserManager = current_app.config["USER_MANAGER"]
    auth_url = um.generate_authorize_url(
        redirect_uri=url_for("auth.callback", _external=True),
        state=state,
    )
    return jsonify({"auth_url": auth_url})


@auth_bp.route("/callback")
def callback():
    """LittleSkin 授权回调地址，处理 code，签发 JWT，重定向到客户端本地服务器"""
    code = request.args.get("code")
    state = request.args.get("state")  # 即客户端传回的 redirect_uri
    if not code or not state:
        return "Missing code or state", 400

    um: UserManager = current_app.config["USER_MANAGER"]
    # 交换 token
    token = um.exchange_code(code, redirect_uri=url_for("auth.callback", _external=True))
    if not token:
        return "Failed to get token", 400

    # 获取用户信息
    user_info = um.get_user_info(token)
    if not user_info:
        return "Failed to get user info", 400

    # 签发 JWT
    jwt_token = um.generate_jwt(user_info)

    # 重定向到客户端本地地址，并附带 token
    redirect_target = f"{state}?token={jwt_token}"
    return redirect(redirect_target)


# 将 UserManager 实例注入到 app 配置的辅助函数
def init_usermgr(app):
    app.config["USER_MANAGER"] = UserManager(
        client_id=Config.LITTLESKIN_CLIENT_ID,
        client_secret=Config.LITTLESKIN_CLIENT_SECRET,
        jwt_secret=Config.JWT_SECRET,
    )
    app.register_blueprint(auth_bp)