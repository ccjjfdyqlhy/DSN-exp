// psychoscope/static/js/voice.js
// 感知模式（Sensing Mode）— 响度筛 + 自动录音 → 委托 sendRecording

var VoiceSensing = (function () {
    'use strict';

    var THRESHOLD = 0.02;
    var HOLD_MS = 800;
    var MAX_RECORD_SEC = 30;
    var POLL_INTERVAL = 80;

    var enabled = false;
    var muted = false;
    var sending = false;       // 正在发送，防止并发
    var sendStarted = 0;       // 上次发送开始时间
    var audioCtx = null;
    var mediaStream = null;
    var analyser = null;
    var mediaRecorder = null;
    var audioChunks = [];
    var recordStartTime = null;
    var pollTimer = null;
    var gate = null;

    // external refs (set by app.js)
    var _sendRecording = null;
    var _waveformCanvas = null;

    function LoudnessGate(threshold, holdMs) {
        this.threshold = threshold;
        this.holdMs = holdMs;
        this.speaking = false;
        this.silenceStart = null;
    }
    LoudnessGate.prototype.process = function (rms) {
        if (rms > this.threshold) {
            if (!this.speaking) {
                this.speaking = true;
                this.silenceStart = null;
                return 'voice_start';
            }
            this.silenceStart = null;
            return 'voice_continue';
        } else {
            if (this.speaking) {
                if (this.silenceStart === null) {
                    this.silenceStart = Date.now();
                    return 'voice_continue';
                } else if (Date.now() - this.silenceStart > this.holdMs) {
                    this.speaking = false;
                    this.silenceStart = null;
                    return 'voice_end';
                }
                return 'voice_continue';
            }
            return 'silence';
        }
    };
    LoudnessGate.prototype.reset = function () { this.speaking = false; this.silenceStart = null; };

    function calcRMS(data) {
        var sum = 0;
        for (var i = 0; i < data.length; i++) { var v = (data[i] - 128) / 128; sum += v * v; }
        return Math.sqrt(sum / data.length);
    }

    function drawWaveform(rms) {
        if (!_waveformCanvas) return;
        var ctx = _waveformCanvas.getContext('2d');
        var w = _waveformCanvas.width;
        var h = _waveformCanvas.height;
        ctx.fillStyle = 'rgba(10,10,20,0.35)';
        ctx.fillRect(0, 0, w, h);
        var barH = Math.min(rms * h * 6, h * 0.85);
        var midY = h / 2;
        var color = rms < THRESHOLD ? '#444' : '#4caf50';
        ctx.fillStyle = color;
        ctx.fillRect(0, midY - barH / 2, w, barH);
    }

    function startRecording() {
        if (!mediaStream) return;
        if (mediaRecorder && mediaRecorder.state === 'recording') return;
        audioChunks = [];
        recordStartTime = Date.now();
        try {
            mediaRecorder = new MediaRecorder(mediaStream, { mimeType: 'audio/webm; codecs=opus' });
        } catch (_) {
            mediaRecorder = new MediaRecorder(mediaStream);
        }
        mediaRecorder.ondataavailable = function (e) { if (e.data.size > 0) audioChunks.push(e.data); };
        mediaRecorder.start(200);
    }

    function stopAndSend() {
        if (!mediaRecorder || mediaRecorder.state === 'inactive') return;
        if (sending) return;
        var elapsed = Date.now() - sendStarted;
        if (sendStarted > 0 && elapsed < 5000) return;  // 发完后 5s 内不发下一段
        sending = true;
        sendStarted = Date.now();
        var chunks = audioChunks.slice();
        var startTime = recordStartTime;
        mediaRecorder.onstop = function () {
            if (muted || chunks.length === 0) { sending = false; return; }
            var blob = new Blob(chunks, { type: 'audio/webm' });
            var duration = (Date.now() - startTime) / 1000;
            if (_sendRecording) _sendRecording(blob, duration);
            setTimeout(function () { sending = false; }, 5000);
        };
        mediaRecorder.stop();
        mediaRecorder = null;
    }

    function poll() {
        if (!enabled || !analyser) return;
        try {
            var data = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteTimeDomainData(data);
        } catch (_) { return; }
        var rms = calcRMS(data);
        drawWaveform(rms);

        if (muted) return;
        var evt = gate.process(rms);
        if (evt === 'voice_start') startRecording();
        else if (evt === 'voice_end') stopAndSend();
    }

    // ── public API ──

    function init(opts) {
        opts = opts || {};
        THRESHOLD = opts.threshold || THRESHOLD;
        HOLD_MS = opts.holdMs || HOLD_MS;
        _sendRecording = opts.sendRecording || null;
        _waveformCanvas = opts.canvas || null;
        gate = new LoudnessGate(THRESHOLD, HOLD_MS);
    }

    function start() {
        if (enabled) return;
        enabled = true;
        gate.reset();
        if (typeof playbackQueue !== 'undefined' && playbackQueue && playbackQueue.resume) {
            playbackQueue.resume();
        }
        sending = false;

        navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
            mediaStream = stream;
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            var source = audioCtx.createMediaStreamSource(stream);
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            pollTimer = setInterval(poll, POLL_INTERVAL);
            updateStatus('空闲', '#888');
        }).catch(function (e) {
            updateStatus('麦克风不可用', '#f44336');
        });
    }

    function stop() {
        enabled = false;
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        if (mediaRecorder && mediaRecorder.state === 'recording') { mediaRecorder.stop(); mediaRecorder = null; }
        if (mediaStream) { mediaStream.getTracks().forEach(function (t) { t.stop(); }); mediaStream = null; }
        if (audioCtx) { try { audioCtx.close(); } catch (_) {} audioCtx = null; }
        analyser = null;
    }

    function setMuted(val) { muted = !!val; }
    function isMuted() { return muted; }
    function isEnabled() { return enabled; }
    function setThreshold(val) { THRESHOLD = parseFloat(val); if (gate) gate.threshold = THRESHOLD; }
    function setHoldMs(val) { HOLD_MS = parseInt(val); if (gate) gate.holdMs = HOLD_MS; }

    return {
        init: init, start: start, stop: stop,
        setMuted: setMuted, isMuted: isMuted, isEnabled: isEnabled,
        setThreshold: setThreshold, setHoldMs: setHoldMs,
    };
})();
