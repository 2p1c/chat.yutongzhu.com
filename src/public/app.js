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
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  // Builds the cells effect for the active theme. Destroying + rebuilding on theme
  // switch is simple and reliable (switches are rare, so the cost is negligible).
  function initVanta() {
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

  /* ── Chat input (UI only for now — backend not wired yet) ── */
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

    function autogrow() {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }

    function updateSend() {
      sendBtn.disabled = textarea.value.trim().length === 0;
    }

    function addMessage(role, content) {
      if (!messages) return;
      var div = document.createElement('div');
      div.className = 'chat-message';
      var roleEl = document.createElement('span');
      roleEl.className = 'chat-role';
      roleEl.textContent = role === 'user' ? 'You' : 'Agent';
      var bodyEl = document.createElement('div');
      bodyEl.className = 'chat-body';
      bodyEl.textContent = content;
      div.appendChild(roleEl);
      div.appendChild(bodyEl);
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function send() {
      var text = textarea.value.trim();
      if (!text) return;
      addMessage('user', text);
      textarea.value = '';
      textarea.style.height = 'auto';
      updateSend();
      textarea.focus();
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
})();
