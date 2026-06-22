import os
from fastmcp import FastMCP
import requests
from typing import Optional

# Initialize FastMCP server
mcp = FastMCP("ZendeskKB")

# Configuration (to be passed via env vars or config)
ZENDESK_SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN")
ZENDESK_EMAIL = os.environ.get("ZENDESK_EMAIL")
ZENDESK_API_TOKEN = os.environ.get("ZENDESK_API_TOKEN")

@mcp.tool()
def get_article(article_id: str) -> str:
    """
    Fetch a specific article from the Zendesk Help Center by its ID.
    Returns the article body (HTML/Text).
    """
    if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
        return "ERROR: Zendesk credentials not configured."
        
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/help_center/articles/{article_id}.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    
    try:
        response = requests.get(url, auth=auth, timeout=10)
        response.raise_for_status()
        data = response.json()
        article = data.get("article", {})
        return f"TITLE: {article.get('title')}\n\nBODY: {article.get('body')}"
    except Exception as e:
        return f"ERROR: Failed to fetch article {article_id}: {str(e)}"

@mcp.tool()
def search_articles(query: str, locale: str = "en-us") -> str:
    """
    Search Zendesk Help Center articles in real-time.
    Returns a list of matching article IDs and titles.
    """
    if not all([ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, ZENDESK_API_TOKEN]):
        return "ERROR: Zendesk credentials not configured."
        
    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/help_center/articles/search.json"
    auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)
    params = {"query": query, "locale": locale}
    
    try:
        response = requests.get(url, auth=auth, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        
        output = []
        for res in results[:5]:  # Top 5
            output.append(f"- ID: {res.get('id')}, Title: {res.get('title')}")
            
        return "\n".join(output) if output else "No results found."
    except Exception as e:
        return f"ERROR: search failed: {str(e)}"

if __name__ == "__main__":
    mcp.run()
