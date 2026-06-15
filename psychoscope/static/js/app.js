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
    var pendingUsage = null;
    var forceScrollToNew = false;
    // voice input
    var inputMode = 'text';
    var recordState = 'idle';
    var recordStartTime = 0;
    var mediaRecorder = null;
    var audioChunks = [];
    var audioStream = null;
    var mouseInsideRecord = true;
    var altDuringRecord = false;
    var spaceHeldForRecord = false;
    var waveformInterval = null;
    var audioCtx = null;
    var audioAnalyser = null;
    var tabHoldTimer = null;
    var tabHoldFired = false;
    var confirmTimer = null;
    var confirmActive = false;

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
        inputTextMode: $('#input-text-mode'),
        inputVoiceMode: $('#input-voice-mode'),
        btnRecord: $('#btn-record'),
        recordLabel: $('#record-label'),
        recordWaveform: $('#record-waveform'),
        btnModeSwitch: $('#btn-mode-switch'),
        modeSwitchIcon: $('#mode-switch-icon'),
        quickConfirm: $('#quick-confirm'),
        btnConfirm: $('#btn-confirm'),
        confirmProgressBar: $('#confirm-progress-bar'),
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

    // scroll — 使用 scroll 事件替代 IntersectionObserver
    var scrollToBottom = function () {
        if (forceScrollToNew || autoScroll) {
            dom.textBoxWrapper.scrollTop = dom.textBoxWrapper.scrollHeight;
        }
    };
    var backToBottom = function () {
        dom.textBoxWrapper.scrollTop = dom.textBoxWrapper.scrollHeight;
    };
    dom.textBoxWrapper.addEventListener('scroll', function () {
        var atBottom = dom.textBoxWrapper.scrollTop + dom.textBoxWrapper.clientHeight >= dom.textBoxWrapper.scrollHeight - 10;
        if (atBottom) {
            dom.textBoxWrapper.classList.remove('scrolling-up');
            dom.scrollBtn.style.display = 'none';
            autoScroll = true; isPaused = false;
        } else {
            dom.textBoxWrapper.classList.add('scrolling-up');
            dom.scrollBtn.style.display = 'flex';
            autoScroll = false; isPaused = true;
            forceScrollToNew = false;
        }
    });

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
            // AI 回复到达时，若用户消息打字机仍在运行，强制完成
            if (activeTypewriter && speaker !== '>') {
                activeTypewriter.finalize();
                activeTypewriter = null;
            }

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
                    p.narrations.forEach(function (n) { addNarratorLine(n); });
                    addLineStatic(aiName, p.text, 'active-group-bottom');
                } else if (m.role === 'system') {
                    if (/^\[Agent|^\[工具结果/.test(m.content)) return;
                    addSystemLine(m.content);
                }
            });
            var lines = dom.textBox.querySelectorAll('.text-line');
            lines.forEach(function (l) {
                if (l.classList.contains('narrator-line')) {
                    l.classList.add('active');
                    return;
                }
                l.classList.remove('active', 'active-group-top', 'active-group-bottom');
                l.classList.add('history');
            });
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    var wrapper = dom.textBoxWrapper;
                    var last = dom.textBox.querySelector('.text-line:last-of-type');
                    if (last) {
                        var top = last.offsetTop - wrapper.clientHeight / 2 + last.offsetHeight / 2;
                        wrapper.scrollTo({ top: Math.max(0, top), behavior: 'auto' });
                    }
                });
            });
        }).catch(function (e) { notify('load failed: ' + e.message, true); });
    }
    function newChat() {
        currentChatId = null;
        renderChatList();
        dom.sidebar.classList.add('hidden');
        dom.textBox.querySelectorAll('.text-line').forEach(function (e) { e.remove(); });
        if (inputMode === 'text') dom.msgInput.focus();
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
            if (inputMode === 'text') dom.msgInput.focus();
        };
        reader.readAsDataURL(file);
    }

    function removeImage() {
        currentImageData = null;
        dom.previewImg.src = '';
        dom.imagePreview.classList.add('hidden');
        dom.btnImage.classList.remove('has-image');
        dom.imageInput.value = '';
        if (inputMode === 'text') dom.msgInput.focus();
    }

    // ── Voice Input ──
    function switchInputMode(mode) {
        if (mode === inputMode) return;
        inputMode = mode;
        if (mode === 'voice') {
            dom.inputTextMode.classList.add('hidden');
            dom.inputVoiceMode.classList.remove('hidden');
            dom.btnModeSwitch.classList.add('active');
            dom.modeSwitchIcon.innerHTML = '<path d="M17 7h-4V3h-2v4H7v2h4v4h2V9h4V7z"/><path d="M20 11c0 3.53-2.61 6.43-6 6.92V21h-4v-3.08c-3.39-.49-6-3.39-6-6.92h2c0 2.76 2.24 5 5 5s5-2.24 5-5h2z"/>';
            dom.btnModeSwitch.title = '切换到文字输入模式';
        } else {
            dom.inputVoiceMode.classList.add('hidden');
            dom.inputTextMode.classList.remove('hidden');
            dom.btnModeSwitch.classList.remove('active');
            dom.modeSwitchIcon.innerHTML = '<path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/><path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>';
            dom.btnModeSwitch.title = '切换语音输入模式';
            dom.msgInput.focus();
        }
    }

    async function startRecording() {
        if (recordState !== 'idle' || isProcessing) return;
        try {
            audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunks = [];
            mediaRecorder = new MediaRecorder(audioStream, { mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm' });
            mediaRecorder.ondataavailable = function (e) { if (e.data.size > 0) audioChunks.push(e.data); };
            mediaRecorder.start(100);
            recordStartTime = Date.now();
            recordState = 'recording';
            mouseInsideRecord = true;
            altDuringRecord = false;
            dom.btnRecord.classList.add('recording');
            dom.btnRecord.classList.remove('cancelling');
            dom.inputVoiceMode.classList.add('recording');
            dom.inputVoiceMode.classList.remove('cancelling');
            dom.recordLabel.textContent = '松开 发送';
            startWaveform();
        } catch (e) {
            notify('麦克风不可用: ' + e.message, true);
        }
    }

    function stopRecording(send) {
        var duration = (Date.now() - recordStartTime) / 1000;
        stopWaveform();
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.onstop = function () {
                if (audioStream) { audioStream.getTracks().forEach(function (t) { t.stop(); }); audioStream = null; }
                if (send && duration >= 1.0) {
                    var blob = new Blob(audioChunks, { type: audioChunks[0] ? audioChunks[0].type : 'audio/webm' });
                    sendRecording(blob, duration);
                }
                mediaRecorder = null;
                audioChunks = [];
            };
            mediaRecorder.stop();
        }
        recordState = 'idle';
        dom.btnRecord.classList.remove('recording', 'cancelling');
        dom.inputVoiceMode.classList.remove('recording', 'cancelling');
        dom.recordLabel.textContent = '按住 说话';
    }

    function cancelRecording() {
        if (recordState !== 'recording') return;
        recordState = 'cancelling';
        dom.btnRecord.classList.add('cancelling');
        dom.btnRecord.classList.remove('recording');
        dom.inputVoiceMode.classList.add('cancelling');
        dom.inputVoiceMode.classList.remove('recording');
        dom.recordLabel.textContent = '松开 丢弃';
    }

    function uncancelRecording() {
        if (recordState !== 'cancelling') return;
        recordState = 'recording';
        dom.btnRecord.classList.remove('cancelling');
        dom.btnRecord.classList.add('recording');
        dom.inputVoiceMode.classList.remove('cancelling');
        dom.inputVoiceMode.classList.add('recording');
        dom.recordLabel.textContent = '松开 发送';
    }

    function startWaveform() {
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            var source = audioCtx.createMediaStreamSource(audioStream);
            audioAnalyser = audioCtx.createAnalyser();
            audioAnalyser.fftSize = 256;
            source.connect(audioAnalyser);
            var canvas = dom.recordWaveform;
            var ctx = canvas.getContext('2d');
            canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
            canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
            var bufferLength = audioAnalyser.frequencyBinCount;
            var dataArray = new Uint8Array(bufferLength);
            waveformInterval = setInterval(function () {
                if (!audioAnalyser) return;
                audioAnalyser.getByteFrequencyData(dataArray);
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                var barWidth = canvas.width / bufferLength;
                var isCancelling = recordState === 'cancelling';
                for (var i = 0; i < bufferLength; i++) {
                    var x = canvas.width - (i + 1) * barWidth;
                    var h = (dataArray[i] / 255) * canvas.height * 0.8;
                    var y = (canvas.height - h) / 2;
                    ctx.fillStyle = isCancelling
                        ? 'rgba(255,60,60,' + (0.4 + dataArray[i] / 510) + ')'
                        : 'rgba(255,255,255,' + (0.15 + dataArray[i] / 510) + ')';
                    ctx.fillRect(x, y, barWidth - 1, h);
                }
            }, 50);
        } catch (_) {}
    }

    function stopWaveform() {
        if (waveformInterval) { clearInterval(waveformInterval); waveformInterval = null; }
        if (audioCtx) { audioCtx.close().catch(function () {}); audioCtx = null; audioAnalyser = null; }
        var canvas = dom.recordWaveform;
        var ctx = canvas.getContext('2d');
        canvas.width = canvas.offsetWidth * (window.devicePixelRatio || 1);
        canvas.height = canvas.offsetHeight * (window.devicePixelRatio || 1);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    function blobToBase64(blob) {
        return new Promise(function (resolve) {
            var reader = new FileReader();
            reader.onloadend = function () {
                var b64 = reader.result.split(',')[1] || reader.result;
                resolve(b64);
            };
            reader.readAsDataURL(blob);
        });
    }

    async function sendRecording(audioBlob, durationSec) {
        var seconds = durationSec.toFixed(1);
        addSystemLine('录音 ' + seconds + 's');
        isProcessing = true;
        forceScrollToNew = true;
        dom.btnModeSwitch.classList.add('processing');
        streamAbort = new AbortController();
        try {
            var b64 = await blobToBase64(audioBlob);
            var auth = getAuthHeader();
            var reqHeaders = { 'Content-Type': 'application/json' };
            if (auth) reqHeaders['Authorization'] = auth;
            var reqBody = { audio_b64: b64, chat_id: currentChatId, chat_name: 'Psychoscope', tts_enabled: ttsEnabled };
            if (currentImageData) {
                reqBody.image_data = currentImageData;
                currentImageData = null;
                dom.previewImg.src = '';
                dom.imagePreview.classList.add('hidden');
                dom.btnImage.classList.remove('has-image');
                dom.imageInput.value = '';
            }
            updateStatusBar();
            var res = await fetch(API_BASE + '/api/asr/passthrough', {
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
                            case 'thinking':
                                if (ev.text) updateStatusBarText(ev.text);
                                break;
                            case 'text_ready':
                                console.log('[SSE:text_ready] reply:', (ev.reply || '').substring(0, 60));
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
                            case 'task_result':
                                break;
                            case 'confirm_requested':
                                showConfirm();
                                break;
                            case 'line':
                                if (ev.text) { lineQueue.push(ev); processLineQueue(); }
                                break;
                            case 'completed':
                                if (ev.timing) pendingTiming = ev.timing;
                                if (ev.usage) pendingUsage = ev.usage;
                                if (ev.audio && !ttsEnabled) audioB64 = ev.audio;
                                break;
                        }
                    } catch (_) {}
                }
            }
            while (isProcessingLines || lineQueue.length > 0) { await wait(100); }
            while (activeTypewriter) { await wait(100); }
            if (pendingTiming) { showTimingLine(pendingTiming, pendingUsage); pendingTiming = null; pendingUsage = null; }
            if (currentChatId) { await loadChats(); renderChatList(); }
            updateStatusBar();
        } catch (e) {
            console.error('[sendRecording] ERROR:', e.name, e.message, e);
            if (e.name !== 'AbortError') addErrorLine('ERROR: ' + e.message);
        } finally {
            isProcessing = false;
            activeTypewriter = null;
            streamAbort = null;
            forceScrollToNew = false;
            dom.btnModeSwitch.classList.remove('processing');
            if (inputMode === 'voice') {
                dom.recordLabel.textContent = '按住 说话';
            }
        }
    }
    var ACTION_LABELS = {
        shell: 'executing shell', python: 'executing python',
        write_file: 'writing file', edit_file: 'editing file',
    };

    async function msgFlow(text) {
        try {
            archiveActiveLines();
            forceScrollToNew = true;

            // 启动用户消息打字机（不等待），同时立即发送 API 请求
            var userMsgDone = false;
            var userMsgPromise = addMessage('>', text, true).then(function () {
                userMsgDone = true;
            }).catch(function () {});
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
                            case 'thinking':
                                if (ev.text) updateStatusBarText(ev.text);
                                break;
                            case 'text_ready':
                                console.log('[SSE:text_ready] reply:', (ev.reply || '').substring(0, 60));
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
                            case 'task_result':
                                break;
                            case 'confirm_requested':
                                showConfirm();
                                break;
                            case 'line':
                                if (ev.text) {
                                    lineQueue.push(ev);
                                    processLineQueue();
                                }
                                break;
                            case 'completed':
                                // wait for typewriter + line queue below
                                if (ev.timing) {
                                    pendingTiming = ev.timing;
                                }
                                if (ev.usage) pendingUsage = ev.usage;
                                if (ev.audio && !ttsEnabled) audioB64 = ev.audio;
                                if (ev.confirm_requested) showConfirm();
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
                showTimingLine(pendingTiming, pendingUsage);
                pendingTiming = null;
                pendingUsage = null;
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
            forceScrollToNew = false;
            dom.btnSend.textContent = '→';
            dom.btnSend.classList.remove('stop-mode');
            dom.msgInput.disabled = false;
            if (inputMode === 'text') dom.msgInput.focus();
        }
    }

    function sendMessage() {
        var text = dom.msgInput.value.trim();
        if (!text || isProcessing) return;
        hideConfirm();
        isProcessing = true;
        dom.btnSend.textContent = '■';
        dom.btnSend.classList.add('stop-mode');
        dom.msgInput.disabled = true;
        dom.msgInput.value = '';
        dom.msgInput.style.height = 'auto';
        streamAbort = new AbortController();
        msgFlow(text);
    }

    function abortStream() {
        if (streamAbort) { streamAbort.abort(); streamAbort = null; }
        if (activeTypewriter) { activeTypewriter.abort(); activeTypewriter = null; }
        isProcessing = false;
        forceScrollToNew = false;
        dom.btnSend.textContent = '→';
        dom.btnSend.classList.remove('stop-mode');
        dom.msgInput.disabled = false;
        dom.msgInput.style.height = 'auto';
        if (inputMode === 'text') dom.msgInput.focus();
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
                showTimingLine(pendingTiming, pendingUsage);
                pendingTiming = null;
                pendingUsage = null;
            }
        })();
    }

    function showTimingLine(timing, usage) {
        if (!timing) return;
        var parts = [];
        if (timing.model_invoke_ms) parts.push('MODEL ' + (timing.model_invoke_ms / 1000).toFixed(1) + 's');
        if (timing.post_process_ms) parts.push('AGENT ' + (timing.post_process_ms / 1000).toFixed(1) + 's');
        if (timing.tts_ms) parts.push('TTS ' + (timing.tts_ms / 1000).toFixed(1) + 's');
        parts.push('TOTAL ' + (timing.total_ms / 1000).toFixed(1) + 's');
        if (usage) {
            var tok = usage.total_tokens || 0;
            var pin = usage.prompt_tokens || 0;
            var pout = usage.completion_tokens || 0;
            if (tok > 0) parts.push('TOK ' + pin + '+' + pout + '=' + tok);
        }
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
    function updateStatusBarText(text) {
        dom.statusBar.textContent = text;
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
    dom.btnSend.addEventListener('click', function () {
        if (isProcessing) abortStream();
        else sendMessage();
    });
    dom.btnTTS.addEventListener('click', toggleTTS);
    dom.scrollBtn.addEventListener('click', backToBottom);
    dom.btnImage.addEventListener('click', selectImage);
    dom.imageInput.addEventListener('change', handleImageSelected);
    dom.btnRemoveImage.addEventListener('click', removeImage);
    // ── 语音输入绑定 ──
    dom.btnModeSwitch.addEventListener('click', function () {
        switchInputMode(inputMode === 'text' ? 'voice' : 'text');
    });
    dom.btnRecord.addEventListener('mousedown', function (e) {
        e.preventDefault();
        if (inputMode !== 'voice' || isProcessing) return;
        startRecording();
    });
    dom.btnRecord.addEventListener('mouseup', function () {
        if (mediaRecorder && recordState === 'recording') {
            stopRecording(true);
        } else if (mediaRecorder && recordState === 'cancelling') {
            stopRecording(false);
        }
    });
    dom.btnRecord.addEventListener('mouseleave', function () {
        mouseInsideRecord = false;
        if (mediaRecorder && recordState === 'recording') cancelRecording();
    });
    dom.btnRecord.addEventListener('mouseenter', function () {
        mouseInsideRecord = true;
        if (mediaRecorder && recordState === 'cancelling' && !altDuringRecord) uncancelRecording();
    });
    dom.btnRecord.addEventListener('touchstart', function (e) {
        e.preventDefault();
        if (inputMode !== 'voice' || isProcessing) return;
        startRecording();
    });
    dom.btnRecord.addEventListener('touchend', function () {
        if (mediaRecorder && recordState === 'recording') {
            stopRecording(true);
        } else if (mediaRecorder && recordState === 'cancelling') {
            stopRecording(false);
        }
    });
    // ── 键盘绑定 ──
    dom.msgInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            if (isProcessing) abortStream();
            else sendMessage();
        } else if (e.key === 'Escape' && isProcessing) {
            e.preventDefault(); abortStream();
        }
    });

    dom.msgInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 140) + 'px';
    });

    document.addEventListener('keydown', function (e) {
        // Enter: quick confirm
        if (e.key === 'Enter' && confirmActive && !e.ctrlKey && !e.metaKey && !isProcessing) {
            e.preventDefault();
            doConfirm();
            return;
        }
        // Ctrl: hold 2s switch mode
        if (e.key === 'Control' && !e.repeat && !tabHoldFired) {
            if (!tabHoldTimer) {
                tabHoldTimer = setTimeout(function () {
                    tabHoldFired = true;
                    tabHoldTimer = null;
                    switchInputMode(inputMode === 'text' ? 'voice' : 'text');
                }, 2000);
            }
            return;
        }
        // Space: voice recording
        if (e.key === ' ' && inputMode === 'voice' && recordState === 'idle' && !isProcessing && document.activeElement !== dom.msgInput) {
            e.preventDefault();
            spaceHeldForRecord = true;
            startRecording();
            return;
        }
        // Alt during recording = cancel
        if (e.key === 'Alt' && recordState === 'recording') {
            altDuringRecord = true;
            cancelRecording();
        }
        if (e.altKey && (e.key === 't' || e.key === 'T')) {
            e.preventDefault(); toggleTTS();
        }
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 'q' || e.key === 'Q') {
                e.preventDefault();
                if (confirm('确定退出登录？')) logout();
            }
        }
    });

    document.addEventListener('keyup', function (e) {
        // Ctrl: if released before 2s, do nothing
        if (e.key === 'Control') {
            if (tabHoldTimer && !tabHoldFired) {
                clearTimeout(tabHoldTimer);
                tabHoldTimer = null;
            }
            if (tabHoldFired) {
                e.preventDefault();
                tabHoldFired = false;
            }
            return;
        }
        // Space: stop recording
        if (e.key === ' ' && spaceHeldForRecord && (recordState === 'recording' || recordState === 'cancelling')) {
            e.preventDefault();
            spaceHeldForRecord = false;
            var shouldSend = recordState === 'recording';
            if (recordState === 'cancelling' && altDuringRecord) {
                shouldSend = false;
            }
            stopRecording(shouldSend);
            altDuringRecord = false;
            return;
        }
        // Alt released after cancelling - stay cancelled
        if (e.key === 'Alt' && recordState === 'cancelling' && altDuringRecord) {
            altDuringRecord = false;
        }
    });

    // ── SVG 键帽组件 ──
    function createKeyCapSVG(label) {
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '24');
        svg.setAttribute('height', '18');
        svg.setAttribute('viewBox', '0 0 24 18');
        svg.classList.add('key-cap-svg');
        svg.innerHTML =
            '<rect x="1" y="1" width="22" height="16" rx="3"/>' +
            '<text x="12" y="12" text-anchor="middle" font-size="9">' + label + '</text>';
        return svg;
    }

    // ── Alt 键位提示系统 ──
    var altHeld = false;
    var keyHintTips = [];

    function showKeyHints() {
        if (altHeld) return;
        altHeld = true;
        var elements = document.querySelectorAll('[data-key-hint]');
        elements.forEach(function (el) {
            var rect = el.getBoundingClientRect();
            var hintsText = el.getAttribute('data-key-hint');
            if (!hintsText) return;

            var tip = document.createElement('div');
            tip.className = 'key-hint-tip';
            tip.style.position = 'fixed';
            tip.style.left = rect.left + 'px';
            tip.style.top = rect.top - 24 < 0
                ? (rect.bottom + 4) + 'px'
                : (rect.top - 24) + 'px';

            var groups = hintsText.split('|');
            groups.forEach(function (group, gi) {
                var parts = group.split(':');
                var keysStr = parts[0];
                var label = parts[1] || '';

                var keyParts = keysStr.split('+');
                keyParts.forEach(function (kp, ki) {
                    tip.appendChild(createKeyCapSVG(kp.trim()));
                    if (ki < keyParts.length - 1) {
                        var plus = document.createElement('span');
                        plus.textContent = '+';
                        plus.style.cssText = 'font-size:8px;color:var(--text-dim);margin:0 1px;';
                        tip.appendChild(plus);
                    }
                });

                if (label) {
                    var lbl = document.createElement('span');
                    lbl.className = 'key-hint-label';
                    lbl.textContent = label;
                    tip.appendChild(lbl);
                }

                if (gi < groups.length - 1) {
                    var sep = document.createElement('span');
                    sep.textContent = ' ';
                    sep.style.width = '8px';
                    sep.style.display = 'inline-block';
                    tip.appendChild(sep);
                }
            });

            document.body.appendChild(tip);
            requestAnimationFrame(function () { tip.classList.add('visible'); });
            keyHintTips.push(tip);
        });
    }

    function hideKeyHints() {
        altHeld = false;
        var tips = keyHintTips.slice();
        keyHintTips = [];
        tips.forEach(function (tip) {
            tip.classList.remove('visible');
            setTimeout(function () { if (tip.parentNode) tip.remove(); }, 150);
        });
    }

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Alt' && !e.repeat) showKeyHints();
    });
    document.addEventListener('keyup', function (e) {
        if (e.key === 'Alt') hideKeyHints();
    });
    window.addEventListener('blur', function () {
        hideKeyHints();
        if (recordState === 'recording' || recordState === 'cancelling') {
            stopRecording(false);
            altDuringRecord = false;
            spaceHeldForRecord = false;
        }
        if (tabHoldTimer) { clearTimeout(tabHoldTimer); tabHoldTimer = null; tabHoldFired = false; }
    });
    document.addEventListener('click', function (e) {
        if (!dom.sidebar.classList.contains('hidden') && !dom.sidebar.contains(e.target) && e.target !== dom.btnChatList) {
            dom.sidebar.classList.add('hidden');
        }
    });

    // ── Quick Confirm ──
    var CONFIRM_TIMEOUT = 15000;

    function showConfirm() {
        if (confirmActive) return;
        confirmActive = true;
        dom.quickConfirm.classList.remove('hidden');
        dom.quickConfirm.classList.add('active');
        dom.inputArea.classList.add('has-confirm');
        dom.quickConfirm.classList.remove('active-hidden');

        // 进度条从满到空，15s
        var startTime = Date.now();
        dom.confirmProgressBar.style.width = '100%';
        dom.confirmProgressBar.style.transition = 'none';

        if (confirmTimer) clearInterval(confirmTimer);
        confirmTimer = setInterval(function () {
            var elapsed = Date.now() - startTime;
            var remaining = Math.max(0, CONFIRM_TIMEOUT - elapsed);
            var pct = (remaining / CONFIRM_TIMEOUT) * 100;
            dom.confirmProgressBar.style.transition = 'width 0.1s linear';
            dom.confirmProgressBar.style.width = pct + '%';

            if (remaining <= 0) {
                hideConfirm();
            }
        }, 100);
    }

    function hideConfirm() {
        if (confirmTimer) { clearInterval(confirmTimer); confirmTimer = null; }
        dom.confirmProgressBar.style.width = '0%';
        dom.quickConfirm.classList.remove('active');
        dom.quickConfirm.classList.add('active-hidden');
        dom.inputArea.classList.remove('has-confirm');

        setTimeout(function () {
            if (!confirmActive) {
                dom.quickConfirm.classList.add('hidden');
                dom.quickConfirm.classList.remove('active-hidden');
            }
        }, 350);

        confirmActive = false;
    }

    function doConfirm() {
        hideConfirm();
        dom.msgInput.value = '接受';
        sendMessage();
    }

    dom.btnConfirm.addEventListener('click', function (e) {
        e.preventDefault();
        if (!confirmActive) return;
        doConfirm();
    });

    // ── init
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
        if (inputMode === 'text') dom.msgInput.focus();
    }
    init();
})();
