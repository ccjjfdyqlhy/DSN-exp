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
    var aiName = 'EXA';
    var currentImageData = null;
    var lineQueue = [];
    var isProcessingLines = false;
    var pendingTiming = null;

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
        btnLogout: $('#btn-logout'),
        btnPair: $('#btn-pair'),
        btnRecover: $('#btn-recover'),
        pairingCode: $('#pairing-code'),
        userName: $('#user-name'),
        recoverUserId: $('#recover-user-id'),
        loginStatus: $('#login-status'),
        pairingSection: $('#pairing-section'),
        recoverSection: $('#recover-section'),
        btnNewChat: $('#btn-new-chat'),
        btnChatList: $('#btn-chat-list'),
        btnTheme: $('#btn-theme'),
        btnCloseSidebar: $('#btn-close-sidebar'),
        btnImage: $('#btn-image'),
        imageInput: $('#image-input'),
        imagePreview: $('#image-preview'),
        previewImg: $('#preview-img'),
        btnRemoveImage: $('#btn-remove-image'),
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
    var renderMarkdown = function (text) {
        return escapeHtml(text)
            .replace(/\*\*(.+?)\*\*/g, '<strong class="md-bold">$1</strong>')
            .replace(/\n/g, '<br>');
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
        line.innerHTML = renderMarkdown(text);
        scrollToBottom();
    }

    function addNarratorLine(text) {
        console.log('[narrator] rendering:', text.substring(0, 80));
        var line = document.createElement('div');
        line.className = 'text-line narrator-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        line.innerHTML = renderMarkdown(text);
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
        ts.innerHTML = renderMarkdown(text);
        line.appendChild(ts);
        scrollToBottom();
    }

    function addSystemLine(text) {
        var line = document.createElement('div');
        line.className = 'text-line system-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        line.innerHTML = renderMarkdown(text);
        scrollToBottom();
    }

    function addErrorLine(text) {
        var line = document.createElement('div');
        line.className = 'text-line error-line';
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        requestAnimationFrame(function () { line.classList.add('active'); });
        line.innerHTML = renderMarkdown(text);
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
    function getAuthHeader() {
        if (!token) return null;
        if (token.indexOf('dsn_ses_') === 0) return 'Session ' + token;
        if (token.indexOf('dsn_apk_') === 0) return null;  // API key uses separate header
        return 'Bearer ' + token;  // JWT or legacy
    }
    function apiCall(path, method, body) {
        var headers = { 'Content-Type': 'application/json' };
        var auth = getAuthHeader();
        if (auth) headers['Authorization'] = auth;
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
    function apiPost(path, body) {
        var headers = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = 'Bearer ' + token;
        console.log('[apiPost]', path, 'token=' + (token ? token.substring(0, 12) + '...' : 'null'));
        return fetch(API_BASE + path, { method: 'POST', headers: headers, body: JSON.stringify(body), credentials: 'include' });
    }
    function apiPostJson(path, body) {
        return apiPost(path, body).then(function (r) {
            if (r.status === 401) { logout(); throw new Error('login expired'); }
            return r.json().then(function (d) {
                if (!r.ok) throw new Error(d.error || 'request failed (' + r.status + ')');
                return d;
            });
        });
    }

    async function tryPairLogin() {
        var code = (dom.pairingCode.value || '').trim();
        var name = (dom.userName.value || '').trim();
        if (!code) { dom.loginStatus.textContent = '请输入配对码'; return; }
        if (!name) { dom.loginStatus.textContent = '请输入名字'; return; }
        dom.loginStatus.textContent = '配对中...';
        try {
            var resp = await apiPostJson('/api/auth/pairing/verify', { code: code, display_name: name, is_admin: true });
            token = resp.session_id;
            localStorage.setItem('dsn_session', token);
            if (resp.uid) localStorage.setItem('dsn_user_id', resp.uid);
            if (resp.display_name) localStorage.setItem('dsn_display_name', resp.display_name);
            if (resp.device_token) localStorage.setItem('dsn_device_token', resp.device_token);
            dom.loginOverlay.classList.add('hidden');
            await loadChats();
            updateStatusBar();
        } catch (e) {
            dom.loginStatus.textContent = e.message || '配对失败';
        }
    }

    async function tryRecoverLogin() {
        var displayName = (dom.recoverUserId.value || '').trim();
        if (!displayName) { dom.loginStatus.textContent = '请输入用户名'; return; }
        dom.loginStatus.textContent = '恢复中...';
        var deviceToken = localStorage.getItem('dsn_device_token') || '';
        console.log('[recover] attempting recovery for name=' + displayName + ' api_base=' + API_BASE + ' device_token=' + (deviceToken ? deviceToken.substring(0, 12) + '...' : 'null'));
        try {
            var resp = await apiPostJson('/api/auth/session/recover', { display_name: displayName, device_token: deviceToken });
            console.log('[recover] success:', resp);
            token = resp.session_id;
            localStorage.setItem('dsn_session', token);
            localStorage.setItem('dsn_user_id', resp.uid);
            dom.loginOverlay.classList.add('hidden');
            await loadChats();
            updateStatusBar();
        } catch (e) {
            console.error('[recover] FAILED:', e.message, e);
            dom.loginStatus.textContent = e.message || '恢复失败';
        }
    }

    function logout() {
        token = null; currentChatId = null; chats = [];
        localStorage.removeItem('jwt_token');
        localStorage.removeItem('dsn_session');
        localStorage.removeItem('dsn_user_id');
        // Keep dsn_device_token and dsn_display_name — needed for recovery after logout
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
                if (m.role === 'user') {
                    var content = m.content
                        .replace(/^\[.*?\]\s*/, '')
                        .replace(/^\[图片描述:[^\]]*\]\s*\n?/, '');
                    addLineStatic('>', content, 'active-group-top');
                } else if (m.role === 'assistant') {
                    var p = parseControlTags(m.content);
                    p.narrations.forEach(function (n) { addLineStatic('', n, 'narration-line'); });
                    addLineStatic(aiName, p.text, 'active-group-bottom');
                } else if (m.role === 'system') {
                    if (/^\[系统\]|^\[Agent|^\[工具结果/.test(m.content)) return;
                    addSystemLine(m.content);
                }
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

    // image upload
    function selectImage() {
        dom.imageInput.click();
    }

    function handleImageSelected(e) {
        var file = e.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function (ev) {
            currentImageData = ev.target.result;
            dom.previewImg.src = ev.target.result;
            dom.imagePreview.classList.remove('hidden');
            dom.btnImage.classList.add('has-image');
            dom.msgInput.focus();
        };
        reader.readAsDataURL(file);
    }

    function removeImage() {
        currentImageData = null;
        dom.previewImg.src = '';
        dom.imagePreview.classList.add('hidden');
        dom.btnImage.classList.remove('has-image');
        dom.imageInput.value = '';
        dom.msgInput.focus();
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

            var auth = getAuthHeader();
            var reqHeaders = { 'Content-Type': 'application/json' };
            if (auth) reqHeaders['Authorization'] = auth;
            console.log('[msgFlow] sending to', API_BASE + '/api/chat/stream_send', 'token=' + (token ? token.substring(0, 12) + '...' : 'null') + ' chat_id=' + currentChatId);
            var reqBody = { message: text, chat_id: currentChatId, chat_name: 'Psychoscope', tts_enabled: ttsEnabled };
            if (currentImageData) {
                reqBody.image_data = currentImageData;
                currentImageData = null;
                dom.previewImg.src = '';
                dom.imagePreview.classList.add('hidden');
                dom.btnImage.classList.remove('has-image');
                dom.imageInput.value = '';
            }
            var res = await fetch(API_BASE + '/api/chat/stream_send', {
                method: 'POST',
                headers: reqHeaders,
                body: JSON.stringify(reqBody),
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
                            case 'narrative_update':
                                if (ev.text) addNarratorLine(ev.text);
                                break;
                            case 'text_ready':
                                if (ttsEnabled) break;
                                if (ev.chat_id && !currentChatId) currentChatId = ev.chat_id;
                                if (ev.reply) await addMessage(aiName, ev.reply, true);
                                break;
                            case 'agent_action':
                                addNarrationLine(ACTION_LABELS[ev.desc] || ev.desc || 'executing action');
                                updateStatusBar();
                                break;
                            case 'text_update':
                                if (ev.reply) await addMessage(aiName, ev.reply, false);
                                break;
                            case 'line':
                                if (ev.text) {
                                    lineQueue.push(ev);
                                    processLineQueue();
                                }
                                break;
                            case 'completed':
                                if (ev.timing) {
                                    pendingTiming = ev.timing;
                                }
                                if (ev.audio && !ttsEnabled) audioB64 = ev.audio;
                                break;
                        }
                    } catch (_) {}
                }
            }

            // Wait for line queue and active typewriter to finish
            while (isProcessingLines || lineQueue.length > 0) {
                await wait(100);
            }
            while (activeTypewriter) {
                await wait(100);
            }
            if (pendingTiming) {
                showTimingLine(pendingTiming);
                pendingTiming = null;
            }

            if (currentChatId) { await loadChats(); renderChatList(); }
            updateStatusBar();

        } catch (e) {
            console.error('[msgFlow] ERROR:', e.name, e.message, e);
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

    function playAudioBase64Wait(b64) {
        return new Promise(function (resolve) {
            try {
                var raw = atob(b64);
                var bytes = new Uint8Array(raw.length);
                for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
                var url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
                var a = new Audio(url);
                a.onended = function () { URL.revokeObjectURL(url); resolve(); };
                a.onerror = function () { URL.revokeObjectURL(url); resolve(); };
                var played = a.play();
                if (played && played.catch) played.catch(function () { resolve(); });
            } catch (_) { resolve(); }
        });
    }

    function processLineQueue() {
        if (isProcessingLines || lineQueue.length === 0) return;
        isProcessingLines = true;
        (async function () {
            var isFirstLine = true;
            while (lineQueue.length > 0) {
                var line = lineQueue.shift();
                var audioPromise = line.audio_b64
                    ? playAudioBase64Wait(line.audio_b64)
                    : Promise.resolve();
                if (line.audio_b64) {
                    await addMessage(aiName, line.text, isFirstLine);
                    isFirstLine = false;
                    await audioPromise;
                } else {
                    await addMessage(aiName, line.text, isFirstLine);
                    isFirstLine = false;
                }
            }
            isProcessingLines = false;
            if (pendingTiming && lineQueue.length === 0) {
                showTimingLine(pendingTiming);
                pendingTiming = null;
            }
        })();
    }

    function showTimingLine(timing) {
        if (!timing) return;
        var parts = [];
        if (timing.model_invoke_ms) parts.push('MODEL ' + (timing.model_invoke_ms / 1000).toFixed(1) + 's');
        if (timing.post_process_ms) parts.push('AGENT ' + (timing.post_process_ms / 1000).toFixed(1) + 's');
        if (timing.tts_ms) parts.push('TTS ' + (timing.tts_ms / 1000).toFixed(1) + 's');
        parts.push('TOTAL ' + (timing.total_ms / 1000).toFixed(1) + 's');
        var line = document.createElement('div');
        line.className = 'text-line timing-line active';
        line.textContent = parts.join('  \u00b7  ');
        dom.textBox.insertBefore(line, dom.bottomAnchor);
        scrollToBottom();
    }

    // status bar
    function updateStatusBar() {
        var count = dom.textBox.querySelectorAll('.text-line').length;
        dom.statusBar.textContent = 'INDEX: ' + count;
    }

    // events
    dom.btnLogout.addEventListener('click', function () { if (confirm('logout?')) logout(); });
    dom.btnPair.addEventListener('click', tryPairLogin);
    dom.btnRecover.addEventListener('click', tryRecoverLogin);
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
    dom.btnImage.addEventListener('click', selectImage);
    dom.imageInput.addEventListener('change', handleImageSelected);
    dom.btnRemoveImage.addEventListener('click', removeImage);
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
        // Check server auth status
        try {
            var statusResp = await fetch(API_BASE + '/api/auth/status').then(function (r) { return r.json(); });
            if (statusResp.has_active_pairing) {
                dom.pairingSection.style.display = 'block';
                var fb = document.getElementById('recover-section-fallback');
                if (fb) fb.style.display = 'none';
            } else {
                dom.pairingSection.style.display = 'none';
                var fb = document.getElementById('recover-section-fallback');
                if (fb) fb.style.display = 'block';
            }
            dom.recoverSection.style.display = 'block';
        } catch (_) {}

        token = localStorage.getItem('jwt_token') || localStorage.getItem('dsn_session');
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
