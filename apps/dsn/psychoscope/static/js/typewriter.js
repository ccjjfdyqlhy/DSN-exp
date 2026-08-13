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
     * 逐字输出文本，支持 **加粗** 标记。
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
        const segments = this._parseBold(text);

        for (const seg of segments) {
            if (this._aborted) break;

            if (seg.type === 'bold') {
                const strong = document.createElement('strong');
                strong.className = 'md-bold';
                cursor.before(strong);
                strong.appendChild(cursor);

                for (let i = 0; i < seg.content.length; i++) {
                    if (this._aborted) break;
                    const char = seg.content[i];
                    if (char === '\n') {
                        cursor.before(document.createElement('br'));
                    } else {
                        cursor.before(document.createTextNode(char));
                    }
                    let delay = this.speed + Math.random() * this.jitter;
                    if (punctuation.has(char)) delay += this.punctuationPause;
                    if (char === '\n') delay += this.newlinePause;
                    await this._wait(delay);
                }

                strong.parentElement.appendChild(cursor);
            } else {
                for (let i = 0; i < seg.content.length; i++) {
                    if (this._aborted) break;
                    const char = seg.content[i];
                    if (char === '\n') {
                        cursor.before(document.createElement('br'));
                    } else {
                        cursor.before(document.createTextNode(char));
                    }
                    let delay = this.speed + Math.random() * this.jitter;
                    if (punctuation.has(char)) delay += this.punctuationPause;
                    if (char === '\n') delay += this.newlinePause;
                    if (this._onChar) {
                        this._onChar(char, i, seg.content.length);
                    }
                    await this._wait(delay);
                }
            }
        }

        this._removeCursor();
        this.isTyping = false;

        if (!this._aborted && this._onComplete) {
            this._onComplete(this._fullText);
        }
    }

    /**
     * 将文本按 **...** 分割为普通文本段和加粗段。
     * @param {string} text
     * @returns {Array<{type:'text'|'bold', content:string}>}
     */
    _parseBold(text) {
        const segments = [];
        const re = /\*\*(.+?)\*\*/g;
        let lastIndex = 0;
        let match;
        while ((match = re.exec(text)) !== null) {
            if (match.index > lastIndex) {
                segments.push({ type: 'text', content: text.slice(lastIndex, match.index) });
            }
            segments.push({ type: 'bold', content: match[1] });
            lastIndex = match.index + match[0].length;
        }
        if (lastIndex < text.length) {
            segments.push({ type: 'text', content: text.slice(lastIndex) });
        }
        return segments.length ? segments : [{ type: 'text', content: text }];
    }

    /**
     * 立即显示完整文本 (跳过打字动画)
     */
    finalize(text) {
        this.abort();
        this.element.textContent = text || this._fullText;
        if (this._onComplete) {
            this._onComplete(this._fullText);
        }
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
