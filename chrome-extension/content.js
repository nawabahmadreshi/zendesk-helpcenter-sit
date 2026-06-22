/**
 * Aquera AI Help Widget
 * 
 * Self-contained, embeddable help widget that:
 * 1. Scans the DOM on page load for context (headings, buttons, tabs, integration_id)
 * 2. Pre-fetches contextual help from the AI backend
 * 3. Shows a floating help button that opens a panel with contextual tips
 * 4. Lets users ask follow-up questions answered via the Zendesk KB
 */
(function () {
  'use strict';
  
  // Secondary runtime domain check
  const isAquera = window.location.hostname.endsWith('aquera.com') || 
                   window.location.hostname.endsWith('aquera.io') || 
                   window.location.hostname === 'localhost' || 
                   window.location.hostname === '127.0.0.1';
  
  console.log('[Aquera] AI Widget Loading...', { hostname: window.location.hostname, isAquera });
  
  if (!isAquera) {
    console.log('[Aquera] Domain not authorized. Terminating.');
    return;
  }

  // ── SOTA: Console Log Capture ────────────────────────────────────
  class LogCapturer {
    constructor() {
      this.logs = [];
      this.limit = 20;
      this.setup();
    }
    setup() {
      ['log', 'error', 'warn', 'info'].forEach(method => {
        const original = console[method];
        console[method] = (...args) => {
          this.logs.push({
            level: method,
            ts: new Date().toLocaleTimeString(),
            text: args.map(a => (typeof a === 'object' ? JSON.stringify(a) : String(a))).join(' ').slice(0, 500)
          });
          if (this.logs.length > this.limit) this.logs.shift();
          original.apply(console, args);
        };
      });
    }
    getLogs() { return this.logs; }
  }
  const logCapturer = new LogCapturer();

  // ── SOTA: Browser-Native AI (window.ai) logic REMOVED ──────────
  const localAI = { available: false, summarize: async () => null };


  // --- Configuration ---
  const scriptTag = document.currentScript || document.querySelector('script[src*="widget.js"]');
  const API_URL = (scriptTag && scriptTag.getAttribute('data-api-url')) || 'http://127.0.0.1:8000';
  const POSITION = (scriptTag && scriptTag.getAttribute('data-position')) || 'bottom-right';
  const userId = 'user_' + Math.random().toString(36).substr(2, 9);

  // ── Shared Helpers ────────────────────────────────────────────────

  function getVersionConfidence(uV, aV) {
    if (!uV || !aV) return 0.5;
    if (uV === aV) return 1.0;
    const uM = uV.split('.')[0], aM = aV.split('.')[0];
    return uM === aM ? 0.8 : 0.2;
  }

  function getWidgetCSS() {
    return `
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

      :host {
        all: initial;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      }

      * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
      }

      .aq-help-container {
        position: fixed;
        z-index: 2147483647;
      }

      .aq-help-container.bottom-right { bottom: 30px; right: 30px; }
      .aq-help-container.bottom-left { bottom: 30px; left: 30px; }

      /* Floating Button */
      .aq-help-btn {
        display: flex; align-items: center; gap: 12px; padding: 14px 24px;
        background: #ffffff; color: #2563eb; border: 1px solid rgba(37, 99, 235, 0.3);
        border-radius: 4px; cursor: pointer; font-size: 15px; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.05em;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08), 0 0 20px rgba(37, 99, 235, 0.1);
        transition: all 0.4s cubic-bezier(0.19, 1, 0.22, 1);
        position: relative; overflow: hidden;
      }
      .aq-help-btn:hover { border-color: #2563eb; box-shadow: 0 15px 35px rgba(0, 0, 0, 0.12), 0 0 40px rgba(37, 99, 235, 0.2); transform: translateY(-2px); }

      /* Panel */
      .aq-help-panel {
        position: absolute; bottom: 100px; right: 0; width: 440px; height: 680px;
        background: #ffffff; border: 1px solid rgba(0, 0, 0, 0.1); border-radius: 12px;
        display: none; flex-direction: column; overflow: hidden;
        box-shadow: 0 20px 50px rgba(0, 0, 0, 0.15), 0 0 40px rgba(37, 99, 235, 0.05);
        transition: all 0.4s cubic-bezier(0.19, 1, 0.22, 1);
        opacity: 0; transform: translateY(20px) scale(0.95); pointer-events: none;
      }
      .aq-help-panel.open { display: flex; opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }

      .aq-help-content { flex: 1; padding: 0; overflow-y: auto; display: flex; flex-direction: column; }
      .aq-help-context-header { position: sticky; top: 0; z-index: 100; padding: 24px; background: #ffffff; border-bottom: 1px solid rgba(0, 0, 0, 0.05); box-shadow: 0 2px 10px rgba(0,0,0,0.02); }
      .aq-help-title { color: #111827; font-size: 20px; font-weight: 800; text-transform: uppercase; display: flex; align-items: center; gap: 10px; }
      .aq-help-title span { color: #2563eb; }
      .aq-help-subtitle { color: #6b7280; font-size: 11px; text-transform: uppercase; }

      .aq-help-chat-messages { padding: 24px; display: flex; flex-direction: column; gap: 20px; }
      .aq-help-msg { max-width: 85%; padding: 12px 16px; border-radius: 8px; font-size: 14px; line-height: 1.6; }
      .aq-help-msg.assistant { align-self: flex-start; background: #f3f4f6; border-left: 3px solid #2563eb; color: #111827; }
      .aq-help-msg.user { align-self: flex-end; background: #2563eb; color: #ffffff; font-weight: 500; }

      .aq-msg-meta { font-size: 10px; text-transform: uppercase; margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
      .aq-help-msg-content p { margin-bottom: 12px; }
      .aq-help-msg-content p:last-child { margin-bottom: 0; }

      .aq-help-panel-footer { padding: 16px 20px; background: #ffffff; border-top: 1px solid rgba(0, 0, 0, 0.08); display: flex; gap: 12px; }
      .aq-input-container { position: relative; flex: 1; display: flex; background: #f9fafb; border-radius: 4px; border: 1px solid rgba(0, 0, 0, 0.1); }
      .aq-help-input { background: transparent !important; border: none !important; flex: 1; padding: 12px 16px; color: #111827; font-size: 14px; outline: none; }
      .aq-help-send { width: 44px; height: 44px; background: #2563eb; border: none; border-radius: 4px; color: #ffffff; cursor: pointer; display: flex; align-items: center; justify-content: center; }

      /* Thumbs */
      .aq-thumbs { display: flex; gap: 8px; margin-top: 8px; }
      .aq-thumb-btn { background: none; border: 1px solid rgba(0,0,0,0.1); color: #6b7280; padding: 6px; border-radius: 4px; cursor: pointer; transition: 0.2s; }
      .aq-thumb-btn:hover { border-color: #2563eb; color: #2563eb; }
      .aq-thumb-btn.selected.up { color: #2563eb; border-color: #2563eb; background: rgba(37,99,235,0.1); }
      .aq-thumb-btn.selected.down { color: #ef4444; border-color: #ef4444; background: rgba(239,68,68,0.1); }

      /* Status/CRAG */
      .aq-status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 6px; }
      .aq-status-dot-green { background: #10b981; }
      .aq-status-dot-red { background: #ef4444; }
      .aq-crag-badge { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 4px; margin-top: 8px; width: fit-content; }
      .aq-crag-badge.high { background: rgba(37,99,235,0.1); color: #2563eb; border: 1px solid #2563eb; }

      /* Animation */
      .aq-help-loading { display: flex; gap: 4px; align-items: center; padding: 4px 0; }
      .aq-help-dot { width: 6px; height: 6px; background: #2563eb; border-radius: 50%; animation: pulse 1s infinite alternate; }
      .aq-help-dot:nth-child(2) { animation-delay: 0.2s; }
      .aq-help-dot:nth-child(3) { animation-delay: 0.4s; }
      @keyframes pulse { from { opacity: 0.4; transform: scale(0.8); } to { opacity: 1; transform: scale(1.1); } }
      .fetching .aq-help-title span { animation: glow 1.5s infinite alternate; }
      @keyframes glow { from { text-shadow: 0 0 5px rgba(37,99,235,0.3); } to { text-shadow: 0 0 15px rgba(37,99,235,0.6); } }

      /* Scanning Animation line */
      @keyframes aq-scanning {
        0% { transform: translateY(-100%); opacity: 0; }
        50% { opacity: 0.5; }
        100% { transform: translateY(100%); opacity: 0; }
      }
      .aq-scanner-line {
        position: absolute; top: 0; left: 0; width: 100%; height: 2px;
        background: linear-gradient(90deg, transparent, #2563eb, transparent);
        box-shadow: 0 0 15px #2563eb; animation: aq-scanning 2s infinite linear;
        pointer-events: none; z-index: 10; display: none;
      }
      .fetching .aq-scanner-line { display: block; }

      .aq-ghost-text {
        position: absolute; top: 12px; left: 16px; color: rgba(0, 0, 0, 0.3);
        font-size: 14px; pointer-events: none; white-space: pre; z-index: 1;
      }
      
      .aq-server-status {
        width: 8px; height: 8px; border-radius: 50%; background: #9ca3af;
        display: inline-block; margin-left: 8px; transition: 0.3s;
      }
      .aq-server-status.online { background: #10b981; box-shadow: 0 0 8px #10b981; }
      .aq-server-status.offline { background: #ef4444; }

      /* Contextual context card (immediate DOM data) */
      .aq-context-card {
        background: rgba(37, 99, 235, 0.04); border: 1px solid rgba(37, 99, 235, 0.15);
        border-radius: 8px; padding: 14px 16px; margin-bottom: 4px;
      }
      .aq-context-card-title {
        font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
        color: #2563eb; font-weight: 700; margin-bottom: 8px;
        display: flex; align-items: center; gap: 6px;
      }
      .aq-context-tag {
        display: inline-block; font-size: 11px; color: #4b5563;
        background: #f3f4f6; border: 1px solid #e5e7eb;
        border-radius: 4px; padding: 2px 8px; margin: 2px 3px 2px 0;
      }

      /* Action suggestion chips */
      .aq-suggestions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px 24px 4px; }
      .aq-suggestion-chip {
        font-size: 12px; padding: 6px 12px; border-radius: 4px;
        border: 1px solid rgba(37, 99, 235, 0.3); color: #2563eb;
        background: rgba(37, 99, 235, 0.05); cursor: pointer; transition: 0.2s;
        white-space: nowrap;
      }
      .aq-suggestion-chip:hover { background: rgba(37, 99, 235, 0.15); border-color: #2563eb; }

      /* AI response section label */
      .aq-section-label {
        font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em;
        color: #6b7280; font-weight: 600; padding: 8px 24px 4px; margin-top: 4px;
      }

      /* Inline Field Hints */
      .aq-inline-hint {
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        color: #2563eb;
        background: rgba(37, 99, 235, 0.04);
        border: 1px solid rgba(37, 99, 235, 0.1);
        border-radius: 4px;
        padding: 4px 8px;
        margin-top: 6px;
        display: flex;
        gap: 6px;
        align-items: flex-start;
        animation: fadeIn 0.5s ease;
        line-height: 1.4;
      }
      .aq-inline-hint span:first-child { font-weight: bold; }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(-5px); } to { opacity: 1; transform: translateY(0); } }
    `;
  }

  // --- Classes (Observability & Context) ---

  class EventTracker {
    constructor() { this.events = []; }
    addEvent(type, data) {
      this.events.push({ type, data, ts: Date.now() });
      if (this.events.length > 50) this.events.shift();
      console.log(`[Aquera Tracker] ${type}`, data);
    }
    getStream() { return this.events; }
  }

  class ActionEngine {
    execute(step) {
      console.log("ActionEngine executing:", step);
      const el = document.querySelector(step.target);
      if (!el) return false;
      if (step.action === 'click') { el.click(); return true; }
      if (step.action === 'fill') { el.value = step.value; el.dispatchEvent(new Event('input')); return true; }
      return false;
    }
  }

  class ContextScanner {
    constructor() { this.context = null; }
    scan() {
      const headings = Array.from(document.querySelectorAll('h1, h2, h3, [class*="heading"], [class*="title"]')).map(h => h.innerText.trim()).filter(t => t.length > 3);
      const buttons = Array.from(document.querySelectorAll('button, .btn, [role="button"]')).map(b => b.innerText.trim()).filter(t => t.length > 2).slice(0, 10);
      const integrationId = (document.querySelector('[data-integration-id]')?.getAttribute('data-integration-id')) || "";
      const breadcrumb = document.querySelector('[aria-label="breadcrumb"], [class*="breadcrumb"]')?.innerText.replace(/\n/g, ' > ').trim() || '';

      const modalEl = this.detectOpenModal();
      
      this.context = {
        page_title: document.title,
        url_path: window.location.pathname,
        headings: headings.slice(0, 5),
        buttons: buttons,
        integration_id: integrationId,
        breadcrumb: breadcrumb,
        is_modal: !!modalEl,
        modal_title: modalEl?.title || null,
        fields: this.collectFields(modalEl?.element || document.body),
        product_version: (document.querySelector('[data-app-version]')?.getAttribute('data-app-version')) || 'v14',
        buttons: buttons,
        nearby_text: this.getNearbyText(modalEl?.element || document.body),
        logs: logCapturer.getLogs() // SOTA: Diagnostic logs
      };
      return this.context;
    }

    getNearbyText(root) {
      // Get semantic text to ground the AI
      const main = root.querySelector('main, .main-content, #main-content, [role="main"]') || root;
      const text = main.innerText
        .slice(0, 5000)
        .replace(/\s+/g, ' ')
        .trim();
      return text.slice(0, 1000);
    }

    detectOpenModal() {
      const selectors = ['dialog[open]', '[role="dialog"]:not([hidden])', '[class*="modal"]:not([hidden])', '.MuiDialog-root'];
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && this.isVisible(el)) {
          const title = el.querySelector('h1, h2, h3, [class*="title"], [class*="heading"]')?.innerText?.trim() || 'Dialog';
          return { title, element: el };
        }
      }
      return null;
    }

    collectFields(root) {
      const fields = [];
      const inputs = root.querySelectorAll('input:not([type="hidden"]):not([type="submit"]), textarea, select, [role="textbox"]');
      for (const input of inputs) {
        if (!this.isVisible(input)) continue;
        const id = input.id || input.name || '';
        const label = this.getFieldLabel(input);
        if (label) fields.push({ id, label, required: input.required || input.getAttribute('aria-required') === 'true', type: input.type || 'text' });
      }
      return fields;
    }

    getFieldLabel(input) {
      if (input.id) {
        const lbl = document.querySelector(`label[for="${input.id}"]`);
        if (lbl) return lbl.innerText.replace('*', '').trim();
      }
      return input.getAttribute('aria-label') || input.placeholder || input.name || '';
    }

    isVisible(el) {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
    }
}

  // --- Global Instances ---
  const tracker = new EventTracker();
  const actionEngine = new ActionEngine();
  const scanner = new ContextScanner();

  // --- UI Helpers ---

  function renderMarkdown(text) {
    if (!text) return '';
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n\s*\*\s(.*?)(?=\n|$)/g, '<li>$1</li>')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');
  }

  function createWidget() {
    const host = document.createElement('div');
    host.id = 'aquera-ai-help-host';
    document.body.appendChild(host);

    const shadow = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = getWidgetCSS();
    shadow.appendChild(style);

    const container = document.createElement('div');
    container.className = 'aq-help-container ' + POSITION;
    shadow.appendChild(container);

    const btn = document.createElement('button');
    btn.className = 'aq-help-btn';
    btn.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
      Co-Pilot
    `;
    container.appendChild(btn);

    const panel = document.createElement('div');
    panel.className = 'aq-help-panel';
    panel.innerHTML = `
      <div class="aq-scanner-line"></div>
      <div class="aq-help-content">
        <div class="aq-help-context-header">
          <div class="aq-help-title">Aquera <span>AI</span> <div id="aq-server-status" class="aq-server-status" title="Server Checking..."></div></div>
          <div class="aq-help-subtitle">Contextual Intelligence</div>
        </div>
        <div class="aq-help-chat-messages"></div>
        <div class="aq-help-scroll-anchor"></div>
      </div>
      <div class="aq-help-panel-footer">
        <div class="aq-input-container">
          <span class="aq-ghost-text"></span>
          <input type="text" class="aq-help-input" placeholder="How can I help?">
        </div>
        <button class="aq-help-send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
      </div>
    `;
    container.appendChild(panel);

    return { shadow, btn, panel, input: panel.querySelector('.aq-help-input'), sendBtn: panel.querySelector('.aq-help-send'), messages: panel.querySelector('.aq-help-chat-messages') };
  }

  // --- Interaction Logic ---

  function initWidget() {
    const ui = createWidget();
    let isOpen = false;
    let chatHistory = [];

    ui.btn.onclick = () => {
      isOpen = !isOpen;
      ui.panel.classList.toggle('open', isOpen);
      if (isOpen) {
        ui.input.focus();
        runProactiveAnalysis('manual'); // Standardized on the new path
      }
    };

    // --- Proactive Intelligence ---
    let isFetching = false;
    async function runProactiveAnalysis(source = 'initial') {
        if (isFetching) return;
        isFetching = true;
        console.log(`[Aquera] ${source} analysis triggered.`);
        const ctx = scanner.scan();
        // Relaxed guard: Attempt analysis even on "empty" pages to provide general context
        // if (!ctx.headings.length && !ctx.is_modal && !ctx.fields.length) return;

        // Immediately update location badge if panel is open
        if (isOpen) updateLocationBadge(ctx.modal_title || ctx.headings[0] || ctx.page_title);

        // Show AI Thinking Indicator
        const loading = addMsg('assistant', null, true);
        ui.panel.classList.add('fetching');

        try {
            const fetchOptions = {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_id: userId,
                    page_type: ctx.integration_id ? 'integration' : 'general',
                    page_heading: ctx.headings[0] || '',
                    page_url: window.location.href,
                    breadcrumb: ctx.breadcrumb,
                    version: ctx.product_version,
                    fields: ctx.fields,
                    buttons: ctx.buttons,
                    nearby_text: ctx.nearby_text,
                    modal_title: ctx.modal_title,
                    is_modal: ctx.is_modal,
                    integration_id: ctx.integration_id
                })
            };

            let result = null;
            const fullUrl = API_URL + '/api/help/page_context';

            // Check if we can use the background proxy (Chrome Extension context)
            if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage) {
                console.log('[Aquera] Attempting proxy fetch via background script...', { url: fullUrl });
                const proxyResp = await new Promise(resolve => {
                    chrome.runtime.sendMessage({ type: 'FETCH_AI_HELP', url: fullUrl, options: fetchOptions }, (response) => {
                        console.log('[Aquera] Received response from background proxy:', response);
                        resolve(response);
                    });
                });
                if (proxyResp && proxyResp.ok) {
                    result = proxyResp.data;
                } else if (proxyResp && proxyResp.error) {
                    console.error('[Aquera] Background proxy reported error:', proxyResp.error);
                }
            } else {
                // Direct fetch (Standalone Widget mode)
                const resp = await fetch(fullUrl, fetchOptions);
                if (resp.ok) result = await resp.json();
            }


            if (!result) {
                throw new Error('Empty response from AI server');
            }

            removeMsg(loading);
            renderProactiveAnalysis(result, ctx);
            injectInlineHints(ctx.fields, result.field_hints);

            // AUTO-OPEN LOGIC
            const hasSeenIntro = localStorage.getItem('aq_intro_seen');
            const shouldPop = (source === 'initial' && !hasSeenIntro) || (source === 'modal');

            if (shouldPop && !isOpen) {
                isOpen = true;
                ui.panel.classList.add('open');
                if (source === 'initial') {
                    localStorage.setItem('aq_intro_seen', 'true');
                }
            }
        } catch (e) {
            removeMsg(loading);
            const errorMsg = e.message || 'Unknown network error';
            addMsg('assistant', `⚠️ **Connection Error**: ${errorMsg}. \\n\\n*Backend expected at: ${API_URL}*`);
            console.error('[Aquera] Proactive analysis failed:', e);
        } finally {
            ui.panel.classList.remove('fetching');
            isFetching = false;
        }
    }

    function updateLocationBadge(name) {
        // REMOVED at user request: I DONT NEED THIS : 📍 You are on:
        return;
    }

    function renderProactiveAnalysis(data, ctx) {
        // Clear previous analysis blocks
        ui.messages.querySelectorAll('[data-aq-type="proactive"]').forEach(el => el.remove());

        const block = document.createElement('div');
        block.setAttribute('data-aq-type', 'proactive');
        block.style.marginBottom = '20px';

        // 1. Summary Bubble
        const summary = document.createElement('div');
        summary.className = 'aq-help-msg assistant';
        summary.innerHTML = `<div style="display:flex; gap:8px; align-items:flex-start;">
            <div style="color:#2563eb; font-size:14px; margin-top:2px;">✦</div>
            <div class="aq-help-msg-content" style="flex:1;">
               ${renderMarkdown(data.page_summary)}
            </div>
        </div>`;
        block.appendChild(summary);

        // 2. Field Guide Table
        if (Object.keys(data.field_hints).length > 0) {
            const guide = document.createElement('div');
            guide.style.cssText = 'background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:12px; margin-top:12px; font-size:12px;';
            guide.innerHTML = ``;
            for (const [label, hint] of Object.entries(data.field_hints)) {
                const row = document.createElement('div');
                row.style.cssText = 'display:flex; gap:8px; margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid #f3f4f6;';
                row.innerHTML = `<span style="font-weight:600; color:#111827; min-width:80px;">${label}</span><span style="color:#4b5563;">${hint}</span>`;
                guide.appendChild(row);
            }
            block.appendChild(guide);
        }

        ui.messages.prepend(block);
        
        // 3. Update Suggestion Chips
        renderActionChips(data.quick_actions, ctx);
    }

    function renderActionChips(actions, ctx) {
        const existing = ui.panel.querySelector('.aq-suggestions');
        if (existing) existing.remove();

        const container = document.createElement('div');
        container.className = 'aq-suggestions';
        actions.forEach(a => {
            const chip = document.createElement('button');
            chip.className = 'aq-suggestion-chip';
            chip.textContent = a;
            chip.onclick = () => { ui.input.value = a; sendMessage(); };
            container.appendChild(chip);
        });
        ui.panel.querySelector('.aq-help-panel-footer').before(container);
    }

    function injectInlineHints(fields, hints) {
        fields.forEach(f => {
            const hint = hints[f.label] || hints[f.id];
            if (!hint || !f.id) return;
            const el = document.getElementById(f.id) || document.querySelector(`[name="${f.id}"]`);
            if (!el || el.parentNode.querySelector('.aq-inline-hint')) return;

            const hintEl = document.createElement('div');
            hintEl.className = 'aq-inline-hint';
            hintEl.style.cssText = 'font-size:11px; color:#2563eb; margin-top:4px; display:flex; gap:4px; align-items:flex-start;';
            hintEl.innerHTML = `<span>✦</span> <span>${hint}</span>`;
            el.parentNode.insertBefore(hintEl, el.nextSibling);
        });
    }

    // --- Modal Watcher ---
    function startModalWatcher() {
        const observer = new MutationObserver((mutations) => {
            for (const m of mutations) {
                for (const node of m.addedNodes) {
                    if (node.nodeType !== 1) continue;
                    if (node.hasAttribute('role') && node.getAttribute('role') === 'dialog' || node.classList.contains('modal')) {
                        runProactiveAnalysis('modal');
                        return;
                    }
                }
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }
    startModalWatcher();

    // Trigger initial analysis
    runProactiveAnalysis('initial');

    // --- Interaction Trigger ---
    let interactionTimeout = null;
    document.addEventListener('click', (e) => {
        // If they click a button, card, or tab, trigger a contextual refresh
        if (e.target.closest('button, a, .card, [role="tab"]')) {
            if (interactionTimeout) clearTimeout(interactionTimeout);
            interactionTimeout = setTimeout(() => {
                runProactiveAnalysis('interaction');
            }, 500);
        }
    });

    // --- Ghost Autocomplete Logic ---
    const ghostText = ui.panel.querySelector('.aq-ghost-text');
    let ghostCompletion = '';
    let autocompleteTimeout = null;

    ui.input.addEventListener('input', function() {
        const query = ui.input.value;
        ghostText.textContent = '';
        ghostCompletion = '';
        if (autocompleteTimeout) clearTimeout(autocompleteTimeout);
        if (!query || query.length < 2) return;

        autocompleteTimeout = setTimeout(() => {
            fetch(API_URL + '/api/help/autocomplete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query: query })
            })
            .then(r => r.json())
            .then(data => {
                if (data.ghost && ui.input.value === query) {
                    ghostCompletion = data.ghost;
                    ghostText.textContent = ui.input.value + ghostCompletion;
                }
            })
            .catch(() => {});
        }, 150);
    });

    ui.input.addEventListener('keydown', function(e) {
        if (e.key === 'Tab' && ghostCompletion) {
            e.preventDefault();
            ui.input.value += ghostCompletion;
            ghostText.textContent = '';
            ghostCompletion = '';
        }
    });

    // --- Server Health Monitor ---
    function checkHealth() {
        const statusDot = ui.panel.querySelector('#aq-server-status');
        if (!statusDot) return;
        fetch(API_URL + '/health')
            .then(r => r.json())
            .then(data => {
                const isOnline = data.ok || data.status === 'ok';
                statusDot.className = 'aq-server-status ' + (isOnline ? 'online' : 'offline');
                statusDot.title = isOnline ? 'AI Server Online' : 'AI Server Error';
            })
            .catch(() => {
                statusDot.className = 'aq-server-status offline';
                statusDot.title = 'AI Server Offline';
            });
    }
    checkHealth();
    setInterval(checkHealth, 30000);

    ui.sendBtn.onclick = () => sendMessage();
    ui.input.onkeydown = (e) => { if (e.key === 'Enter') sendMessage(); };

    // --- SPA Navigation Detection ---
    let lastUrl = window.location.href;
    function listenForNavigation() {
        const resetAndRefresh = () => {
            if (window.location.href === lastUrl) return; 
            console.log('[Aquera] URL Change detected. Resetting context...', { from: lastUrl, to: window.location.href });
            lastUrl = window.location.href;
            chatHistory = []; // Clear old session
            ui.messages.innerHTML = ''; // Clear UI
            runProactiveAnalysis('navigation');
        };

        // 1. Listen for browser back/forward
        window.addEventListener('popstate', resetAndRefresh);

        // 2. Wrap pushState/replaceState
        const originalPushState = history.pushState;
        history.pushState = function() {
            originalPushState.apply(this, arguments);
            resetAndRefresh();
        };

        const originalReplaceState = history.replaceState;
        history.replaceState = function() {
            originalReplaceState.apply(this, arguments);
            resetAndRefresh();
        };
    }
    listenForNavigation();

    async function sendMessage() {
      const q = ui.input.value.trim();
      if (!q) return;
      addMsg('user', q);
      ui.input.value = '';
      ghostText.textContent = '';
      
      const loading = addMsg('assistant', null, true);
      ui.panel.classList.add('fetching'); // Start premium scanner
      
      try {
        const resp = await fetch(API_URL + '/api/help/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: q, page_context: scanner.scan(), chat_history: chatHistory })
        });
        const data = await resp.json();
        removeMsg(loading);
        addMsg('assistant', data.response, false, data.article_id);
        chatHistory.push({ role: 'user', content: q }, { role: 'assistant', content: data.response });
      } catch (e) {
        removeMsg(loading);
        addMsg('assistant', 'Sorry, I am having trouble connecting to my brain.');
      } finally {
        ui.panel.classList.remove('fetching');
      }
    }


    function addMsg(role, content, isLoading, articleId) {
      const div = document.createElement('div');
      div.className = `aq-help-msg ${role}`;
      
      if (isLoading) {
        div.innerHTML = `<div style="display:flex; gap:8px; align-items:center;">
          <div style="color:#2563eb; font-size:14px;">✦</div>
          <div class="aq-help-loading"><div class="aq-help-dot"></div><div class="aq-help-dot"></div><div class="aq-help-dot"></div></div>
        </div>`;
      } else {
        let rawHtml = renderMarkdown(content);
        let finalHtml = rawHtml;
        
        if (role === 'assistant') {
           finalHtml = `<div style="display:flex; gap:8px; align-items:flex-start;">
              <div style="color:#2563eb; font-size:14px; margin-top:2px;">✦</div>
              <div class="aq-help-msg-content" style="flex:1;">${rawHtml}</div>
           </div>`;
        } else {
           finalHtml = `<div class="aq-help-msg-content">${rawHtml}</div>`;
        }

        if (articleId) {
          finalHtml += `<div class="aq-crag-badge high" style="margin-left: 22px;">Source: Knowledge Base</div>`;
        }
        div.innerHTML = finalHtml;
      }
      ui.messages.appendChild(div);
      div.scrollIntoView({ behavior: 'smooth' });
      return div;
    }

    function removeMsg(el) { if (el) el.remove(); }
  }

  // --- Start ---
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWidget);
  } else {
    initWidget();
  }

})();
