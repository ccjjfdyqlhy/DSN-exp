let ws = null;
let messageId = 0;
let currentAssistantEl = null;
let isProcessing = false;
let mode = 'agent';
let commands = [];
let cmdSelectedIdx = -1;
let hasSentMessage = false;
let thinkingCollapsed = true;
let _thinkingTimer = null;
let isTempChat = false;
let _prevSessionState = null;
let _optionsOpen = false;

// ─── WebSocket ────────────────────────────────────────────────────

function connect() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onopen = () => {
    showToast('Connected');
    fetchStatus();
    fetchCommands();
    fetchOptions();
    fetchBackendSessions().then(() => updateSessionList());
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleMessage(data);
    } catch (e) {
      console.error('WebSocket message handler error:', e);
    }
  };

  ws.onclose = () => {
    showToast('Disconnected — reconnecting...');
    setTimeout(connect, 2000);
  };

  ws.onerror = () => ws.close();
}

function sendJson(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj));
  }
}

// ─── Message Handlers ─────────────────────────────────────────────

function handleMessage(data) {
  switch (data.type) {

    case 'thinking_start':
      showThinkingBar();
      if (!currentAssistantEl) {
        currentAssistantEl = createAssistantMessage();
      }
      // 生成过程中始终展开折叠框，让推理/工具调用过程实时可见
      ensureThinkingEl(false);
      setThinkingCollapsed(false);
      break;

    case 'thinking_text':
      if (currentAssistantEl) {
        updateThinkingBanner(data.content);
      }
      break;

    case 'thinking_status':
      updateThinkingBar(data.status || '');
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.thinking-banner-text');
        if (st && data.status) st.textContent = data.status;
      }
      break;

    case 'thinking_done':
      hideThinkingBar();
      isProcessing = false;
      if (currentAssistantEl) {
        const st = currentAssistantEl.querySelector('.thinking-banner-text');
        if (st && st.textContent) {
          const label = st.textContent.trim();
          const past = {
            'Thinking': 'Thought', 'Bashing': 'Bashed', 'Reading': 'Read',
            'Writing': 'Wrote', 'Editing': 'Edited', 'Globbing': 'Globbed',
            'Grepping': 'Grepped', 'Fetching': 'Fetched', 'Searching': 'Searched',
            'Tracing': 'Traced', 'Checking': 'Checked', 'Batching': 'Batched',
            'Listing': 'Listed', 'Diffing': 'Diffed', 'Analyzing': 'Analyzed',
            'Resolving': 'Resolved', 'Streaming': 'Streamed',
            'Preparing command': 'Command prepared', 'Preparing read': 'Read prepared',
            'Preparing write': 'Write prepared', 'Preparing edit': 'Edit prepared',
            'Preparing search': 'Search prepared', 'Preparing list': 'List prepared',
            'Preparing diff': 'Diff prepared', 'Preparing analysis': 'Analysis prepared',
            'Preparing fetch': 'Fetch prepared', 'Preparing trace': 'Trace prepared',
            'Preparing check': 'Check prepared',
          };
          st.textContent = past[label] || past[label.split(':')[0].trim()] || label;
        }
        // 生成结束后按用户偏好折叠/展开
        setThinkingCollapsed(thinkingCollapsed);
      }
      fetchBackendSessions().then(updateSessionList);
      break;

    case 'tool_calls':
      noteToolCallsInStatusBar(data.calls);
      if (!currentAssistantEl) {
        currentAssistantEl = createAssistantMessage();
      }
      for (const call of (data.calls || [])) {
        addThinkingToolItem(call);
      }
      for (const call of (data.calls || [])) {
        if (['file.write', 'file.edit', 'write_file', 'edit_file'].includes(call.name)) {
          previewEditCall(call);
        }
      }
      break;

    case 'tool_result':
      markThinkingToolResult(data.id, data.success);
      if (['file.write', 'file.edit', 'write_file', 'edit_file'].includes(data.name) && _lastEditPath) {
        loadDiffFileContent(_lastEditPath);
      }
      break;

    case 'tool_results':
      (data.results || []).forEach(r => markThinkingToolResult(r.id, true));
      break;

    case 'summary':
      appendSummary(data);
      break;

    case 'text':
      updateThinkingBar('Replying');
      appendAssistantText(data.content);
      break;

    case 'text_delta':
      updateThinkingBar('Replying');
      appendAssistantTextDelta(data.content);
      break;

    case 'reasoning_delta':
      updateThinkingBar('Thinking');
      appendReasoningDelta(data.content);
      break;

    case 'progress':
      updateProgressBar(data.elapsed, data.estimated);
      break;

    case 'todo':
      showTodoList(data.items, data.done);
      break;

    case 'sub_task_start':
      showSubTasks(data.tasks);
      break;

    case 'sub_task_result':
      updateSubTask(data.title, data.success, data.elapsed, data.tools);
      break;

    case 'command_output':
      // Command responses: not from AI, reset processing immediately
      appendCommandOutput(data.content);
      break;

    case 'error':
      hideThinkingBar();
      isProcessing = false;
      appendError(data.content);
      break;

    case 'mode_changed':
      mode = data.mode;
      {
        const mb = document.getElementById('modeBadge');
        if (mb) { mb.textContent = mode; mb.className = 'mode-badge ' + mode; }
      }
      {
        const hint = document.getElementById('inputHint');
        hint.textContent = mode === 'oneshot'
          ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
          : '';
      }
      showToast(`Mode: ${mode}`);
      updateModelBtnLabel();
      break;

    case 'model_switched':
      currentModel = data.model;
      {
        const mn = document.getElementById('modelName');
        if (mn) mn.textContent = data.display || data.model;
      }
      showToast(`Model: ${data.display || data.model}`);
      updateModelBtnLabel();
      break;

    case 'session_loaded':
      showToast(`Session loaded: ${data.count} msgs, mode=${data.mode}`);
      break;

    case 'session_id':
      if (data.session_id) {
        sessionId = data.session_id;
        fetchBackendSessions().then(updateSessionList);
      }
      break;

    case 'trace':
      recordTrace(data);
      break;

    case 'context_update':
      _contextSnapshot = data.context;
      if (data.context && data.context.session_id && sessionId !== data.context.session_id) {
        const oldId = sessionId;
        sessionId = data.context.session_id;
        try {
          const sessions = loadSessionList().filter(s => s.id !== oldId);
          localStorage.setItem(SESSION_LIST_KEY, JSON.stringify(sessions));
        } catch (e) {}
        fetchBackendSessions().then(updateSessionList);
      }
      if (document.getElementById('rightSidebarTitle').textContent === 'Context Structure') {
        renderContext();
      }
      break;

    case 'session_new':
      // 新建会话：回到欢迎页并刷新工作区路径
      if (data.path) setWelcomeProject(data.path);
      break;

    case 'workspace_opened':
      // 切换/打开工作区：同步欢迎页路径
      if (data.path) setWelcomeProject(data.path);
      break;
  }
}

function setWelcomeProject(path) {
  const projEl = document.getElementById('welcomeProject');
  if (projEl && path) {
    projEl.textContent = path;
    projEl.title = path;
  }
}

// ─── DOM ──────────────────────────────────────────────────────────

function $(sel) { return document.querySelector(sel); }

function messagesEl() { return document.getElementById('messages'); }

function welcomeEl() { return document.getElementById('welcome'); }

function scrollToBottom() {
  const el = messagesEl();
  el.scrollTop = el.scrollHeight;
  checkScrollPosition();
}

function checkScrollPosition() {
  const el = messagesEl();
  const inputArea = document.getElementById('inputArea');
  const hint = document.getElementById('scrollHint');
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  if (atBottom) {
    inputArea.classList.remove('scrolled-up');
    if (hint) hint.style.display = 'none';
  } else {
    inputArea.classList.add('scrolled-up');
    if (hint) hint.style.display = 'block';
  }
}

function scrollToTop() {
  messagesEl().scrollTop = 0;
  checkScrollPosition();
}

function createAssistantMessage() {
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.id = `msg-${++messageId}`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
  return div;
}

function hideWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = "none";
}

// ─── Execution Panel (replaces thinking bar) ─────────────────────

function showThinkingBar() {
  const panel = document.getElementById('executionPanel');
  panel.style.display = 'block';
  const bar = panel.querySelector('.ep-progress-fill');
  if (bar) bar.style.width = '0%';
  // 状态栏只负责"进度 + 一行当前步骤"，不承载推理内容和工具明细
  document.getElementById('execStatus').textContent = 'Thinking';
  document.getElementById('execElapsed').textContent = '';
  setSendButtonStop(true);
  _execStart = Date.now();
  startExecTicker();
}

function updateThinkingBar(text) {
  // 状态栏只显示一行当前步骤，压成单行并截断，避免变成滚动的推理流
  const el = document.getElementById('execStatus');
  if (!el) return;
  const line = String(text || '').replace(/\s+/g, ' ').trim();
  el.textContent = line.length > 90 ? line.slice(0, 90) + '…' : line;
}

function hideThinkingBar() {
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  stopExecTicker();
}

function stopGeneration() {
  sendJson({ type: 'stop' });
  hideThinkingBar();
}

function setSendButtonStop(isStop) {
  const btn = document.getElementById('sendBtn');
  if (isStop) {
    btn.classList.add('stop');
    btn.innerHTML = '&#x25A0;';
    btn.onclick = stopGeneration;
  } else {
    btn.classList.remove('stop');
    btn.innerHTML = '&#x27A4;';
    btn.onclick = sendMessage;
  }
}

// ─── Thinking Banner (in-message) ──────────────────────────────────

function ensureThinkingEl(collapsed) {
  if (!currentAssistantEl) return;
  let details = currentAssistantEl.querySelector('.thinking-details');
  if (!details) {
    details = document.createElement('div');
    details.className = 'thinking-details';
    const header = document.createElement('div');
    header.className = 'thinking-details-header';
    header.onclick = function() { toggleThinkingDetails(header); };
    header.innerHTML = `
      <span class="arrow">&#x25B6;</span>
      <span class="thinking-banner-text"></span>
    `;
    const body = document.createElement('div');
    body.className = 'thinking-details-body';
    details.appendChild(header);
    details.appendChild(body);
    currentAssistantEl.appendChild(details);
    if (collapsed) {
      body.style.display = 'none';
      header.classList.add('collapsed');
    } else {
      header.querySelector('.arrow').textContent = '\u25BC';
      body.style.display = 'block';
      header.classList.remove('collapsed');
    }
  }
}

function setThinkingCollapsed(collapsed) {
  if (!currentAssistantEl) return;
  const details = currentAssistantEl.querySelector('.thinking-details');
  if (!details) return;
  const body = details.querySelector('.thinking-details-body');
  const header = details.querySelector('.thinking-details-header');
  const arrow = header && header.querySelector('.arrow');
  if (collapsed) {
    if (body) body.style.display = 'none';
    if (header) header.classList.add('collapsed');
    if (arrow) arrow.textContent = '\u25B6';
  } else {
    if (body) body.style.display = 'block';
    if (header) header.classList.remove('collapsed');
    if (arrow) arrow.textContent = '\u25BC';
  }
}

function updateThinkingBanner(text) {
  if (!currentAssistantEl) return;
  ensureThinkingEl(thinkingCollapsed);
  const header = currentAssistantEl.querySelector('.thinking-details-header');
  const banner = currentAssistantEl.querySelector('.thinking-banner-text');
  if (!header || !banner) return;
  if (!header._texts) header._texts = [];
  header._texts.push(text);
  if (header._texts.length > 6) header._texts.shift();
  const clean = text.slice(0, 120).replace(/\n/g, ' ');
  if (!clean) return;
  banner.style.opacity = '1';
  banner.style.transform = 'translateY(0)';
  banner.textContent = clean;
  if (_thinkingTimer) clearTimeout(_thinkingTimer);
  _thinkingTimer = setTimeout(() => {
    banner.style.opacity = '0.6';
  }, 800);
}

function addThinkingToolItem(call) {
  if (!currentAssistantEl) return;
  ensureThinkingEl(false);
  setThinkingCollapsed(false);
  const body = currentAssistantEl.querySelector('.thinking-details-body');
  if (!body) return;
  let detail = '';
  try {
    const args = JSON.parse(call.args);
    if (call.name === 'read_file' || call.name === 'file.read') {
      const p = args.filePath || args.path || '';
      const o = args.offset; const l = args.limit;
      detail = o && l ? `${p}:${o}-${l}` : p;
    } else if (call.name === 'write_file' || call.name === 'edit_file'
               || call.name === 'file.write' || call.name === 'file.edit') {
      detail = args.filePath || args.path || args.target || '';
    } else if (call.name === 'bash' || call.name === 'proc.run') {
      detail = (args.command || '').split('\n')[0].slice(0, 60);
    } else if (call.name === 'glob') {
      detail = args.pattern || '';
    } else if (call.name === 'grep' || call.name === 'grep_context') {
      detail = '/' + (args.pattern || '') + '/';
    } else if (call.name === 'web_fetch' || call.name === 'web.fetch') {
      detail = args.url || '';
    } else if (call.name === 'symbol_search' || call.name === 'code.locate_symbol') {
      detail = args.query || args.name || '';
    } else if (call.name === 'callers' || call.name === 'read_symbol') {
      detail = args.symbol || args.name || '';
    } else if (call.name === 'list_dir' || call.name === 'file.list' || call.name === 'file.tree') {
      detail = args.path || '';
    } else if (call.name === 'py_check' || call.name === 'code.syntax_check') {
      detail = args.file_path || args.path || '';
    }
  } catch (e) {}
  const item = document.createElement('div');
  item.className = 'thinking-tool-item';
  item.setAttribute('data-call-id', call.id);
  item.textContent = call.name + (detail ? ': ' + detail : '');
  item.style.color = 'var(--text-dim)';
  body.appendChild(item);
  const banner = currentAssistantEl.querySelector('.thinking-banner-text');
  if (banner) banner.textContent = toolStatusLabel(call.name) + (detail ? ': ' + detail : '');
}

// 工具执行结果标记在思考栏对应条目上（成功/失败），状态栏不重复渲染。
function markThinkingToolResult(callId, success) {
  if (!currentAssistantEl || !callId) return;
  const item = currentAssistantEl.querySelector(
    `.thinking-tool-item[data-call-id="${callId}"]`);
  if (!item) return;
  item.style.color = success ? 'var(--green)' : 'var(--red)';
  if (!item.dataset.marked) {
    item.dataset.marked = '1';
    item.textContent = (success ? '\u2705 ' : '\u274C ') + item.textContent;
  }
}

function toolStatusLabel(name) {
  const m = {
    bash:'Running', read_file:'Reading', write_file:'Writing', edit_file:'Editing',
    glob:'Globbing', grep:'Grepping', grep_context:'Grepping', list_dir:'Listing',
    diff_file:'Diffing', ast_summary:'Analyzing', web_fetch:'Fetching',
    symbol_search:'Searching', callers:'Tracing', read_symbol:'Reading',
    py_check:'Checking', github:'GitHubbing', todowrite:'Updating todo',
    'proc.run':'Running', 'file.read':'Reading', 'file.write':'Writing',
    'file.edit':'Editing', 'file.list':'Listing', 'file.tree':'Tree',
    'text.diff':'Diffing', 'web.fetch':'Fetching', 'code.locate_symbol':'Searching',
    'code.syntax_check':'Checking', 'code.diagnose':'Diagnosing',
    'project.summary':'Analyzing', 'project.snapshot':'Snapshotting',
    'project.todo':'Updating todo', 'batch.run':'Batching'
  };
  return m[name] || 'Working';
}

function toggleThinkingDetails(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  if (body.style.display === 'none' || !body.style.display) {
    body.style.display = 'block';
    arrow.textContent = '\u25BC';
    header.classList.remove('collapsed');
    let reasonEl = body.querySelector('.thinking-reason');
    if (!reasonEl) {
      reasonEl = document.createElement('div');
      reasonEl.className = 'thinking-reason';
      body.insertBefore(reasonEl, body.firstChild);
    }
    if (header._texts) reasonEl.textContent = header._texts.join('\n');
  } else {
    body.style.display = 'none';
    arrow.textContent = '\u25B6';
    header.classList.add('collapsed');
  }
}

// ─── Execution Panel (live above input) ───────────────────────────

let _execStart = null;
let _execTicker = null;

// 工具明细只落在消息内的思考栏（thinking-details），状态栏不再重复渲染。
// 这里仅把"当前正在执行哪个工具"压成一行更新到状态栏。
function noteToolCallsInStatusBar(calls) {
  if (!calls || !calls.length) return;
  const last = calls[calls.length - 1];
  updateThinkingBar(toolStatusLabel(last.name) + ' · ' + last.name);
}

function startExecTicker() {
  stopExecTicker();
  _execTicker = setInterval(() => {
    if (_execStart) {
      const elapsed = (Date.now() - _execStart) / 1000;
      document.getElementById('execElapsed').textContent = elapsed.toFixed(1) + 's';
    }
  }, 200);
}

function stopExecTicker() {
  if (_execTicker) {
    clearInterval(_execTicker);
    _execTicker = null;
  }
}

// ─── Messages ─────────────────────────────────────────────────────

function appendUserMessage(text) {
  hideWelcome();
  const div = document.createElement('div');
  div.className = 'message message-user';
  div.id = `msg-${++messageId}`;
  div.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
}

function appendAssistantText(text) {
  hideWelcome();
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let contentEl = currentAssistantEl.querySelector('.message-content');
  if (!contentEl) {
    contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    currentAssistantEl.appendChild(contentEl);
  }
  contentEl.innerHTML = renderMarkdown(text);
  scrollToBottom();
  hasSentMessage = true;
  saveSessionToList();
}

function appendAssistantTextDelta(text) {
  hideWelcome();
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let contentEl = currentAssistantEl.querySelector('.message-content');
  if (!contentEl) {
    contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    currentAssistantEl.appendChild(contentEl);
  }
  let rawEl = currentAssistantEl.querySelector('.message-raw');
  if (!rawEl) {
    rawEl = document.createElement('div');
    rawEl.className = 'message-raw';
    rawEl.style.display = 'none';
    currentAssistantEl.appendChild(rawEl);
  }
  rawEl.textContent += text;
  contentEl.innerHTML = renderMarkdown(rawEl.textContent);
  scrollToBottom();
}

function appendReasoningDelta(text) {
  hideWelcome();
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let thinkingEl = currentAssistantEl.querySelector('.thinking-details');
  if (!thinkingEl) {
    thinkingEl = document.createElement('div');
    thinkingEl.className = 'thinking-details';
    const header = document.createElement('div');
    header.className = 'thinking-details-header';
    header.onclick = function() { toggleThinkingDetails(header); };
    header.innerHTML = '<span class="arrow">&#x25B6;</span><span class="status-text">Thought</span>';
    const body = document.createElement('div');
    body.className = 'thinking-details-body';
    body.style.display = 'none';
    thinkingEl.appendChild(header);
    thinkingEl.appendChild(body);
    currentAssistantEl.appendChild(thinkingEl);
  }
  const body = thinkingEl.querySelector('.thinking-details-body');
  let reasonEl = body.querySelector('.reasoning-content');
  if (!reasonEl) {
    reasonEl = document.createElement('div');
    reasonEl.className = 'reasoning-content';
    reasonEl.style.color = 'var(--text-dim)';
    reasonEl.style.fontStyle = 'italic';
    reasonEl.style.whiteSpace = 'pre-wrap';
    body.appendChild(reasonEl);
  }
  reasonEl.textContent += text;
  body.style.display = 'block';
  const arrow = thinkingEl.querySelector('.arrow');
  if (arrow) arrow.textContent = '\u25BC';
  const header = thinkingEl.querySelector('.thinking-details-header');
  if (header) header.classList.remove('collapsed');

  // 状态栏只更新一行文字，推理正文仅在思考栏里显示
  // 状态栏只显示一行：思考阶段固定为 Thinking
  const status = document.getElementById('execStatus');
  if (status) status.textContent = 'Thinking';
  scrollToBottom();
}

function updateProgressBar(elapsed) {
  const fill = document.querySelector('.ep-progress-fill');
  const label = document.getElementById('execElapsed');
  if (label) {
    const est = arguments.length > 1 && arguments[1] ? arguments[1] : 60;
    const remaining = Math.max(0, est - elapsed);
    label.textContent = elapsed + 's / ' + est + 's';
  }
  if (fill) {
    const est = arguments.length > 1 && arguments[1] ? arguments[1] : 60;
    const pct = Math.min(Math.floor(elapsed / est * 100), 95);
    fill.style.width = pct + '%';
  }
}

// ─── Options ───────────────────────────────────────────────────────

let _optionsCache = { thinking_collapsed_default: true };

async function fetchOptions() {
  try {
    const r = await fetch('/api/options');
    _optionsCache = await r.json();
    thinkingCollapsed = _optionsCache.thinking_collapsed_default;
  } catch (e) {}
}

async function saveOption(key, value) {
  _optionsCache[key] = value;
  if (key === 'thinking_collapsed_default') thinkingCollapsed = value;
  try {
    await fetch('/api/options', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value })
    });
  } catch (e) {}
}

function toggleOptions() {
  const panel = document.getElementById('settingsPanel');
  const chat = document.getElementById('chatArea');
  const inputArea = document.getElementById('inputArea');
  _optionsOpen = !_optionsOpen;
  if (_optionsOpen) {
    chat.style.display = 'none';
    inputArea.style.display = 'none';
    panel.style.display = 'block';
    renderSettings();
  } else {
    chat.style.display = '';
    inputArea.style.display = '';
    panel.style.display = 'none';
  }
}

function renderSettings() {
  const content = document.getElementById('settingsContent');
  content.innerHTML = `
    <div class="setting-row">
      <label for="optCollapse">Thinking details collapsed by default</label>
      <input type="checkbox" id="optCollapse"
        ${_optionsCache.thinking_collapsed_default ? 'checked' : ''}
        onchange="saveOption('thinking_collapsed_default', this.checked)">
    </div>
  `;
}

// ─── Temp Chat ─────────────────────────────────────────────────────

function toggleTempChat() {
  const main = document.getElementById('main');
  const sidebar = document.getElementById('sidebar');
  const btn = document.getElementById('tempChatBtn');
  const welcome = document.getElementById('welcome');
  const welcomeText = document.getElementById('welcomeText');
  const inputArea = document.getElementById('inputArea');

  isTempChat = !isTempChat;

  if (isTempChat) {
    _prevSessionState = {
      messagesHtml: document.getElementById('messages').innerHTML,
      welcomeDisplay: welcome.style.display,
      welcomeTextContent: welcomeText.textContent,
    };
    btn.classList.add('active');
    main.classList.add('temp-mode');
    if (!sidebar.classList.contains('collapsed')) {
      toggleSidebar();
    }
    welcome.style.display = 'flex';
    welcomeText.textContent = 'Chat without memory and history.';
    document.getElementById('messages').innerHTML = '';
    hasSentMessage = false;
    currentAssistantEl = null;
    inputArea.classList.add('welcome-input');
    document.getElementById('executionPanel').style.display = 'none';
    sendJson({ type: 'temp_session' });
  } else {
    btn.classList.remove('active');
    main.classList.remove('temp-mode');
    if (sidebar.classList.contains('collapsed')) {
      toggleSidebar();
    }
    if (_prevSessionState) {
      document.getElementById('messages').innerHTML = _prevSessionState.messagesHtml;
      welcome.style.display = _prevSessionState.welcomeDisplay;
      welcomeText.textContent = _prevSessionState.welcomeTextContent;
    }
    hasSentMessage = false;
    currentAssistantEl = null;
    inputArea.classList.remove('welcome-input');
    if (!_prevSessionState || _prevSessionState.messagesHtml) {
      hideWelcome();
    } else {
      inputArea.classList.add('welcome-input');
    }
    sendJson({ type: 'restore_session' });
  }
}

function showTodoList(items, done) {
  let todoEl = document.getElementById('todo-panel');
  if (!todoEl) {
    todoEl = document.createElement('div');
    todoEl.id = 'todo-panel';
    todoEl.className = 'todo-panel';
    const msgs = messagesEl();
    msgs.insertBefore(todoEl, msgs.firstChild);
  }
  let html = '<div class="todo-header">Task Plan</div>';
  items.forEach(item => {
    const icon = item.status === 'completed' ? '✓' : item.status === 'in_progress' ? '⏳' : ' ';
    let cls = item.status === 'completed' ? 'done' : item.status === 'in_progress' ? 'active' : '';
    html += `<div class="todo-item ${cls}"><span class="todo-icon">[${icon}]</span> ${escapeHtml(item.content)}</div>`;
  });
  todoEl.innerHTML = html;
  if (done) {
    setTimeout(() => {
      const panel = document.getElementById('todo-panel');
      if (panel) panel.style.opacity = '0.5';
    }, 1000);
  }
}

function showSubTasks(tasks) {
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let body = currentAssistantEl.querySelector('.thinking-details-body');
  if (!body) {
    ensureThinkingEl(true);
    toggleThinkingDetails(currentAssistantEl.querySelector('.thinking-details-header'));
    body = currentAssistantEl.querySelector('.thinking-details-body');
  }
  if (!body) return;
  let container = body.querySelector('.sub-tasks');
  if (!container) {
    container = document.createElement('div');
    container.className = 'sub-tasks';
    body.appendChild(container);
  }
  tasks.forEach(t => {
    const item = document.createElement('div');
    item.className = 'sub-task-item';
    item.setAttribute('data-sub-title', t.title);
    item.innerHTML = `<span class="sub-task-icon">⏳</span> ${escapeHtml(t.title)}`;
    container.appendChild(item);
  });
}

function updateSubTask(title, success, elapsed, tools) {
  if (!currentAssistantEl) return;
  const item = currentAssistantEl.querySelector(`.sub-task-item[data-sub-title="${title}"]`);
  if (!item) return;
  const icon = item.querySelector('.sub-task-icon');
  if (icon) icon.textContent = success ? '✓' : '✗';
  item.style.color = success ? 'var(--green)' : 'var(--red)';
  item.innerHTML = `<span class="sub-task-icon">${success ? '✓' : '✗'}</span> ${escapeHtml(title)} <span style="font-size:10px;color:var(--text-muted)">${elapsed}s · ${tools} tools</span>`;
}

function appendCommandOutput(text) {
  hideWelcome();
  currentAssistantEl = null;
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.id = `msg-${++messageId}`;
  div.innerHTML = `<div class="message-header" style="color:var(--text-dim)">System</div>
    <div class="message-content">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  isProcessing = false;
}

function appendSummary(data) {
  if (!currentAssistantEl) {
    currentAssistantEl = createAssistantMessage();
  }
  let summaryEl = currentAssistantEl.querySelector('.summary-bar');
  if (!summaryEl) {
    summaryEl = document.createElement('div');
    summaryEl.className = 'summary-bar';
    currentAssistantEl.appendChild(summaryEl);
  }
  const fmt = (n) => {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
  };
  let balanceHtml = '';
  const bal = window._balance;
  if (bal && bal.balanceUsd !== undefined) {
    balanceHtml = `<span title="Balance">$${bal.balanceUsd.toFixed(2)}</span>`;
  }
  if (data.usage_supported === false) {
    summaryEl.innerHTML = `
      <span title="Usage not available">Usage not supported</span>
      <span title="Elapsed">${data.elapsed}s</span>
      ${balanceHtml}
    `;
  } else {
    summaryEl.innerHTML = `
      <span title="Input tokens">↑ ${fmt(data.input_tokens)} in</span>
      <span title="Output tokens">↓ ${fmt(data.output_tokens)} out</span>
      <span title="Cache hit">cache ${fmt(data.cache_hit)}/${data.cache_pct}%</span>
      <span title="Cost">¥${data.cost}</span>
      <span title="Context usage">ctx ${data.ctx_pct}%</span>
      <span title="Output usage">out ${data.out_pct}%</span>
      <span title="Elapsed">${data.elapsed}s</span>
      ${balanceHtml}
    `;
  }
  // Fetch balance in background
  fetch('/api/balance').then(r => r.json()).then(b => { window._balance = b; }).catch(() => {});
}

function appendError(text) {
  hideWelcome();
  const div = document.createElement('div');
  div.className = 'message message-assistant';
  div.innerHTML = `<div class="message-header" style="color:var(--red)">Error</div>
    <div class="message-content" style="color:var(--red)">${escapeHtml(text)}</div>`;
  messagesEl().appendChild(div);
  scrollToBottom();
  saveChatToStorage();
}

// ─── Input ────────────────────────────────────────────────────────

const input = document.getElementById('input');

input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 240) + 'px';
  handleCommandAutocomplete();
});

input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
  if ((e.key === 'End' || (e.ctrlKey && e.key === 'e')) && !input.value.trim()) {
    e.preventDefault();
    scrollToBottom();
  }
  if ((e.key === 'Home' || (e.ctrlKey && e.key === 'h')) && !input.value.trim()) {
    e.preventDefault();
    scrollToTop();
  }
  if (e.key === 'Escape') {
    hideCmdPanel();
  }
  if (e.key === 'Tab') {
    const panel = document.getElementById('cmdPanel');
    if (panel.style.display !== 'none' && cmdSelectedIdx >= 0) {
      e.preventDefault();
      selectCommand(cmdSelectedIdx);
    }
  }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const panel = document.getElementById('cmdPanel');
    if (panel.style.display !== 'none') {
      e.preventDefault();
      const items = panel.querySelectorAll('.cmd-item');
      if (e.key === 'ArrowDown') {
        cmdSelectedIdx = Math.min(cmdSelectedIdx + 1, items.length - 1);
      } else {
        cmdSelectedIdx = Math.max(cmdSelectedIdx - 1, 0);
      }
      items.forEach((el, i) => el.classList.toggle('selected', i === cmdSelectedIdx));
    }
  }
});

function sendMessage() {
  if (isProcessing) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    showToast('连接已断开，正在重连…', 'error');
    return;
  }
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  hideCmdPanel();

  const inputArea = document.getElementById('inputArea');
  if (inputArea.classList.contains('welcome-input')) {
    inputArea.classList.remove('welcome-input');
    document.getElementById('welcome').style.display = 'none';
  }

  if (_optionsOpen) {
    document.getElementById('settingsPanel').style.display = 'none';
    document.getElementById('chatArea').style.display = '';
    document.getElementById('inputArea').style.display = '';
    _optionsOpen = false;
  }

  appendUserMessage(text);
  currentAssistantEl = null;
  hasSentMessage = true;
  isProcessing = true;
  sendJson({ type: 'message', content: text });
}

// ─── Command Autocomplete ─────────────────────────────────────────

function handleCommandAutocomplete() {
  const text = input.value;
  const cursorPos = input.selectionStart;
  const beforeCursor = text.slice(0, cursorPos);
  const lineStart = beforeCursor.lastIndexOf('\n') + 1;
  const fromLineStart = beforeCursor.slice(lineStart);

  if (fromLineStart === '/') {
    showAllCommands();
    cmdSelectedIdx = 0;
  } else if (fromLineStart.startsWith('/')) {
    const partial = fromLineStart.slice(1).toLowerCase();
    showFilteredCommands(partial);
    cmdSelectedIdx = 0;
  } else {
    hideCmdPanel();
  }
}

function showAllCommands() {
  const panel = document.getElementById('cmdPanel');
  panel.innerHTML = commands.map((c, i) =>
    `<div class="cmd-item ${i === 0 ? 'selected' : ''}" onclick="selectCommandByCmd('${c.cmd}')">
      <span class="cmd-key">${escapeHtml(c.cmd)}</span>
      <span class="cmd-desc">${escapeHtml(c.desc)}</span>
    </div>`
  ).join('');
  panel.style.display = 'block';
}

function showFilteredCommands(partial) {
  const filtered = commands.filter(c =>
    c.cmd.slice(1).toLowerCase().includes(partial) ||
    c.desc.toLowerCase().includes(partial)
  );
  const panel = document.getElementById('cmdPanel');
  if (filtered.length === 0) {
    panel.style.display = 'none';
    return;
  }
  panel.innerHTML = filtered.map((c, i) =>
    `<div class="cmd-item ${i === 0 ? 'selected' : ''}" onclick="selectCommandByCmd('${c.cmd}')">
      <span class="cmd-key">${escapeHtml(c.cmd)}</span>
      <span class="cmd-desc">${escapeHtml(c.desc)}</span>
    </div>`
  ).join('');
  panel.style.display = 'block';
}

function selectCommand(idx) {
  const panel = document.getElementById('cmdPanel');
  const items = panel.querySelectorAll('.cmd-item');
  if (items[idx]) {
    const cmd = items[idx].querySelector('.cmd-key').textContent;
    insertCommand(cmd);
  }
}

function selectCommandByCmd(cmd) {
  insertCommand(cmd);
}

function insertCommand(cmd) {
  const text = input.value;
  const cursorPos = input.selectionStart;
  const beforeCursor = text.slice(0, cursorPos);
  const lineStart = beforeCursor.lastIndexOf('\n') + 1;
  const beforeLine = text.slice(0, lineStart);
  const afterCursor = text.slice(cursorPos);

  input.value = beforeLine + cmd + ' ' + afterCursor;
  const newPos = beforeLine.length + cmd.length + 1;
  input.setSelectionRange(newPos, newPos);
  hideCmdPanel();
  input.focus();
}

function hideCmdPanel() {
  document.getElementById('cmdPanel').style.display = 'none';
  cmdSelectedIdx = -1;
}

// ─── Commands ─────────────────────────────────────────────────────

async function fetchCommands() {
  try {
    const resp = await fetch('/api/commands');
    commands = await resp.json();
  } catch (e) {
    commands = [
      { cmd: '/mode', desc: 'Toggle agent/oneshot mode' },
      { cmd: '/help', desc: 'Show available commands' },
      { cmd: '/clear', desc: 'Clear conversation' },
      { cmd: '/stats', desc: 'Show context stats' },
      { cmd: '/cost', desc: 'Show session token cost' },
    ];
  }
}

function toggleMode() {
  const newMode = mode === 'agent' ? 'oneshot' : 'agent';
  sendJson({ type: 'mode', mode: newMode });
  const hint = document.getElementById('inputHint');
  hint.textContent = newMode === 'oneshot'
    ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
    : '';
}

function clearChat() {
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  const inputArea = document.getElementById('inputArea');
  inputArea.classList.remove('scrolled-up');
  showWelcome();
  scrollToBottom();
  sendJson({ type: 'message', content: '/clear' });
}

function newSession() {
  saveCurrentBeforeNew();
  sessionId = _genId();
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  isProcessing = false;
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'flex';
  const inputArea = document.getElementById('inputArea');
  inputArea.classList.remove('scrolled-up');
  inputArea.classList.add('welcome-input');
  input.focus();
  scrollToBottom();
  updateSessionList();
}

let sessionId = 'sess_' + Date.now();
const SESSION_LIST_KEY = 'dekacode_sessions';

function _genId() { return 'sess_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6); }

function saveSessionToList() {
  const preview = getChatPreview();
  if (!preview || preview === 'Empty conversation') return;
  let sessions = loadSessionList();
  const ts = Date.now();
  const existing = sessions.findIndex(s => s.id === sessionId);
  if (existing >= 0) {
    sessions[existing] = { id: sessionId, preview, ts, html: messagesEl().innerHTML };
  } else {
    sessions.push({ id: sessionId, preview, ts, html: messagesEl().innerHTML });
  }
  sessions = sessions.slice(-20);
  try {
    localStorage.setItem(SESSION_LIST_KEY, JSON.stringify(sessions));
  } catch (e) { /* ignore */ }
  updateSessionList();
}

function loadSessionList() {
  try {
    const raw = localStorage.getItem(SESSION_LIST_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveCurrentBeforeNew() {
  // 会话只持久化到 ~/.dekacode，不再写 localStorage。
}

function optionsMenu() {
  const menu = document.getElementById('optionsMenu');
  menu.classList.toggle('open');
}

document.addEventListener('click', (e) => {
  const menu = document.getElementById('optionsMenu');
  const btn = document.querySelector('.action-btn');
  if (menu && menu.classList.contains('open') && !menu.contains(e.target) && !btn.contains(e.target)) {
    menu.classList.remove('open');
  }
});

// ─── localStorage Persistence ─────────────────────────────────────

const STORAGE_KEY = 'dekacode_chat';

function saveChatToStorage() {
  const html = messagesEl().innerHTML;
  try {
    localStorage.setItem(STORAGE_KEY, html);
  } catch (e) { /* quota exceeded */ }
}

function restoreChatFromStorage() {
  const sessions = loadSessionList();
  if (sessions.length > 0) {
    const last = sessions[sessions.length - 1];
    if (last && last.html) {
      sessionId = last.id;
      messagesEl().innerHTML = last.html;
      document.querySelectorAll('.thinking-details').forEach(d => {
        const st = d.querySelector('.thinking-banner-text');
        if (st) {
          const count = d.querySelectorAll('.thinking-tool-item').length;
          st.textContent = count > 0 ? `${count} tools completed` : '';
        }
      });
      hasSentMessage = true;
      hideWelcome();
    } else {
      showWelcome();
    }
  } else {
    showWelcome();
  }
  updateSessionList();
  scrollToBottom();
}

// ─── Welcome / dekacode.png ────────────────────────────────────────

function showWelcome() {
  const w = welcomeEl();
  if (w) w.style.display = "";
}

// ─── Session List ─────────────────────────────────────────────────

let _backendSessions = [];

async function fetchBackendSessions() {
  try {
    const r = await fetch('/api/sessions');
    _backendSessions = await r.json();
  } catch (e) {
    _backendSessions = [];
  }
}

function updateSessionList() {
  const list = document.getElementById('sessionList');
  if (!list) return;
  const backend = _backendSessions || [];
  if (backend.length === 0) {
    list.innerHTML = '<div class="session-empty">No sessions yet</div>';
    return;
  }
  let html = '<div class="session-group">All Sessions (TUI + Web)</div>';
  html += backend.map(s => {
    const preview = s.summary || s.id;
    const ts = new Date(s.updated_at).getTime();
    return `<div class="session-item" onclick="loadBackendSession('${s.id}')">
      <div class="session-preview">${escapeHtml(preview)}</div>
      <div class="session-time">${formatTime(ts)} · ${s.message_count} msgs · ¥${s.total_cost.toFixed(4)}</div>
    </div>`;
  }).join('');
  list.innerHTML = html;
}

// 历史会话渲染：把 assistant 的 tool_calls 渲染成与流式一致的 thinking-details 折叠框
let _lastHistoricalThinkingBody = null;

function renderHistoricalAssistant(m) {
  if (m.content) appendAssistantText(m.content);
  if (m.tool_calls && m.tool_calls.length) {
    if (!currentAssistantEl) currentAssistantEl = createAssistantMessage();
    ensureThinkingEl(true);
    setThinkingCollapsed(true);
    const body = currentAssistantEl.querySelector('.thinking-details-body');
    _lastHistoricalThinkingBody = body;
    for (const tc of m.tool_calls) {
      const name = tc.name || (tc.function && tc.function.name) || '';
      const argsRaw = tc.args || (tc.function && tc.function.arguments) || '';
      let detail = '';
      try {
        const args = JSON.parse(argsRaw || '{}');
        if (args.path) detail = args.path;
        else if (args.pattern) detail = args.pattern;
        else if (args.command) detail = String(args.command).split('\n')[0].slice(0, 60);
        else if (args.url) detail = args.url;
      } catch (e) {}
      const div = document.createElement('div');
      div.className = 'thinking-tool-item';
      div.style.color = 'var(--text-dim)';
      div.textContent = `▸ ${name}${detail ? ': ' + detail : ''}`;
      body.appendChild(div);
    }
    const banner = currentAssistantEl.querySelector('.thinking-banner-text');
    if (banner) banner.textContent = `${m.tool_calls.length} tools`;
  }
}

function renderHistoricalToolResult(m) {
  const body = _lastHistoricalThinkingBody;
  const div = document.createElement('div');
  div.className = 'thinking-tool-item';
  div.style.color = 'var(--text-muted)';
  div.textContent = `  [tool] ${m.name || ''}`;
  if (body) body.appendChild(div);
  else {
    messagesEl().appendChild(div);
  }
}

async function loadBackendSession(sid) {
  try {
    const r = await fetch(`/api/sessions/${sid}/messages`);
    const msgs = await r.json();
    if (!msgs || msgs.length === 0) {
      showToast('Empty session');
      return;
    }
    // 渲染到聊天区
    const inputArea = document.getElementById('inputArea');
    inputArea.classList.remove('welcome-input');
    inputArea.classList.remove('scrolled-up');
    messagesEl().innerHTML = '';
    currentAssistantEl = null;
    _lastHistoricalThinkingBody = null;
    messageId = 0;
    for (const m of msgs) {
      if (m.role === 'user') {
        appendUserMessage(m.content || '');
      } else if (m.role === 'assistant') {
        renderHistoricalAssistant(m);
      } else if (m.role === 'tool') {
        renderHistoricalToolResult(m);
      }
    }
    hasSentMessage = true;
    hideWelcome();
    scrollToBottom();
    // 通知后端加载到 ctx
    sendJson({ type: 'load_session', session_id: sid });
    showToast(`Loaded session ${sid.slice(-6)}`);
  } catch (e) {
    showToast('Failed to load session');
  }
}

function startFreshSession() {
  sessionId = _genId();
  // 清理本地残留会话，避免刷新后误显示/误加载已删除的会话
  try {
    localStorage.removeItem(SESSION_LIST_KEY);
    localStorage.removeItem(STORAGE_KEY);
  } catch (e) {}
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  hasSentMessage = false;
  isProcessing = false;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'flex';
  const inputArea = document.getElementById('inputArea');
  inputArea.classList.remove('scrolled-up');
  inputArea.classList.add('welcome-input');
  input.focus();
  scrollToBottom();
  updateSessionList();
}

function restoreSession(idx) {
  _closeOverlay();
  _optionsOpen = false;
  const sessions = loadSessionList();
  const s = sessions[idx];
  if (!s || !s.html) return;
  saveCurrentBeforeNew();
  const inputArea = document.getElementById('inputArea');
  inputArea.classList.remove('welcome-input');
  inputArea.classList.remove('scrolled-up');
  sessionId = s.id;
  messagesEl().innerHTML = s.html;
  // Mark all thinking-details status as Done
  document.querySelectorAll('.thinking-details').forEach(d => {
    const st = d.querySelector('.thinking-banner-text');
    if (st) {
      const count = d.querySelectorAll('.thinking-tool-item').length;
      st.textContent = count > 0 ? `${count} tools completed` : '';
    }
  });
  hasSentMessage = true;
  hideWelcome();
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  isProcessing = false;
  scrollToBottom();
  updateSessionList();
}

function getChatPreview() {
  const msgs = messagesEl().querySelectorAll('.message-user .bubble');
  if (msgs.length === 0) return '';
  let texts = [];
  for (const m of msgs) {
    const t = m.textContent.trim();
    if (t && !t.startsWith('/')) {
      texts.push(t);
    }
  }
  if (texts.length === 0) return '';
  return texts[texts.length - 1].slice(0, 60);
}

function formatTime(ts) {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

// ─── Markdown ─────────────────────────────────────────────────────

function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => `<pre><code>${escapeHtml(code)}</code></pre>`);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^(\|.+\|)\n(\|[-:| ]+\|)\n((?:\|.+\|\n?)*)/gm, (_, head, sep, body) => {
    const headers = head.slice(1, -1).split('|').map(c => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').filter(Boolean).map(line => {
      const cells = line.slice(1, -1).split('|').map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
  });
  html = html.replace(/^[-*_]{3,}\s*$/gm, '<hr>');
  html = html.replace(/\n\n/g, '</p><p>');
  html = html.replace(/\n/g, '<br>');
  return '<p>' + html + '</p>';
}

// ─── Utilities ────────────────────────────────────────────────────

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._timeout);
  el._timeout = setTimeout(() => el.classList.remove('show'), 2500);
}

// ─── Status ───────────────────────────────────────────────────────

let currentModel = 'flash';
let availableModels = [];

async function fetchStatus() {
  try {
    const resp = await fetch('/api/status');
    const data = await resp.json();
    {
      const mn = document.getElementById('modelName');
      if (mn) mn.textContent = data.model || '\u2014';
      const sc = document.getElementById('symbolCount');
      if (sc) sc.textContent = data.symbols || '\u2014';
    }
    const projEl = document.getElementById('welcomeProject');
    if (projEl && data.project) {
      projEl.textContent = data.project;
    }
  } catch (e) { /* ignore */ }
}

async function fetchModels() {
  try {
    const resp = await fetch('/api/models');
    availableModels = await resp.json();
    if (availableModels.length > 0) {
      currentModel = availableModels.find(m => m.active)?.id || availableModels[0].id;
    }
  } catch (e) {
    availableModels = [
      { id: 'flash', label: 'Flash', active: true },
      { id: 'pro', label: 'Pro', active: false },
    ];
  }
  updateModelBtnLabel();
}

function updateModelBtnLabel() {
  const label = document.getElementById('modelBtnLabel');
  if (!label) return;
  const modeName = mode === 'agent' ? 'Agent' : 'OneShot';
  const modelName = (availableModels.find(m => m.id === currentModel)?.label || currentModel);
  label.textContent = modeName + ' ' + modelName;
}

function toggleModelPanel() {
  const panel = document.getElementById('modelPanel');
  if (panel.style.display === 'block') {
    panel.style.display = 'none';
    return;
  }

  const modeLabel = mode === 'agent' ? 'Agent' : 'OneShot';

  let modeHtml = `
    <div class="mp-section mp-mode-section">
      <div class="mp-mode-label">${modeLabel}</div>
      <div class="mp-slider">
        <div class="mp-slider-option ${mode === 'agent' ? 'active' : ''}" onclick="setMode('agent')">Agent</div>
        <div class="mp-slider-option ${mode === 'oneshot' ? 'active' : ''}" onclick="setMode('oneshot')">OneShot</div>
        <div class="mp-slider-option locked">anaii</div>
      </div>
    </div>`;

  let modelHtml = `<div class="mp-section">`;
  for (const m of availableModels) {
    const active = m.id === currentModel ? 'active' : '';
    const label = m.label || m.id;
    modelHtml += `
      <div class="model-option ${active}" onclick="selectModel('${m.id}')">
        <div class="mo-main">${active ? '<span class="model-check">&#x2713;</span> ' : ''}${escapeHtml(label)}</div>
        <div class="mo-sub">${escapeHtml(m.model || '')}</div>
      </div>`;
  }
  modelHtml += `</div>`;

  panel.innerHTML = modeHtml + modelHtml;
  panel.style.display = 'block';
}

function selectModel(id) {
  if (id === currentModel) {
    document.getElementById('modelPanel').style.display = 'none';
    return;
  }
  currentModel = id;
  sendJson({ type: 'switch_model', model: id });
  document.getElementById('modelPanel').style.display = 'none';
  updateModelBtnLabel();
}

function setMode(newMode) {
  if (newMode === mode) {
    document.getElementById('modelPanel').style.display = 'none';
    return;
  }
  mode = newMode;
  sendJson({ type: 'mode', mode: newMode });
  {
    const mb = document.getElementById('modeBadge');
    if (mb) { mb.textContent = newMode; mb.className = 'mode-badge ' + newMode; }
  }
  const hint = document.getElementById('inputHint');
  hint.textContent = newMode === 'oneshot'
    ? 'One-Shot mode \u2014 use @req, @sym, @grep, @ls, @tree to declare context'
    : '';
  document.getElementById('modelPanel').style.display = 'none';
  updateModelBtnLabel();
}

// Close model panel on outside click
document.addEventListener('click', (e) => {
  const panel = document.getElementById('modelPanel');
  const btn = document.getElementById('modelBtn');
  if (panel && panel.style.display === 'block' && !panel.contains(e.target) && !btn.contains(e.target)) {
    panel.style.display = 'none';
  }
});

// ─── Init ─────────────────────────────────────────────────────────

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed');
  const btn = document.getElementById('sidebarToggle');
  if (sidebar.classList.contains('collapsed')) {
    btn.style.left = '10px';
  } else {
    btn.style.left = '226px';
  }
}

const WELCOME_PHRASES = [
  "How can I help you?",
  "What are we building today?",
  "Ready to code — what's the plan?",
  "What would you like me to work on?",
  "Fire away — what do you need?",
  "What's on your mind?",
  "Let's build something great.",
  "I'm listening — what's the task?",
  "What should we tackle next?",
  "Tell me what you need done.",
  "All ears — where do we start?",
  "What's the mission?",
  "Ready when you are — what's first?",
  "What can I help you craft?",
];

document.addEventListener('DOMContentLoaded', () => {
  // Set random welcome phrase
  const wt = document.querySelector('.welcome-text');
  if (wt) wt.textContent = WELCOME_PHRASES[Math.floor(Math.random() * WELCOME_PHRASES.length)];

  // Cache-bust the logo
  const logo = document.getElementById('welcomeLogo');
  if (logo) logo.src = '/logo.png?_=' + Date.now();

  // 首次进入页面总是开启新会话，不自动恢复上一个会话
  startFreshSession();
  connect();
  fetchModels();
  if (input) input.focus();
  document.getElementById('sendBtn').onclick = sendMessage;

  // Welcome page: center the input if welcome is visible
  const inputArea = document.getElementById('inputArea');
  if (inputArea && !hasSentMessage) {
    inputArea.classList.add('welcome-input');
  }

  // Scroll-aware input collapse
  const msgs = messagesEl();
  msgs.addEventListener('scroll', checkScrollPosition);
  document.getElementById('scrollHint').addEventListener('click', scrollToBottom);

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _optionsOpen) {
      toggleOptions();
      return;
    }
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'End' || (e.ctrlKey && e.key === 'e')) {
      e.preventDefault();
      scrollToBottom();
    }
    if (e.key === 'Home' || (e.ctrlKey && e.key === 'h')) {
      e.preventDefault();
      scrollToTop();
    }
  });
});

// ══════════════════════════════════════════════════════════════════
// DSN Dekacode 增强功能：主题 / 上下文 / 统计 / Diff / 配置 / 会话
// ══════════════════════════════════════════════════════════════════

// ── 深色 / 浅色主题 ──
function applyTheme(theme) {
  if (!theme) theme = 'dark';
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem('dekacode_theme', theme); } catch (e) {}
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
  applyTheme(cur);
  showToast('Theme: ' + cur);
}
applyTheme(localStorage.getItem('dekacode_theme') || 'dark');

// ── 通用 Overlay 面板管理 ──
function _hideAllOverlays() {
  ['settingsPanel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });
}
function _openOverlay(id) {
  _hideAllOverlays();
  document.getElementById(id).style.display = 'block';
  document.getElementById('chatArea').style.display = 'none';
  document.getElementById('inputArea').style.display = 'none';
}
function _closeOverlay() {
  _hideAllOverlays();
  document.getElementById('chatArea').style.display = '';
  document.getElementById('inputArea').style.display = '';
}

// ── 顶部 App 指令栏 / 工作区下拉 ──
function toggleTopMenu(name) {
  // 显式互斥：只展开当前菜单，其余全部收起
  ['file', 'edit', 'view'].forEach(k => {
    const el = document.getElementById(k + 'Menu');
    if (!el) return;
    if (k === name) {
      el.classList.remove('hidden');
    } else {
      el.classList.add('hidden');
    }
  });
}
document.addEventListener('click', (e) => {
  // 点击下拉菜单里的按钮后，收起对应的菜单
  const ddBtn = e.target.closest('.top-dropdown button');
  if (ddBtn) {
    const dd = ddBtn.closest('.top-dropdown');
    if (dd) dd.classList.add('hidden');
  }
  if (!e.target.closest('.top-menu')) {
    document.querySelectorAll('.top-dropdown').forEach(el => el.classList.add('hidden'));
  }
  if (!e.target.closest('.new-session-wrap')) {
    const dd = document.getElementById('workspaceDropdown');
    if (dd) dd.classList.add('hidden');
  }
});
function openSessionFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json,.json';
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const payload = {
        summary: data.session_id || data.summary || 'imported',
        messages: data.messages || [],
      };
      const d = await fetch('/api/sessions/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(r => r.json());
      if (d.success) {
        showToast('Session imported');
        await fetchBackendSessions();
        updateSessionList();
      } else {
        showToast(d.error || 'Import failed', 'error');
      }
    } catch (e) {
      showToast('Invalid session JSON', 'error');
    }
  };
  input.click();
}
function openWorkspaceFolder() {
  const resolveAndOpen = (name, samplePaths) => {
    if (!name) { showToast('无法获取文件夹名', 'error'); return; }
    fetch('/api/workspaces/resolve', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, samplePaths: samplePaths || [] }),
    }).then(r => r.json()).then(d => {
      const candidates = d.candidates || [];
      if (candidates.length === 1) {
        openWorkspacePath(candidates[0]);
      } else if (candidates.length > 1) {
        showWorkspaceCandidatePicker(candidates);
      } else {
        showServerFolderBrowser();
      }
    });
  };

  // 优先使用 File System Access API 的原生“选择文件夹”窗口
  if (window.showDirectoryPicker) {
    window.showDirectoryPicker()
      .then(async (handle) => {
        const name = handle.name;
        const samplePaths = [];
        // 读一小部分文件名，帮助后端定位（只读前几项）
        for await (const entry of handle.values()) {
          if (samplePaths.length >= 5) break;
          samplePaths.push(entry.name);
        }
        resolveAndOpen(name, samplePaths);
      })
      .catch(err => {
        if (err && err.name === 'AbortError') return;
        // 某些环境虽然有 API 但不允许（如非安全上下文），回退到 webkitdirectory
        pickViaInput(resolveAndOpen);
      });
    return;
  }
  pickViaInput(resolveAndOpen);
}

function pickViaInput(resolveAndOpen) {
  const input = document.createElement('input');
  input.type = 'file';
  input.webkitdirectory = true;
  input.onchange = () => {
    const files = input.files;
    if (!files || !files.length) return;
    const rel = files[0].webkitRelativePath || '';
    const name = rel.split('/')[0];
    const samplePaths = [];
    for (let i = 0; i < files.length && samplePaths.length < 5; i++) {
      samplePaths.push(files[i].webkitRelativePath.split('/').slice(1).join('/') || files[i].name);
    }
    resolveAndOpen(name, samplePaths);
  };
  input.click();
}

function openWorkspacePath(path) {
  fetch('/api/workspaces', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  }).then(r => r.json()).then(d => {
    if (d.workspace) {
      showToast('Workspace opened: ' + d.workspace.path);
      sendJson({ type: 'open_workspace', path: d.workspace.path });
      fetchBackendSessions().then(updateSessionList);
    } else {
      showToast(d.detail || 'Open failed', 'error');
    }
  });
}

function showWorkspaceCandidatePicker(candidates) {
  const old = document.getElementById('workspaceCandidatePicker');
  if (old) old.remove();
  const div = document.createElement('div');
  div.id = 'workspaceCandidatePicker';
  div.className = 'workspace-picker-overlay';
  div.innerHTML = `
    <div class="workspace-picker">
      <h3>找到多个同名文件夹，请选择</h3>
      ${candidates.map(p =>
        `<button onclick="openWorkspacePath('${p}')">${escapeHtml(p)}</button>`
      ).join('')}
      <button onclick="this.closest('#workspaceCandidatePicker').remove()">取消</button>
    </div>`;
  document.body.appendChild(div);
}

// 服务器端目录浏览：在服务端文件系统里选择工作区（作为浏览器选择器的兜底）
let _wsBrowser = { path: '/', el: null };

async function showServerFolderBrowser() {
  if (_wsBrowser.el) _wsBrowser.el.remove();
  _wsBrowser.path = '/';
  const div = document.createElement('div');
  div.id = 'workspaceServerBrowser';
  div.className = 'workspace-picker-overlay';
  div.addEventListener('click', (e) => { if (e.target === div) { div.remove(); _wsBrowser.el = null; } });
  document.body.appendChild(div);
  _wsBrowser.el = div;
  await wsBrowserRender();
  return div;
}

async function wsBrowserRender() {
  const div = _wsBrowser.el;
  if (!div) return;
  const path = _wsBrowser.path;
  let d;
  try {
    d = await fetch('/api/fs/list?path=' + encodeURIComponent(path)).then(r => r.json());
  } catch (e) {
    div.innerHTML = '<div class="workspace-picker">读取失败</div>';
    return;
  }
  const dirs = (d.dirs || []).filter(x => !x.name.startsWith('.'));
  const parent = path === '/' ? null : path.replace(/\/+$/, '').split('/').slice(0, -1).join('/') || '/';
  div.innerHTML = `
    <div class="workspace-picker">
      <h3>在服务器上选择工作区目录</h3>
      <div class="ws-browser-path">${escapeHtml(path)}</div>
      <div class="ws-browser-buttons">
        <button onclick="wsBrowserPick()">选择当前目录为工作区</button>
        ${parent ? `<button onclick="wsBrowserNav('${parent.replace(/'/g, "\\'")}')">↑ 上级</button>` : ''}
      </div>
      <div class="ws-browser-list">
        ${dirs.length ? dirs.map(x => {
          const full = path.replace(/\/+$/, '') + '/' + x.name;
          return `<button onclick="wsBrowserNav('${full.replace(/'/g, "\\'")}')">📁 ${escapeHtml(x.name)}</button>`;
        }).join('') : '<div style="color:var(--text-muted)">（空目录）</div>'}
      </div>
      <button onclick="document.getElementById('workspaceServerBrowser').remove(); _wsBrowser.el=null;">取消</button>
    </div>`;
}
window.wsBrowserNav = async function(path) {
  _wsBrowser.path = path;
  await wsBrowserRender();
};
window.wsBrowserPick = function() {
  openWorkspacePath(_wsBrowser.path);
  const div = _wsBrowser.el;
  if (div) { div.remove(); _wsBrowser.el = null; }
};
function toggleWorkspaceDropdown(event) {
  if (event) event.stopPropagation();
  const dd = document.getElementById('workspaceDropdown');
  if (dd.classList.contains('hidden')) {
    fetch('/api/workspaces').then(r => r.json()).then(d => {
      const ws = d.workspaces || [];
      dd.innerHTML = ws.length
        ? ws.map(w => `<button onclick="newSessionInWorkspace('${w.id}')">${escapeHtml(w.name || w.path)}</button>`).join('')
        : '<button disabled>暂无已打开工作区</button>';
      dd.classList.remove('hidden');
    });
  } else {
    dd.classList.add('hidden');
  }
}
function newSessionInWorkspace(workspaceId) {
  document.getElementById('workspaceDropdown').classList.add('hidden');
  sendJson({ type: 'new_session', workspace_id: workspaceId });
  newSession(true); // 前端清空界面；后端 session_id 会在首次消息后同步
}

// ── 右侧侧栏统一管理 ──
function closeRightSidebar() {
  const rs = document.getElementById('rightSidebar');
  rs.classList.remove('open');
}
function openRightSidebar(title, renderFn) {
  document.getElementById('rightSidebarTitle').textContent = title;
  const rs = document.getElementById('rightSidebar');
  rs.classList.add('open');
  if (renderFn) renderFn();
}

// ── 上下文结构图示 ──
let _contextSnapshot = null;
function toggleContextPanel() {
  const rs = document.getElementById('rightSidebar');
  const title = document.getElementById('rightSidebarTitle');
  if (rs.classList.contains('open') && title.textContent === 'Context Structure') {
    closeRightSidebar();
    return;
  }
  openRightSidebar('Context Structure', renderContext);
}
function _fmtSize(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return String(Math.round(n || 0));
}
function renderContext() {
  const el = document.getElementById('rightSidebarContent');
  if (!_contextSnapshot) {
    el.innerHTML = '<div class="context-tree">No context yet. Send a message or load a session.</div>';
    return;
  }
  const sysChars = (_contextSnapshot.system_prompt || '').length;
  const toolChars = Object.entries(_contextSnapshot.roles || {})
    .filter(([k]) => k === 'tool')
    .reduce((sum, [, v]) => sum + v * 80, 0);
  const convoChars = Math.max(0, (_contextSnapshot.total_chars || 0) - sysChars - toolChars);
  const total = Math.max(1, sysChars + toolChars + convoChars);
  const budget = 1000000;
  const used = Math.min(100, Math.round(total / budget * 100));
  const sysPct = Math.round(sysChars / total * 100);
  const toolPct = Math.round(toolChars / total * 100);
  const convoPct = Math.max(0, 100 - sysPct - toolPct);

  el.innerHTML = `
    <div class="context-usage">
      <div class="ctx-head">
        <div class="ctx-pct">上下文已用 ${used}%</div>
        <div class="ctx-total">~${_fmtSize(total)} / 1M</div>
      </div>
      <div class="ctx-bar">
        <div class="ctx-bar-seg ctx-sys" style="width:${sysPct}%"></div>
        <div class="ctx-bar-seg ctx-tool" style="width:${toolPct}%"></div>
        <div class="ctx-bar-seg ctx-convo" style="width:${convoPct}%"></div>
      </div>
      <div class="ctx-breakdown">
        <span class="ctx-item"><span class="ctx-dot ctx-sys"></span>系统提示词 ~${_fmtSize(sysChars)}</span>
        <span class="ctx-item"><span class="ctx-dot ctx-tool"></span>工具 ~${_fmtSize(toolChars)}</span>
        <span class="ctx-item"><span class="ctx-dot ctx-convo"></span>对话消息 ~${_fmtSize(convoChars)}</span>
      </div>
    </div>
    <div class="context-tree" style="margin-top:12px">
      Session   : ${escapeHtml(_contextSnapshot.session_id || '(new)')}
      History   : ${escapeHtml(_contextSnapshot.history)} messages
      Tool calls: ${escapeHtml(_contextSnapshot.tool_calls)}
    </div>
  `;
}

// ── 统计页面 ──
function toggleStatsPanel() {
  const rs = document.getElementById('rightSidebar');
  const title = document.getElementById('rightSidebarTitle');
  if (rs.classList.contains('open') && title.textContent === 'Statistics') {
    closeRightSidebar();
    return;
  }
  openRightSidebar('Statistics', loadStats);
}
async function loadStats() {
  const el = document.getElementById('rightSidebarContent');
  el.innerHTML = '<div class="stat-grid"><div class="stat-card"><div class="num">…</div><div class="label">Loading</div></div></div>';
  try {
    const d = await fetch('/api/stats').then(r => r.json());
    const cards = [
      ['Sessions', d.sessions], ['Messages', d.messages], ['Tool calls', d.tool_calls],
      ['Tool messages', d.tool_messages], ['Symbols', d.symbols], ['Files', d.files],
      ['Tools', d.tools], ['Skills', d.skills], ['Input tokens', d.total_input_tokens],
      ['Cost', '¥' + d.total_cost], ['Model', d.model],
    ];
    el.innerHTML = '<div class="stat-grid">' + cards.map(([label, value]) =>
      `<div class="stat-card"><div class="num">${escapeHtml(value)}</div><div class="label">${escapeHtml(label)}</div></div>`
    ).join('') + '</div>';
  } catch (e) {
    el.innerHTML = '<p style="color:var(--red)">Failed to load stats</p>';
  }
}

// ── Diff 可视化编辑器（IDE 风格） ──
let _lastEditPath = '';
let _highlighter = null;
try { _highlighter = new Highlighter('Monokai'); } catch (e) { _highlighter = null; }

function _guessLang(path) {
  const ext = String(path || '').split('.').pop().toLowerCase();
  const map = {
    py: 'python', js: 'js', mjs: 'js', cjs: 'js', ts: 'typescript', tsx: 'tsx',
    jsx: 'jsx', json: 'json', md: 'markdown', html: 'html', htm: 'html',
    css: 'css', scss: 'scss', yaml: 'yaml', yml: 'yaml', sh: 'bash', bash: 'bash',
    java: 'java', c: 'c', cpp: 'cpp', h: 'c', go: 'go', rs: 'rust', rb: 'ruby',
  };
  return map[ext] || 'txt';
}
function highlightCode(code, lang) {
  if (_highlighter && typeof _highlighter.renderBlock === 'function') {
    try { return _highlighter.renderBlock(lang || 'txt', String(code)); } catch (e) {}
  }
  return escapeHtml(code);
}
function toggleDiffPanel() {
  const rs = document.getElementById('rightSidebar');
  const title = document.getElementById('rightSidebarTitle');
  if (rs.classList.contains('open') && title.textContent === 'Diff Visual Editor') {
    closeRightSidebar();
    return;
  }
  openRightSidebar('Diff Visual Editor', renderDiffEditor);
}
function renderDiffEditor(autoLoad) {
  const el = document.getElementById('rightSidebarContent');
  const path = _lastEditPath || '';
  el.innerHTML = `
    <div class="ide-editor">
      <div class="diff-toolbar">
        <input type="text" id="diff-path" placeholder="path/to/file.py" value="${escapeHtml(path)}">
        <button class="btn" onclick="loadDiffFile()">Load</button>
      </div>
      <div class="ide-code-wrap">
        <div class="ide-gutter" id="ide-gutter"></div>
        <pre class="ide-code" id="ide-code"></pre>
      </div>
    </div>`;
  if (path && autoLoad !== false) loadDiffFileContent(path);
}
async function loadDiffFileContent(path, content) {
  if (!path) { showToast('Enter file path', 'error'); return; }
  _lastEditPath = path;
  let newContent = content;
  if (newContent === undefined) {
    const d = await fetch('/api/diff/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    }).then(r => r.json());
    newContent = d.content || d.original || '';
  }
  const lang = _guessLang(path);
  const lines = String(newContent).split('\n');
  const gutter = document.getElementById('ide-gutter');
  const code = document.getElementById('ide-code');
  if (gutter) gutter.innerHTML = lines.map((_, i) => `<div class="ide-line-num">${i + 1}</div>`).join('');
  if (code) code.innerHTML = highlightCode(lines.join('\n'), lang);
  const wrap = document.querySelector('.ide-code-wrap');
  if (wrap) wrap.scrollTop = wrap.scrollHeight;
}
async function loadDiffFile() {
  const path = document.getElementById('diff-path').value.trim();
  await loadDiffFileContent(path);
}
function openRightDiff(path, content) {
  _lastEditPath = path || '';
  openRightSidebar('Diff Visual Editor', () => renderDiffEditor(false));
  if (path) loadDiffFileContent(path, content);
}
function _extractEditPath(args) {
  if (!args) return '';
  const raw = args.filePath || args.path || args.target || '';
  if (typeof raw !== 'string') return '';
  const m = raw.match(/^(.+):\d+-\d+$/);
  return m ? m[1] : raw;
}
async function previewFileEdit(path, args) {
  const d = await fetch('/api/diff/preview', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  }).then(r => r.json());
  const original = d.original || '';
  const m = String(args.target || args.filePath || '').match(/^(.+):(\d+)?-(\d+)?$/);
  if (!m) return;
  const start = parseInt(m[2] || '1', 10);
  const end = parseInt(m[3] || m[2] || '1', 10);
  const lines = original.split('\n');
  const replacement = String(args.replacement || '').split('\n');
  const newLines = lines.slice(0, start - 1).concat(replacement, lines.slice(end));
  loadDiffFileContent(path, newLines.join('\n'));
}
function previewEditCall(call) {
  let args = {};
  try { args = JSON.parse(call.args || '{}'); } catch (e) {}
  const path = _extractEditPath(args);
  if (!path) return;
  if (call.name === 'file.write' || call.name === 'write_file') {
    openRightDiff(path, args.content || '');
  } else if (call.name === 'file.edit' || call.name === 'edit_file') {
    _lastEditPath = path;
    openRightSidebar('Diff Visual Editor', () => renderDiffEditor(false));
    previewFileEdit(path, args);
  }
}

// ── 配置 / Provider / 技能（增强 Settings） ──
function toggleOptions() {
  const panel = document.getElementById('settingsPanel');
  if (panel.style.display === 'block') {
    _closeOverlay();
    _optionsOpen = false;
    return;
  }
  _openOverlay('settingsPanel');
  _optionsOpen = true;
  renderSettings();
}
function renderSettings() {
  const content = document.getElementById('settingsContent');
  content.innerHTML = `
    <div class="setting-row">
      <label>Theme</label>
      <button class="btn" onclick="toggleTheme()">Toggle Light/Dark</button>
    </div>
    <h3 style="margin-top:16px;color:var(--accent)">General Config</h3>
    <div id="config-list"></div>
    <h3 style="margin-top:16px;color:var(--accent)">Provider / Models</h3>
    <div id="provider-form"></div>
    <h3 style="margin-top:16px;color:var(--accent)">Skills</h3>
    <div id="skills-list"></div>
    <div style="margin-top:8px"><button class="btn" onclick="reloadSkills()">Reload Skills</button></div>
    <h3 style="margin-top:16px;color:var(--accent)">Prompts</h3>
    <div id="prompts-list"></div>
  `;
  loadConfigList();
  loadProviderForm();
  loadSkillsList();
  loadPromptsList();
}
async function loadConfigList() {
  const el = document.getElementById('config-list');
  try {
    const d = await fetch('/api/config').then(r => r.json());
    const keys = ['max_steps', 'max_output_chars', 'context_budget', 'max_history_messages',
                  'input_price_per_mtok', 'output_price_per_mtok',
                  'skills_dir', 'prompts_dir', 'enable_skills', 'theme', 'thinking_collapsed_default'];
    el.innerHTML = keys.map(k => {
      const val = d[k];
      const isBool = typeof val === 'boolean';
      const input = isBool
        ? `<input type="checkbox" data-key="${k}" ${val ? 'checked' : ''} onchange="saveConfigKey('${k}', this)">`
        : `<input type="${typeof val === 'number' ? 'number' : 'text'}" value="${escapeHtml(val)}" data-key="${k}" onchange="saveConfigKey('${k}', this)">`;
      return `<div class="setting-row"><label>${escapeHtml(k)}</label>${input}</div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = '<p style="color:var(--red)">Failed to load config</p>';
  }
}
async function saveConfigKey(key, input) {
  const value = input.type === 'checkbox' ? input.checked : input.value;
  try {
    const d = await fetch('/api/config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    }).then(r => r.json());
    if (d.error) showToast(d.error, 'error');
    else { showToast('Config updated: ' + key); renderSettings(); }
  } catch (e) { showToast('Save failed', 'error'); }
}
function _modelMapToArray(models) {
  if (Array.isArray(models)) return models;
  return Object.entries(models || {}).map(([id, model]) => ({ id, label: id.charAt(0).toUpperCase() + id.slice(1), model }));
}
function renderProviderForm(providers, selectedId) {
  const el = document.getElementById('provider-form');
  const p = providers.find(x => x.id === selectedId) || providers[0] || {};
  const models = _modelMapToArray(p.models || []);
  const modelMap = {};
  models.forEach(m => { modelMap[m.id] = m.model; });
  el.dataset.providerId = p.id || '';
  el.innerHTML = `
    <div class="setting-row">
      <label>Provider</label>
      <select id="provider-select" onchange="selectProvider(this.value)">
        ${providers.map(x => `<option value="${escapeHtml(x.id)}" ${x.id === p.id ? 'selected' : ''}>${escapeHtml(x.name || x.id)}</option>`).join('')}
      </select>
      <button class="btn" onclick="addProvider()">+ Add</button>
      <button class="btn btn-danger" onclick="deleteProvider()">Delete</button>
    </div>
    <div class="setting-row"><label>Provider Name</label><input id="provider-name" value="${escapeHtml(p.name || '')}"></div>
    <div class="setting-row"><label>Base URL</label><input id="provider-url" value="${escapeHtml(p.base_url || '')}"></div>
    <div class="setting-row"><label>API Key</label><input id="provider-key" value="${escapeHtml(p.api_key || '')}"></div>
    <div class="setting-row">
      <label>协议</label>
      <select id="provider-protocol">
        <option value="chat" ${(p.protocol || 'chat') === 'chat' ? 'selected' : ''}>chat.completions</option>
        <option value="responses" ${(p.protocol || '') === 'responses' ? 'selected' : ''}>responses</option>
      </select>
    </div>
    <div class="setting-row"><label>Flash Model</label><input id="model-flash" value="${escapeHtml(modelMap.flash || '')}"></div>
    <div class="setting-row"><label>Pro Model</label><input id="model-pro" value="${escapeHtml(modelMap.pro || '')}"></div>
    <div class="setting-row"><label>OpenAI Model</label><input id="model-openai" value="${escapeHtml(modelMap.openai || '')}"></div>
    <div style="margin-top:8px"><button class="btn btn-primary" onclick="saveProvider()">Save Provider</button></div>
  `;
}
async function loadProviderForm() {
  try {
    const d = await fetch('/api/providers').then(r => r.json());
    const providers = d.providers || [];
    window._providersCache = providers;
    const active = providers.find(p => p.active) || providers[0];
    renderProviderForm(providers, active && active.id);
  } catch (e) {
    document.getElementById('provider-form').innerHTML = '<p style="color:var(--red)">Failed to load provider</p>';
  }
}
function selectProvider(id) {
  renderProviderForm(window._providersCache || [], id);
}
function addProvider() {
  const id = 'provider_' + Date.now();
  const providers = window._providersCache || [];
  providers.push({ id, name: 'New Provider', base_url: '', api_key: '', protocol: 'chat', models: { flash: '', pro: '', openai: '' } });
  window._providersCache = providers;
  renderProviderForm(providers, id);
}
async function deleteProvider() {
  const id = document.getElementById('provider-form').dataset.providerId;
  if (!id || !confirm('Delete provider ' + id + '?')) return;
  const d = await fetch('/api/providers/' + id, { method: 'DELETE' }).then(r => r.json());
  if (d.success) {
    showToast('Provider deleted');
    loadProviderForm();
  } else {
    showToast(d.detail || 'Delete failed', 'error');
  }
}
async function saveProvider() {
  const id = document.getElementById('provider-form').dataset.providerId;
  const payload = {
    id,
    name: document.getElementById('provider-name').value,
    base_url: document.getElementById('provider-url').value,
    api_key: document.getElementById('provider-key').value,
    protocol: document.getElementById('provider-protocol').value,
    flash_model: document.getElementById('model-flash').value,
    pro_model: document.getElementById('model-pro').value,
    openai_model: document.getElementById('model-openai').value,
    active: true,
  };
  try {
    const d = await fetch('/api/providers', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(r => r.json());
    if (d.error) { showToast(d.error, 'error'); return; }
    showToast('Provider saved');
    renderSettings();
  } catch (e) { showToast('Save failed', 'error'); }
}
async function loadSkillsList() {
  const el = document.getElementById('skills-list');
  try {
    const d = await fetch('/api/skills').then(r => r.json());
    const report = d.report || {};
    const loaded = (report.loaded || []).map(x => `${x.module} (${x.tools})`).join(', ') || '(none)';
    const errors = (report.errors || []).join('; ') || '(none)';
    el.innerHTML = `
      <div class="setting-row"><label>Loaded skills</label><span>${escapeHtml(loaded)}</span></div>
      <div class="setting-row"><label>Errors</label><span>${escapeHtml(errors)}</span></div>
      <div class="setting-row"><label>Tool count</label><span>${escapeHtml((d.tools || []).length)}</span></div>
      <div class="setting-row"><label>Tools</label><span style="font-size:11px">${escapeHtml((d.tools || []).join(', '))}</span></div>
    `;
  } catch (e) {
    el.innerHTML = '<p style="color:var(--red)">Failed to load skills</p>';
  }
}
async function reloadSkills() {
  const d = await fetch('/api/skills/reload', { method: 'POST' }).then(r => r.json());
  showToast('Skills reloaded');
  loadSkillsList();
}
async function loadPromptsList() {
  const el = document.getElementById('prompts-list');
  try {
    const d = await fetch('/api/prompts').then(r => r.json());
    const prompts = d.prompts || [];
    el.innerHTML = prompts.map(p => `
      <div class="setting-row">
        <label>${escapeHtml(p.name)}</label>
        <button class="btn" onclick="editPrompt('${escapeHtml(p.name)}')">Edit</button>
      </div>
    `).join('') || '<div class="setting-row"><label>No prompts</label></div>';
    if (prompts.length === 0) {
      el.innerHTML += '<div class="setting-row"><label>New prompt</label><button class="btn" onclick="editPrompt(\'new.md\')">Create</button></div>';
    }
  } catch (e) {
    el.innerHTML = '<p style="color:var(--red)">Failed to load prompts</p>';
  }
}
let _editingPrompt = null;
function editPrompt(name) {
  _editingPrompt = name;
  const el = document.getElementById('prompts-list');
  el.innerHTML = `
    <div class="setting-row"><label>File</label><input id="prompt-name" value="${escapeHtml(name)}"></div>
    <div class="setting-row" style="align-items:flex-start"><label>Content</label><textarea id="prompt-content" rows="10" style="flex:1;min-width:0;font-family:var(--font)"></textarea></div>
    <div style="margin-top:8px">
      <button class="btn btn-primary" onclick="savePrompt()">Save</button>
      <button class="btn" onclick="loadPromptsList()">Cancel</button>
    </div>
  `;
  fetch('/api/prompts').then(r => r.json()).then(d => {
    const p = (d.prompts || []).find(x => x.name === name);
    if (p) document.getElementById('prompt-content').value = p.content;
  }).catch(() => {});
}
async function savePrompt() {
  const name = document.getElementById('prompt-name').value.trim();
  const content = document.getElementById('prompt-content').value;
  if (!name) { showToast('Prompt name required', 'error'); return; }
  const d = await fetch('/api/prompts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, content }),
  }).then(r => r.json());
  if (d.success) { showToast('Prompt saved'); loadPromptsList(); }
  else showToast(d.error || 'Save failed', 'error');
}

// ── 会话列表逻辑增强 ──
function newSession(skipServer) {
  _closeOverlay();
  _optionsOpen = false;
  if (!skipServer) sendJson({ type: 'new_session' });
  sessionId = _genId();
  messagesEl().innerHTML = '';
  currentAssistantEl = null;
  document.getElementById('executionPanel').style.display = 'none';
  setSendButtonStop(false);
  hasSentMessage = false;
  isProcessing = false;
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'flex';
  const inputArea = document.getElementById('inputArea');
  inputArea.classList.remove('scrolled-up');
  inputArea.classList.add('welcome-input');
  input.focus();
  _contextSnapshot = null;
  scrollToBottom();
  updateSessionList();
}
function saveCurrentBeforeNew() {
  // 会话只持久化到 ~/.dekacode，不再写 localStorage。
}
function updateSessionList() {
  const list = document.getElementById('sessionList');
  if (!list) return;
  const backend = _backendSessions || [];
  if (backend.length === 0) {
    list.innerHTML = '<div class="session-empty">No sessions yet</div>';
    return;
  }
  const groups = {};
  backend.forEach(s => {
    const key = s.workspace_id || 'global';
    if (!groups[key]) groups[key] = { path: s.workspace_path || '~ (全局)', items: [] };
    groups[key].items.push(s);
  });
  let html = '<div class="session-group">Sessions <button class="session-act" onclick="importBackendSession()" title="Import JSON">⤒</button></div>';
  Object.values(groups).forEach(g => {
    html += `<div class="session-group">${escapeHtml(g.path)}</div>`;
    html += g.items.map(s => {
      const preview = s.summary || s.id;
      const ts = new Date(s.updated_at).getTime();
      const active = s.id === sessionId ? ' active' : '';
      return `<div class="session-item${active}" onclick="loadBackendSession('${s.id}')">
        <div class="session-preview">${escapeHtml(preview)}</div>
        <div class="session-time">${formatTime(ts)} · ${s.message_count} msgs · ¥${s.total_cost.toFixed(4)}</div>
        <div class="session-actions">
          <button class="session-act" onclick="event.stopPropagation(); renameBackendSession('${s.id}')" title="Rename">✎</button>
          <button class="session-act" onclick="event.stopPropagation(); exportBackendSession('${s.id}')" title="Export">⤓</button>
          <button class="session-act session-del" onclick="event.stopPropagation(); deleteBackendSession('${s.id}')" title="Delete">✕</button>
        </div>
      </div>`;
    }).join('');
  });
  list.innerHTML = html;
}
async function deleteBackendSession(sid) {
  if (!confirm('Delete session ' + sid + '?')) return;
  const d = await fetch('/api/sessions/' + sid, { method: 'DELETE' }).then(r => r.json());
  if (d.success) {
    showToast('Session deleted');
    await fetchBackendSessions();
    updateSessionList();
  } else {
    showToast('Delete failed', 'error');
  }
}
async function renameBackendSession(sid) {
  const newName = prompt('New session name:', sid);
  if (!newName || newName === sid) return;
  const d = await fetch('/api/sessions/' + sid, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ summary: newName }),
  }).then(r => r.json());
  if (d.success) {
    showToast('Session renamed');
    await fetchBackendSessions();
    updateSessionList();
  } else {
    showToast('Rename failed', 'error');
  }
}
async function exportBackendSession(sid) {
  const d = await fetch(`/api/sessions/${sid}/export`).then(r => r.json());
  if (d.error) { showToast(d.error, 'error'); return; }
  const blob = new Blob([JSON.stringify(d, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = `dekacode-session-${sid}.json`; a.click();
  URL.revokeObjectURL(url);
  showToast('Session exported');
}
function importBackendSession() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'application/json,.json';
  input.onchange = async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const payload = {
        summary: data.session_id || data.summary || 'imported',
        messages: data.messages || [],
      };
      const d = await fetch('/api/sessions/import', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }).then(r => r.json());
      if (d.success) {
        showToast('Session imported');
        await fetchBackendSessions();
        updateSessionList();
      } else {
        showToast(d.error || 'Import failed', 'error');
      }
    } catch (e) {
      showToast('Invalid session JSON', 'error');
    }
  };
  input.click();
}
async function loadBackendSession(sid) {
  _closeOverlay();
  _optionsOpen = false;
  try {
    const r = await fetch(`/api/sessions/${sid}/messages`);
    const msgs = await r.json();
    if (!msgs || msgs.length === 0) { showToast('Empty session'); return; }
    const inputArea = document.getElementById('inputArea');
    inputArea.classList.remove('welcome-input');
    inputArea.classList.remove('scrolled-up');
    messagesEl().innerHTML = '';
    currentAssistantEl = null;
    _lastHistoricalThinkingBody = null;
    messageId = 0;
    for (const m of msgs) {
      if (m.role === 'user') appendUserMessage(m.content || '');
      else if (m.role === 'assistant') renderHistoricalAssistant(m);
      else if (m.role === 'tool') renderHistoricalToolResult(m);
    }
    hasSentMessage = true;
    hideWelcome();
    scrollToBottom();
    sessionId = sid;
    sendJson({ type: 'load_session', session_id: sid });
    updateSessionList();
    showToast('Loaded session ' + sid.slice(-6));
  } catch (e) {
    showToast('Failed to load session');
  }
}



// ══════════════════════════════════════════════════════════════════
// Trace 视图：以时间轴 + 可折叠日志展示一次请求的完整过程
// ══════════════════════════════════════════════════════════════════

// 每个 turn 一条记录：{ id, label, startedAt, events: [...] }
let _traceTurns = [];
let _traceExpanded = {};      // eventKey -> bool（日志展开状态）
let _traceFollow = true;      // 是否自动跟随最新事件

const TRACE_MAX_TURNS = 30;

const TRACE_META = {
  turn_start:   { icon: '▶',  label: '请求开始',   cls: 'tr-start' },
  round_start:  { icon: '↻',  label: '第 N 轮',    cls: 'tr-round' },
  model_output: { icon: '✎',  label: '模型输出',   cls: 'tr-model' },
  tool_call:    { icon: '⚙',  label: '工具调用',   cls: 'tr-call' },
  tool_result:  { icon: '✓',  label: '工具结果',   cls: 'tr-result' },
  done:         { icon: '■',  label: '循环结束',   cls: 'tr-done' },
  turn_end:     { icon: '●',  label: '请求完成',   cls: 'tr-end' },
  stopped:      { icon: '⏹',  label: '已停止',     cls: 'tr-stopped' },
  error:        { icon: '✕',  label: '错误',       cls: 'tr-error' },
};

function recordTrace(data) {
  if (!data || !data.event) return;
  if (data.event === 'turn_start') {
    _traceTurns.push({
      id: 'turn-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6),
      label: getLastUserPreview() || '(请求)',
      startedAt: Date.now(),
      events: [],
    });
    if (_traceTurns.length > TRACE_MAX_TURNS) _traceTurns.shift();
  }
  if (_traceTurns.length === 0) {
    _traceTurns.push({
      id: 'turn-orphan-' + Date.now(),
      label: getLastUserPreview() || '(请求)',
      startedAt: Date.now(),
      events: [],
    });
  }
  const turn = _traceTurns[_traceTurns.length - 1];
  turn.events.push(data);
  updateTraceBadge();
  if (isTraceOpen()) renderTrace();
}

function getLastUserPreview() {
  const bubbles = messagesEl().querySelectorAll('.message-user .bubble');
  if (!bubbles.length) return '';
  return bubbles[bubbles.length - 1].textContent.trim().slice(0, 48);
}

function isTraceOpen() {
  const rs = document.getElementById('rightSidebar');
  const title = document.getElementById('rightSidebarTitle');
  return rs && rs.classList.contains('open') && title.textContent === 'Trace';
}

function updateTraceBadge() {
  const btn = document.getElementById('navTrace');
  if (!btn) return;
  const total = _traceTurns.reduce((n, t) => n + t.events.length, 0);
  btn.textContent = total ? `🧭 Trace (${total})` : '🧭 Trace';
}

function toggleTracePanel() {
  if (isTraceOpen()) {
    closeRightSidebar();
    return;
  }
  openRightSidebar('Trace', renderTrace);
}

function clearTrace() {
  _traceTurns = [];
  _traceExpanded = {};
  updateTraceBadge();
  renderTrace();
}

function toggleTraceFollow() {
  _traceFollow = !_traceFollow;
  renderTrace();
}

function toggleTraceEvent(key) {
  _traceExpanded[key] = !_traceExpanded[key];
  renderTrace();
}

function toggleTraceTurn(turnId) {
  const t = _traceTurns.find(x => x.id === turnId);
  if (!t) return;
  t.collapsed = !t.collapsed;
  renderTrace();
}

function _traceEventTitle(ev) {
  const meta = TRACE_META[ev.event] || { label: ev.event };
  switch (ev.event) {
    case 'round_start':
      return `第 ${ev.round} 轮开始`;
    case 'tool_call':
      return `调用 ${ev.name}`;
    case 'tool_result':
      return `${ev.name} ${ev.success ? '成功' : '失败'}`;
    case 'model_output':
      return `模型输出（推理 ${ev.reasoning_chars || 0} 字 / 正文 ${ev.text_chars || 0} 字）`;
    case 'turn_start':
      return `请求开始 · ${ev.model || ''} · ${ev.mode || ''}`;
    case 'turn_end':
      return `请求完成 · ↑${ev.input_tokens || 0} ↓${ev.output_tokens || 0} tok`;
    case 'done':
      return ev.hit_max ? '循环结束（达到步数上限）' : '循环结束';
    case 'error':
      return `错误: ${ev.error || ''}`;
    default:
      return meta.label;
  }
}

// 返回该事件可折叠的详细日志（无内容则返回 ''）
function _traceEventDetail(ev) {
  const lines = [];
  const put = (k, v) => {
    if (v === undefined || v === null || v === '' ) return;
    lines.push(`${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`);
  };
  switch (ev.event) {
    case 'turn_start':
      put('model', ev.model); put('mode', ev.mode);
      put('max_steps', ev.max_steps); put('history', ev.history);
      put('activated', ev.activated);
      break;
    case 'round_start':
      put('activated', ev.activated);
      break;
    case 'tool_call':
      put('id', ev.id); put('name', ev.name);
      if (ev.args) lines.push('arguments:\n' + _prettyJson(ev.args));
      break;
    case 'tool_result':
      put('id', ev.id); put('status', ev.status);
      put('elapsed', ev.elapsed !== null && ev.elapsed !== undefined ? ev.elapsed + 's' : '');
      put('error', ev.error); put('hint', ev.hint);
      if (ev.content) lines.push('output:\n' + ev.content);
      break;
    case 'turn_end':
      put('session_id', ev.session_id); put('saved_messages', ev.saved_messages);
      put('input_tokens', ev.input_tokens); put('output_tokens', ev.output_tokens);
      break;
    case 'error':
      put('error', ev.error);
      break;
  }
  return lines.join('\n');
}

function _prettyJson(raw) {
  try { return JSON.stringify(JSON.parse(raw), null, 2); } catch (e) { return String(raw); }
}

function renderTrace() {
  const el = document.getElementById('rightSidebarContent');
  if (!el || !isTraceOpen()) return;

  const toolbar = `
    <div class="trace-toolbar">
      <button class="btn" onclick="toggleTraceFollow()">${_traceFollow ? '⏸ 暂停跟随' : '▶ 自动跟随'}</button>
      <button class="btn" onclick="clearTrace()">清空</button>
    </div>`;

  if (_traceTurns.length === 0) {
    el.innerHTML = toolbar +
      '<div class="trace-empty">暂无 trace。发送一条消息后，这里会按时间轴显示完整的请求过程。</div>';
    return;
  }

  const turnsHtml = _traceTurns.slice().reverse().map(turn => {
    const evs = turn.events;
    const last = evs[evs.length - 1] || {};
    const total = (last.t !== undefined ? last.t : 0);
    const toolCount = evs.filter(e => e.event === 'tool_call').length;
    const failed = evs.some(e => (e.event === 'tool_result' && !e.success) || e.event === 'error');
    const running = !evs.some(e => e.event === 'turn_end' || e.event === 'error' || e.event === 'stopped');

    const itemsHtml = turn.collapsed ? '' : evs.map((ev, i) => {
      const meta = TRACE_META[ev.event] || { icon: '·', label: ev.event, cls: '' };
      const key = turn.id + ':' + i;
      const detail = _traceEventDetail(ev);
      const open = !!_traceExpanded[key];
      const dur = (ev.event === 'tool_result' && ev.elapsed != null)
        ? `<span class="trace-dur">${ev.elapsed}s</span>` : '';
      const bad = (ev.event === 'error' || (ev.event === 'tool_result' && !ev.success));
      return `
        <div class="trace-item ${meta.cls} ${bad ? 'trace-bad' : ''}">
          <div class="trace-rail"><span class="trace-dot">${meta.icon}</span></div>
          <div class="trace-body">
            <div class="trace-head" ${detail ? `onclick="toggleTraceEvent('${key}')"` : ''}>
              <span class="trace-time">+${(ev.t || 0).toFixed(2)}s</span>
              <span class="trace-title">${escapeHtml(_traceEventTitle(ev))}</span>
              ${dur}
              ${detail ? `<span class="trace-caret">${open ? '▾' : '▸'}</span>` : ''}
            </div>
            ${detail && open ? `<pre class="trace-detail">${escapeHtml(detail)}</pre>` : ''}
          </div>
        </div>`;
    }).join('');

    return `
      <div class="trace-turn">
        <div class="trace-turn-head" onclick="toggleTraceTurn('${turn.id}')">
          <span class="trace-caret">${turn.collapsed ? '▸' : '▾'}</span>
          <span class="trace-turn-title">${escapeHtml(turn.label)}</span>
          <span class="trace-turn-meta">
            ${running ? '<span class="trace-running">运行中</span>' : ''}
            ${failed ? '<span class="trace-failed">有失败</span>' : ''}
            ${toolCount} 工具 · ${total.toFixed(2)}s
          </span>
        </div>
        ${itemsHtml ? `<div class="trace-items">${itemsHtml}</div>` : ''}
      </div>`;
  }).join('');

  el.innerHTML = toolbar + turnsHtml;
  if (_traceFollow) el.scrollTop = 0;
}
