import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import httpx
from bs4 import BeautifulSoup
import re

app = FastAPI()

# The real Aquera admin URL
TARGET_URL = "https://admin.aquera.io"

# The script to inject
WIDGET_SCRIPT = '<script src="http://localhost:8000/widget/widget.js" data-api-url="http://localhost:8000"></script>'

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def proxy(request: Request, path: str):
    url = f"{TARGET_URL}/{path}"
    
    # Forward the query parameters
    if request.url.query:
        url += f"?{request.url.query}"
        
    client = httpx.AsyncClient(base_url=TARGET_URL)
    
    # Forward headers (excluding Host to avoid routing issues)
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("accept-encoding", None) # Let httpx handle compression
    
    # For GET requests that return HTML, we intercept and inject
    if request.method == "GET":
        response = await client.get(url, headers=headers)
        
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            # We got HTML! Time to inject our widget
            html = response.text
            
            # Remove strict CSP headers so our widget can load and communicate
            response_headers = dict(response.headers)
            response_headers.pop("content-security-policy", None)
            
            # Inject the script tag right before the closing body tag
            if "</body>" in html:
                html = html.replace("</body>", f"{WIDGET_SCRIPT}\n</body>")
            else:
                html += WIDGET_SCRIPT
                
            return HTMLResponse(content=html, status_code=response.status_code, headers=response_headers)
            
    # For all other requests (JS, CSS, images, API calls), transparently forward them
    body = await request.body()
    response = await client.request(
        method=request.method,
        url=url,
        headers=headers,
        content=body,
    )
    
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=dict(response.headers)
    )

if __name__ == "__main__":
    print("==================================================================")
    print("🚀 Local Aquera Proxy Server starting... ")
    print("Go to: http://localhost:8001")
    print("Log in normally, and the AI Widget will be natively injected!")
    print("==================================================================")
    uvicorn.run(app, host="0.0.0.0", port=8001)
