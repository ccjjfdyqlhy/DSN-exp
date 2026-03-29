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
    <script>
        window.MathJax = {
            tex: {
                inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
                displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
                processEscapes: true
            },
            options: {
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
            },
            startup: { typeset: false }
        };
    </script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    
    <style>
        :root { 
            --primary: #007aff; 
            --sidebar-width: 260px;
            --transition: 0.3s ease;
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

        .animate-up { animation: floatUp 0.4s ease-out forwards; }
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

        /* 底部动态卡片和进度条集成样式 */
        .inline-status-card {
            display: flex; align-items: center; gap: 10px;
            padding: 10px 18px; margin-top: 10px; margin-bottom: 5px;
            background: var(--glass-bg); backdrop-filter: blur(25px);
            border: 1px solid var(--border-highlight);
            border-radius: 12px; position: relative; overflow: hidden;
            width: fit-content; max-width: 100%;
            box-shadow: 0 4px 15px rgba(0,0,0,0.05);
            transition: opacity 0.3s ease;
        }
        .status-icon {
            color: var(--primary); display: flex; align-items: center; justify-content: center;
            animation: statusPulse 1.5s infinite alternate;
        }
        @keyframes statusPulse {
            from { opacity: 1; transform: scale(1); }
            to { opacity: 0.6; transform: scale(1.1); }
        }
        .status-text { font-size: 0.95rem; color: var(--text-main); font-weight: 500; }
        
        .progress-bottom {
            position: absolute; bottom: 0; left: 0;
            width: 100%; height: 3px; background: rgba(0, 122, 255, 0.15);
            overflow: hidden;
        }
        .progress-bottom-bar {
            width: 40%; height: 100%; background: var(--primary);
            animation: googleProgress 1.6s infinite ease-in-out; border-radius: 3px;
        }
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

        /* 麦克风正在录音闪烁动画 */
        .recording-pulse { color: #ff3b30 !important; animation: recPulse 1s infinite alternate; }
        @keyframes recPulse { from { opacity: 1; } to { opacity: 0.4; } }
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
                <button id="mic-btn" class="icon-btn" onclick="toggleRecording()" title="按住录音" style="color: var(--text-muted);">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>
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
            text = text.replace(/<action>([\s\S]*?)<\/action>/g, (_, p1) => `<details><summary>执行了动作</summary><pre>${p1}</pre></details>`);
            text = text.replace(/<task>([\s\S]*?)<\/task>/g, (_, p1) => `<details><summary>执行了任务</summary><pre>${p1}</pre></details>`);
            return marked.parse(text);
        }

        function parseMessage(content, role) {
            let datePart = null, timePart = null, cleanText = content;
            const match = content.match(/^\[(.*?)\s+(.*?)\]\s*([\s\S]*)/);
            if (match) {
                datePart = match[1];
                timePart = match[2];
                cleanText = match[3];
            }
            return { datePart, timePart, cleanText };
        }

        // --- 录音逻辑 ---
        let mediaRecorder;
        let audioChunks = [];
        let isRecording = false;

        async function toggleRecording() {
            const micBtn = document.getElementById('mic-btn');
            if (isRecording) {
                mediaRecorder.stop();
                isRecording = false;
                micBtn.classList.remove('recording-pulse');
                return;
            }
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];
                mediaRecorder.addEventListener("dataavailable", event => audioChunks.push(event.data));
                mediaRecorder.addEventListener("stop", async () => {
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                    micBtn.style.opacity = '0.5';
                    try {
                        const res = await fetch('/asr', { method: 'POST', body: audioBlob });
                        const data = await res.json();
                        if (data.text) {
                            document.getElementById('userInput').value = data.text;
                            send(true); 
                        }
                    } catch(e) { console.error("ASR 错误", e); }
                    micBtn.style.opacity = '1';
                    stream.getTracks().forEach(t => t.stop());
                });
                mediaRecorder.start();
                isRecording = true;
                micBtn.classList.add('recording-pulse');
            } catch(e) {
                alert("无法获取麦克风权限。");
            }
        }

        // --- 状态指示卡片控制 ---
        const statusMap = {
            'parsing': { text: '进行模态转换', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>' },
            'request': { text: '构建回答', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"></path><path d="M12 12v9"></path><path d="M8 17l4 4 4-4"></path></svg>' },
            'execution': { text: '执行任务', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>' },
            'tts': { text: '正在合成语音', icon: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path></svg>' }
        };

        function updateInlineStatus(loaderId, stage) {
            if (!statusMap[stage]) return;
            const iconEl = document.getElementById(`icon_${loaderId}`);
            const textEl = document.getElementById(`text_${loaderId}`);
            if(iconEl && textEl) {
                iconEl.innerHTML = statusMap[stage].icon;
                textEl.innerText = statusMap[stage].text;
                scrollToBottom();
            }
        }

        // --- 逐行渲染渲染器 ---
        function applyTypewriterEffect(containerElem, rawText) {
            let contentDiv = containerElem.querySelector('.bot-content');
            if(!contentDiv) {
                contentDiv = document.createElement('div');
                contentDiv.className = 'bot-content';
                containerElem.insertBefore(contentDiv, containerElem.firstChild);
            }
            contentDiv.innerHTML = formatAiMessage(rawText);
            
            const lines = Array.from(contentDiv.children);
            if(lines.length === 0) return;
            
            lines.forEach(line => {
                line.style.opacity = '0';
                line.style.transform = 'translateY(10px)';
                line.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            });

            let i = 0;
            const interval = setInterval(() => {
                if (i >= lines.length) {
                    clearInterval(interval);
                    if (window.MathJax && window.MathJax.typesetPromise) { MathJax.typesetPromise([containerElem]); }
                    return;
                }
                lines[i].style.opacity = '1';
                lines[i].style.transform = 'translateY(0)';
                scrollToBottom();
                i++;
            }, 500);
        }

        async function send(isAsr = false) {
            const input = document.getElementById('userInput');
            const text = input.value.trim();
            if(!text) return;
            
            const now = new Date();
            const dStr = now.toLocaleDateString('en-CA');
            const tStr = now.toTimeString().split(' ')[0];
            
            appendMsgObj({role: 'user', content: `[${dStr} ${tStr}] ${text}`}, false, false);
            
            input.value = '';
            autoHeight(input);

            const loaderId = 'loader_' + Date.now();
            const loaderDiv = document.createElement('div');
            loaderDiv.id = loaderId;
            loaderDiv.className = 'msg-container bot-container animate-up';
            // 加入行内状态卡片及底部进度条
            loaderDiv.innerHTML = `
                <div class="bot">
                    <div class="bot-content"></div>
                    <div class="inline-status-card" id="status_${loaderId}">
                        <div class="status-icon" id="icon_${loaderId}">
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>
                        </div>
                        <div class="status-text" id="text_${loaderId}">准备处理...</div>
                        <div class="progress-bottom"><div class="progress-bottom-bar"></div></div>
                    </div>
                </div>`;
            document.getElementById('chat-env').appendChild(loaderDiv);
            scrollToBottom();

            try {
                const res = await fetch('/chat_stream', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        message: text,
                        chat_id: currentChatId,
                        tts_enabled: ttsEnabled,
                        is_asr_input: isAsr === true
                    })
                });

                const reader = res.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let targetContainer = document.getElementById(loaderId).querySelector('.bot');

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value, {stream: true});
                    const lines = chunk.split('\\n');
                    
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const data = JSON.parse(line.substring(6));
                            updateInlineStatus(loaderId, data.status);
                            
                            if (data.status === 'text_ready') {
                                currentChatId = data.chat_id;
                                document.getElementById(loaderId).classList.remove('animate-up');
                                applyTypewriterEffect(targetContainer, data.reply);
                            } 
                            else if (data.status === 'completed') {
                                const card = document.getElementById(`status_${loaderId}`);
                                if(card) {
                                    card.style.opacity = '0';
                                    setTimeout(() => card.remove(), 300);
                                }
                                if(data.filtered) {
                                    document.getElementById(loaderId).remove();
                                }
                                if(ttsEnabled && data.audio) {
                                    new Audio("data:audio/wav;base64," + data.audio).play();
                                }
                                loadHistory(); 
                            }
                        }
                    }
                }
            } catch(e) { 
                const card = document.getElementById(`status_${loaderId}`);
                if(card) card.remove();
            }
        }

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

            if (window.MathJax && window.MathJax.typesetPromise) {
                MathJax.typesetPromise([msgDiv]).then(() => scrollToBottom());
            } else {
                scrollToBottom();
            }
        }

        async function reloadCurrentChat(flashLast = false) {
            if (!currentChatId) return;
            const hRes = await fetch('/history?id=' + currentChatId);
            const hData = await hRes.json();
            document.getElementById('chat-env').innerHTML = '';
            globalLastDate = null;
            hData.messages.forEach((m, idx) => {
                const isLast = idx === hData.messages.length - 1;
                appendMsgObj(m, flashLast && isLast, true);
            });
        }

        function scrollToBottom() {
            const env = document.getElementById('chat-env');
            env.scrollTo({top: env.scrollHeight, behavior: 'smooth'});
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
                    if(currentChatId === c.chat_id) return;
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

# ---------- 后端逻辑 ----------
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
        if self.path == "/chat_stream":
            content_length = int(self.headers['Content-Length'])
            post_data = json.loads(self.rfile.read(content_length))
            payload = {
                "message": post_data["message"],
                "chat_name": "Web会话",
                "chat_id": post_data.get("chat_id"),
                "tts_enabled": post_data.get("tts_enabled", True),
                "is_asr_input": post_data.get("is_asr_input", False)
            }
            # 代理流式请求给 app.py /api/chat/stream_send
            resp = requests.post(f"{SERVER_BASE_URL}/api/chat/stream_send", json=payload, headers=self.get_headers(), stream=True)
            self.send_response(200)
            self.send_header("Content-type", "text/event-stream")
            self.end_headers()
            for chunk in resp.iter_content(chunk_size=None):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    
        elif self.path == "/asr":
            content_length = int(self.headers['Content-Length'])
            audio_bytes = self.rfile.read(content_length)
            files = {'audio': ('audio.webm', audio_bytes, 'audio/webm')}
            resp = requests.post(f"{SERVER_BASE_URL}/api/asr/recognize", files=files, headers=self.get_headers())
            self.send_json(resp.json())
            
        elif self.path == "/chat":
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