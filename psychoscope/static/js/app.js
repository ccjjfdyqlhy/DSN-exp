// psychoscope/static/js/app.js
// DSN-exp Psychoscope Client — visual novel style + SSE Agent Loop

(function () {
    'use strict';

    var API_BASE = localStorage.getItem('api_base') || 'http://localhost:5000';

    // theme
    function detectTheme() {
        var s = localStorage.getItem('psychoscope_theme');
        if (s) return s;
        return (new Date().getHours() >= 6 && new Date().getHours() < 18) ? 'light' : 'dark';
    }
    function applyTheme(t) {
        document.documentElement.setAttribute('data-theme', t);
        localStorage.setItem('psychoscope_theme', t);
    }
    function toggleTheme() {
        applyTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
    }
    applyTheme(detectTheme());

    // state
    var token = null;
    var currentChatId = null;
    var chats = [];
    var isProcessing = false;
    var activeTypewriter = null;
    var autoScroll = true;
    var isPaused = false;
    var ttsEnabled = false;
    var streamAbort = null;

    // DOM
    var $ = function (s) { return document.querySelector(s); };
    var dom = {
        textBox: $('#text-box'),
        textBoxWrapper: $('#text-box-wrapper'),
        bottomAnchor: $('#bottom-anchor'),
        msgInput: $('#message-input'),
        btnSend: $('#btn-send'),
        btnTTS: $('#btn-tts'),
        scrollBtn: $('#scroll-bottom-btn'),
        statusBar: $('#status-bar'),
        header: $('#header'),
        inputArea: $('#input-area'),
        loginOverlay: $('#login-overlay'),
        loadingOverlay: $('#loading-overlay'),
        sidebar: $('#sidebar'),
        chatList: $('#chat-list'),
        notification: $('#notification'),
        btnLogin: $('#btn-login'),
        btnLogout: $('#btn-logout'),
        btnNewChat: $('#btn-new-chat'),
        btnChatList: $('#btn-chat-list'),
        btnTheme: $('#btn-theme'),
        btnCloseSidebar: $('#btn-close-sidebar'),
    };

    // utils
    var wait = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
    var formatTime = function (ts) {
        if (!ts) return '';
        var d = new Date(ts), f = function (n) { return String(n).padStart(2, '0'); };
        var now = new Date();
        if (d.toDateString() === now.toDateString()) return f(d.getHours()) + ':' + f(d.getMinutes());
        return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + f(d.getHours()) + ':' + f(d.getMinutes());
    };
    var notify = function (msg, isErr) {
        var el = dom.notification;
        el.textContent = msg;
        el.className = isErr ? 'error' : '';
        clearTimeout(el._timeout);
        el._timeout = setTimeout(function () { el.className = 'hidden'; }, 3000);
    };
    var escapeHtml = function (s) {
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    };

    // scroll
    var scrollToBottom = function () {
        if (autoScroll) dom.textBoxWrapper.scrollTo({ top: dom.textBoxWrapper.scrollHeight, behavior: 'smooth' });
    };
    var backToBottom = function () {
        dom.textBoxWrapper.scrollTo({ top: dom.textBoxWrapper.scrollHeight, behavior: 'smooth' });
    };
    var observer = new IntersectionObserver(function (entries) {
        var e = entries[0];
        if (e.isIntersecting) {
            dom.textBoxWrapper.classList.remove('scrolling-up');
            dom.scrollBtn.style.display = 'none';
            autoScroll = true; isPaused = false;
        } else {
            dom.textBoxWrapper.classList.add('scrolling-up');
            dom.scrollBtn.style.display = 'flex';
            autoScroll = false; isPaused = true;
        }
    }, { threshold: 0.1 });
    observer.observe(dom.bottomAnchor);

    // control tag parsing
    var CONTROL_TAGS = [
        { name: 'text', keepContent: true },
        { name: 'task', keepContent: false },
        { name: 'tool', keepContent: false },
        { name: 'recall', keepContent: false },
    ];
    var ACTION_BLOCK_RE = /```action\s*\n[\s\S]*?```/gi;

    function parseControlTags(raw) {
        var text = raw.replace(ACTION_BLOCK_RE, '');
        var narrations = [];
        for (var ti = 0; ti < CONTROL_TAGS.length; ti++) {
            var tag = CONTROL_TAGS[ti];
            var re = new RegExp('<' + tag.name + '>(.*?)</' + tag.name + '>', 'gis');
            var match;
            while ((match = re.exec(text)) !== null) {
                var inner = match[1].trim();
                if (tag.keepContent) {
                    text = text.replace(match[0], inner);
                } else {
                    text = text.replace(match[0], '');
                    var desc = describeAction(tag.name, inner);
                    if (desc) narrations.push(desc);
                }
            }
        }
        text = text.replace(/<[^>]+>/g, '').replace(/\n{3,}/g, '\n\n').trim();
        return { text: text, narrations: narrations };
    }

    function describeAction(tagName, inner) {
        if (tagName === 'task') {
            try {
                var d = JSON.parse(inner);
                var map = { reminder: '设置了一个提醒', reasoner: '开始深度推理', action: '执行了一个操作', analysis: '开始分析任务' };
                return map[d.type] || '安排了一个任务';
            } catch (_) { return '执行了一项后台任务'; }
        }
        if (tagName === 'tool') {
            try { var td = JSON.parse(inner); return '使用了工具 ' + (td.tool || td.skill || ''); }
            catch (_) { return '调用了外部工具'; }
        }
        if (tagName === 'recall') return '检索了相关记忆';
        return null;
    }

    // text line management (novel.html style)
    function archiveActiveLines() {
        var lines = dom.textBox.querySelectorAll('.text-line:not(.history)');
        lines.forEach(function (l) {
            l.classList.remove('active', 'active-group-top', 'active-group-bottom', 'system-line', 'error-line', 'narration-line');
            l.classList.add('history');
        });
    }

    function addNarrationLine(text) {
        var line = document.createElement('div');
        line.className = 'text-line narration-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        var sp = document.createElement('span');
        sp.className = 'speaker';
        sp.textContent = 'ASSISTANT';
        line.appendChild(sp);
        var t = document.createElement('span');
        t.textContent = text;
        line.appendChild(t);
        scrollToBottom();
    }

    function addLineStatic(speaker, text, className) {
        var line = document.createElement('div');
        line.className = 'text-line ' + (className || '');
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        if (speaker) {
            var sp = document.createElement('span');
            sp.className = 'speaker';
            sp.textContent = speaker.toUpperCase();
            line.appendChild(sp);
        }
        var ts = document.createElement('span');
        ts.textContent = text;
        line.appendChild(ts);
        scrollToBottom();
    }

    function addSystemLine(text) {
        var line = document.createElement('div');
        line.className = 'text-line system-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        line.textContent = text;
        scrollToBottom();
    }

    function addErrorLine(text) {
        var line = document.createElement('div');
        line.className = 'text-line error-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        line.textContent = text;
        scrollToBottom();
    }

    function addMessage(speaker, text, isInteraction) {
        return new Promise(function (resolve) {
            if (!isInteraction) archiveActiveLines();
            var line = document.createElement('div');
            line.className = 'text-line';
            dom.textBox.insertBefore(line, dom.bottomAnchor);
            requestAnimationFrame(function () {
                line.classList.add('active');
                if (isInteraction) {
                    var prev = line.previousElementSibling;
                    if (prev && !prev.classList.contains('history')) {
                        prev.classList.replace('active', 'active-group-top');
                        line.classList.replace('active', 'active-group-bottom');
                    }
                }
            });
            if (speaker) {
                var sp = document.createElement('span');
                sp.className = 'speaker';
                sp.textContent = speaker.toUpperCase();
                line.appendChild(sp);
            }
            var textSpan = document.createElement('span');
            line.appendChild(textSpan);
            activeTypewriter = new TypeWriter(textSpan, {
                speed: 30,
                isPaused: function () { return isPaused; },
                onScroll: function () { scrollToBottom(); },
                onComplete: function () { activeTypewriter = null; scrollToBottom(); resolve(); },
            });
            activeTypewriter.type(text);
        });
    }

    // API
    function apiCall(path, method, body) {
        var headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        return fetch(API_BASE + path, { method: method || 'GET', headers: headers, body: body ? JSON.stringify(body) : undefined });
    }
    function apiGet(path) {
        return apiCall(path).then(function (r) {
            if (r.status === 401) { logout(); throw new Error('login expired'); }
            return r.json().then(function (d) {
                if (!r.ok) throw new Error(d.error || 'request failed (' + r.status + ')');
                return d;
            });
        });
    }

    // auth
    function login() {
        window.location.href = API_BASE + '/api/auth/start?redirect_uri=' + encodeURIComponent(window.location.origin + '/');
    }
    function logout() {
        token = null; currentChatId = null; chats = [];
        localStorage.removeItem('jwt_token');
        dom.textBox.querySelectorAll('.text-line').forEach(function (e) { e.remove(); });
        dom.chatList.innerHTML = '';
        dom.sidebar.classList.add('hidden');
        dom.loginOverlay.classList.remove('hidden');
        dom.statusBar.textContent = '';
    }

    // chat management
    function loadChats() {
        return apiGet('/api/chat/list').then(function (d) { chats = d.chats || []; renderChatList(); })
            .catch(function (e) { notify('load list failed: ' + e.message, true); });
    }
    function renderChatList() {
        dom.chatList.innerHTML = '';
        if (chats.length === 0) {
            dom.chatList.innerHTML = '<div style="font-family:LanaPixel,sans-serif;padding:20px;font-size:10px;letter-spacing:2px;color:var(--text-faint);text-align:center">no chats</div>';
            return;
        }
        chats.forEach(function (c) {
            var el = document.createElement('div');
            el.className = 'chat-list-item' + (c.chat_id === currentChatId ? ' active' : '');
            el.innerHTML = '<div class="chat-list-item-name">' + escapeHtml(c.chat_name || 'unnamed') + '</div>' +
                '<div class="chat-list-item-time">' + (c.message_count || 0) + ' msgs - ' + formatTime(c.created_at) + '</div>';
            el.addEventListener('click', function () { selectChat(c.chat_id); });
            dom.chatList.appendChild(el);
        });
    }
    function selectChat(id) {
        if (isProcessing) return;
        currentChatId = id;
        renderChatList();
        dom.sidebar.classList.add('hidden');
        dom.textBox.querySelectorAll('.text-line').forEach(function (e) { e.remove(); });
        return apiGet('/api/chat/' + id).then(function (d) {
            var msgs = d.messages || [];
            msgs.forEach(function (m) {
                if (m.role === 'user') addLineStatic('>', m.content, 'active-group-top');
                else if (m.role === 'assistant') {
                    var p = parseControlTags(m.content);
                    p.narrations.forEach(function (n) { addLineStatic('ASSISTANT', n, 'narration-line'); });
                    addLineStatic('ASSISTANT', p.text, 'active-group-bottom');
                } else if (m.role === 'system') addSystemLine(m.content);
            });
            var lines = dom.textBox.querySelectorAll('.text-line');
            lines.forEach(function (l) {
                l.classList.remove('active', 'active-group-top', 'active-group-bottom');
                l.classList.add('history');
            });
            scrollToBottom();
        }).catch(function (e) { notify('load failed: ' + e.message, true); });
    }
    function newChat() {
        currentChatId = null;
        renderChatList();
        dom.sidebar.classList.add('hidden');
        dom.textBox.querySelectorAll('.text-line').forEach(function (e) { e.remove(); });
        dom.msgInput.focus();
        updateStatusBar();
    }

    // SSE streaming send
    var ACTION_LABELS = {
        shell: 'executing shell', python: 'executing python',
        write_file: 'writing file', edit_file: 'editing file',
    };

    async function msgFlow(text) {
        try {
            archiveActiveLines();
            await addMessage('>', text, true);
            updateStatusBar();

            var res = await fetch(API_BASE + '/api/chat/stream_send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (token || '') },
                body: JSON.stringify({ message: text, chat_id: currentChatId, chat_name: 'Psychoscope', tts_enabled: ttsEnabled }),
                signal: streamAbort.signal,
            });

            if (res.status === 401) { logout(); return; }
            if (!res.ok) {
                var je = await res.json().catch(function () { return {}; });
                addErrorLine(je.error || 'request failed (' + res.status + ')');
                return;
            }

            var reader = res.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var audioB64 = null;

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                var lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    if (line.indexOf('data: ') !== 0) continue;
                    try {
                        var ev = JSON.parse(line.slice(6));
                        switch (ev.status) {
                            case 'text_ready':
                                if (ev.chat_id && !currentChatId) currentChatId = ev.chat_id;
                                if (ev.reply) await addMessage('ASSISTANT', ev.reply, true);
                                break;
                            case 'agent_action':
                                addNarrationLine(ACTION_LABELS[ev.desc] || ev.desc || 'executing action');
                                updateStatusBar();
                                break;
                            case 'text_update':
                                if (ev.reply) await addMessage('ASSISTANT', ev.reply, false);
                                break;
                            case 'completed':
                                if (ev.audio) audioB64 = ev.audio;
                                break;
                        }
                    } catch (_) {}
                }
            }

            if (currentChatId) { await loadChats(); renderChatList(); }
            updateStatusBar();
            if (ttsEnabled && audioB64) playAudioBase64(audioB64);

        } catch (e) {
            if (e.name !== 'AbortError') addErrorLine('ERROR: ' + e.message);
        } finally {
            isProcessing = false;
            activeTypewriter = null;
            streamAbort = null;
            dom.btnSend.disabled = false;
            dom.msgInput.disabled = false;
            dom.msgInput.focus();
        }
    }

    function sendMessage() {
        var text = dom.msgInput.value.trim();
        if (!text || isProcessing) return;
        isProcessing = true;
        dom.btnSend.disabled = true;
        dom.msgInput.disabled = true;
        dom.msgInput.value = '';
        streamAbort = new AbortController();
        msgFlow(text);
    }

    function abortStream() {
        if (streamAbort) { streamAbort.abort(); streamAbort = null; }
        if (activeTypewriter) { activeTypewriter.abort(); activeTypewriter = null; }
        isProcessing = false;
        dom.btnSend.disabled = false;
        dom.msgInput.disabled = false;
        dom.msgInput.focus();
    }

    // TTS
    function toggleTTS() {
        ttsEnabled = !ttsEnabled;
        dom.btnTTS.classList.toggle('active', ttsEnabled);
        dom.btnTTS.title = ttsEnabled ? 'tts: on' : 'tts: off';
    }
    function playAudioBase64(b64) {
        try {
            var raw = atob(b64);
            var bytes = new Uint8Array(raw.length);
            for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
            var url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
            var a = new Audio(url);
            a.onended = function () { URL.revokeObjectURL(url); };
            a.play().catch(function () {});
        } catch (_) {}
    }

    // status bar
    function updateStatusBar() {
        var count = dom.textBox.querySelectorAll('.text-line').length;
        dom.statusBar.textContent = 'INDEX: ' + count;
    }

    // events
    dom.btnLogin.addEventListener('click', login);
    dom.btnLogout.addEventListener('click', function () { if (confirm('logout?')) logout(); });
    dom.btnNewChat.addEventListener('click', newChat);
    dom.btnTheme.addEventListener('click', toggleTheme);
    dom.btnCloseSidebar.addEventListener('click', function () { dom.sidebar.classList.add('hidden'); });
    dom.btnChatList.addEventListener('click', async function () {
        if (dom.sidebar.classList.contains('hidden')) { await loadChats(); dom.sidebar.classList.remove('hidden'); }
        else dom.sidebar.classList.add('hidden');
    });
    dom.btnSend.addEventListener('click', sendMessage);
    dom.btnTTS.addEventListener('click', toggleTTS);
    dom.scrollBtn.addEventListener('click', backToBottom);
    dom.msgInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
        else if (e.key === 'Escape' && isProcessing) { e.preventDefault(); abortStream(); }
    });
    document.addEventListener('click', function (e) {
        if (!dom.sidebar.classList.contains('hidden') && !dom.sidebar.contains(e.target) && e.target !== dom.btnChatList) {
            dom.sidebar.classList.add('hidden');
        }
    });

    // init
    async function init() {
        var p = new URLSearchParams(window.location.search);
        var ut = p.get('token');
        if (ut) { token = ut; localStorage.setItem('jwt_token', token); window.history.replaceState({}, document.title, '/'); }
        else token = localStorage.getItem('jwt_token');
        if (!token) { dom.loginOverlay.classList.remove('hidden'); return; }
        try {
            await loadChats();
            dom.loginOverlay.classList.add('hidden');
            if (chats.length > 0 && chats[0].chat_id) await selectChat(chats[0].chat_id);
            updateStatusBar();
        } catch (e) {
            if (e.message && e.message.indexOf('login') >= 0) logout();
            else { notify('init failed: ' + e.message, true); dom.loginOverlay.classList.add('hidden'); updateStatusBar(); }
        }
        dom.msgInput.focus();
    }
    init();
})();
