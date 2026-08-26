(function () {
  'use strict';

  /* ── Animated Vanta cells background ── */

  // Per-theme cell palettes. color1/color2 = cell fill tones, backgroundColor = canvas backdrop.
  var THEMES = {
    light: { color1: 0x8fb4ec, color2: 0xc9d9f2, backgroundColor: 0xf8f5f0 },
    dark:  { color1: 0x6366f1, color2: 0x8b5cf6, backgroundColor: 0x0e0e11 }
  };

  var vanta = null;

  function currentTheme() {
    // Only light/dark are valid theme keys; anything else (e.g. a stale
    // 'auto'/'system' value in localStorage) falls back to dark.
    var t = document.documentElement.getAttribute('data-theme');
    return THEMES[t] ? t : 'dark';
  }

  // Builds the cells effect for the active theme. Destroying + rebuilding on theme
  // switch is simple and reliable (switches are rare, so the cost is negligible).
  function initVanta() {
    // Vanta is purely decorative. If WebGL/three.js fails (hardware acceleration
    // disabled, bad driver, etc.) it must never break the chat — so isolate it.
    try {
      var el = document.getElementById('vanta-bg');
      if (!el || !window.VANTA || !window.VANTA.CELLS) return;
      if (vanta) { vanta.destroy(); vanta = null; }
      vanta = window.VANTA.CELLS({
        el: el,
        mouseControls: true,
        touchControls: true,
        gyroControls: false,
        minHeight: 200,
        minWidth: 200,
        scale: 1.0,
        scaleMobile: 0.8,
        color1: THEMES[currentTheme()].color1,
        color2: THEMES[currentTheme()].color2,
        backgroundColor: THEMES[currentTheme()].backgroundColor
      });
    } catch (err) {
      console.warn('[vanta] init failed (decorative only):', err);
    }
  }

  // Respect the system "reduce motion" preference: no animation, plain background.
  var prefersReducedMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!prefersReducedMotion) initVanta();

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

  /* ── Chat — wired to the Storage Service API ──
     Frontend → HTTP API (/api/sessions/{id}/...) → StorageService → Redis / PostgreSQL / pgvector.
     No Agent / LLM in this phase; the backend returns a clearly-marked MOCK reply.
  */
  (function () {
    var textarea = document.getElementById('chat-textarea');
    var sendBtn = document.getElementById('chat-send');
    var messages = document.getElementById('messages');
    if (!textarea || !sendBtn) return;
    setChatPlaceholder();

    // Focus halo: fade the glass backdrop to transparent around the input.
    var page = document.querySelector('.page');
    var inputBox = textarea.closest('.chat-input');
    if (page && inputBox) {
      inputBox.addEventListener('focusin', function () { page.classList.add('chat-focus'); });
      inputBox.addEventListener('focusout', function () { page.classList.remove('chat-focus'); });
    }

    // Same origin: the backend serves both /api and the static frontend.
    var API_BASE = '';

    // Session id persisted in localStorage so a page refresh restores the same session.
    var SESSION_KEY = 'session_id';
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
      var div = document.createElement('div');
      div.className = 'chat-message' + (msg.mock ? ' chat-message-mock' : '');
      var roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = msg.role === 'user' ? 'You' : (msg.mock ? 'Agent (Mock)' : 'Agent');
      var bodyEl = document.createElement('div');
      bodyEl.className = 'chat-body';
      bodyEl.textContent = msg.content || '';
      div.appendChild(roleEl);
      div.appendChild(bodyEl);
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function render(list) {
      if (!messages) return;
      messages.textContent = '';
      (list || []).forEach(addMessage);
    }

    // Restore history for this session on page load (refresh → same session).
    fetch(API_BASE + '/api/sessions/' + sessionId)
      .then(function (r) { return r.json(); })
      .then(function (data) { render(data.messages); })
      .catch(function (err) {
        console.error('[chat] failed to restore session:', err);
        addMessage({ role: 'assistant', mock: true, content: '[Storage service unreachable — is the backend running?]' });
      });

    // Parse an SSE stream from a ReadableStream reader.
    // onMessage(json), onError(json) receive parsed JSON from `data:` lines.
    // The terminator `[DONE]` resolves; `event: error` rejects.
    function readSSE(reader, onMessage, onError) {
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
            onMessage(json);
          }
          return pump();
        });
      }
      return pump();
    }

    function send() {
      var text = textarea.value.trim();
      if (!text || sending) return;
      sending = true;
      updateSend();
      addMessage({ role: 'user', content: text });
      // Clear the input immediately on send so the user can keep typing while
      // the agent streams its reply. The message text itself is already in the
      // chat history above.
      textarea.value = '';
      textarea.style.height = 'auto';

      // Pre-create the assistant bubble so we can append text tokens into it.
      var bubble = document.createElement('div');
      bubble.className = 'chat-message';
      var roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = 'Agent';
      var bodyEl = document.createElement('div');
      bodyEl.className = 'chat-body';
      bubble.appendChild(roleEl);
      bubble.appendChild(bodyEl);
      messages.appendChild(bubble);
      messages.scrollTop = messages.scrollHeight;
      var assistantText = '';

      function failAndCleanup(reason) {
        bubble.remove();
        console.error('[chat] send failed:', reason);
        addMessage({ role: 'assistant', mock: true, content: '[Send failed — ' + reason + ']' });
      }

      fetch(API_BASE + '/api/sessions/' + sessionId + '/messages', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, user_id: 'user_demo' })
      })
        .then(function (r) {
          if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
          return readSSE(
            r.body.getReader(),
            function onMessage(evt) {
              if (evt && typeof evt.delta === 'string') {
                assistantText += evt.delta;
                bodyEl.textContent = assistantText;
                messages.scrollTop = messages.scrollHeight;
              } else if (evt && evt.done && evt.message) {
                // Server confirmed the final assistant message — replace the
                // streamed text with the authoritative copy from the server.
                assistantText = evt.message.content || '';
                bodyEl.textContent = assistantText;
              }
            },
            function onError(err) {
              failAndCleanup((err && err.payload && (err.payload.detail || err.payload.error)) || 'agent error');
            }
          );
        })
        .catch(function (err) {
          if (err && err.sseError) {
            failAndCleanup((err.payload && (err.payload.detail || err.payload.error)) || 'agent error');
          } else {
            failAndCleanup(err && err.message ? err.message : 'storage service unreachable');
          }
        })
        .then(function () {
          sending = false;
          updateSend();
          textarea.focus();
          // Notify the sidebar IIFE so its `message_count` can refresh.
          try { window.dispatchEvent(new CustomEvent('chat:message-sent')); } catch (e) {}
        });
    }

    textarea.addEventListener('input', function () {
      autogrow();
      updateSend();
    });
    textarea.addEventListener('keydown', function (e) {
      // Enter sends; Shift+Enter inserts a newline.
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
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
    var API_BASE = '';
    var USER_ID = 'user_demo';
    var SESSION_KEY = 'session_id';
    var SENT_EVENT = 'chat:message-sent';

    var sidebar = document.getElementById('sidebar');
    var sidebarList = document.getElementById('sidebar-list');
    var btnToggle = document.getElementById('btn-sidebar-toggle');
    var btnNew = document.getElementById('btn-new-session');
    var btnClose = document.getElementById('btn-sidebar-close');
    var btnNewInline = document.getElementById('btn-new-session-inline');
    var messagesEl = document.getElementById('messages');
    if (!sidebar || !btnToggle || !btnNew) return;

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
      var div = document.createElement('div');
      div.className = 'chat-message' + (msg.mock ? ' chat-message-mock' : '');
      var roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = msg.role === 'user' ? 'You' : (msg.mock ? 'Agent (Mock)' : 'Agent');
      var bodyEl = document.createElement('div');
      bodyEl.className = 'chat-body';
      bodyEl.textContent = msg.content || '';
      div.appendChild(roleEl);
      div.appendChild(bodyEl);
      messagesEl.appendChild(div);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function renderMessages(list) {
      if (!messagesEl) return;
      messagesEl.textContent = '';
      (list || []).forEach(renderMessage);
    }

    function loadSessionIntoView(sessionId) {
      if (!sessionId) { renderMessages([]); return; }
      fetch(API_BASE + '/api/sessions/' + encodeURIComponent(sessionId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { renderMessages((data && data.messages) || []); })
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
      fetch(API_BASE + '/api/users/' + encodeURIComponent(USER_ID) + '/sessions')
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
    }

    function createNewSession() {
      if (btnNew.disabled) return;
      btnNew.disabled = true;
      fetch(API_BASE + '/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: USER_ID })
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
  })();
})();
