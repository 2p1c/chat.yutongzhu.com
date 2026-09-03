(function () {
  'use strict';

  // Production: same origin (nginx proxies /api). Local: Docker Desktop
  // drops SSE from the web container to host uvicorn, so the browser talks
  // to :8001 directly.
  var API_BASE = (location.port === '8000' &&
    (location.hostname === '127.0.0.1' || location.hostname === 'localhost'))
    ? 'http://127.0.0.1:8001'
    : '';

  var AUTH_EVENT = 'chat:ready';
  var SESSION_KEY = 'session_id';

  function isLocalHost() {
    return location.hostname === '127.0.0.1' || location.hostname === 'localhost';
  }

  function apiFetch(path, opts) {
    opts = opts || {};
    var headers = {};
    if (opts.headers) {
      Object.keys(opts.headers).forEach(function (k) { headers[k] = opts.headers[k]; });
    }
    opts.headers = headers;
    opts.credentials = 'include';
    return fetch(API_BASE + path, opts);
  }

  function apiErrorDetail(data, fallback) {
    if (!data) return fallback;
    if (typeof data.detail === 'string') return data.detail;
    if (Array.isArray(data.detail) && data.detail[0] && data.detail[0].msg) {
      return data.detail[0].msg;
    }
    return fallback;
  }

  function lucideSvg(pathDs, rects) {
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '2');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    (rects || []).forEach(function (r) {
      var rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('width', r.w);
      rect.setAttribute('height', r.h);
      rect.setAttribute('x', r.x);
      rect.setAttribute('y', r.y);
      rect.setAttribute('rx', r.rx);
      rect.setAttribute('ry', r.ry);
      svg.appendChild(rect);
    });
    (pathDs || []).forEach(function (d) {
      var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      svg.appendChild(path);
    });
    return svg;
  }

  function copyIcon() {
    return lucideSvg(
      ['M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2'],
      [{ w: '14', h: '14', x: '8', y: '8', rx: '2', ry: '2' }]
    );
  }

  function checkIcon() {
    return lucideSvg(['M20 6 9 17l-5-5']);
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'absolute';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) {}
    document.body.removeChild(ta);
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        fallbackCopy(text);
      });
    }
    fallbackCopy(text);
    return Promise.resolve();
  }

  function flashCopied(btn) {
    if (btn._copyTimer) clearTimeout(btn._copyTimer);
    btn.textContent = '';
    btn.appendChild(checkIcon());
    btn.setAttribute('aria-label', 'Copied');
    btn._copyTimer = setTimeout(function () {
      btn.textContent = '';
      btn.appendChild(copyIcon());
      btn.setAttribute('aria-label', 'Copy');
      btn._copyTimer = null;
    }, 1500);
  }

  function formatLoopEvent(evt) {
    if (!evt || !evt.type) return JSON.stringify(evt);
    var step = evt.step != null ? ('step ' + evt.step) : 'step ?';
    if (evt.type === 'llm') {
      var calls = (evt.toolCalls || []).map(function (c) {
        return (c.name || '?') + '(' + (c.arguments || '') + ')';
      }).join(', ');
      return step + ' · llm' + (calls ? ' · ' + calls : '')
        + (evt.contentPreview ? '\n' + evt.contentPreview : '');
    }
    if (evt.type === 'tool_result') {
      return step + ' · tool ' + (evt.name || '?')
        + (evt.resultPreview ? '\n' + evt.resultPreview : '');
    }
    if (evt.type === 'final') {
      return step + ' · final'
        + (evt.content ? '\n' + evt.content : '');
    }
    if (evt.type === 'max_steps') {
      return step + ' · max steps'
        + (evt.content ? '\n' + evt.content : '');
    }
    if (evt.type === 'interrupt') {
      var pending = (evt.pending || []).map(function (p) {
        return (p.name || '?') + (p.summary ? ': ' + p.summary : '');
      }).join('\n');
      return step + ' · interrupt' + (pending ? '\n' + pending : '');
    }
    return step + ' · ' + evt.type;
  }

  function clearLoopDebug() {
    var list = document.getElementById('loop-debug-list');
    if (list) list.textContent = '';
    updateLoopEmptyHint();
  }

  function updateLoopEmptyHint() {
    var list = document.getElementById('loop-debug-list');
    var hint = document.getElementById('loop-debug-empty');
    if (!list || !hint) return;
    hint.hidden = list.childNodes.length > 0;
  }

  function setLoopDebugOpen(open) {
    var panel = document.getElementById('loop-debug');
    var toggle = document.getElementById('btn-loop-toggle');
    if (!panel) return;
    panel.classList.toggle('open', open);
    panel.setAttribute('aria-hidden', open ? 'false' : 'true');
    document.body.classList.toggle('loop-debug-open', open);
    if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    try { localStorage.setItem('loop_debug_open', open ? '1' : '0'); } catch (e) {}
  }

  function showLoopDebugToggle() {
    if (!isLocalHost()) return;
    var toggle = document.getElementById('btn-loop-toggle');
    if (toggle) toggle.hidden = false;
    updateLoopEmptyHint();
  }

  function appendLoopEvent(evt) {
    if (!isLocalHost()) return;
    var list = document.getElementById('loop-debug-list');
    if (!list) return;
    var li = document.createElement('li');
    li.className = 'loop-debug-item';
    li.textContent = formatLoopEvent(evt);
    list.appendChild(li);
    list.scrollTop = list.scrollHeight;
    updateLoopEmptyHint();
  }

  /* ── Animated Vanta fog background (ink-wash palettes) ── */

  // Light: 宣纸 + 焦/浓/淡墨. Dark: 墨底 + 飞白高光.
  var THEMES = {
    light: {
      highlightColor: 0xcfc9bc,
      midtoneColor: 0x5c5852,
      lowlightColor: 0x1c1b19,
      baseColor: 0xe8e4da,
      blurFactor: 0.62,
      speed: 0.5,
      zoom: 1.15
    },
    dark: {
      highlightColor: 0x8a8680,
      midtoneColor: 0x3d3a36,
      lowlightColor: 0x080807,
      baseColor: 0x141311,
      blurFactor: 0.55,
      speed: 0.45,
      zoom: 1.1
    }
  };

  var vanta = null;

  function currentTheme() {
    // Only light/dark are valid theme keys; anything else (e.g. a stale
    // 'auto'/'system' value in localStorage) falls back to dark.
    var t = document.documentElement.getAttribute('data-theme');
    return THEMES[t] ? t : 'dark';
  }

  function vantaHex(color) {
    return '#' + ('000000' + color.toString(16)).slice(-6);
  }

  function applyVantaFallback(el) {
    el.style.backgroundColor = vantaHex(THEMES[currentTheme()].baseColor);
  }

  // Builds the fog effect for the active theme. Destroying + rebuilding on theme
  // switch is simple and reliable (switches are rare, so the cost is negligible).
  function initVanta() {
    // Vanta is purely decorative. If WebGL/three.js fails (hardware acceleration
    // disabled, bad driver, etc.) it must never break the chat — so isolate it.
    try {
      var el = document.getElementById('vanta-bg');
      if (!el) return;
      applyVantaFallback(el);
      if (!window.VANTA || !window.VANTA.FOG) return;
      if (vanta) { vanta.destroy(); vanta = null; }
      var palette = THEMES[currentTheme()];
      vanta = window.VANTA.FOG({
        el: el,
        mouseControls: true,
        touchControls: true,
        gyroControls: false,
        minHeight: 200,
        minWidth: 200,
        highlightColor: palette.highlightColor,
        midtoneColor: palette.midtoneColor,
        lowlightColor: palette.lowlightColor,
        baseColor: palette.baseColor,
        backgroundColor: palette.baseColor,
        blurFactor: palette.blurFactor,
        speed: palette.speed,
        zoom: palette.zoom
      });
    } catch (err) {
      console.warn('[vanta] init failed (decorative only):', err);
    }
  }

  function bootVanta() {
    if (prefersReducedMotion) return;
    initVanta();
  }

  // Respect the system "reduce motion" preference: no animation, plain background.
  var prefersReducedMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var isCoarsePointer = window.matchMedia &&
    window.matchMedia('(pointer: coarse)').matches;

  if (!prefersReducedMotion) initVanta();

  // Mobile Safari often finishes layout after first paint; retry without touching desktop.
  if (isCoarsePointer) {
    window.addEventListener('load', bootVanta);
    window.addEventListener('pageshow', bootVanta);
    var vantaResizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(vantaResizeTimer);
      vantaResizeTimer = setTimeout(function () {
        if (prefersReducedMotion) return;
        if (vanta && typeof vanta.resize === 'function') vanta.resize();
        else bootVanta();
      }, 250);
    });
  }

  /* ── Chat input placeholder follows the active language ── */
  var CHAT_PLACEHOLDERS = { en: 'Ask me anything…', zh: '问我任何问题…' };

  function setChatPlaceholder() {
    var t = document.getElementById('chat-textarea');
    if (!t) return;
    var lang = document.documentElement.getAttribute('data-lang') || 'zh';
    t.placeholder = CHAT_PLACEHOLDERS[lang] || CHAT_PLACEHOLDERS.en;
  }

  /* ── Theme toggle (mirrors src/lib/theme.ts) ── */
  (function () {
    var btn = document.getElementById('theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') || 'dark';
      var next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      // Swap the animation to the new theme's palette.
      if (!prefersReducedMotion) initVanta();
    });
  })();

  /* ── Language toggle (mirrors src/lib/lang.ts) ── */
  (function () {
    var btn = document.getElementById('lang-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-lang') || 'zh';
      var next = current === 'zh' ? 'en' : 'zh';
      document.documentElement.setAttribute('data-lang', next);
      try { localStorage.setItem('lang', next); } catch (e) {}
      setChatPlaceholder();
    });
  })();

  /* ── Assistant "think" trace dropdown ──
     Splits <think>...</think> from the rest of an assistant message and
     renders the trace inside a <details> block. The open/closed state is
     persisted in localStorage so the user's choice survives a refresh.
  */
  function parseThink(text) {
    var s = String(text == null ? '' : text);
    var openIdx = s.indexOf('<think>');
    if (openIdx < 0) return { pre: s, think: null, body: '' };
    var pre = s.slice(0, openIdx);
    var afterOpen = s.slice(openIdx + '<think>'.length);
    var closeIdx = afterOpen.indexOf('</think>');
    if (closeIdx < 0) return { pre: pre, think: afterOpen, body: '' };
    return {
      pre: pre,
      think: afterOpen.slice(0, closeIdx),
      // Strip leading whitespace (the "\n\n" Agent emits after </think>) so
      // .chat-body displays the first character flush against the left edge.
      body: afterOpen.slice(closeIdx + '</think>'.length).replace(/^\s+/, '')
    };
  }

  var THINK_OPEN_KEY = 'think_open';
  function getThinkOpen() {
    try {
      var v = localStorage.getItem(THINK_OPEN_KEY);
      // Default: open. The user can collapse it, and the choice persists.
      if (v == null) return true;
      return v === '1';
    } catch (e) { return true; }
  }
  function setThinkOpen(open) {
    try { localStorage.setItem(THINK_OPEN_KEY, open ? '1' : '0'); } catch (e) {}
  }

  // Replaces the content of `parent` (a .chat-message) with the think details
  // + chat-body for the given text. Preserves any existing first child (the
  // role label) so this works both for one-shot rendering and for incremental
  // re-renders during a streaming response.
  function renderMessageContent(parent, content) {
    while (parent.childNodes.length > 1) {
      parent.removeChild(parent.lastChild);
    }
    var parts = parseThink(content || '');
    if (parts.think != null) {
      var details = document.createElement('details');
      details.className = 'chat-think';
      if (getThinkOpen()) details.open = true;
      details.addEventListener('toggle', function () { setThinkOpen(details.open); });
      var summary = document.createElement('summary');
      // Lucide chevron-down (24x24 stroke SVG). Rotated 180° via CSS when
      // <details> is open so the same icon doubles as chevron-up.
      var chevron = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      chevron.setAttribute('class', 'chat-think-chevron');
      chevron.setAttribute('viewBox', '0 0 24 24');
      chevron.setAttribute('fill', 'none');
      chevron.setAttribute('stroke', 'currentColor');
      chevron.setAttribute('stroke-width', '2');
      chevron.setAttribute('stroke-linecap', 'round');
      chevron.setAttribute('stroke-linejoin', 'round');
      var chevronPath = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      chevronPath.setAttribute('d', 'm6 9 6 6 6-6');
      chevron.appendChild(chevronPath);
      summary.appendChild(chevron);
      summary.appendChild(document.createTextNode('think'));
      details.appendChild(summary);
      var thinkBody = document.createElement('div');
      thinkBody.className = 'chat-think-body';
      thinkBody.textContent = parts.think;
      details.appendChild(thinkBody);
      parent.appendChild(details);
    }
    var bodyDiv = document.createElement('div');
    bodyDiv.className = 'chat-body';
    bodyDiv.textContent = parts.pre + parts.body;
    parent.appendChild(bodyDiv);
    var copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'chat-message-copy';
    copyBtn.setAttribute('aria-label', 'Copy');
    copyBtn.setAttribute('title', 'Copy');
    copyBtn.appendChild(copyIcon());
    parent.appendChild(copyBtn);
  }

  function createMessageEl(msg) {
    var div = document.createElement('div');
    div.className = 'chat-message'
      + (msg.role === 'user' ? ' chat-message-user' : '')
      + (msg.mock ? ' chat-message-mock' : '');
    var roleEl = document.createElement('span');
    roleEl.className = 'chat-role';
    roleEl.textContent = msg.role === 'user' ? 'You' : (msg.mock ? 'Agent (Mock)' : 'Agent');
    div.appendChild(roleEl);
    renderMessageContent(div, msg.content);
    return div;
  }

  /* ── Chat — wired to the Storage Service API ──
     Frontend → HTTP API (/api/sessions/{id}/...) → StorageService → Redis / PostgreSQL / pgvector.
     No Agent / LLM in this phase; the backend returns a clearly-marked MOCK reply.
  */
  (function () {
    var textarea = document.getElementById('chat-textarea');
    var sendBtn = document.getElementById('chat-send');
    var messages = document.getElementById('messages');
    var composer = document.getElementById('composer-card');
    var composerWrap = document.querySelector('.chat-composer');
    if (!textarea || !sendBtn) return;
    setChatPlaceholder();

    // Focus halo: fade the glass backdrop to transparent around the input.
    var page = document.querySelector('.page');
    var inputBox = textarea.closest('.chat-input');
    if (page && inputBox) {
      inputBox.addEventListener('focusin', function () { page.classList.add('chat-focus'); });
      inputBox.addEventListener('focusout', function () { page.classList.remove('chat-focus'); });
    }

    // API_BASE is set at the top of this file.


    // Session id persisted in localStorage so a page refresh restores the same session.
    var sessionId = (function () {
      try {
        var existing = localStorage.getItem(SESSION_KEY);
        if (existing) return existing;
        var fresh = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
        localStorage.setItem(SESSION_KEY, fresh);
        return fresh;
      } catch (e) {
        return String(Date.now());
      }
    })();

    var sending = false;

    function autogrow() {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }

    function updateSend() {
      sendBtn.disabled = sending || textarea.value.trim().length === 0;
    }

    // msg: { role: 'user'|'assistant', content: string, mock?: boolean }
    function addMessage(msg) {
      if (!messages) return;
      messages.appendChild(createMessageEl(msg));
      messages.scrollTop = messages.scrollHeight;
    }

    function render(list) {
      if (!messages) return;
      messages.textContent = '';
      (list || []).forEach(addMessage);
    }

    function restoreSession() {
      var sid;
      try { sid = localStorage.getItem(SESSION_KEY) || sessionId; }
      catch (e) { sid = sessionId; }
      sessionId = sid;
      apiFetch('/api/sessions/' + sid)
        .then(function (r) {
          if (r.status === 401) return null;
          if (r.status === 404) {
            var fresh = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
            try { localStorage.setItem(SESSION_KEY, fresh); } catch (e) {}
            sessionId = fresh;
            render([]);
            return null;
          }
          return r.ok ? r.json() : null;
        })
        .then(function (data) {
          if (data) render(data.messages);
          restoreHitlForSession(sessionId);
        })
        .catch(function (err) {
          console.error('[chat] failed to restore session:', err);
          addMessage({ role: 'assistant', mock: true, content: '[Storage service unreachable — is the backend running?]' });
        });
    }

    window.addEventListener(AUTH_EVENT, restoreSession);

    function currentSid() {
      try { return localStorage.getItem(SESSION_KEY) || sessionId; }
      catch (e) { return sessionId; }
    }

    function hitlKey(sid) { return 'hitl:' + sid; }
    function runWhateverKey(sid) { return 'run_whatever:' + sid; }

    function loadHitl(sid) {
      try {
        var raw = localStorage.getItem(hitlKey(sid));
        if (!raw) return null;
        var parsed = JSON.parse(raw);
        if (!parsed || !parsed.run_id || !Array.isArray(parsed.pending)) return null;
        return parsed;
      } catch (e) { return null; }
    }

    function saveHitl(sid, payload) {
      try { localStorage.setItem(hitlKey(sid), JSON.stringify(payload)); } catch (e) {}
    }

    function clearHitl(sid) {
      try { localStorage.removeItem(hitlKey(sid)); } catch (e) {}
    }

    function isRunWhatever(sid) {
      try { return localStorage.getItem(runWhateverKey(sid)) === '1'; }
      catch (e) { return false; }
    }

    function setRunWhatever(sid, on) {
      try {
        if (on) localStorage.setItem(runWhateverKey(sid), '1');
        else localStorage.removeItem(runWhateverKey(sid));
      } catch (e) {}
    }

    function hideComposerCard() {
      if (!composer) return;
      composer.hidden = true;
      composer.textContent = '';
      composer.className = 'composer-card';
      if (composerWrap) composerWrap.classList.remove('composer-open');
    }

    function showComposerCard(kind) {
      if (!composer) return;
      composer.hidden = false;
      composer.className = 'composer-card composer-card-' + kind;
      composer.textContent = '';
      if (composerWrap) composerWrap.classList.add('composer-open');
    }

    function isHitlCardOpen() {
      return !!(composer && !composer.hidden && composer.classList.contains('composer-card-hitl'));
    }

    function addComposerOption(label, hint, onClick) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'composer-option';
      var title = document.createElement('span');
      title.textContent = label;
      btn.appendChild(title);
      if (hint) {
        var hintEl = document.createElement('span');
        hintEl.className = 'composer-option-hint';
        hintEl.textContent = hint;
        btn.appendChild(hintEl);
      }
      btn.addEventListener('click', onClick);
      composer.appendChild(btn);
      return btn;
    }

    var SLASH_COMMANDS = [
      { cmd: '/run-whatever', hint: '跳过审批，自动执行页面修改' }
    ];

    function matchingSlash(text) {
      if (!text || text.charAt(0) !== '/') return [];
      var q = text.toLowerCase();
      return SLASH_COMMANDS.filter(function (item) {
        return item.cmd.indexOf(q) === 0;
      });
    }

    function updateSlashMenu() {
      if (isHitlCardOpen()) return;
      var matches = matchingSlash(textarea.value);
      if (!matches.length) {
        if (composer && composer.classList.contains('composer-card-slash')) hideComposerCard();
        return;
      }
      showComposerCard('slash');
      matches.forEach(function (item) {
        addComposerOption(item.cmd, item.hint, function () {
          textarea.value = item.cmd;
          hideComposerCard();
          send();
        });
      });
    }

    function removeHitlCards() {
      if (isHitlCardOpen()) hideComposerCard();
    }

    function showHitlCard(payload) {
      var pending = payload.pending || [];
      var summaries = [];
      pending.forEach(function (item) {
        if (item.summary) summaries.push(item.summary);
      });
      showComposerCard('hitl');
      if (summaries.length) {
        var summaryEl = document.createElement('div');
        summaryEl.className = 'composer-summary';
        summaryEl.textContent = summaries.join('\n');
        composer.appendChild(summaryEl);
      }
      var options = [
        { label: '同意', hint: '在当前页执行修改', action: 'approve' },
        { label: '拒绝', hint: '不改页面，把拒绝发给 Agent', action: 'reject' },
        { label: 'run-whatever', hint: '本次执行，之后也跳过审批', action: 'run-whatever' }
      ];
      options.forEach(function (opt) {
        addComposerOption(opt.label, opt.hint, function () {
          var buttons = composer.querySelectorAll('button');
          for (var i = 0; i < buttons.length; i++) buttons[i].disabled = true;
          resumeHitl(currentSid(), payload, opt.action);
        });
      });
    }

    function resultsForPending(pending, rejected) {
      return (pending || []).map(function (item) {
        if (rejected) {
          return {
            tool_call_id: item.tool_call_id,
            content: '用户拒绝修改页面',
            outcome: 'rejected'
          };
        }
        var outcome = 'ok';
        var content;
        try {
          var value = eval(item.code); // current page — must not be an isolated iframe
          content = value === undefined ? 'undefined' : String(value);
        } catch (err) {
          outcome = 'error';
          content = err && err.message ? err.message : String(err);
        }
        return { tool_call_id: item.tool_call_id, content: content, outcome: outcome };
      });
    }

    function restoreHitlForSession(sid) {
      removeHitlCards();
      var saved = loadHitl(sid);
      if (!saved) {
        sending = false;
        updateSend();
        return;
      }
      sending = true;
      updateSend();
      showHitlCard(saved);
    }

    function handleInterrupt(evt) {
      var sid = currentSid();
      var payload = { run_id: evt.run_id, pending: evt.pending || [] };
      saveHitl(sid, payload);
      sending = true;
      updateSend();
      if (isRunWhatever(sid)) {
        resumeHitl(sid, payload, 'approve');
        return;
      }
      showHitlCard(payload);
    }

    function resumeHitl(sid, payload, action) {
      if (action === 'run-whatever') setRunWhatever(sid, true);
      var results = resultsForPending(payload.pending, action === 'reject');
      removeHitlCards();
      clearHitl(sid);
      sending = true;
      updateSend();
      streamAgent('/api/sessions/' + sid + '/resume', {
        run_id: payload.run_id,
        results: results
      });
    }

    window.addEventListener('chat:session-changed', function (e) {
      var sid = e && e.detail && e.detail.sessionId;
      if (!sid) return;
      sessionId = sid;
      restoreHitlForSession(sid);
    });

    // Parse an SSE stream from a ReadableStream reader.
    // onMessage(json) receives parsed JSON from `data:` lines.
    // The terminator `[DONE]` resolves; `event: error` rejects.
    // `event: interrupt` calls onInterrupt and resolves — it is not a failure.
    function readSSE(reader, onMessage, onError, onLoop, onInterrupt) {
      var decoder = new TextDecoder('utf-8');
      var buffer = '';
      function pump() {
        return reader.read().then(function (res) {
          if (res.done) return;
          buffer += decoder.decode(res.value, { stream: true });
          // SSE events are separated by a blank line.
          var parts = buffer.split('\n\n');
          buffer = parts.pop(); // keep the trailing partial
          for (var i = 0; i < parts.length; i++) {
            var block = parts[i];
            var eventName = 'message';
            var dataLines = [];
            var lines = block.split('\n');
            for (var j = 0; j < lines.length; j++) {
              var line = lines[j];
              if (line.indexOf('event:') === 0) eventName = line.slice(6).trim();
              else if (line.indexOf('data:') === 0) dataLines.push(line.slice(5).trim());
            }
            var data = dataLines.join('\n');
            if (!data) continue;
            if (data === '[DONE]') return;  // resolve
            var json = null;
            try { json = JSON.parse(data); } catch (e) { continue; }
            if (eventName === 'error') throw { sseError: true, payload: json };
            if (eventName === 'interrupt') {
              if (onInterrupt) onInterrupt(json);
              return;
            }
            if (eventName === 'loop') {
              if (onLoop) onLoop(json);
              continue;
            }
            onMessage(json);
          }
          return pump();
        });
      }
      return pump();
    }

    function streamAgent(path, body) {
      var bubble = document.createElement('div');
      bubble.className = 'chat-message';
      var roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = 'Agent';
      bubble.appendChild(roleEl);
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
      var assistantText = '';

      function failAndCleanup(reason) {
        bubble.remove();
        console.error('[chat] send failed:', reason);
        addMessage({ role: 'assistant', mock: true, content: '[Send failed — ' + reason + ']' });
        sending = false;
        updateSend();
      }

      return apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function (r) {
          if (r.status === 401) throw new Error('not authenticated');
          if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
          var interruptEvt = null;
          return readSSE(
            r.body.getReader(),
            function onMessage(evt) {
              if (evt && typeof evt.delta === 'string') {
                assistantText += evt.delta;
                renderMessageContent(bubble, assistantText);
                messages.scrollTop = messages.scrollHeight;
              } else if (evt && evt.done && evt.message) {
                assistantText = evt.message.content || '';
                renderMessageContent(bubble, assistantText);
              }
            },
            null,
            appendLoopEvent,
            function onInterrupt(evt) { interruptEvt = evt; }
          ).then(function () { return interruptEvt; });
        })
        .then(function (interruptEvt) {
          if (interruptEvt) {
            if (!assistantText) bubble.remove();
            handleInterrupt(interruptEvt);
            return;
          }
          sending = false;
          updateSend();
          textarea.focus();
          try { window.dispatchEvent(new CustomEvent('chat:message-sent')); } catch (e) {}
        })
        .catch(function (err) {
          if (err && err.sseError) {
            var payload = err.payload || {};
            var reason = payload.detail || payload.error || 'agent error';
            if (payload.status) reason = String(payload.status) + ' — ' + reason;
            failAndCleanup(reason);
          } else {
            failAndCleanup(err && err.message ? err.message : 'storage service unreachable');
          }
        });
    }

    function send() {
      var text = textarea.value.trim();
      if (!text || sending) return;
      var sid = currentSid();

      if (text === '/run-whatever') {
        var next = !isRunWhatever(sid);
        setRunWhatever(sid, next);
        addMessage({ role: 'user', content: text });
        textarea.value = '';
        textarea.style.height = 'auto';
        hideComposerCard();
        addMessage({
          role: 'assistant',
          mock: true,
          content: next
            ? '已开启 run-whatever：之后改页面将自动执行，不再弹出审批。再输入一次则关闭。'
            : '已关闭 run-whatever：之后改页面会再次弹出审批。'
        });
        updateSend();
        return;
      }

      sending = true;
      updateSend();
      addMessage({ role: 'user', content: text });
      // Clear the input immediately on send so the user can keep typing while
      // the agent streams its reply. The message text itself is already in the
      // chat history above.
      textarea.value = '';
      textarea.style.height = 'auto';
      hideComposerCard();
      clearLoopDebug();
      streamAgent('/api/sessions/' + sid + '/messages', { message: text });
    }

    textarea.addEventListener('input', function () {
      autogrow();
      updateSend();
      updateSlashMenu();
    });
    textarea.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        if (composer && !composer.hidden && composer.classList.contains('composer-card-slash')) {
          e.preventDefault();
          hideComposerCard();
        }
        return;
      }
      // Enter sends; Shift+Enter inserts a newline.
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!isHitlCardOpen()) {
          var matches = matchingSlash(textarea.value);
          if (matches.length === 1) textarea.value = matches[0].cmd;
        }
        send();
      }
    });
    sendBtn.addEventListener('click', send);
  })();

  /* ── Dynamic year (this page is static HTML so the server-side ${...} approach doesn't apply) ── */
  (function () {
    var el = document.getElementById('current-year');
    if (el) el.textContent = new Date().getFullYear();
  })();

  /* ── Sidebar — icon rail + session list grouped by recency ──
     Independent from the chat IIFE above: reads the same localStorage key and
     fetches its own session view on switch. Sends a `chat:message-sent` event
     after a successful send so the sidebar can refresh its `message_count`.
  */
  (function () {
    var SENT_EVENT = 'chat:message-sent';

    var sidebar = document.getElementById('sidebar');
    var sidebarList = document.getElementById('sidebar-list');
    var btnToggle = document.getElementById('btn-sidebar-toggle');
    var btnNew = document.getElementById('btn-new-session');
    var btnClose = document.getElementById('btn-sidebar-close');
    var btnNewInline = document.getElementById('btn-new-session-inline');
    var messagesEl = document.getElementById('messages');
    var SIDEBAR_OPEN_KEY = 'sidebar_open';
    if (!sidebar || !btnToggle || !btnNew) return;

    // Restore the open/closed state from the previous page load so the user's
    // choice survives a refresh. Load the session list eagerly (no toggle
    // handler fires here) so the panel isn't briefly empty.
    if (localStorage.getItem(SIDEBAR_OPEN_KEY) === '1') {
      setSidebarOpen(true);
    }

    function currentSessionId() {
      try { return localStorage.getItem(SESSION_KEY); }
      catch (e) { return null; }
    }

    function setCurrentSessionId(id) {
      try { localStorage.setItem(SESSION_KEY, id); } catch (e) {}
    }

    // Backend returns "YYYY-MM-DDTHH:MM:SS[.fff]" without a timezone suffix;
    // treat it as UTC so JS computes day-buckets against the same wall clock
    // the user sees locally.
    function parseTime(s) {
      if (!s) return 0;
      var needsZ = s.charAt(s.length - 1) !== 'Z' && s.indexOf('+') < 0;
      return new Date(needsZ ? s + 'Z' : s).getTime();
    }

    function escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function truncate(s, n) {
      if (!s) return '新会话';
      return s.length > n ? s.slice(0, n) + '…' : s;
    }

    function renderMessage(msg) {
      if (!messagesEl || !msg) return;
      messagesEl.appendChild(createMessageEl(msg));
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function renderMessages(list) {
      if (!messagesEl) return;
      messagesEl.textContent = '';
      (list || []).forEach(renderMessage);
    }

    function loadSessionIntoView(sessionId) {
      if (!sessionId) { renderMessages([]); return; }
      apiFetch('/api/sessions/' + encodeURIComponent(sessionId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          renderMessages((data && data.messages) || []);
          try {
            window.dispatchEvent(new CustomEvent('chat:session-changed', {
              detail: { sessionId: sessionId }
            }));
          } catch (e) {}
        })
        .catch(function () { renderMessages([]); });
    }

    function highlightActive() {
      var cur = currentSessionId();
      var items = sidebarList.querySelectorAll('.sidebar-item');
      for (var i = 0; i < items.length; i++) {
        if (items[i].getAttribute('data-session-id') === cur) items[i].classList.add('active');
        else items[i].classList.remove('active');
      }
    }

    function bucketize(sessions) {
      var now = new Date();
      var startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      var sevenDaysAgo = startOfToday - 7 * 24 * 60 * 60 * 1000;
      var thirtyDaysAgo = startOfToday - 30 * 24 * 60 * 60 * 1000;
      var groups = { today: [], sevenDays: [], thirtyDays: [] };
      (sessions || []).forEach(function (s) {
        var t = parseTime(s.created_at);
        if (t >= startOfToday) groups.today.push(s);
        else if (t >= sevenDaysAgo) groups.sevenDays.push(s);
        else if (t >= thirtyDaysAgo) groups.thirtyDays.push(s);
        // > 30 days: not shown (per the three-bucket spec)
      });
      return groups;
    }

    function renderSidebar(sessions) {
      if (!sidebarList) return;
      var groups = bucketize(sessions);
      var html = '';
      var sections = [
        { key: 'today', label: '今天' },
        { key: 'sevenDays', label: '7 天内' },
        { key: 'thirtyDays', label: '30 天内' }
      ];
      sections.forEach(function (sec) {
        var items = groups[sec.key];
        if (!items.length) return;
        html += '<div class="sidebar-group">';
        html += '<div class="sidebar-group-title">' + escapeHtml(sec.label) + '</div>';
        items.forEach(function (s) {
          var title = truncate(s.title, 30);
          html += '<button class="sidebar-item" type="button" '
            + 'data-session-id="' + escapeHtml(s.session_id) + '" '
            + 'title="' + escapeHtml(s.title || '新会话') + '">'
            + escapeHtml(title) + '</button>';
        });
        html += '</div>';
      });
      if (!html) html = '<div class="sidebar-empty">暂无最近会话</div>';
      sidebarList.innerHTML = html;
      highlightActive();
    }

    function loadSidebar() {
      apiFetch('/api/me/sessions')
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (data) { renderSidebar(data || []); })
        .catch(function (err) {
          console.error('[sidebar] list failed:', err);
          if (sidebarList) sidebarList.innerHTML = '<div class="sidebar-empty">无法加载会话列表</div>';
        });
    }

    function switchTo(sessionId) {
      if (!sessionId) return;
      setCurrentSessionId(sessionId);
      loadSessionIntoView(sessionId);
      loadSidebar(); // refresh active highlight + counts
    }

    function toggleSidebar() {
      var open = !sidebar.classList.contains('open');
      setSidebarOpen(open);
      if (open) loadSidebar();
    }

    function setSidebarOpen(open) {
      sidebar.classList.toggle('open', open);
      sidebar.setAttribute('aria-hidden', open ? 'false' : 'true');
      document.body.classList.toggle('sidebar-open', open);
      try { localStorage.setItem(SIDEBAR_OPEN_KEY, open ? '1' : '0'); } catch (e) {}
    }

    function createNewSession() {
      if (btnNew.disabled) return;
      btnNew.disabled = true;
      apiFetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      })
        .then(function (r) {
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        })
        .then(function (data) {
          if (data && data.session_id) switchTo(data.session_id);
        })
        .catch(function (err) {
          console.error('[sidebar] create session failed:', err);
          window.alert('新建会话失败');
        })
        .then(function () { btnNew.disabled = false; });
    }

    btnToggle.addEventListener('click', toggleSidebar);
    btnNew.addEventListener('click', createNewSession);
    if (btnClose) btnClose.addEventListener('click', function () { setSidebarOpen(false); });
    if (btnNewInline) btnNewInline.addEventListener('click', createNewSession);
    sidebarList.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('.sidebar-item');
      if (!btn) return;
      var sid = btn.getAttribute('data-session-id');
      if (sid) switchTo(sid);
    });
    // Refresh message_count after a chat send. The chat IIFE above dispatches
    // this event on successful send; refresh only — don't touch current view.
    window.addEventListener(SENT_EVENT, function () { if (sidebar.classList.contains('open')) loadSidebar(); });
    window.addEventListener(AUTH_EVENT, function () {
      if (sidebar.classList.contains('open')) loadSidebar();
    });
  })();

  /* ── Copy button (event delegation so streaming re-renders keep working) ── */
  (function () {
    var messagesEl = document.getElementById('messages');
    if (!messagesEl) return;
    messagesEl.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('.chat-message-copy');
      if (!btn) return;
      e.preventDefault();
      var msg = btn.closest('.chat-message');
      var body = msg && msg.querySelector('.chat-body');
      var text = body ? (body.textContent || '') : '';
      copyText(text).then(function () { flashCopied(btn); });
    });
  })();

  /* ── Local loop inspector (right sidebar, localhost only) ── */
  (function () {
    showLoopDebugToggle();
    var toggle = document.getElementById('btn-loop-toggle');
    var closeBtn = document.getElementById('btn-loop-close');
    var clearBtn = document.getElementById('loop-debug-clear');
    var panel = document.getElementById('loop-debug');
    if (!isLocalHost() || !panel) return;
    if (toggle) {
      toggle.addEventListener('click', function () {
        setLoopDebugOpen(!panel.classList.contains('open'));
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener('click', function () { setLoopDebugOpen(false); });
    }
    if (clearBtn) clearBtn.addEventListener('click', clearLoopDebug);
    try {
      if (localStorage.getItem('loop_debug_open') === '1') setLoopDebugOpen(true);
    } catch (e) {}
  })();

  /* ── Email OTP (optional overlay; guests can chat without signing in) ── */
  (function () {
    var gate = document.getElementById('auth-gate');
    var form = document.getElementById('auth-form');
    var emailInput = document.getElementById('auth-email');
    var codeWrap = document.getElementById('auth-code-wrap');
    var codeInput = document.getElementById('auth-code');
    var errorEl = document.getElementById('auth-error');
    var submitBtn = document.getElementById('auth-submit');
    var loginBtn = document.getElementById('btn-login');
    var logoutBtn = document.getElementById('btn-logout');
    var closeBtn = document.getElementById('auth-close');
    if (!gate || !form || !emailInput || !submitBtn) return;

    var awaitingCode = false;

    function setAuthError(msg) {
      if (!errorEl) return;
      if (!msg) {
        errorEl.hidden = true;
        errorEl.textContent = '';
        return;
      }
      errorEl.hidden = false;
      errorEl.textContent = msg;
    }

    function setVerifyMode(on) {
      awaitingCode = on;
      if (codeWrap) codeWrap.hidden = !on;
      var sends = form.querySelectorAll('[data-auth-send]');
      var verifies = form.querySelectorAll('[data-auth-verify]');
      for (var i = 0; i < sends.length; i++) sends[i].hidden = on;
      for (var j = 0; j < verifies.length; j++) verifies[j].hidden = !on;
      if (on && codeInput) codeInput.focus();
    }

    function setAuthButtons(loggedIn) {
      if (loginBtn) loginBtn.hidden = loggedIn;
      if (logoutBtn) logoutBtn.hidden = !loggedIn;
    }

    function hideOverlay() {
      gate.hidden = true;
    }

    function showGate() {
      gate.hidden = false;
      setVerifyMode(false);
      setAuthError('');
      if (emailInput) emailInput.focus();
    }

    function enterGuestMode() {
      hideOverlay();
      setAuthButtons(false);
      try { window.dispatchEvent(new CustomEvent(AUTH_EVENT)); } catch (e) {}
    }

    function onLoggedIn() {
      hideOverlay();
      setAuthButtons(true);
      try { window.dispatchEvent(new CustomEvent(AUTH_EVENT)); } catch (e) {}
    }

    function clearChatUi() {
      var messagesEl = document.getElementById('messages');
      if (messagesEl) messagesEl.textContent = '';
      var list = document.getElementById('sidebar-list');
      if (list) list.innerHTML = '';
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var email = emailInput.value.trim();
      if (!email) return;
      setAuthError('');
      submitBtn.disabled = true;
      var path = awaitingCode ? '/api/auth/verify' : '/api/auth/request';
      var body = awaitingCode
        ? { email: email, code: (codeInput && codeInput.value.trim()) || '' }
        : { email: email };
      apiFetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, status: r.status, data: data };
          }).catch(function () {
            return { ok: r.ok, status: r.status, data: null };
          });
        })
        .then(function (res) {
          if (!res.ok) {
            setAuthError(apiErrorDetail(res.data, 'request failed (' + res.status + ')'));
            return;
          }
          if (awaitingCode) {
            clearChatUi();
            onLoggedIn();
            return;
          }
          setVerifyMode(true);
        })
        .catch(function (err) {
          setAuthError((err && err.message) || 'network error');
        })
        .then(function () { submitBtn.disabled = false; });
    });

    if (loginBtn) {
      loginBtn.addEventListener('click', showGate);
    }
    if (closeBtn) {
      closeBtn.addEventListener('click', hideOverlay);
    }
    gate.addEventListener('click', function (e) {
      if (e.target === gate) hideOverlay();
    });

    if (logoutBtn) {
      logoutBtn.addEventListener('click', function () {
        apiFetch('/api/auth/logout', { method: 'POST' })
          .catch(function () {})
          .then(function () {
            clearChatUi();
            enterGuestMode();
          });
      });
    }

    apiFetch('/api/me')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data && data.guest === false) onLoggedIn();
        else enterGuestMode();
      })
      .catch(function () { enterGuestMode(); });
  })();
})();
