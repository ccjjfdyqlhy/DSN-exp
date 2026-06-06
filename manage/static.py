"""DSN-exp 配置管理终端 — HTML 页面模板"""

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DSN-exp · 配置管理终端</title>
<style>
:root {
  --bg:#f5f0e8;--bg2:#ede8de;--bg3:#e3ddd2;
  --surface:rgba(255,252,245,0.85);--surface2:rgba(237,232,222,0.7);
  --border:rgba(160,140,110,0.25);--border2:rgba(160,140,110,0.45);
  --text:#2a2218;--text2:#6b5e4a;--text3:#9c8c78;
  --accent:#8b5e3c;--accent2:#b07d55;--accent-glow:rgba(139,94,60,0.15);
  --ink:#1a1410;--gold:#c9a84c;--red:#8b3a3a;--green:#4a7c59;--blue:#3a6b8b;
  --toggle-bg:#ccc5b8;--toggle-on:#8b5e3c;
  --slider-track:#ccc5b8;--slider-thumb:#8b5e3c;
  --shadow:rgba(42,34,24,0.12);--shadow2:rgba(42,34,24,0.06);
  --noise-opacity:0.03;--ease:0.3s cubic-bezier(0.4,0,0.2,1);
  --spring:0.38s cubic-bezier(0.34,1.56,0.64,1);
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#12100d;--bg2:#1a1712;--bg3:#221e18;
    --surface:rgba(30,26,20,0.92);--surface2:rgba(40,35,28,0.7);
    --border:rgba(120,100,70,0.2);--border2:rgba(120,100,70,0.4);
    --text:#e8e0d0;--text2:#a89880;--text3:#6e5e48;
    --accent:#c9a47a;--accent2:#a07840;--accent-glow:rgba(201,164,122,0.12);
    --ink:#f0e8d8;--gold:#e8c87a;--red:#c47a7a;--green:#7ab890;--blue:#7ab8d0;
    --toggle-bg:#3a3228;--toggle-on:#c9a47a;
    --slider-track:#3a3228;--slider-thumb:#c9a47a;
    --shadow:rgba(0,0,0,0.4);--shadow2:rgba(0,0,0,0.2);--noise-opacity:0.05;
  }
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{
  font-family:'Segoe UI','Noto Sans SC','Microsoft YaHei',sans-serif;
  background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;position:relative;
}
body::before{
  content:'';position:fixed;inset:0;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='300' height='300'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='300' height='300' filter='url(%23n)' opacity='1'/%3E%3C/svg%3E");
  opacity:var(--noise-opacity);pointer-events:none;z-index:0;
}
.layout{display:grid;grid-template-columns:260px 1fr;min-height:100vh;position:relative;z-index:1}
.sidebar{
  background:var(--surface);border-right:1px solid var(--border2);
  padding:2rem 1.2rem;position:sticky;top:0;height:100vh;overflow-y:auto;
  backdrop-filter:blur(20px);display:flex;flex-direction:column;
}
.sidebar::-webkit-scrollbar{width:4px}
.sidebar::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
.brand{margin-bottom:2rem;padding-bottom:1.2rem;border-bottom:1px solid var(--border)}
.brand-sub{font-family:'Consolas','Courier New',monospace;font-size:.58rem;letter-spacing:.2em;color:var(--text3);text-transform:uppercase;margin-bottom:.35rem}
.brand-title{font-size:1.2rem;font-weight:700;color:var(--ink);line-height:1.2}
.brand-title span{display:block;font-size:.68rem;font-weight:400;color:var(--text2);margin-top:.2rem;letter-spacing:.04em}
.nav-label{font-family:'Consolas','Courier New',monospace;font-size:.52rem;letter-spacing:.2em;color:var(--text3);text-transform:uppercase;margin:1.2rem 0 .4rem .6rem}
.nav-item{
  display:flex;align-items:center;gap:.6rem;padding:.5rem .6rem;border-radius:6px;
  cursor:pointer;transition:all var(--ease);color:var(--text2);font-size:.78rem;
  border:1px solid transparent;position:relative;overflow:hidden;margin-bottom:1px;
}
.nav-item::before{
  content:'';position:absolute;left:0;top:0;width:2px;height:100%;
  background:var(--accent);transform:scaleY(0);transition:transform var(--ease);border-radius:0 2px 2px 0;
}
.nav-item:hover{background:var(--surface2);color:var(--text);border-color:var(--border)}
.nav-item.active{background:var(--accent-glow);color:var(--accent);border-color:var(--border2)}
.nav-item.active::before{transform:scaleY(1)}
.nav-icon{width:14px;height:14px;flex-shrink:0;stroke:currentColor;fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.save-status{
  margin-top:auto;padding-top:1.2rem;border-top:1px solid var(--border);
  font-family:'Consolas','Courier New',monospace;font-size:.58rem;color:var(--text3);
  letter-spacing:.06em;display:flex;align-items:center;gap:.4rem;
}
.save-dot{width:6px;height:6px;border-radius:50%;background:var(--green);flex-shrink:0;transition:background var(--ease)}
.save-dot.saving{background:var(--gold);animation:pulse .8s ease infinite}
.save-dot.error{background:var(--red)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.main{padding:2.5rem 3rem 5rem;overflow-y:auto}
.section-panel{display:none;animation:fadeSlide .45s cubic-bezier(0.4,0,0.2,1)}
.section-panel.active{display:block}
@keyframes fadeSlide{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.section-header{margin-bottom:2.5rem;position:relative;padding-bottom:1.2rem}
.section-header::after{content:'';position:absolute;bottom:0;left:0;width:50px;height:2px;background:var(--accent)}
.section-number{font-family:'Consolas','Courier New',monospace;font-size:.55rem;letter-spacing:.25em;color:var(--text3);text-transform:uppercase;margin-bottom:.35rem}
.section-title{font-size:1.8rem;font-weight:700;color:var(--ink);line-height:1.1}
.section-desc{margin-top:.5rem;font-size:.76rem;color:var(--text2);line-height:1.7;max-width:560px}
.setting-card{
  background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:1.1rem 1.4rem;margin-bottom:.5rem;
  transition:border-color var(--ease),box-shadow var(--ease),transform var(--ease);
  position:relative;overflow:hidden;backdrop-filter:blur(10px);
}
.setting-card::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,var(--accent-glow) 0%,transparent 60%);opacity:0;transition:opacity var(--ease)}
.setting-card:hover{border-color:var(--border2);box-shadow:0 4px 20px var(--shadow2);transform:translateY(-1px)}
.setting-card:hover::before{opacity:1}
.setting-row{display:flex;align-items:flex-start;gap:1.2rem;position:relative;z-index:1}
.setting-info{flex:1;min-width:0}
.setting-title{font-size:.8rem;font-weight:600;color:var(--text);margin-bottom:.15rem}
.setting-desc{font-size:.68rem;color:var(--text3);line-height:1.6}
.setting-key{font-family:'Consolas','Courier New',monospace;font-size:.58rem;color:var(--accent2);margin-bottom:.25rem;opacity:.7}
.setting-control{flex-shrink:0;display:flex;align-items:center}
.toggle{position:relative;width:44px;height:24px;cursor:pointer}
.toggle input{opacity:0;width:0;height:0;position:absolute}
.toggle-track{position:absolute;inset:0;background:var(--toggle-bg);border-radius:12px;transition:background .3s ease}
.toggle-thumb{position:absolute;width:18px;height:18px;top:3px;left:3px;background:#fff;border-radius:50%;transition:transform var(--spring),box-shadow var(--ease);box-shadow:0 1px 4px rgba(0,0,0,.3)}
.toggle input:checked~.toggle-track{background:var(--toggle-on)}
.toggle input:checked~.toggle-thumb{transform:translateX(20px)}
.slider-wrap{display:flex;flex-direction:column;align-items:flex-end;gap:.35rem;min-width:150px}
.slider-val{font-family:'Consolas','Courier New',monospace;font-size:.65rem;color:var(--accent);letter-spacing:.04em}
input[type=range]{-webkit-appearance:none;appearance:none;width:150px;height:4px;background:var(--slider-track);border-radius:2px;outline:none;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:var(--slider-thumb);box-shadow:0 0 0 3px var(--accent-glow);transition:transform var(--spring),box-shadow var(--ease);cursor:grab}
input[type=range]::-webkit-slider-thumb:active{cursor:grabbing;transform:scale(1.2);box-shadow:0 0 0 6px var(--accent-glow)}
.num-wrap{display:flex;align-items:center;border:1px solid var(--border2);border-radius:6px;overflow:hidden;background:var(--bg2)}
.num-btn{width:26px;height:30px;background:var(--surface2);border:none;cursor:pointer;color:var(--text2);font-size:.9rem;display:flex;align-items:center;justify-content:center;transition:background var(--ease),color var(--ease);flex-shrink:0}
.num-btn:hover{background:var(--accent-glow);color:var(--accent)}
.num-btn:active{transform:scale(.92)}
.num-input{width:64px;height:30px;background:transparent;border:none;border-left:1px solid var(--border);border-right:1px solid var(--border);color:var(--text);font-family:'Consolas','Courier New',monospace;font-size:.7rem;text-align:center;outline:none;transition:background var(--ease)}
.num-input:focus{background:var(--accent-glow)}
.text-input{width:100%;margin-top:.5rem;padding:.5rem .75rem;background:var(--bg2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:.75rem;line-height:1.5;outline:none;transition:border-color var(--ease),box-shadow var(--ease);resize:vertical;position:relative;z-index:1;font-family:'Consolas','Courier New',monospace}
.text-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-glow)}
select.text-input{
  -webkit-appearance:none;appearance:none;cursor:pointer;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239c8c78' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right .6rem center;padding-right:2rem;
}
.collapse-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:.5rem;overflow:hidden;transition:border-color var(--ease),box-shadow var(--ease)}
.collapse-card:hover{border-color:var(--border2);box-shadow:0 4px 20px var(--shadow2)}
.collapse-header{padding:1.1rem 1.4rem;cursor:pointer;display:flex;align-items:center;gap:.8rem;user-select:none;position:relative}
.collapse-header::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,var(--accent-glow) 0%,transparent 60%);opacity:0;transition:opacity var(--ease)}
.collapse-header:hover::before{opacity:1}
.collapse-title{font-size:.8rem;font-weight:600;color:var(--text);flex:1;position:relative;z-index:1}
.collapse-arrow{width:14px;height:14px;stroke:var(--text3);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;transition:transform var(--spring);flex-shrink:0;position:relative;z-index:1}
.collapse-card.open .collapse-arrow{transform:rotate(180deg)}
.collapse-body{max-height:0;overflow:hidden;transition:max-height .45s cubic-bezier(0.4,0,0.2,1),padding .3s ease;padding:0 1.4rem}
.collapse-card.open .collapse-body{max-height:4000px;padding:0 1.4rem 1.1rem}
.collapse-inner{padding-top:.6rem;border-top:1px solid var(--border);display:flex;flex-direction:column;gap:.6rem}
.divider{display:flex;align-items:center;gap:.8rem;margin:1.8rem 0 1rem}
.divider-line{flex:1;height:1px;background:var(--border)}
.divider-label{font-family:'Consolas','Courier New',monospace;font-size:.55rem;letter-spacing:.18em;color:var(--text3);text-transform:uppercase;white-space:nowrap}
.toast{position:fixed;bottom:1.5rem;right:1.5rem;background:var(--surface);border:1px solid var(--border2);border-radius:8px;padding:.6rem 1.1rem;font-family:'Consolas','Courier New',monospace;font-size:.6rem;color:var(--text2);letter-spacing:.04em;box-shadow:0 8px 32px var(--shadow);transform:translateY(100px);opacity:0;transition:all .4s cubic-bezier(0.34,1.56,0.64,1);z-index:9999;pointer-events:none}
.toast.show{transform:translateY(0);opacity:1}
.secret-wrap{display:flex;align-items:center;gap:.4rem}
.secret-wrap .text-input{width:220px;margin-top:0}
.eye-btn{background:var(--surface2);border:1px solid var(--border2);border-radius:5px;cursor:pointer;color:var(--text2);padding:.35rem .5rem;font-size:.6rem;transition:background var(--ease);white-space:nowrap}
.eye-btn:hover{background:var(--accent-glow);color:var(--accent)}
.badge{display:inline-block;padding:.12rem .45rem;border-radius:3px;font-family:'Consolas','Courier New',monospace;font-size:.55rem;letter-spacing:.04em}
.badge-on{background:rgba(74,124,89,.15);color:var(--green);border:1px solid rgba(74,124,89,.3)}
.badge-off{background:rgba(139,58,58,.15);color:var(--red);border:1px solid rgba(139,58,58,.3)}
.badge-cat{background:var(--accent-glow);color:var(--accent);border:1px solid var(--border2)}
.file-list-item{display:flex;align-items:center;gap:.6rem;padding:.55rem .75rem;border-radius:6px;cursor:pointer;transition:all var(--ease);font-size:.74rem;border:1px solid transparent}
.file-list-item:hover{background:var(--surface2);border-color:var(--border)}
.file-list-item.active{background:var(--accent-glow);border-color:var(--border2);color:var(--accent)}
.file-list-item .file-name{flex:1;font-family:'Consolas','Courier New',monospace;font-size:.7rem}
.file-list-item .file-cat{font-size:.58rem;color:var(--text3)}
.main::-webkit-scrollbar{width:6px}
.main::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}
@media(max-width:800px){.layout{grid-template-columns:1fr}.sidebar{position:static;height:auto}.main{padding:1.5rem 1.2rem 3rem}}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
  <div class="brand">
    <div class="brand-sub">DSN-exp · v1.0</div>
    <div class="brand-title">配置管理<span>Configuration Manager</span></div>
  </div>
  <div class="nav-label">配置章节</div>
  <div class="nav-item active" data-target="core" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><rect x="2" y="2" width="7" height="7" rx="1" opacity=".4"/><rect x="15" y="15" width="7" height="7" rx="1" opacity=".4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2"/></svg>系统核心
  </div>
  <div class="nav-item" data-target="memory" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><path d="M12 3a4 4 0 0 1 4 4v2h2a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h2V7a4 4 0 0 1 4-4z"/><path d="M10 9h4" opacity=".5"/></svg>记忆与认知
  </div>
  <div class="nav-item" data-target="auth" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><path d="M12 2l8 4v5c0 5-3.5 9.7-8 11-4.5-1.3-8-6-8-11V6l8-4z"/><path d="M9 11l2 2 4-4" stroke-width="2"/></svg>认证与安全
  </div>
  <div class="nav-item" data-target="personality" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><path d="M12 2a6 6 0 0 1 6 6c0 2-1 3.5-2.5 4.5L18 20H6l2.5-7.5C7 11.5 6 10 6 8a6 6 0 0 1 6-6z"/><path d="M9 20v1a3 3 0 0 0 6 0v-1"/></svg>人格预设
  </div>
  <div class="nav-item" data-target="world" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10 15 15 0 0 1-4-10 15 15 0 0 1 4-10z"/></svg>世界叙事
  </div>
  <div class="nav-item" data-target="subapps" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/></svg>子应用管理
  </div>
  <div class="nav-item" data-target="prompts" onclick="switchSection(this)">
    <svg class="nav-icon" viewBox="0 0 24 24"><path d="M4 4h16v16H4zM8 8h8M8 12h8M8 16h5" stroke-width="1.5"/></svg>提示词编辑
  </div>
  <div class="save-status" id="saveStatus">
    <div class="save-dot" id="saveDot"></div>
    <span id="saveText">就绪</span>
  </div>
</aside>

<main class="main">
<div id="content"></div>
</main>
</div>

<div class="toast" id="toast"></div>

<script>
// ============================================================
// 全局状态 + 错误捕获
// ============================================================
window.onerror = function(msg, url, line, col, err) {
  console.error('[manage] GLOBAL ERROR:', msg, 'at', url, line + ':' + col, err);
  var el = document.getElementById('content');
  if (el) {
    var stack = (err && err.stack) ? err.stack.replace(/</g, '&lt;') : '';
    el.innerHTML = '<div style="padding:3rem;color:var(--red);font-family:monospace;font-size:.7rem;white-space:pre-wrap">[manage 未捕获错误]\n' + msg + '\n' + url + ':' + line + ':' + col + '\n\n' + stack + '</div>';
  }
  return true;
};
window.addEventListener('unhandledrejection', function(e) {
  console.error('[manage] UNHANDLED PROMISE REJECTION:', e.reason);
});

var CONFIG = null;
var activeFile = null;
var saveTimer = null;

// ============================================================
// 安全初始化（含详细日志）
// ============================================================
function init() {
  console.log('[manage] init() called');
  fetch('/api/config')
    .then(function(r) {
      console.log('[manage] init: fetch status=' + r.status);
      return r.json();
    })
    .then(function(data) {
      console.log('[manage] init: CONFIG loaded, _sources=' + Object.keys(data._sources || {}).length + ', prompts=' + (data._prompts || []).length);
      CONFIG = data;
      try {
        renderAll();
        console.log('[manage] init: renderAll completed successfully');
      } catch(e) {
        console.error('[manage] init: renderAll threw:', e);
        showError('renderAll 失败: ' + e.message + ' | ' + (e.stack || ''));
      }
    })
    .catch(function(e) {
      console.error('[manage] init: fetch failed:', e);
      showError('无法连接到配置服务器: ' + e.message);
    });
}

function showError(msg) {
  var el = document.getElementById('content');
  if (el) el.innerHTML = '<div style="padding:3rem;color:var(--red);font-family:monospace;font-size:.7rem;white-space:pre-wrap">[manage 错误]\n' + msg + '</div>';
}

function safeBuild(fn, name) {
  try { var r = fn(); console.log('[manage] build ' + name + ' OK'); return r; }
  catch(e) { console.error('[manage] build ' + name + ' FAILED:', e); showError('构建 ' + name + ' 失败: ' + e.message); return null; }
}

function renderAll() {
  console.log('[manage] renderAll() start');
  var container = document.getElementById('content');
  if (!container) { console.error('[manage] renderAll: #content not found'); return; }
  container.innerHTML = '';
  var builders = [
    ['Core', buildCore],
    ['Memory', buildMemory],
    ['Auth', buildAuth],
    ['Personality', buildPersonality],
    ['World', buildWorld],
    ['Subapps', buildSubapps],
    ['Prompts', buildPrompts]
  ];
  var i;
  for (i = 0; i < builders.length; i++) {
    console.log('[manage] renderAll: building ' + builders[i][0]);
    var panel = safeBuild(builders[i][1], builders[i][0]);
    if (panel) container.appendChild(panel);
  }
  console.log('[manage] renderAll: panels appended');
  var active = document.querySelector('.section-panel.active');
  if (!active) {
    var core = document.getElementById('core');
    if (core) core.classList.add('active');
  }
  console.log('[manage] renderAll: done');
}

// 延迟初始化卡片（代替 MutationObserver，避免时序问题）
function initDelayed() {
  var cards = document.querySelectorAll('.setting-card[_init_]');
  var i;
  for (i = 0; i < cards.length; i++) {
    try {
      if (!cards[i]._inited) { cards[i]._inited = true; cards[i]._init_(); }
    } catch(e) { console.error('Card init error:', e); }
  }
}

// 挂载后等 DOM 稳定再初始化卡片
function afterRender(fn) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { setTimeout(fn, 30); });
  } else {
    setTimeout(fn, 30);
  }
}

// ============================================================
// Section 切换
// ============================================================
function switchSection(navEl) {
  var items = document.querySelectorAll('.nav-item');
  var i;
  for (i = 0; i < items.length; i++) items[i].classList.remove('active');
  navEl.classList.add('active');
  var target = navEl.dataset.target;
  var panels = document.querySelectorAll('.section-panel');
  for (i = 0; i < panels.length; i++) panels[i].classList.remove('active');
  requestAnimationFrame(function() {
    var p = document.getElementById(target);
    if (p) { p.classList.add('active'); if (target === 'prompts') refreshFileList(); }
  });
}

// ============================================================
// 构建器工厂函数 — 所有构建都用 addChild 追加 DOM
// 避免 innerHTML += 和 document.getElementById 时序问题
// ============================================================

function buildCore() {
  var env = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys) || {};
  var el = mkPanel('core', '01', 'System Core', '系统核心', '模型与服务的基础配置。');
  addChild(el, mkDivider('DeepSeek API'));
  addChild(el, mkSecret('DEEPSEEK_API_KEY', 'API Key', '核心模型 API 访问密钥'));
  addChild(el, mkToggle('REASONER_ENABLED', '推理模型开关', '启用深层推理模型'));
  addChild(el, mkText('REASONER_MODEL', '推理模型名称', '如 deepseek-v4-pro'));
  addChild(el, mkNumber('REASONER_TIMEOUT', '推理超时(秒)', 60, 3600, 60));
  addChild(el, mkDivider('主模型配置'));
  addChild(el, mkSelect('MAIN_MODEL_TYPE', '模型驱动', [['deepseek','DeepSeek API'],['lmstudio','LMStudio 本地']]));
  addChild(el, mkText('MAIN_MODEL_NAME', '模型名称', ''));
  addChild(el, mkSlider('LMSTUDIO_TEMPERATURE', '温度', 0, 2, 0.05));
  addChild(el, mkNumber('LMSTUDIO_MAX_TOKENS', '最大 Token', 256, 32768, 256));
  addChild(el, mkNumber('LMSTUDIO_TIMEOUT', 'LMStudio 超时(秒)', 30, 600, 30));
  addChild(el, mkDivider('服务配置'));
  addChild(el, mkText('LMSTUDIO_BASE_URL', 'LMStudio 地址', ''));
  addChild(el, mkText('TTS_BASE_URL', 'TTS 地址', ''));
  addChild(el, mkText('SERVER_HOST', '监听地址', ''));
  addChild(el, mkNumber('SERVER_PORT', '监听端口', 1, 65535, 1));
  addChild(el, mkText('SERVER_BASE_URL', '对外地址', ''));
  addChild(el, mkNumber('LOCAL_CALLBACK_PORT', '回调端口', 1, 65535, 1));
  addChild(el, mkDivider('Agent 循环'));
  addChild(el, mkNumber('AGENT_MAX_STEPS', '最大步数', 1, 50, 1));
  initValues(el, env);
  return el;
}

function buildMemory() {
  var env = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys) || {};
  var el = mkPanel('memory', '02', 'Memory & Cognition', '记忆与认知', '记忆系统与任务管理参数。');
  addChild(el, mkDivider('记忆系统'));
  addChild(el, mkToggle('MEMORY_ENABLED', '启用记忆', ''));
  addChild(el, mkSelect('MEMORY_SUMMARY_BACKEND', '摘要后端', [['deepseek','DeepSeek'],['lmstudio','LMStudio']]));
  addChild(el, mkText('MEMORY_MODEL', '记忆模型', ''));
  addChild(el, mkNumber('MEMORY_SUMMARY_LENGTH', '摘要长度', 20, 500, 10));
  addChild(el, mkNumber('MEMORY_CONTEXT_WINDOW_SIZE', '上下文窗口', 10, 200, 10));
  addChild(el, mkSlider('MEMORY_REPLACE_THRESHOLD_RATIO', '替换阈值', 0, 1, 0.05));
  addChild(el, mkToggle('MEMORY_ASYNC_ENABLED', '异步记忆', ''));
  addChild(el, mkDivider('ASR'));
  addChild(el, mkToggle('ASR_ENABLED', '启用 ASR', ''));
  addChild(el, mkSelect('ASR_DEVICE', 'ASR 设备', [['cuda','CUDA GPU'],['cpu','CPU']]));
  addChild(el, mkToggle('ASR_FILTER_ENABLED', '启用 ASR 过滤', ''));
  addChild(el, mkText('FILTER_MODEL', '过滤模型', ''));
  addChild(el, mkDivider('任务管理'));
  addChild(el, mkToggle('TASK_MANAGER_ENABLED', '启用任务', ''));
  addChild(el, mkNumber('TASK_MAX_WORKERS', '最大 Worker', 1, 20, 1));
  addChild(el, mkSlider('TASK_COMPLEXITY_THRESHOLD', '复杂度阈值', 0, 1, 0.05));
  addChild(el, mkNumber('REMINDER_CHECK_INTERVAL', '提醒间隔(秒)', 10, 3600, 10));
  addChild(el, mkToggle('TASK_NOTIFICATION_ENABLED', '任务通知', ''));
  addChild(el, mkNumber('ACTION_TIMEOUT', '动作超时(秒)', 30, 1800, 30));
  initValues(el, env);
  return el;
}

function buildAuth() {
  var env = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys) || {};
  var el = mkPanel('auth', '03', 'Auth & Security', '认证与安全', 'OAuth2 和分层安全系统配置。');
  addChild(el, mkDivider('LittleSkin OAuth2'));
  addChild(el, mkSecret('LITTLESKIN_CLIENT_ID', 'Client ID', ''));
  addChild(el, mkSecret('LITTLESKIN_CLIENT_SECRET', 'Client Secret', ''));
  addChild(el, mkDivider('JWT'));
  addChild(el, mkSecret('JWT_SECRET', 'JWT 密钥', ''));
  addChild(el, mkDivider('分层认证'));
  addChild(el, mkNumber('AUTH_SESSION_DAYS', 'Session 天数', 1, 365, 1));
  addChild(el, mkNumber('AUTH_PAIRING_DIGITS', '配对码位数', 4, 16, 2));
  addChild(el, mkNumber('AUTH_PAIRING_TIMEOUT', '配对码超时(秒)', 60, 3600, 30));
  addChild(el, mkText('AUTH_WEBAUTHN_RP_NAME', 'Passkey 名称', ''));
  addChild(el, mkText('AUTH_TOTP_ISSUER', 'TOTP 签发者', ''));
  initValues(el, env);
  return el;
}

function buildPersonality() {
  var el = mkPanel('personality', '04', 'Personality Presets', '人格预设', 'AI 性格与情感参数。');
  var presets = (CONFIG && CONFIG._sources && CONFIG._sources.personality_presets && CONFIG._sources.personality_presets.presets) || [];

  // 预设选择器 — 使用全局 initValues 方案
  var selCard = mkCard();
  var selRow = mkRow();
  selRow.appendChild(mkInfo('活跃人格', '选择当前 AI 人格预设。'));
  var selCtrl = mkCtrl();
  var sel = document.createElement('select');
  sel.className = 'text-input';
  sel.id = 'sel_active_preset';
  sel.style.cssText = 'width:160px;margin-top:0;';
  sel.onchange = function() { switchPreset(this.value); };
  presets.forEach(function(p) { var o = document.createElement('option'); o.value = p.file; o.textContent = p.display_name; sel.appendChild(o); });
  selCtrl.appendChild(sel);
  selRow.appendChild(selCtrl);
  selCard.appendChild(selRow);
  addChild(el, selCard);

  // 每个预设的详情面板
  presets.forEach(function(p) {
    var c = document.createElement('div');
    c.id = 'preset-' + p.file;
    c.style.display = 'none';
    var d = p.data || {};
    var eb = d.emotion_baseline || {};
    var ei = d.emotion_inertia || {};
    var aff = d.affinity || {};
    var lrn = d.learning || {};

    addChild(c, mkDivider(p.display_name + ' · 基础信息'));
    addChild(c, makeRawInput('preset_name_' + p.file, '内部名称', d.name || ''));
    addChild(c, makeRawInput('preset_display_' + p.file, '显示名称', d.display_name || ''));
    addChild(c, makeRawInput('preset_desc_' + p.file, '描述', d.description || ''));

    addChild(c, mkDivider('情绪基线'));
    addChild(c, makeRawSlider('eb_joly_' + p.file, '喜悦 (Joly)', eb.joly, 0, 1, 0.01));
    addChild(c, makeRawSlider('eb_sorw_' + p.file, '悲伤 (Sorw)', eb.sorw, 0, 1, 0.01));
    addChild(c, makeRawSlider('eb_angr_' + p.file, '愤怒 (Angr)', eb.angr, 0, 1, 0.01));
    addChild(c, makeRawSlider('eb_fear_' + p.file, '恐惧 (Fear)', eb.fear, 0, 1, 0.01));
    addChild(c, makeRawSlider('eb_meta_' + p.file, '元认知 (Meta)', eb.meta, 0, 1, 0.01));

    addChild(c, mkDivider('情绪惯性'));
    addChild(c, makeRawSlider('ei_joly_' + p.file, '喜悦惯性', ei.joly, 0, 1, 0.01));
    addChild(c, makeRawSlider('ei_sorw_' + p.file, '悲伤惯性', ei.sorw, 0, 1, 0.01));
    addChild(c, makeRawSlider('ei_angr_' + p.file, '愤怒惯性', ei.angr, 0, 1, 0.01));
    addChild(c, makeRawSlider('ei_fear_' + p.file, '恐惧惯性', ei.fear, 0, 1, 0.01));
    addChild(c, makeRawSlider('ei_meta_' + p.file, '元认知惯性', ei.meta, 0, 1, 0.01));

    addChild(c, mkDivider('亲和力'));
    addChild(c, makeRawNumber('aff_init_' + p.file, '初始亲和力', aff.initial, 0, 100, 1));
    addChild(c, makeRawToggle('aff_decay_' + p.file, '亲和力衰减', aff.decay_enabled));

    addChild(c, mkDivider('学习参数'));
    addChild(c, makeRawSlider('lrn_iw_' + p.file, '天赋权重', lrn.innate_weight_init, 0, 3, 0.1));
    addChild(c, makeRawSlider('lrn_iwmin_' + p.file, '最低权重', lrn.innate_weight_min, 0, 1, 0.05));

    addChild(el, c);
  });

  // 选中第一个预设
  if (presets.length > 0) {
    sel.value = presets[0].file;
    var firstPreset = document.getElementById('preset-' + presets[0].file);
    if (firstPreset) firstPreset.style.display = 'block';
  }

  return el;
}

function switchPreset(file) {
  var els = document.querySelectorAll('[id^="preset-"]');
  var i;
  for (i = 0; i < els.length; i++) els[i].style.display = 'none';
  var el = document.getElementById('preset-' + file);
  if (el) el.style.display = 'block';
}

function buildWorld() {
  var worldData = (CONFIG && CONFIG._sources && CONFIG._sources.world && CONFIG._sources.world.data) || {};
  var celestial = worldData.celestial || {};
  var physics = worldData.physics || {};
  var el = mkPanel('world', '05', 'World Narrative', '世界叙事', '叙事世界模型参数。');

  addChild(el, makeWorldInput('name', '世界名称', worldData.name || ''));
  addChild(el, makeWorldTextarea('description', '世界描述', worldData.description || ''));
  addChild(el, mkDivider('天体力学'));
  addChild(el, makeWorldNumber('day_length', '自转周期(秒)', celestial.day_length, 3600, 172800, 3600));
  addChild(el, makeWorldNumber('year_length', '公转周期(秒)', celestial.year_length, 86400, 315360000, 86400));
  addChild(el, makeWorldSlider('time_scale', '时间倍率', celestial.time_scale, 0.1, 100, 0.1));
  addChild(el, makeWorldInput('epoch', '纪元起点', celestial.epoch || ''));

  var moon = celestial.moon || {};
  addChild(el, makeWorldInput('moon_name', '月亮名称', moon.name || ''));
  addChild(el, makeWorldNumber('moon_period', '公转周期(秒)', moon.period || 2551443, 86400, 31536000, 86400));

  addChild(el, mkDivider('物理规律'));
  addChild(el, makeWorldToggle('day_night_visible', '昼夜可见', physics.day_night_visible));
  addChild(el, makeWorldSlider('weather_persistence', '天气持续性', physics.weather_persistence || 0.8, 0, 1, 0.05));
  addChild(el, makeWorldNumber('weather_refresh_interval', '天气刷新间隔(秒)', physics.weather_refresh_interval || 600, 60, 86400, 60));

  return el;
}

function buildSubapps() {
  var subapps = (CONFIG && CONFIG._sources && CONFIG._sources.subapps && CONFIG._sources.subapps.subapps) || [];
  var el = mkPanel('subapps', '06', 'Subapp Management', '子应用管理', '独立子应用配置。');

  subapps.forEach(function(sa) {
    var d = sa.data || {};
    var meta = d.meta || {};
    var model = d.model || {};
    var agent = d.agent || {};
    var schedule = d.schedule || {};

    var cc = document.createElement('div');
    cc.className = 'collapse-card';
    var ch = document.createElement('div');
    ch.className = 'collapse-header';
    ch.onclick = function() { cc.classList.toggle('open'); };
    ch.innerHTML = '<div class="collapse-title">' + (meta.name || sa.dir) + ' <span class="badge badge-cat">' + (meta.version || '1.0') + '</span></div>'
      + '<div style="font-size:.62rem;color:var(--text3)">' + (d.mode || 'interactive') + '</div>'
      + '<svg class="collapse-arrow" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>';
    cc.appendChild(ch);

    var cb = document.createElement('div');
    cb.className = 'collapse-body';
    var ci = document.createElement('div');
    ci.className = 'collapse-inner';

    addChild(ci, makeSubappSelect(sa.dir, 'sa_provider_' + sa.dir, 'Provider', model.provider || 'deepseek', [['deepseek','DeepSeek'],['lmstudio','LMStudio'],['openai','OpenAI']]));
    addChild(ci, makeSubappInput(sa.dir, 'sa_modelname_' + sa.dir, 'Model', model.model || ''));
    addChild(ci, makeSubappSlider(sa.dir, 'sa_temp_' + sa.dir, 'Temperature', model.temperature || 0.7, 0, 2, 0.05));
    addChild(ci, makeSubappNumber(sa.dir, 'sa_maxtok_' + sa.dir, 'Max Tokens', model.max_tokens || 4096, 256, 32768, 256));
    addChild(ci, makeSubappNumber(sa.dir, 'sa_timeout_' + sa.dir, 'Timeout(秒)', model.timeout || 300, 30, 3600, 30));

    if (agent.max_steps !== undefined) {
      addChild(ci, makeSubappNumber(sa.dir, 'sa_steps_' + sa.dir, 'Max Steps', agent.max_steps, 1, 50, 1));
      addChild(ci, makeSubappNumber(sa.dir, 'sa_budget_' + sa.dir, 'Token Budget', agent.token_budget || 8000, 1000, 32000, 1000));
      addChild(ci, makeSubappNumber(sa.dir, 'sa_atimeout_' + sa.dir, 'Agent Timeout(秒)', agent.timeout || 120, 30, 3600, 30));
    }
    if (schedule.cron) {
      addChild(ci, makeSubappInput(sa.dir, 'sa_cron_' + sa.dir, 'Cron', schedule.cron));
    }

    cb.appendChild(ci);
    cc.appendChild(cb);
    addChild(el, cc);
  });
  return el;
}

function buildPrompts() {
  var prompts = CONFIG._prompts || [];
  var el = mkPanel('prompts', '07', 'Prompt Templates', '提示词编辑', '管理系统提示词模板。');
  var cats = [];
  prompts.forEach(function(p) { if (cats.indexOf(p.category) < 0) cats.push(p.category); });
  cats.sort();

  // 顶部信息卡
  var infoCard = mkCard();
  var infoRow = mkRow();
  infoRow.appendChild(mkInfo('提示词文件', '共 <strong>' + prompts.length + '</strong> 个文件'));
  var selCtrl = mkCtrl();
  var filter = document.createElement('select');
  filter.className = 'text-input';
  filter.style.cssText = 'width:120px;margin-top:0;';
  filter.id = 'prompt_cat_filter';
  filter.onchange = function() { refreshFileList(); };
  var optAll = document.createElement('option');
  optAll.value = ''; optAll.textContent = '全部分类';
  filter.appendChild(optAll);
  cats.forEach(function(c) { var o = document.createElement('option'); o.value = c; o.textContent = c; filter.appendChild(o); });
  selCtrl.appendChild(filter);
  infoRow.appendChild(selCtrl);
  infoCard.appendChild(infoRow);
  addChild(el, infoCard);

  // 编辑器区域
  var editorWrap = document.createElement('div');
  editorWrap.style.cssText = 'display:grid;grid-template-columns:260px 1fr;gap:.5rem;margin-top:.5rem;';
  editorWrap.innerHTML = '<div id="prompt_file_list" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:.5rem;max-height:70vh;overflow-y:auto;"></div>'
    + '<div id="prompt_editor_panel" style="background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1rem;display:flex;flex-direction:column;">'
    + '<div id="prompt_editor_header" style="margin-bottom:.75rem;font-size:.68rem;color:var(--text3);">选择左侧文件开始编辑</div>'
    + '<textarea id="prompt_editor" class="text-input" rows="28" style="flex:1;font-size:.65rem;resize:vertical;margin-top:0;" disabled></textarea>'
    + '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:.75rem;gap:.5rem;">'
    + '<div><label style="font-size:.6rem;color:var(--text3);display:flex;align-items:center;gap:.3rem"><input type="checkbox" id="prompt_enabled_cb" disabled onchange="togglePromptEnabled(this.checked)"> 启用</label></div>'
    + '<div style="display:flex;gap:.4rem;"><button class="eye-btn" onclick="reloadPromptFile()">重新加载</button><button class="eye-btn" style="background:var(--accent);color:#fff" onclick="savePromptFile()">保存文件</button></div>'
    + '</div></div>';
  addChild(el, editorWrap);

  setTimeout(function() { refreshFileList(); }, 100);
  return el;
}

// ============================================================
// 提示词编辑器
// ============================================================
function refreshFileList() {
  var prompts = CONFIG._prompts || [];
  var filterEl = document.getElementById('prompt_cat_filter');
  var filter = (filterEl && filterEl.value) || '';
  var listEl = document.getElementById('prompt_file_list');
  if (!listEl) return;

  var filtered = [];
  prompts.forEach(function(p) { if (!filter || p.category === filter) filtered.push(p); });

  listEl.textContent = '';
  filtered.forEach(function(p) {
    var item = document.createElement('div');
    item.className = 'file-list-item' + (activeFile === p.path ? ' active' : '');
    item.onclick = function() { selectPromptFile(p.path); };
    item.innerHTML = '<span class="file-name">' + p.path + '</span>'
      + (p.enabled !== false ? '<span class="badge badge-on">ON</span>' : '<span class="badge badge-off">OFF</span>')
      + '<span class="file-cat">' + p.category + '</span>';
    if (p.description) item.title = p.description;
    listEl.appendChild(item);
  });
}

function selectPromptFile(path) {
  activeFile = path;
  refreshFileList();
  fetch('/api/file?path=' + encodeURIComponent('prompt/prompts/' + path))
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var editor = document.getElementById('prompt_editor');
      var header = document.getElementById('prompt_editor_header');
      if (d.error) { editor.value = '// ' + d.error; editor.disabled = true; return; }
      editor.value = d.content || '';
      editor.disabled = false;
      if (header) header.innerHTML = '<strong>' + path + '</strong>';
      var meta = null;
      (CONFIG._prompts || []).forEach(function(p) { if (p.path === path) meta = p; });
      if (meta) {
        var cb = document.getElementById('prompt_enabled_cb');
        if (cb) { cb.disabled = false; cb.checked = meta.enabled !== false; }
      }
    });
}

function savePromptFile() {
  if (!activeFile) return;
  var editor = document.getElementById('prompt_editor');
  if (!editor) return;
  var content = editor.value;
  setSaving();
  fetch('/api/file/save?path=' + encodeURIComponent('prompt/prompts/' + activeFile), {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({content: content})
  }).then(function() {
    setSaved();
    fetch('/api/prompts/reload').then(function(r) { return r.json(); }).then(function(d) {
      CONFIG._prompts = d.prompts || [];
      refreshFileList();
    });
  }).catch(function() { setError(); });
}

function reloadPromptFile() { if (activeFile) selectPromptFile(activeFile); }

function togglePromptEnabled(val) {
  if (!activeFile) return;
  setSaving();
  fetch('/api/prompts/meta', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: activeFile, enabled: val})
  }).then(function() {
    setSaved();
    fetch('/api/prompts/reload').then(function(r) { return r.json(); }).then(function(d) {
      CONFIG._prompts = d.prompts || [];
      refreshFileList();
    });
  });
}

// ============================================================
// 保存逻辑
// ============================================================
function setSaving() {
  var dot = document.getElementById('saveDot');
  var txt = document.getElementById('saveText');
  if (dot) dot.className = 'save-dot saving';
  if (txt) txt.textContent = '保存中...';
}
function setSaved() {
  var dot = document.getElementById('saveDot');
  var txt = document.getElementById('saveText');
  if (dot) dot.className = 'save-dot';
  if (txt) txt.textContent = '已保存';
  var t = document.getElementById('toast');
  if (t) { t.textContent = '配置已写入'; t.classList.add('show'); setTimeout(function() { t.classList.remove('show'); }, 2000); }
}
function setError() {
  var dot = document.getElementById('saveDot');
  var txt = document.getElementById('saveText');
  if (dot) dot.className = 'save-dot error';
  if (txt) txt.textContent = '保存失败';
}

// ============================================================
// 统一的 initValues — 挂载后批量初始化
// ============================================================
function initValues(section, data) {
  afterRender(function() {
    var inputs = section.querySelectorAll('input, select, textarea');
    var i;
    for (i = 0; i < inputs.length; i++) {
      var el = inputs[i];
      var key = el.id && el.id.replace(/^(inp_|chk_|sel_|val_)/, '');
      if (key && data[key] !== undefined) {
        if (el.type === 'checkbox') {
          el.checked = (data[key] === 'true' || data[key] === '1' || data[key] === 'yes');
        } else if (el.tagName === 'SELECT' || el.type === 'text' || el.type === 'number' || el.type === 'password') {
          el.value = data[key];
        }
      }
    }
  });
}

function saveEnvKey(key, value) {
  if (!CONFIG || !CONFIG._sources || !CONFIG._sources.env) return;
  CONFIG._sources.env.keys[key] = String(value);
  scheduleSaveSection('env', {[key]: String(value)});
}

function scheduleSaveSection(section, data) {
  setSaving();
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(function() {
    fetch('/api/config/save', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({section: section, data: data})
    }).then(function() { setSaved(); }).catch(function() { setError(); });
  }, 500);
}

// ============================================================
// DOM 组件工厂
// ============================================================
function mkPanel(id, num, eng, chn, desc) {
  var el = document.createElement('section');
  el.className = 'section-panel' + (id === 'core' ? ' active' : '');
  el.id = id;
  el.innerHTML = '<div class="section-header"><div class="section-number">\u00A7 ' + num + ' \u00B7 ' + eng + '</div><h1 class="section-title">' + chn + '</h1><p class="section-desc">' + desc + '</p></div>';
  return el;
}

function addChild(parent, child) { if (parent && child) parent.appendChild(child); }

function mkDivider(label) {
  var el = document.createElement('div');
  el.className = 'divider';
  el.innerHTML = '<div class="divider-line"></div><div class="divider-label">' + label + '</div><div class="divider-line"></div>';
  return el;
}

function mkCard() { var e = document.createElement('div'); e.className = 'setting-card'; return e; }
function mkRow() { var e = document.createElement('div'); e.className = 'setting-row'; return e; }
function mkCtrl() { var e = document.createElement('div'); e.className = 'setting-control'; return e; }
function mkInfo(title, desc) {
  var e = document.createElement('div');
  e.className = 'setting-info';
  e.innerHTML = '<div class="setting-title">' + title + '</div><div class="setting-desc">' + desc + '</div>';
  return e;
}

function buildCard(key, inner) {
  var card = mkCard();
  var row = mkRow();
  row.innerHTML = '<div class="setting-info"><div class="setting-key">' + key + '</div>' + inner + '</div>';
  card.appendChild(row);
  return card;
}

function buildCtrl(html) {
  var e = document.createElement('div');
  e.className = 'setting-control';
  e.innerHTML = html;
  return e;
}

function mkToggle(key, title, desc) {
  var card = buildCard(key, '<div class="setting-title">' + title + '</div><div class="setting-desc">' + desc + '</div>');
  card.appendChild(buildCtrl('<label class="toggle"><input type="checkbox" id="chk_' + key + '" onchange="saveEnvKey(\'' + key + '\',this.checked?\'' + 'true' + '\':\'' + 'false' + '\')"><div class="toggle-track"></div><div class="toggle-thumb"></div></label>'));
  return card;
}

function mkSlider(key, title, min, max, step) {
  var v = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys && CONFIG._sources.env.keys[key]) || min;
  var card = buildCard(key, '<div class="setting-title">' + title + '</div>');
  card.appendChild(buildCtrl('<div class="slider-wrap"><div class="slider-val" id="val_' + key + '">' + v + '</div><input type="range" min="' + min + '" max="' + max + '" step="' + step + '" value="' + v + '" oninput="sliderUpdate(this,\'' + key + '\',' + getDec(step) + ')"></div>'));
  return card;
}

function mkText(key, title, desc) {
  var v = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys && CONFIG._sources.env.keys[key]) || '';
  var card = buildCard(key, '<div class="setting-title">' + title + '</div><div class="setting-desc">' + desc + '</div>');
  card.appendChild(buildCtrl('<input type="text" class="text-input" id="inp_' + key + '" value="' + v + '" onchange="saveEnvKey(\'' + key + '\',this.value)" style="width:240px;margin-top:0;">'));
  return card;
}

function mkSecret(key, title, desc) {
  var v = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys && CONFIG._sources.env.keys[key]) || '';
  var card = buildCard(key, '<div class="setting-title">' + title + '</div><div class="setting-desc">' + desc + '</div>');
  card.appendChild(buildCtrl('<div class="secret-wrap"><input type="password" class="text-input" id="inp_' + key + '" value="' + v + '" onchange="saveEnvKey(\'' + key + '\',this.value)" style="width:240px;margin-top:0;" placeholder="***"><button class="eye-btn" onclick="toggleSecret(\'inp_' + key + '\',this)">显示</button></div>'));
  return card;
}

function mkNumber(key, title, min, max, step) {
  var v = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys && CONFIG._sources.env.keys[key]) || '';
  var card = buildCard(key, '<div class="setting-title">' + title + '</div>');
  card.appendChild(buildCtrl('<div class="num-wrap"><button class="num-btn" onclick="stepNum(\'' + key + '\',' + (-step) + ')">\u2212</button><input type="number" class="num-input" id="inp_' + key + '" value="' + v + '" min="' + min + '" max="' + max + '" step="' + step + '" onchange="saveEnvKey(\'' + key + '\',this.value)"><button class="num-btn" onclick="stepNum(\'' + key + '\',' + step + ')">+</button></div>'));
  return card;
}

function mkSelect(key, title, opts) {
  var v = (CONFIG && CONFIG._sources && CONFIG._sources.env && CONFIG._sources.env.keys && CONFIG._sources.env.keys[key]) || opts[0][0];
  var html = opts.map(function(o) { return '<option value="' + o[0] + '"' + (o[0] === v ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('');
  var card = buildCard(key, '<div class="setting-title">' + title + '</div>');
  card.appendChild(buildCtrl('<select class="text-input" id="sel_' + key + '" onchange="saveEnvKey(\'' + key + '\',this.value)" style="width:160px;margin-top:0;">' + html + '</select>'));
  return card;
}

// ============================================================
// Persona raw components — 不带 init 延迟，直接用 inline value
// ============================================================
function makeRawInput(id, title, value) {
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  r.appendChild(mkCtrl('<input type="text" class="text-input" id="' + id + '" value="' + esc(value) + '" style="width:220px;margin-top:0;">'));
  c.appendChild(r); return c;
}
function makeRawSlider(id, title, value, min, max, step) {
  var dec = getDec(step);
  var nv = Number(value) || min;
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  r.innerHTML += '<div class="setting-control"><div class="slider-wrap"><div class="slider-val">' + nv.toFixed(dec) + '</div><input type="range" min="' + min + '" max="' + max + '" step="' + step + '" value="' + nv + '"></div></div>';
  c.appendChild(r); return c;
}
function makeRawNumber(id, title, value, min, max, step) {
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  r.innerHTML += '<div class="setting-control"><div class="num-wrap"><button class="num-btn">\u2212</button><input type="number" class="num-input" id="' + id + '" value="' + (value || '') + '" min="' + min + '" max="' + max + '" step="' + step + '"><button class="num-btn">+</button></div></div>';
  c.appendChild(r); return c;
}
function makeRawToggle(id, title, value) {
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  r.innerHTML += '<div class="setting-control"><label class="toggle"><input type="checkbox" id="' + id + '"' + (value ? ' checked' : '') + '><div class="toggle-track"></div><div class="toggle-thumb"></div></label></div>';
  c.appendChild(r); return c;
}

// ============================================================
// World components — 直接用 inline value
// ============================================================
function makeWorldInput(key, title, value) {
  return cardRow(title, '<input type="text" class="text-input" id="inp_' + key + '" value="' + esc(value) + '" style="width:280px;margin-top:0;">');
}
function makeWorldTextarea(key, title, value) {
  return cardRow(title, '<textarea class="text-input" id="inp_' + key + '" rows="2">' + esc(value) + '</textarea>');
}
function makeWorldSlider(key, title, value, min, max, step) {
  var dec = getDec(step);
  var nv = Number(value) || min;
  return cardRow(title, '<div class="slider-wrap"><div class="slider-val">' + nv.toFixed(dec) + '</div><input type="range" min="' + min + '" max="' + max + '" step="' + step + '" value="' + nv + '"></div>');
}
function makeWorldNumber(key, title, value, min, max, step) {
  return cardRow(title, '<div class="num-wrap"><button class="num-btn">\u2212</button><input type="number" class="num-input" id="inp_' + key + '" value="' + (value || '') + '" min="' + min + '" max="' + max + '" step="' + step + '"><button class="num-btn">+</button></div>');
}
function makeWorldToggle(key, title, value) {
  return cardRow(title, '<label class="toggle"><input type="checkbox" id="chk_' + key + '"' + (value ? ' checked' : '') + '><div class="toggle-track"></div><div class="toggle-thumb"></div></label>');
}

// ============================================================
// Subapp components
// ============================================================
function makeSubappInput(sadir, id, title, value) {
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  r.appendChild(mkCtrl('<input type="text" class="text-input" id="' + id + '" value="' + esc(value) + '" style="width:200px;margin-top:0;">'));
  c.appendChild(r); return c;
}
function makeSubappSelect(sadir, id, title, value, opts) {
  var c = mkCard(); var r = mkRow();
  r.appendChild(mkInfo(title, ''));
  var html = opts.map(function(o) { return '<option value="' + o[0] + '"' + (o[0] === value ? ' selected' : '') + '>' + o[1] + '</option>'; }).join('');
  r.appendChild(mkCtrl('<select class="text-input" id="' + id + '" style="width:130px;margin-top:0;">' + html + '</select>'));
  c.appendChild(r); return c;
}
function makeSubappSlider(sadir, id, title, value, min, max, step) {
  var dec = getDec(step);
  var nv = Number(value) || min;
  return cardRow(title, '<div class="slider-wrap"><div class="slider-val">' + nv.toFixed(dec) + '</div><input type="range" min="' + min + '" max="' + max + '" step="' + step + '" value="' + nv + '"></div>');
}
function makeSubappNumber(sadir, id, title, value, min, max, step) {
  return cardRow(title, '<div class="num-wrap"><button class="num-btn">\u2212</button><input type="number" class="num-input" id="' + id + '" value="' + (value || '') + '" min="' + min + '" max="' + max + '" step="' + step + '"><button class="num-btn">+</button></div>');
}

// ============================================================
// Utilities
// ============================================================
function cardRow(title, ctrlHtml) {
  var c = mkCard(); c.innerHTML = '<div class="setting-row"><div class="setting-info"><div class="setting-title">' + title + '</div></div><div class="setting-control">' + ctrlHtml + '</div></div>';
  return c;
}
function getDec(step) { var s = String(step); return s.indexOf('.') >= 0 ? s.length - s.indexOf('.') - 1 : 0; }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

function sliderUpdate(el, key, dec) {
  var v = parseFloat(el.value);
  var valEl = document.getElementById('val_' + key);
  if (valEl) valEl.textContent = v.toFixed(dec);
  saveEnvKey(key, v);
}

function stepNum(key, delta) {
  var el = document.getElementById('inp_' + key);
  if (!el) return;
  var v = parseFloat(el.value || '0') + delta;
  var mn = el.min ? parseFloat(el.min) : -Infinity;
  var mx = el.max && !isNaN(parseFloat(el.max)) ? parseFloat(el.max) : Infinity;
  v = Math.max(mn, Math.min(mx, v));
  el.value = v;
  saveEnvKey(key, v);
}

function toggleSecret(inputId, btn) {
  var el = document.getElementById(inputId);
  if (!el) return;
  if (el.type === 'password') { el.type = 'text'; btn.textContent = '隐藏'; }
  else { el.type = 'password'; btn.textContent = '显示'; }
}

// ============================================================
// 启动
// ============================================================
(function() {
  console.log('[manage] script loaded, readyState=' + document.readyState);
  function start() { console.log('[manage] starting init...'); init(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { console.log('[manage] DOMContentLoaded'); start(); });
  } else {
    start();
  }
})();
</script>
</body>
</html>
"""
