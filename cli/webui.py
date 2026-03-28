import os
import json
import base64
import threading
import webbrowser
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from cryptography.fernet import Fernet

# ---------- 配置 ----------
SERVER_BASE_URL = "http://localhost:5000"
WEB_PORT = 8080
TOKEN_FILE = "token.enc"
KEY_FILE = "secret.key"

def get_or_create_key():
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f: return f.read()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f: f.write(key)
    return key

cipher = Fernet(get_or_create_key())

def get_token():
    if not os.path.exists(TOKEN_FILE): return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            return cipher.decrypt(f.read()).decode()
    except: return None

HTML_INDEX = """
<!DOCTYPE html>
<html>
<head>
    <title>DSN-exp WebUI</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root { 
            --primary: #007aff; 
            --sidebar-width: 260px;
            --transition: 0.3s ease; /* 改为标准平滑过渡 */
            
            --glass-bg: rgba(255, 255, 255, 0.45);
            --sidebar-bg: rgba(255, 255, 255, 0.6);
            --text-main: #1d1d1f;
            --text-muted: #86868b;
            --border-highlight: rgba(255, 255, 255, 0.7);
            --bg-gradient: linear-gradient(-45deg, #ee7752, #e73c7e, #23a6d5, #23d5ab);
        }

        @media (prefers-color-scheme: dark) {
            :root {
                --glass-bg: rgba(30, 30, 30, 0.4);
                --sidebar-bg: rgba(10, 10, 10, 0.55);
                --text-main: #f5f5f7;
                --text-muted: #a1a1a6;
                --border-highlight: rgba(255, 255, 255, 0.15);
                --bg-gradient: linear-gradient(-45deg, #1a1a2e, #16213e, #0f3460);
            }
        }

        body { 
            font-family: -apple-system, "SF Pro Display", sans-serif; 
            margin: 0; display: flex; height: 100vh; overflow: hidden;
            background: var(--bg-gradient); background-size: 400% 400%;
            animation: gradientBG 15s ease infinite; color: var(--text-main);
        }
        @keyframes gradientBG { 0% {background-position:0% 50%} 50% {background-position:100% 50%} 100% {background-position:0% 50%} }

        #sidebar { 
            width: var(--sidebar-width); background: var(--sidebar-bg); 
            backdrop-filter: blur(30px) saturate(180%); 
            display: flex; flex-direction: column; 
            border-right: 1px solid var(--border-highlight);
            transition: var(--transition); overflow: hidden; position: relative;
        }
        body.collapsed #sidebar { width: 0; border-right: none; }
        
        #sidebar-content { width: var(--sidebar-width); transition: opacity 0.2s; padding-top: 60px; }
        body.collapsed #sidebar-content { opacity: 0; pointer-events: none; }

        #toggle-btn {
            position: absolute; left: 12px; top: 12px; z-index: 100;
            background: transparent; border: none; cursor: pointer; padding: 10px;
            color: var(--text-main); border-radius: 12px; transition: 0.2s;
            display: flex; align-items: center; justify-content: center;
        }
        #toggle-btn:hover { background: rgba(255,255,255,0.2); backdrop-filter: blur(5px); }

        #main { flex: 1; display: flex; flex-direction: column; position: relative; overflow: hidden; }
        
        #chat-env { 
            flex: 1; overflow-y: auto; padding: 20px 18% 180px 18%; 
            display: flex; flex-direction: column; scroll-behavior: smooth;
        }

        /* 消息上浮动画 - 仅在新消息产生时使用 */
        .animate-up {
            animation: floatUp 0.4s ease-out forwards;
        }
        @keyframes floatUp { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }

        .msg-container { display: flex; flex-direction: column; width: 100%; margin-bottom: 28px; }
        .user-container { align-items: flex-end; }
        .bot-container { align-items: flex-start; }

        .user { 
            max-width: 80%; background: var(--primary); 
            color: white; padding: 12px 22px; border-radius: 22px; 
            box-shadow: 0 8px 20px rgba(0,122,255,0.25); 
        }
        .bot { 
            width: 100%; padding: 0 5px 30px 5px; 
            border-bottom: 1px solid rgba(255,255,255,0.1); 
            transition: background-color 0.3s; 
        }
        .bot-content { line-height: 1.8; font-size: 1.05rem; }

        .time-label { font-size: 0.75rem; color: var(--text-muted); margin-bottom: 8px; padding: 0 4px; }
        .date-divider { align-self: center; font-size: 0.8rem; color: var(--text-muted); backdrop-filter: blur(10px); background: rgba(255,255,255,0.15); padding: 5px 16px; border-radius: 20px; margin: 20px 0 30px 0; border: 0.5px solid var(--border-highlight); }

        .flash-panel { animation: flashTwice 0.8s ease-in-out; }
        @keyframes flashTwice {
            0%, 100% { background-color: transparent; }
            30%, 70% { background-color: rgba(255, 255, 255, 0.1); }
        }

        .loading-container { width: 100%; height: 3px; background: rgba(0, 122, 255, 0.1); overflow: hidden; border-radius: 2px; margin: 15px 0; }
        .loading-bar { width: 35%; height: 100%; background: var(--primary); animation: googleProgress 1.6s infinite ease-in-out; }
        @keyframes googleProgress { 0% { transform: translateX(-100%); } 100% { transform: translateX(300%); } }

        #welcome-text {
            position: absolute; top: -55px; left: 50%; transform: translateX(-50%);
            font-size: 1.8rem; font-weight: 600; width: 100%; text-align: center;
            opacity: 0; transition: opacity 0.5s; pointer-events: none;
            color: white; text-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }
        .is-new-chat #welcome-text { opacity: 1; }

        #input-container { 
            position: absolute; bottom: 40px; left: 50%; transform: translateX(-50%);
            width: 65%; max-width: 850px; 
            background: var(--glass-bg); 
            backdrop-filter: blur(35px) saturate(200%);
            border: 1px solid var(--border-highlight);
            border-top: 1.5px solid rgba(255,255,255,0.4);
            box-shadow: 0 15px 45px rgba(0, 0, 0, 0.15);
            padding: 10px 20px;
            border-radius: 40px;
            /* 去掉 cubic-bezier 换成平稳的过渡，消除回弹感 */
            transition: bottom 0.3s ease, transform 0.3s ease, border-radius 0.3s ease, width 0.3s ease;
        }
        .is-new-chat #input-container { bottom: 42%; }
        #input-container.multiline { border-radius: 20px; }

        #input-wrapper { display: flex; align-items: flex-end; gap: 12px; min-height: 48px; }
        
        textarea { 
            flex: 1; border: none; outline: none; background: transparent;
            font-size: 1.15rem; color: var(--text-main);
            resize: none; max-height: 220px; font-family: inherit;
            overflow: hidden; padding: 12px 0; align-self: center;
            line-height: 1.4;
        }

        .icon-btn {
            width: 44px; height: 44px; border-radius: 50%; border: none;
            display: flex; align-items: center; justify-content: center; flex-shrink: 0;
            cursor: pointer; transition: 0.2s; background: transparent; color: var(--text-main);
        }
        .icon-btn:hover { background: rgba(255,255,255,0.2); }
        .btn-send { background: var(--primary) !important; color: white !important; }

        .nav-item {
            padding: 12px 18px; margin: 0 14px 6px; border-radius: 14px;
            cursor: pointer; font-size: 0.95rem; transition: 0.25s;
            display: flex; align-items: center; gap: 12px;
            border: 1px solid transparent;
        }
        .nav-item:hover { background: rgba(255,255,255,0.15); border: 1px solid var(--border-highlight); }
        .nav-item.active { background: var(--primary); color: white; }
    </style>
</head>
<body class="is-new-chat">
    <button id="toggle-btn" onclick="document.body.classList.toggle('collapsed')">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18M3 6h18M3 18h18"/></svg>
    </button>

    <div id="sidebar">
        <div id="sidebar-content">
            <div class="nav-item" onclick="newChat()" style="margin-bottom: 25px; border: 1px solid var(--border-highlight); background: rgba(255,255,255,0.1);">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                <span style="font-weight: 600;">开始新对话</span>
            </div>
            <div id="history-list"></div>
        </div>
    </div>
    
    <div id="main">
        <div id="chat-env"></div>

        <div id="input-container">
            <div id="welcome-text">今天可以怎么帮到你？</div>
            <div id="input-wrapper">
                <button id="tts-btn" class="icon-btn" onclick="toggleTTS()" title="用语音回复" style="color: var(--primary);">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 5L6 9H2v6h4l5 4V5z"></path><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>
                </button>
                <textarea id="userInput" rows="1" placeholder="键入消息..." oninput="autoHeight(this)"></textarea>
                <button class="icon-btn btn-send" onclick="send()">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
                </button>
            </div>
        </div>
    </div>

    <script>
        let currentChatId = null;
        let ttsEnabled = true;
        let globalLastDate = null;

        function toggleTTS() {
            ttsEnabled = !ttsEnabled;
            const btn = document.getElementById('tts-btn');
            btn.style.color = ttsEnabled ? "var(--primary)" : "var(--text-muted)";
            btn.style.opacity = ttsEnabled ? "1" : "0.6";
        }

        function formatAiMessage(raw) {
            let text = raw.replace(/<text>|<\/text>/g, '');
            text = text.replace(/<action>([\s\S]*?)<\/action>/g, (_, p1) => `<details><summary>执行动作</summary><pre>${p1}</pre></details>`);
            text = text.replace(/<task>([\s\S]*?)<\/task>/g, (_, p1) => `<details><summary>设定任务</summary><pre>${p1}</pre></details>`);
            return marked.parse(text);
        }

        function parseMessage(content, role) {
            let datePart = null, timePart = null, cleanText = content;
            if (role === 'user') {
                const match = content.match(/^\[(.*?)\]\s*([\s\S]*)/);
                if (match) {
                    const dt = match[1].split(' ');
                    cleanText = match[2];
                    if (dt.length >= 2) { datePart = dt[0]; timePart = dt[1]; }
                }
            }
            return { datePart, timePart, cleanText };
        }

        async function send() {
            const input = document.getElementById('userInput');
            const text = input.value.trim();
            if(!text) return;
            
            const now = new Date();
            const optimisticText = `[${now.toLocaleDateString().replace(/\//g,'-')} ${now.toTimeString().split(' ')[0]}] ${text}`;
            // 发送新消息：isHistory = false，开启上浮动画
            appendMsgObj({role: 'user', content: optimisticText}, false, false);
            
            input.value = '';
            autoHeight(input);

            const loaderId = 'loader_' + Date.now();
            const loaderDiv = document.createElement('div');
            loaderDiv.id = loaderId;
            loaderDiv.className = 'msg-container bot-container animate-up'; // 加载器显示上浮
            loaderDiv.innerHTML = `<div class="bot"><div class="loading-container"><div class="loading-bar"></div></div></div>`;
            document.getElementById('chat-env').appendChild(loaderDiv);
            scrollToBottom();

            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        message: text,
                        chat_id: currentChatId,
                        tts_enabled: ttsEnabled 
                    })
                });
                const data = await res.json();
                currentChatId = data.chat_id;
                
                // 只有在 TTS 开启的情况下才播放音频
                if(ttsEnabled && data.audio) {
                    new Audio("data:audio/wav;base64," + data.audio).play();
                }
                
                document.getElementById(loaderId).remove();
                await reloadCurrentChat(true); 
                loadHistory();
            } catch(e) { 
                document.getElementById(loaderId).innerHTML = "<div class='bot' style='color:#ff3b30;'>连接失败。</div>";
            }
        }

        // 核心改动：增加 isHistory 参数
        function appendMsgObj(msgObj, isFlash = false, isHistory = true) {
            document.body.classList.remove('is-new-chat');
            const env = document.getElementById('chat-env');
            const { datePart, timePart, cleanText } = parseMessage(msgObj.content, msgObj.role);
            
            if (datePart && datePart !== globalLastDate) {
                const dateDiv = document.createElement('div');
                dateDiv.className = 'date-divider';
                dateDiv.innerText = datePart;
                env.appendChild(dateDiv);
                globalLastDate = datePart;
            }

            const container = document.createElement('div');
            // 如果是历史加载，不带动画类；如果是新产生消息，带上上浮动画
            container.className = `msg-container ${msgObj.role === 'user' ? 'user-container' : 'bot-container'} ${isHistory ? '' : 'animate-up'}`;

            let innerHtml = (msgObj.role === 'user' && timePart) ? `<div class="time-label">${timePart}</div>` : '';
            const msgDiv = document.createElement('div');
            msgDiv.className = `msg ${msgObj.role === 'user' ? 'user' : 'bot'}`;
            if (isFlash && msgObj.role !== 'user') msgDiv.classList.add('flash-panel');

            if(msgObj.role === 'user') {
                msgDiv.innerText = cleanText;
            } else {
                msgDiv.innerHTML = `<div class="bot-content">${formatAiMessage(cleanText)}</div>`;
            }

            container.innerHTML = innerHtml;
            container.appendChild(msgDiv);
            env.appendChild(container);
            scrollToBottom();
        }

        async function reloadCurrentChat(flashLast = false) {
            if (!currentChatId) return;
            const hRes = await fetch('/history?id=' + currentChatId);
            const hData = await hRes.json();
            document.getElementById('chat-env').innerHTML = '';
            globalLastDate = null;
            hData.messages.forEach((m, idx) => {
                const isLast = idx === hData.messages.length - 1;
                // 加载历史或重刷列表时，isHistory 为 true，禁用上浮动画
                appendMsgObj(m, flashLast && isLast, true);
            });
            scrollToBottom();
        }

        function scrollToBottom() {
            const env = document.getElementById('chat-env');
            env.scrollTo({top: env.scrollHeight, behavior: 'auto'});
        }

        function autoHeight(elem) {
            elem.style.height = 'auto';
            const h = elem.scrollHeight;
            elem.style.height = h + 'px';
            const container = document.getElementById('input-container');
            if (h > 50) container.classList.add('multiline');
            else container.classList.remove('multiline');
        }

        function newChat() {
            currentChatId = null;
            globalLastDate = null;
            document.getElementById('chat-env').innerHTML = '';
            document.body.classList.add('is-new-chat');
        }

        async function loadHistory() {
            const res = await fetch('/list');
            const data = await res.json();
            const list = document.getElementById('history-list');
            list.innerHTML = '';
            data.chats.forEach(c => {
                const d = document.createElement('div');
                d.className = `nav-item ${currentChatId === c.chat_id ? 'active' : ''}`;
                d.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                               <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${c.chat_name}</span>`;
                d.onclick = async () => {
                    currentChatId = c.chat_id;
                    await reloadCurrentChat(false);
                    loadHistory();
                };
                list.appendChild(d);
            });
        }
        
        document.getElementById('userInput').addEventListener('keydown', e => {
            if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); send(); }
        });

        loadHistory();
    </script>
</body>
</html>
"""

# ---------- 后端逻辑保持不变 ----------
class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_INDEX.encode())
        elif url.path == "/list":
            resp = requests.get(f"{SERVER_BASE_URL}/api/chat/list", headers=self.get_headers())
            self.send_json(resp.json())
        elif url.path == "/history":
            chat_id = parse_qs(url.query).get('id', [None])[0]
            resp = requests.get(f"{SERVER_BASE_URL}/api/chat/{chat_id}", headers=self.get_headers())
            self.send_json(resp.json())

    def do_POST(self):
        if self.path == "/chat":
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length))
            payload = {
                "message": post_data["message"],
                "chat_name": "Web会话",
                "chat_id": post_data.get("chat_id"),
                "tts_enabled": post_data.get("tts_enabled", True)
            }
            resp = requests.post(f"{SERVER_BASE_URL}/api/chat/send", json=payload, headers=self.get_headers())
            self.send_json(resp.json())

    def get_headers(self):
        return {"Authorization": f"Bearer {get_token()}"}

    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args): pass

def run_server():
    server = HTTPServer(('localhost', WEB_PORT), WebHandler)
    print(f"DSN-exp WebUI 已启动: http://localhost:{WEB_PORT}")
    webbrowser.open(f"http://localhost:{WEB_PORT}")
    server.serve_forever()

if __name__ == "__main__":
    if not get_token():
        print("错误：请先运行 cli.py 授权。")
    else:
        run_server()