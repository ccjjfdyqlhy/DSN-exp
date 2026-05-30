// psychoscope/static/js/typewriter.js
// 打字机引擎 — 从 novel.html 提取并增强为独立模块

class TypeWriter {
    /**
     * @param {HTMLElement} element - 文本容器元素
     * @param {object} [options]
     * @param {number} [options.speed=30] - 基础打字速度 (ms/字符)
     * @param {number} [options.jitter=20] - 随机速度抖动范围
     * @param {number} [options.punctuationPause=400] - 标点符号额外停顿
     * @param {number} [options.newlinePause=200] - 换行额外停顿
     */
    constructor(element, options = {}) {
        this.element = element;
        this.speed = options.speed ?? 30;
        this.jitter = options.jitter ?? 20;
        this.punctuationPause = options.punctuationPause ?? 400;
        this.newlinePause = options.newlinePause ?? 200;

        this.isTyping = false;
        this._aborted = false;
        this._cursor = null;
        this._fullText = '';

        this._onChar = options.onChar || null;
        this._onComplete = options.onComplete || null;
    }

    /**
     * 逐字输出文本
     * @param {string} text
     * @returns {Promise<void>}
     */
    async type(text) {
        this.abort();
        this._fullText = text;
        this.isTyping = true;
        this._aborted = false;

        const cursor = document.createElement('span');
        cursor.className = 'typing-cursor';
        this.element.appendChild(cursor);
        this._cursor = cursor;

        const punctuation = new Set('，,。.!！?？…；;：:、"\'」』）)】]}>》');

        for (let i = 0; i < text.length; i++) {
            if (this._aborted) break;

            const char = text[i];
            cursor.before(document.createTextNode(char));

            let delay = this.speed + Math.random() * this.jitter;
            if (punctuation.has(char)) delay += this.punctuationPause;
            if (char === '\n') delay += this.newlinePause;

            if (this._onChar) {
                this._onChar(char, i, text.length);
            }

            await this._wait(delay);
        }

        this._removeCursor();
        this.isTyping = false;

        if (!this._aborted && this._onComplete) {
            this._onComplete(this._fullText);
        }
    }

    /**
     * 立即显示完整文本 (跳过打字动画)
     */
    finalize(text) {
        this.abort();
        this.element.textContent = text || this._fullText;
    }

    /**
     * 中止当前打字过程
     */
    abort() {
        this._aborted = true;
        this._removeCursor();
        this.isTyping = false;
    }

    _removeCursor() {
        if (this._cursor && this._cursor.parentNode) {
            this._cursor.remove();
        }
        this._cursor = null;
    }

    _wait(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// 导出到全局 (浏览器环境)
if (typeof window !== 'undefined') {
    window.TypeWriter = TypeWriter;
}

// 兼容 ES Module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TypeWriter;
}
