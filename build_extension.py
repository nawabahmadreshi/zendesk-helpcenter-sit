import os

with open('widget/widget.js', 'r') as f:
    widget_code = f.read()

widget_code = widget_code.replace(
    "const API_URL = (scriptTag && scriptTag.getAttribute('data-api-url')) || 'http://localhost:8000';",
    "const API_URL = window.__AQUERA_EXT_API_URL__ || 'http://localhost:8000';"
)

content_js = f"""// content.js - Injected by the Chrome Extension
chrome.storage.sync.get({{ apiUrl: 'http://localhost:8000' }}, function(items) {{
    window.__AQUERA_EXT_API_URL__ = items.apiUrl;
    {widget_code}
}});
"""

with open('chrome-extension/content.js', 'w') as f:
    f.write(content_js)

print("✅ Chrome Extension building complete. Content.js created.")
