# psychoscope/server.py
# DSN-exp Psychoscope Client — 服务端入口点
# 用法: python server.py  或  python server.py --port 5500

import os
import sys
import argparse
from pathlib import Path
from flask import Flask, send_from_directory

HERE = Path(__file__).resolve().parent

app = Flask(
    __name__,
    static_folder=str(HERE / "static"),
    static_url_path="/static",
)

@app.route("/")
def index():
    return send_from_directory(str(HERE / "static"), "index.html")

@app.route("/<path:filename>")
def static_files(filename):
    file_path = HERE / "static" / filename
    if file_path.is_file():
        return send_from_directory(str(HERE / "static"), filename)
    return send_from_directory(str(HERE / "static"), "index.html")

def main():
    parser = argparse.ArgumentParser(description="Psychoscope 客户端服务器")
    parser.add_argument("--host", default=os.environ.get("PSYCHOSCOPE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PSYCHOSCOPE_PORT", 5500)))
    parser.add_argument("--debug", action="store_true", default=os.environ.get("PSYCHOSCOPE_DEBUG", "0") == "1")
    args = parser.parse_args()

    print(f"Psychoscope client running at http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)

if __name__ == "__main__":
    main()
