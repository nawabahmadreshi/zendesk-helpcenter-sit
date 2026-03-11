import uvicorn
from pyngrok import ngrok
import time
import sys

# Open an ngrok tunnel to the dev server
port = 8000
try:
    public_url = ngrok.connect(port).public_url
except Exception as e:
    print(f"Failed to start ngrok: {e}")
    sys.exit(1)

print(f"\n========================================================")
print(f"✅ Secure HTTPS Tunnel Live!")
print(f"========================================================")
print(f"The AI Server is now accessible via HTTPS at: {public_url}")
print("\n👉 Create a NEW bookmarklet with this EXACT code:\n")
bookmarklet = f"javascript:(function(){{var s=document.createElement('script');s.src='{public_url}/widget/widget.js';s.setAttribute('data-api-url','{public_url}');document.body.appendChild(s);console.log('Aquera AI Help injected securely!');}})();"
print(bookmarklet)
print(f"========================================================\n")

# Start the server
uvicorn.run("app.ai_server:app", host="0.0.0.0", port=port, log_level="warning")
