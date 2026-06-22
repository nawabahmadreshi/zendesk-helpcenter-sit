/**
 * Aquera AI Help - Background Proxy
 * Bypasses Mixed Content (HTTPS -> HTTP) and CORS restrictions.
 */

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log('[Aquera Background] Received message:', request.type, request);
    if (request.type === 'FETCH_AI_HELP') {
        const { url, options } = request;
        
        console.log('[Aquera Background] Proxying fetch to:', url);
        
        fetch(url, options)
            .then(async response => {
                const ok = response.ok;
                const status = response.status;
                const data = await response.json().catch(() => null);
                console.log('[Aquera Background] Fetch Success:', { ok, status, data });
                sendResponse({ ok, status, data });
            })
            .catch(error => {
                console.error('[Aquera Background] Fetch error:', error);
                sendResponse({ ok: false, error: `Proxy Error: ${error.message}` });
            });
            
        return true; // Keep message channel open for async response
    }
});
