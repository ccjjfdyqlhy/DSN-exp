#!/usr/bin/env python3
"""
DSN-exp Web Admin Dashboard
Run on port 4500 for server administration via web browser.
Usage:
  python -m web_admin.server              # standalone
  # or import and start from main.py:
  #   from web_admin.server import start_admin_server
  #   start_admin_server()
"""
from __future__ import annotations

import os
import sys
import secrets
import threading
import logging
from pathlib import Path

from flask import Flask, render_template, send_from_directory

WEB_ADMIN_PORT = 4500
WEB_ADMIN_HOST = "0.0.0.0"

logger = logging.getLogger("web_admin")


def create_admin_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
        static_url_path="/static",
    )

    # optionally protect with a random password
    admin_password = os.environ.get("WEB_ADMIN_PASSWORD", "")
    app.config["ADMIN_PASSWORD"] = admin_password

    from web_admin.routes import admin_bp
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    # CORS
    @app.after_request
    def add_cors(response):
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")
        response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        return response

    @app.before_request
    def check_auth():
        from flask import request, jsonify
        if request.method == "OPTIONS":
            return
        if request.path.startswith("/static/"):
            return
        if request.path == "/":
            return
        password = app.config.get("ADMIN_PASSWORD")
        if not password:
            return
        token = request.headers.get("X-Admin-Token", "")
        if token == password:
            return
        # 视频播放 <video> 标签不带自定义头，允许从 query 传 token
        query_token = request.args.get("admin_token", "")
        if query_token and query_token == password:
            return
        return jsonify({"error": "Unauthorized"}), 401

    return app


def start_admin_server(host: str = WEB_ADMIN_HOST, port: int = WEB_ADMIN_PORT,
                       daemon: bool = True):
    """Start the admin web server. Returns (werkzeug_server, thread) or (None, None)."""
    try:
        app = create_admin_app()
    except Exception as e:
        logger.error("Failed to create admin app: %s", e)
        return None, None

    from werkzeug.serving import make_server
    try:
        server = make_server(host, port, app, threaded=True)
    except OSError:
        logger.warning("Port %d already in use, admin server not started", port)
        return None, None

    t = threading.Thread(target=server.serve_forever, daemon=daemon, name="web-admin")
    t.start()
    password = app.config.get("ADMIN_PASSWORD")
    pw_info = "  Authentication: enabled" if password else "  No authentication"
    print(f"\n  Web Admin: http://{host if host != '0.0.0.0' else 'localhost'}:{port}/")
    print(f"  {pw_info}")
    logging.getLogger("web_admin").info("Admin server started on %s:%d", host, port)
    return server, t


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    app = create_admin_app()
    if not app.config.get("ADMIN_PASSWORD"):
        pw = secrets.token_urlsafe(16)
        app.config["ADMIN_PASSWORD"] = pw
        print(f"\n  Generated admin password: {pw}")
        print(f"  Set WEB_ADMIN_PASSWORD env var to use a custom password.\n")
    print(f"  Starting admin dashboard on http://{WEB_ADMIN_HOST}:{WEB_ADMIN_PORT}/")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host=WEB_ADMIN_HOST, port=WEB_ADMIN_PORT, debug=False, threaded=True)


if __name__ == "__main__":
    main()
