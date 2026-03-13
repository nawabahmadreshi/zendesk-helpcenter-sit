// content.js - Injected by the Chrome Extension
chrome.storage.sync.get({ apiUrl: 'http://localhost:8000' }, function(items) {
    window.__AQUERA_EXT_API_URL__ = items.apiUrl;
/**
 * Aquera AI Help Widget
 * 
 * Self-contained, embeddable help widget that:
 * 1. Scans the DOM on page load for context (headings, buttons, tabs, integration_id)
 * 2. Pre-fetches contextual help from the AI backend
 * 3. Shows a floating help button that opens a panel with contextual tips
 * 4. Lets users ask follow-up questions answered via the Zendesk KB
 *
 * Usage:
 *   <script src="/widget/widget.js" data-api-url="http://localhost:8000"></script>
 */
(function () {
  'use strict';
  
  // Inject Puter.js SDK if not present
  if (typeof puter === 'undefined') {
    const s = document.createElement('script');
    s.src = 'https://js.puter.com/v2/';
    document.head.appendChild(s);
  }

  // ── Configuration ─────────────────────────────────────────────────
  const scriptTag = document.currentScript;
  // USE THE EXTENSION CONFIGURED URL IF AVAILABLE
  const API_URL = window.__AQUERA_EXT_API_URL__ || (scriptTag && scriptTag.getAttribute('data-api-url')) || 'http://localhost:8000';
  const POSITION = (scriptTag && scriptTag.getAttribute('data-position')) || 'bottom-right';
  
  console.log('🚀 Aquera AI Widget: Script started with API_URL=', API_URL);

  // ── DOM Scanner ───────────────────────────────────────────────────

  function scanPageContext() {
    const context = {
      page_title: document.title || '',
      url_path: window.location.pathname || '',
      headings: [],        // from main content area
      buttons: [],         // from main content area
      tabs: [],            // from main content area
      form_labels: [],     // from main content area
      form_fields: [],     // NEW: detailed input metadata for auto-fill mapping
      descriptions: [],    // New: to capture paragraph/help text
      nav_items: [],       // from sidebar/nav (secondary)
      active_nav: '',      // New: to capture the currently selected/active nav item
      integration_id: '',
    };

    console.group('Aquera AI: Scanning Page Context');

    // ── STEP 1: Check for open modal/dialog/card — highest priority ──────
    const activeModal = document.querySelector(
      'dialog[open], .modal.show, .modal.in, .mat-dialog-container, ' +
      '.cdk-overlay-pane .mat-dialog-content, .cdk-overlay-pane, ' +
      '.ant-modal, .MuiDialog-root, [role="dialog"]:not([aria-hidden="true"]), ' +
      '.mat-drawer-opened, .mat-sidenav-opened, .offcanvas.show, ' +
      '.p-dialog, .ui-dialog, .p-sidebar, .ui-sidebar, .aq-modal, .card-overlay'
    );

    if (activeModal) {
      console.group('AI Help Context Scanner: Modal detected');
      const modalTitle = activeModal.querySelector('h1, h2, h3, .modal-title, .mat-dialog-title, .dialog-title, .offcanvas-title, [mat-dialog-title]');
      context.page_title = (modalTitle ? modalTitle.textContent.trim() : 'Active Card') + ' (Modal/Card)';
      _extractFromRoot(activeModal, context, false, '[MODAL] ');
      
      // Also scan background but flag it so AI knows it's out of focus
      const mainContent = document.querySelector('main, [role="main"], #main-content, .app-content, .main-container') || document.body;
      _extractFromRoot(mainContent, context, true, '[BACKGROUND] ');

      _extractIntegrationId(context);
      _deduplicate(context);
      console.log('Context Priority: Scanned Modal and Background');
      console.groupEnd();
      return context;
    }

    // ── STEP 2: Find the main content area (No Modal) ─────────────────────────────
    // Scan the entire body, but rely on `_isNavElement` and `_isVisible` to filter out generic layout fluff
    _extractFromRoot(document.body, context, true, '');

    // ── STEP 3: Separately capture navigation/sidebar items ─────────────
    const navRoots = document.querySelectorAll('nav, [role="navigation"], aside, .sidebar, .sidenav, mat-sidenav, .mat-sidenav, .nav-menu, .left-nav, .app-sidebar');
    navRoots.forEach(function(nav) {
      nav.querySelectorAll('a, button, [role="menuitem"], .nav-item, .menu-item, .mat-list-item').forEach(function(el) {
        if (el.closest('#aquera-ai-help-host')) return;
        const text = (el.textContent || el.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
        if (text && text.length < 60 && text.length > 1) {
          context.nav_items.push(text);
          // Detect if this nav item is active/selected
          if (el.classList.contains('active') || el.classList.contains('selected') || 
              el.classList.contains('current') || el.getAttribute('aria-selected') === 'true' ||
              el.getAttribute('aria-current') === 'page' || el.closest('.active, .selected, .current')) {
            context.active_nav = text;
          }
        }
      });
    });

    _extractIntegrationId(context);
    _deduplicate(context);
    console.log('Scan Complete:', context);
    console.groupEnd();
    return context;
  }

  // helper: extract elements from a given root into the context object
  function _extractFromRoot(root, context, excludeNav = false, prefix = '') {
    // 1. Headings
    root.querySelectorAll('h1, h2, h3, h4, [class*="header"], [class*="title"]').forEach(function(el) {
      if (excludeNav && _isNavElement(el)) return;
      if (!_isVisible(el)) return;
      const text = el.textContent.trim().replace(/\s+/g, ' ');
      if (text && text.length < 150 && text.length > 2) context.headings.push(prefix + text);
    });

    // 2. Buttons / Clickables
    root.querySelectorAll('button, [role="button"], a[role="button"], a.btn, .btn, .button, .mat-button, .mat-raised-button, .mat-flat-button, [class*="button"], [class*="btn"], input[type="button"], input[type="submit"]').forEach(function(el) {
      if (el.closest('#aquera-ai-help-host')) return;
      if (excludeNav && _isNavElement(el)) return;
      if (!_isVisible(el)) return;
      const text = (el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim().replace(/\s+/g, ' ');
      if (text && text.length < 80 && text.length > 1) context.buttons.push(prefix + text);
    });

    // 3. Tabs
    root.querySelectorAll('[role="tab"], .mat-tab-label, .nav-link, [mat-tab-link], .tab-item').forEach(function(el) {
      if (el.closest('#aquera-ai-help-host')) return;
      if (!_isVisible(el)) return;
      const text = el.textContent.trim();
      if (text && text.length < 80) context.tabs.push(prefix + text);
    });

    // 5. Broad Text Scanner (Greedy)
    root.querySelectorAll('p, span, div, li, .help-block, .description, .hint, .text-muted, .info-text').forEach(function(el) {
      if (el.closest('#aquera-ai-help-host')) return;
      if (excludeNav && _isNavElement(el)) return;
      
      // Don't capture text from common container wrappers that have child text already captured
      if (el.children.length > 5 && (el.tagName === 'DIV' || el.tagName === 'UL')) return;
      
      if (!_isVisible(el)) return;
      
      const text = el.textContent.trim().replace(/\s+/g, ' ');
      // Filter for meaningful content length (avoid icons/one-word labels)
      if (text && text.length > 15 && text.length < 1000) {
          // Check if it's already a heading or button to avoid duplication
          if (context.headings.indexOf(prefix + text) === -1 && context.buttons.indexOf(prefix + text) === -1) {
              context.descriptions.push(prefix + text);
          }
      }
    });

    // 4. Form Labels / Inputs
    root.querySelectorAll('label, .mat-form-field-label, .form-label, .aq-label, .field-label').forEach(function(el) {
      if (el.closest('#aquera-ai-help-host')) return;
      if (!_isVisible(el)) return;
      const text = el.textContent.trim().replace(/\s+/g, ' ');
      if (text && text.length < 150 && text.length > 1) context.form_labels.push(prefix + text);
    });

    // 6. Form Fields (detailed metadata for AI auto-fill)
    root.querySelectorAll('input:not([type="hidden"]):not([type="button"]):not([type="submit"]), textarea, select').forEach(function(el) {
      if (el.closest('#aquera-ai-help-host')) return;
      if (excludeNav && _isNavElement(el)) return;
      if (!_isVisible(el)) return;
      
      const fieldData = {
        tag: el.tagName.toLowerCase(),
        type: el.type || '',
        name: el.name || '',
        id: el.id || '',
        placeholder: el.placeholder || '',
        value: el.value || '',
      };
      // Only add if it has some identifiable trait
      if (fieldData.name || fieldData.id || fieldData.placeholder) {
          // find associated label if possible
          let labelText = '';
          if (fieldData.id) {
              const labelEl = document.querySelector(`label[for="${fieldData.id}"]`);
              if (labelEl) labelText = labelEl.textContent.trim();
          }
          if (!labelText && el.closest('label')) {
              labelText = el.closest('label').textContent.trim();
          }
          if (labelText) {
              fieldData.label = labelText.replace(/\s+/g, ' ');
          }
          context.form_fields.push(fieldData);
      }
    });
  }

  function _isVisible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    
    // Quick check for dimensions
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;

    // Check ancestors (up to 4 levels for performance/reliability)
    let parent = el.parentElement;
    let depth = 0;
    while (parent && depth < 4) {
        const pStyle = window.getComputedStyle(parent);
        if (pStyle.display === 'none' || pStyle.visibility === 'hidden') return false;
        parent = parent.parentElement;
        depth++;
    }
    return true;
  }

  // helper: check if element is inside a nav/aside (headers removed as they contain primary actions)
  function _isNavElement(el) {
    return !!(el.closest('nav') || el.closest('aside') ||
              el.closest('[role="navigation"]') || el.closest('.sidebar') || el.closest('.sidenav') ||
              el.closest('.left-nav') || el.closest('.app-sidebar'));
  }

  // helper: extract integration_id from multiple sources
  function _extractIntegrationId(context) {
    // 1. Check data attribute
    const integrationEl = document.querySelector('[data-integration-id]');
    if (integrationEl) { context.integration_id = integrationEl.getAttribute('data-integration-id'); return; }
    
    // 2. Check meta tag
    const meta = document.querySelector('meta[name="integration-id"]');
    if (meta) { context.integration_id = meta.getAttribute('content') || ''; return; }
    
    // 4. Match from FULL URL (more aggressive)
    const fullUrl = window.location.href;
    const anyIdMatch = fullUrl.match(/integration_id_([a-zA-Z0-9_-]{10,80})/i) || 
                       fullUrl.match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/i);
    if (anyIdMatch) { 
        context.integration_id = (anyIdMatch[0].startsWith('integration_id_') ? '' : 'integration_id_') + anyIdMatch[0];
        console.log('Context Priority: Extracted ID from Full URL:', context.integration_id);
    }

    // 5. Fallback: search page source for anything looking like an integration_id
    if (!context.integration_id) {
        const bodyText = document.body.innerText || '';
        const textMatch = bodyText.match(/integration_id_([a-zA-Z0-9_-]{10,80})/i);
        if (textMatch) { 
            context.integration_id = 'integration_id_' + textMatch[1].replace('integration_id_', ''); 
            console.log('Context Priority: Extracted ID from page text:', context.integration_id);
        }
    }

    // 6. Final Fallback: Check headings for UUIDs
    if (!context.integration_id) {
        context.headings.forEach(h => {
          const uuidMatch = h.match(/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/i);
          if (uuidMatch && !context.integration_id) {
            context.integration_id = 'integration_id_' + uuidMatch[1];
            console.log('Context Priority: Extracted ID from heading UUID:', context.integration_id);
          }
        });
    }
  }

  // helper: deduplicate all array fields
  function _deduplicate(context) {
    context.headings    = [...new Set(context.headings)].slice(0, 30);
    context.buttons     = [...new Set(context.buttons)].slice(0, 30);
    context.tabs        = [...new Set(context.tabs)].slice(0, 15);
    context.form_labels = [...new Set(context.form_labels)].slice(0, 30);
    context.descriptions = [...new Set(context.descriptions)].slice(0, 50);
    context.nav_items   = [...new Set(context.nav_items)].slice(0, 20);
  }


  // ── Simple Markdown Renderer ──────────────────────────────────────

  function renderMarkdown(text) {
    if (!text) return '';
    let html = text
      // Bold
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      // Italic
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      // Inline code
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      // Headers
      .replace(/^### (.+)$/gm, '<h4>$1</h4>')
      .replace(/^## (.+)$/gm, '<h3>$1</h3>')
      .replace(/^# (.+)$/gm, '<h2>$1</h2>')
      // Bullet points
      .replace(/^[\-\*] (.+)$/gm, '<li>$1</li>')
      // Links
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      // Line breaks
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>');

    // Wrap consecutive <li> in <ul>
    html = html.replace(/(<li>.*?<\/li>(?:<br>)?)+/g, function (match) {
      return '<ul>' + match.replace(/<br>/g, '') + '</ul>';
    });

    return '<p>' + html + '</p>';
  }

  // ── Widget UI (Shadow DOM) ────────────────────────────────────────

  function createWidget() {
    const host = document.createElement('div');
    host.id = 'aquera-ai-help-host';
    document.body.appendChild(host);

    const shadow = host.attachShadow({ mode: 'open' });

    // Inject styles
    const style = document.createElement('style');
    style.textContent = getWidgetCSS();
    shadow.appendChild(style);

    // Widget container
    const container = document.createElement('div');
    container.className = 'aq-help-container ' + POSITION;
    shadow.appendChild(container);

    // Floating button
    const btn = document.createElement('button');
    btn.className = 'aq-help-btn';
    btn.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
      <span class="aq-help-btn-label">AI Help</span>
    `;
    btn.setAttribute('aria-label', 'AI Help');
    container.appendChild(btn);

    // Panel
    const panel = document.createElement('div');
    panel.className = 'aq-help-panel';
    panel.innerHTML = `
      <div class="aq-help-panel-header">
        <div class="aq-help-panel-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 2L2 7l10 5 10-5-10-5z"></path>
            <path d="M2 17l10 5 10-5"></path>
            <path d="M2 12l10 5 10-5"></path>
          </svg>
          <span>Aquera AI Help</span>
        </div>
        <button class="aq-help-close" aria-label="Close">&times;</button>
      </div>
      <div class="aq-help-panel-body">
        <div class="aq-help-context-section">
          <div class="aq-help-context-label">Contextual Help</div>
          <div class="aq-help-context-content">
            <div class="aq-help-loading">
              <div class="aq-help-dot"></div>
              <div class="aq-help-dot"></div>
              <div class="aq-help-dot"></div>
            </div>
          </div>
        </div>
        <div class="aq-help-divider"></div>
        <div class="aq-help-chat-section">
          <div class="aq-help-chat-messages"></div>
        </div>
      </div>
      <div class="aq-help-panel-footer">
        <input type="text" class="aq-help-input" placeholder="Have a question? Ask here..." aria-label="Ask a question">
        <button class="aq-help-send" aria-label="Send">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
    `;
    container.appendChild(panel);

    return { shadow, container, btn, panel };
  }

  // ── Widget Logic ──────────────────────────────────────────────────

  function initWidget() {
    const { shadow, container, btn, panel } = createWidget();
    let isOpen = false;
    let contextLoaded = false;
    let chatHistory = [];
    let pageContext = null;
    let isFetchingContext = false;
    let lastFetchTime = 0;

    const contextContent = shadow.querySelector('.aq-help-context-content');
    const chatMessages = shadow.querySelector('.aq-help-chat-messages');
    const input = shadow.querySelector('.aq-help-input');
    const sendBtn = shadow.querySelector('.aq-help-send');
    const closeBtn = shadow.querySelector('.aq-help-close');

    // Toggle panel
    btn.addEventListener('click', function () {
      isOpen = !isOpen;
      panel.classList.toggle('open', isOpen);
      btn.classList.toggle('active', isOpen);
      if (isOpen) {
        // Always do a fresh scan when panel opens — context may have changed while closed
        fetchContextualHelp(true); // force=true
        contextLoaded = true;
        setTimeout(function () { input.focus(); }, 300);
      }
    });

    closeBtn.addEventListener('click', function () {
      isOpen = false;
      panel.classList.remove('open');
      btn.classList.remove('active');
    });

    // Send question
    function sendQuestion() {
      const question = input.value.trim();
      if (!question) return;

      // Add user message
      addChatMessage('user', question);
      input.value = '';

      // Add loading indicator
      const loadingId = addChatMessage('assistant', null, true);

      // Save to history
      chatHistory.push({ role: 'user', content: question });

      fetch(API_URL + '/api/help/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question,
          page_context: pageContext || scanPageContext(),
          chat_history: chatHistory,
        }),
      })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          removeChatMessage(loadingId);
          const answer = data.response || 'Sorry, I could not find an answer.';
          const articleId = data.article_id;
          addChatMessage('assistant', answer, false, articleId);
          chatHistory.push({ role: 'assistant', content: answer });
        })
        .catch(function (err) {
          console.error('AI Help backend failed, attempting Puter.js fallback...', err);
          
          if (typeof puter !== 'undefined') {
            puter.ai.chat(question)
              .then(function(res) {
                removeChatMessage(loadingId);
                const answer = res.toString() || 'Sorry, I could not find an answer.';
                addChatMessage('assistant', answer + '\n\n*(Answer via Puter AI Fallback)*', false);
                chatHistory.push({ role: 'assistant', content: answer });
              })
              .catch(function(pErr) {
                removeChatMessage(loadingId);
                addChatMessage('assistant', 'Unable to connect to AI services. Please check your connection.');
                console.error('Puter.js fallback failed:', pErr);
              });
          } else {
            removeChatMessage(loadingId);
            addChatMessage('assistant', 'Unable to connect to the AI service. Please try again.');
          }
        });
    }

    sendBtn.addEventListener('click', sendQuestion);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') sendQuestion();
    });

    function addChatMessage(role, content, isLoading, articleId) {
      const msg = document.createElement('div');
      msg.className = 'aq-help-msg aq-help-msg-' + role;
      const msgId = 'msg-' + Date.now();
      msg.id = msgId;

      if (isLoading) {
        msg.innerHTML = '<div class="aq-help-loading"><div class="aq-help-dot"></div><div class="aq-help-dot"></div><div class="aq-help-dot"></div></div>';
      } else {
        let html = role === 'user' ? '<span>' + escapeHtml(content) + '</span>' : renderMarkdown(content);
        
        // Add status dot for assistant messages
        if (role === 'assistant') {
          const statusClass = articleId ? 'aq-status-dot-green' : 'aq-status-dot-red';
          const statusTitle = articleId ? 'Backed by Knowledge Base' : 'General AI Response (No KB match)';
          // Add the dot as a child element later to avoid layout issues with innerHTML
          const dot = document.createElement('div');
          dot.className = `aq-status-dot ${statusClass}`;
          dot.setAttribute('title', statusTitle);
          msg.appendChild(dot);
        }
        
        const contentEl = document.createElement('div');
        contentEl.className = 'aq-help-msg-content';
        contentEl.innerHTML = html;
        msg.appendChild(contentEl);
      }
      chatMessages.appendChild(msg);
      chatMessages.scrollTop = chatMessages.scrollHeight;
      return msgId;
    }

    function removeChatMessage(id) {
      const el = shadow.getElementById(id);
      if (el) el.remove();
    }

    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    // Pre-fetch contextual help
    function fetchContextualHelp(force) {
      const now = Date.now();
      if (!force && isFetchingContext) return;
      if (!force && (now - lastFetchTime < 3000)) return; // Throttling: 3 seconds
      
      isFetchingContext = true;
      lastFetchTime = now;

      pageContext = scanPageContext();
      contextLoaded = true;

      console.log('Aquera AI: Sending context to server...', pageContext);
      fetch(API_URL + '/api/help/context', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          page_context: pageContext,
          chat_history: chatHistory
        }),
      })
        .then(function (r) { 
          console.log('Aquera AI: Server response status:', r.status);
          return r.json(); 
        })
        .then(function (data) {
          isFetchingContext = false;
          console.log('Aquera AI: Received response:', data);
          
          let contentHtml = renderMarkdown(data.response || 'No contextual help available.');
          
          if (data.article_title) {
            contentHtml += `
              <div class="aq-help-source-badge">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
                VERIFIED: ${escapeHtml(data.article_title)}
              </div>
            `;
          }

          // ** NEW: Render Proactive Action Suggestions **
          if (data.action_suggestions && Array.isArray(data.action_suggestions) && data.action_suggestions.length > 0) {
              contentHtml += '<div class="aq-action-suggestions-container">';
              contentHtml += '<div class="aq-action-header">Suggested Actions:</div>';
              
              data.action_suggestions.forEach((action, index) => {
                  // We encode the structured action object into the button's dataset
                  const encodedAction = escapeHtml(JSON.stringify(action));
                  contentHtml += `
                    <button class="aq-action-btn" data-action='${encodedAction}'>
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                      ${escapeHtml(action.label || 'Execute Action')}
                    </button>
                  `;
              });
              contentHtml += '</div>';
          }
          
          contextContent.innerHTML = contentHtml;
          contextContent.classList.add('loaded');
          
          // Attach event listeners to the new action buttons
          _attachActionListeners(contextContent);
        })
        .catch(function (err) {
          isFetchingContext = false;
          console.error(`Aquera AI: Context fetch failed for URL ${API_URL}/api/help/context`, err);
          contextContent.innerHTML = `<p class="aq-help-error">Unable to load contextual help. Is the AI server running at <strong>${API_URL}</strong>?</p>`;
          contextContent.classList.add('loaded');
        });
    }

    // --- NEW: Action Execution Engine ---
    function _attachActionListeners(container) {
        container.querySelectorAll('.aq-action-btn').forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                const actionStr = this.getAttribute('data-action');
                if (!actionStr) return;
                
                try {
                    const actionGroup = JSON.parse(actionStr);
                    this.innerHTML = '<div class="aq-help-dot"></div> Executing...';
                    this.style.opacity = '0.7';
                    this.style.pointerEvents = 'none';
                    
                    // The AI might return a single action or an array of steps
                    const steps = Array.isArray(actionGroup.steps) ? actionGroup.steps : [actionGroup];
                    
                    let successCount = 0;
                    steps.forEach(step => {
                        if (executeDOMAction(step)) successCount++;
                    });
                    
                    setTimeout(() => {
                        if (successCount === steps.length) {
                             this.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Complete';
                             this.style.backgroundColor = '#10b981'; // Green success
                             this.style.color = '#fff';
                        } else {
                             this.innerHTML = '⚠️ Partial Success';
                        }
                    }, 500);

                } catch (err) {
                    console.error('Aquera AI: Failed to parse or execute action', err);
                    this.innerHTML = 'Action Failed';
                }
            });
        });
    }

    function executeDOMAction(step) {
        console.log("Aquera AI: Executing step", step);
        const targetSelector = step.target;
        if (!targetSelector) return false;
        
        // Escape specific confusing characters if the AI suggests weird CSS selectors,
        // though it's safer to rely on IDs or name attributes.
        const el = document.querySelector(targetSelector);
        if (!el) {
            console.warn(`Aquera AI: Target element not found for selector: ${targetSelector}`);
            return false;
        }

        try {
            switch(step.action) {
                case 'fill_form':
                case 'fill_field':
                    el.value = step.value;
                    // Dispatch events so React/Angular/Vue recognize the change
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    // Try to trigger nice visuals
                    el.style.transition = 'box-shadow 0.3s ease, background-color 0.3s ease';
                    el.style.backgroundColor = '#ecfdf5'; // light green highlight
                    setTimeout(() => { el.style.backgroundColor = ''; }, 1500);
                    break;
                case 'click_button':
                case 'click':
                    el.click();
                    break;
                default:
                    console.warn(`Aquera AI: Unknown action type ${step.action}`);
                    return false;
            }
            return true;
        } catch (e) {
            console.error("Aquera AI: Action execution error", e);
            return false;
        }
    }

    // Auto-fetch on page load (background)
    setTimeout(function () {
      pageContext = scanPageContext();
    }, 1000);

    // Shared rescan logic 
    function attemptRescan(isUrlChange = false) {
      if (!isOpen) {
        pageContext = scanPageContext();
        return;
      }
      const newContext = scanPageContext();
      const currentSig = JSON.stringify(newContext);
      const oldSig = pageContext ? JSON.stringify(pageContext) : '';

      if (isUrlChange || currentSig !== oldSig) {
        pageContext = newContext;
        if (contextContent) {
           contextContent.innerHTML = '<div class="aq-help-loading"><div class="aq-help-dot"></div><div class="aq-help-dot"></div><div class="aq-help-dot"></div></div>';
           contextContent.classList.remove('loaded');
        }
        fetchContextualHelp();
      }
    }

    // Re-scan on click anywhere (for dynamic modals opening without URL changes)
    // Capture context BEFORE the click so we can detect what changed after
    let preClickSig = null;
    let clickTimeout = null;
    document.addEventListener('click', function(e) {
      if (e.target.closest('#aquera-ai-help-host')) return; // ignore widget clicks
      // Snapshot context state at the moment of click
      preClickSig = JSON.stringify(scanPageContext());
      clearTimeout(clickTimeout);
      clickTimeout = setTimeout(function() {
        // After 800ms (modal animation time), scan again and compare
        const postClickContext = scanPageContext();
        const postClickSig = JSON.stringify(postClickContext);
        if (isOpen && postClickSig !== preClickSig) {
          // Something visually changed on screen — update contextual help
          pageContext = postClickContext;
          if (contextContent) {
            contextContent.innerHTML = '<div class="aq-help-loading"><div class="aq-help-dot"></div><div class="aq-help-dot"></div><div class="aq-help-dot"></div></div>';
            contextContent.classList.remove('loaded');
          }
          fetchContextualHelp(false); // force=false
        } else if (!isOpen) {
          // Update background context silently even when panel is closed
          pageContext = postClickContext;
        }
      }, 800);
    }, true);

    // 2. Re-scan on SPA navigation or heavy DOM mutations
    let lastUrl = window.location.href;
    let scanTimeout = null;

    const observer = new MutationObserver(function () {
      const currentUrl = window.location.href;
      const isUrlChange = currentUrl !== lastUrl;
      
      if (isUrlChange) {
        lastUrl = currentUrl;
        contextLoaded = false;
        chatHistory = [];
        if (contextContent) {
          contextContent.innerHTML = '<div class="aq-help-loading"><div class="aq-help-dot"></div><div class="aq-help-dot"></div><div class="aq-help-dot"></div></div>';
          contextContent.classList.remove('loaded');
        }
        if (chatMessages) chatMessages.innerHTML = '';
      }

      clearTimeout(scanTimeout);
      scanTimeout = setTimeout(function() {
        attemptRescan(isUrlChange);
      }, 500);
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });

    // Expose for manual triggering/debugging
    window.AqueraAI = {
      refresh: function() { fetchContextualHelp(true); },
      getContext: function() { return scanPageContext(); }
    };
  }

  // ── Widget CSS ────────────────────────────────────────────────────

  function getWidgetCSS() {
    return `
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

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
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        font-size: 14px;
        line-height: 1.5;
        color: #e1e4e8;
      }

      .aq-help-container.bottom-right {
        bottom: 24px;
        right: 24px;
      }

      .aq-help-container.bottom-left {
        bottom: 24px;
        left: 24px;
      }

      /* ── Floating Button ──────────────────────────── */

      .aq-help-btn {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 20px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: white;
        border: none;
        border-radius: 50px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 600;
        font-family: inherit;
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4), 0 0 40px rgba(139, 92, 246, 0.15);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        position: relative;
        overflow: hidden;
      }

      .aq-help-btn::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(135deg, rgba(255,255,255,0.2), transparent);
        opacity: 0;
        transition: opacity 0.3s;
      }

      .aq-help-btn:hover {
        transform: translateY(-2px) scale(1.02);
        box-shadow: 0 6px 28px rgba(99, 102, 241, 0.5), 0 0 60px rgba(139, 92, 246, 0.2);
      }

      .aq-help-btn:hover::before { opacity: 1; }

      .aq-help-btn.active {
        transform: scale(0.95);
        opacity: 0.8;
      }

      .aq-help-btn svg { flex-shrink: 0; }

      /* ── Panel ────────────────────────────────────── */

      .aq-help-panel {
        position: absolute;
        bottom: 64px;
        right: 0;
        width: 400px;
        max-height: 560px;
        background: rgba(15, 17, 26, 0.95);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border: 1px solid rgba(99, 102, 241, 0.2);
        border-radius: 16px;
        box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5), 0 0 80px rgba(99, 102, 241, 0.08);
        display: flex;
        flex-direction: column;
        opacity: 0;
        transform: translateY(16px) scale(0.96);
        pointer-events: none;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      }

      .aq-help-panel.open {
        opacity: 1;
        transform: translateY(0) scale(1);
        pointer-events: all;
      }

      /* Header */
      .aq-help-panel-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      }

      .aq-help-panel-title {
        display: flex;
        align-items: center;
        gap: 10px;
        font-weight: 600;
        font-size: 15px;
        color: #f0f0f0;
      }

      .aq-help-panel-title svg {
        color: #8b5cf6;
      }

      /* Verified Source Badge */
      .aq-help-source-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        margin-top: 12px;
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(16, 185, 129, 0.2);
        border-radius: 6px;
        color: #10b981;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        animation: aq-fade-in 0.5s ease-out;
      }

      .aq-help-source-link {
        color: #10b981;
        text-decoration: none;
        display: flex;
        align-items: center;
        gap: 4px;
        transition: opacity 0.2s;
      }

      .aq-help-source-link:hover {
        opacity: 0.8;
      }

      @keyframes aq-fade-in {
        from { opacity: 0; transform: translateY(4px); }
        to { opacity: 1; transform: translateY(0); }
      }

      .aq-help-close {
        background: none;
        border: none;
        color: #6b7280;
        font-size: 22px;
        cursor: pointer;
        padding: 4px 8px;
        border-radius: 6px;
        transition: all 0.2s;
        line-height: 1;
        font-family: inherit;
      }

      .aq-help-close:hover {
        background: rgba(255, 255, 255, 0.06);
        color: #e1e4e8;
      }

      /* Status Dot */
      .aq-status-dot {
        width: 10px;
        height: 10px;
        border-radius: 50%;
        display: inline-block;
        margin-top: 5px;
        flex-shrink: 0;
        box-shadow: 0 0 8px currentcolor;
        border: 1px solid rgba(255,255,255,0.2);
      }
      .aq-status-dot-green { background-color: #10b981; color: #10b981; }
      .aq-status-dot-red { background-color: #ef4444; color: #ef4444; }

      /* Body */
      .aq-help-panel-body {
        flex: 1;
        overflow-y: auto;
        padding: 16px 20px;
        min-height: 0;
        max-height: 380px;
      }

      .aq-help-panel-body::-webkit-scrollbar { width: 4px; }
      .aq-help-panel-body::-webkit-scrollbar-track { background: transparent; }
      .aq-help-panel-body::-webkit-scrollbar-thumb {
        background: rgba(139, 92, 246, 0.3);
        border-radius: 4px;
      }

      /* Context Section */
      .aq-help-context-label {
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #8b5cf6;
        margin-bottom: 10px;
      }

      .aq-help-context-content {
        color: #c9cdd3;
        font-size: 13px;
        line-height: 1.65;
        transition: opacity 0.3s;
      }

      .aq-help-context-content.loaded {
        animation: fadeIn 0.4s ease;
      }

      .aq-help-context-content p { margin-bottom: 8px; }
      .aq-help-context-content p:last-child { margin-bottom: 0; }
      .aq-help-context-content ul {
        margin: 6px 0;
        padding-left: 18px;
      }
      .aq-help-context-content li {
        margin-bottom: 4px;
        list-style: disc;
      }
      .aq-help-context-content strong { color: #e1e4e8; font-weight: 600; }
      .aq-help-context-content code {
        background: rgba(139, 92, 246, 0.12);
        padding: 1px 5px;
        border-radius: 4px;
        font-size: 12px;
        color: #c4b5fd;
      }
      .aq-help-context-content a {
        color: #818cf8;
        text-decoration: none;
      }
      .aq-help-context-content a:hover { text-decoration: underline; }
      .aq-help-context-content h2,
      .aq-help-context-content h3,
      .aq-help-context-content h4 {
        color: #e1e4e8;
        margin: 12px 0 6px;
        font-size: 13px;
      }

      /* Divider */
      .aq-help-divider {
        height: 1px;
        background: rgba(255, 255, 255, 0.06);
        margin: 16px 0;
      }

      /* Chat Section */
      .aq-help-chat-messages {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .aq-help-msg {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 10px 14px;
        border-radius: 12px;
        font-size: 13px;
        line-height: 1.6;
        max-width: 92%;
        animation: slideUp 0.25s ease;
      }

      .aq-help-msg-content {
        flex: 1;
        min-width: 0;
      }

      .aq-help-msg p { margin-bottom: 6px; }
      .aq-help-msg p:last-child { margin-bottom: 0; }
      .aq-help-msg ul { margin: 4px 0; padding-left: 16px; }
      .aq-help-msg li { margin-bottom: 2px; list-style: disc; }
      .aq-help-msg strong { color: #e1e4e8; }
      .aq-help-msg code {
        background: rgba(139, 92, 246, 0.12);
        padding: 1px 4px;
        border-radius: 3px;
        font-size: 12px;
        color: #c4b5fd;
      }
      .aq-help-msg a {
        color: #818cf8;
        text-decoration: none;
      }
      .aq-help-msg a:hover { text-decoration: underline; }

      .aq-help-msg-user {
        background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.15));
        border: 1px solid rgba(99, 102, 241, 0.15);
        color: #e1e4e8;
        align-self: flex-end;
        border-bottom-right-radius: 4px;
      }

      .aq-help-msg-assistant {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.06);
        color: #c9cdd3;
        align-self: flex-start;
        border-bottom-left-radius: 4px;
      }

      /* Footer / Input */
      .aq-help-panel-footer {
        display: flex;
        gap: 8px;
        padding: 12px 16px;
        border-top: 1px solid rgba(255, 255, 255, 0.06);
      }

      .aq-help-input {
        flex: 1;
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 10px;
        padding: 10px 14px;
        color: #e1e4e8;
        font-size: 13px;
        font-family: inherit;
        outline: none;
        transition: border-color 0.2s, box-shadow 0.2s;
      }

      .aq-help-input::placeholder {
        color: #6b7280;
      }

      .aq-help-input:focus {
        border-color: rgba(99, 102, 241, 0.4);
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
      }

      .aq-help-send {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        border: none;
        border-radius: 10px;
        color: white;
        cursor: pointer;
        flex-shrink: 0;
        transition: all 0.2s;
      }

      .aq-help-send:hover {
        transform: scale(1.05);
        box-shadow: 0 2px 12px rgba(99, 102, 241, 0.4);
      }

      .aq-help-send:active { transform: scale(0.95); }

      /* Loading Animation */
      .aq-help-loading {
        display: flex;
        gap: 6px;
        padding: 4px 0;
      }

      .aq-help-dot {
        width: 7px;
        height: 7px;
        background: #8b5cf6;
        border-radius: 50%;
        animation: dotPulse 1.4s infinite ease-in-out both;
      }

      .aq-help-dot:nth-child(1) { animation-delay: -0.32s; }
      .aq-help-dot:nth-child(2) { animation-delay: -0.16s; }

      .aq-help-error {
        color: #f87171;
        font-size: 12px;
      }

      /* Animations */
      @keyframes dotPulse {
        0%, 80%, 100% { transform: scale(0.4); opacity: 0.4; }
        40% { transform: scale(1); opacity: 1; }
      }

      @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
      }

      @keyframes slideUp {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
      }

      /* Responsive */
      @media (max-width: 480px) {
        .aq-help-panel {
          width: calc(100vw - 32px);
          right: -8px;
          max-height: 70vh;
        }
      }
    `;
  }

  // ── Initialize ────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWidget);
  } else {
    initWidget();
  }

})();

});
