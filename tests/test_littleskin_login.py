
# tests/test_littleskin_login.py
# PASSED v1_260214

import json
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import webbrowser
import threading
import sys
from urllib.parse import urlparse, parse_qs

# ==================== 配置区域 ====================
# 请将以下信息替换为你在 LittleSkin 申请的实际值
BASE_URL = "https://littleskin.cn"          # 皮肤站地址，不要以斜杠结尾
CLIENT_ID = input("请输入 LittleSkin 客户端 ID: ")                 # 客户端 ID
CLIENT_SECRET = input("请输入 LittleSkin 客户端密钥: ")         # 客户端密钥
REDIRECT_URI = "http://localhost:5000/littleskin_callback"  # 回调地址，必须与申请时一致
PORT = 5000                                   # 本地服务器端口
# =================================================

AUTHORIZE_URL = f"{BASE_URL}/oauth/authorize"
TOKEN_URL = f"{BASE_URL}/oauth/token"
USER_API_URL = f"{BASE_URL}/api/user"

# 存储全局服务器引用，以便在回调中关闭
server = None


def exchange_code_for_token(code):
    """用 code 换取 access_token"""
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    # 使用 POST 提交表单数据
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(data).encode("utf-8"),
                                 method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            return resp_data.get("access_token")
    except Exception as e:
        print("获取 token 失败:", e)
        return None


def get_user_info(access_token):
    """用 access_token 获取用户信息"""
    req = urllib.request.Request(USER_API_URL)
    req.add_header("Authorization", f"Bearer {access_token}")
    try:
        with urllib.request.urlopen(req) as resp:
            user_data = json.loads(resp.read().decode("utf-8"))
            return user_data
    except Exception as e:
        print("获取用户信息失败:", e)
        return None


def permission_to_str(permission):
    """将权限数值转换为可读文字"""
    mapping = {
        -1: "封禁",
        0: "普通用户",
        1: "管理员",
        2: "超级管理员"
    }
    return mapping.get(permission, "未知")


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            # 首页：显示登录链接
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            # 构造授权链接
            auth_url = (f"{AUTHORIZE_URL}?client_id={CLIENT_ID}"
                        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
                        f"&response_type=code&scope=")
            html = f"""
            <html>
            <head><title>用户登录</title></head>
            <body>
                <h1>LittleSkin OAuth2 登录示例</h1>
                <p><a href="{auth_url}" target="_blank">点击这里登录</a></p>
                <p>如果浏览器没有自动打开，请手动点击链接。</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
            # 自动打开浏览器
            webbrowser.open(auth_url)

        elif parsed.path == "/littleskin_callback":
            # 回调地址：获取 code 并完成登录
            qs = parse_qs(parsed.query)
            code_list = qs.get("code", [])
            error_list = qs.get("error", [])
            if error_list:
                self.send_error_page(f"授权失败：{error_list[0]}")
                return
            if not code_list:
                self.send_error_page("未收到授权码")
                return

            code = code_list[0]
            # 用 code 换 token
            access_token = exchange_code_for_token(code)
            if not access_token:
                self.send_error_page("获取访问令牌失败")
                return

            # 获取用户信息
            user_info = get_user_info(access_token)
            if not user_info:
                self.send_error_page("获取用户信息失败")
                return

            # 显示用户信息
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = f"""
            <html>
            <head><title>用户信息</title></head>
            <body>
                <h1>登录成功！</h1>
                <table border="1">
                    <tr><th>UID</th><td>{user_info.get('uid')}</td></tr>
                    <tr><th>邮箱</th><td>{user_info.get('email')}</td></tr>
                    <tr><th>昵称</th><td>{user_info.get('nickname')}</td></tr>
                    <tr><th>头像类型</th><td>{user_info.get('avatar')}</td></tr>
                    <tr><th>积分</th><td>{user_info.get('score')}</td></tr>
                    <tr><th>权限</th><td>{permission_to_str(user_info.get('permission'))}</td></tr>
                    <tr><th>最后签到</th><td>{user_info.get('last_sign_at')}</td></tr>
                    <tr><th>注册时间</th><td>{user_info.get('register_at')}</td></tr>
                    <tr><th>邮箱验证</th><td>{'是' if user_info.get('verified') else '否'}</td></tr>
                </table>
                <p>你可以关闭此窗口。</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))

            # 延迟关闭服务器（给浏览器足够时间接收响应）
            threading.Timer(1.0, shutdown_server).start()

        else:
            self.send_error(404, "Not Found")

    def send_error_page(self, message):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        html = f"""
        <html>
        <head><title>错误</title></head>
        <body>
            <h1>发生错误</h1>
            <p>{message}</p>
            <p><a href="/">返回首页</a></p>
        </body>
        </html>
        """
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        # 禁止输出多余日志
        pass


def shutdown_server():
    """关闭服务器"""
    global server
    if server:
        print("登录流程完成，服务器正在关闭...")
        server.shutdown()
        server.server_close()


def main():
    global server
    # 检查必要配置
    if CLIENT_ID == "your_client_id" or CLIENT_SECRET == "your_client_secret":
        print("请先在脚本中填写正确的 CLIENT_ID 和 CLIENT_SECRET！")
        sys.exit(1)

    server_address = ("", PORT)
    server = HTTPServer(server_address, OAuthHandler)
    print(f"启动本地服务器，访问 http://localhost:{PORT} 开始登录")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n用户中断，服务器停止。")
        server.shutdown()


if __name__ == "__main__":
    main()