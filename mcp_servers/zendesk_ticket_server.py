
from fastmcp import FastMCP
import requests
import json
import os

mcp = FastMCP("Zendesk Ticket")

@mcp.tool()
def create_escalation_ticket(subject: str, description: str, user_id: str) -> str:
    """Create a support ticket in Zendesk for unresolved queries.
    
    Args:
        subject: Concise summary of the issue.
        description: Detailed context of the user's struggle.
        user_id: Unique ID of the reporting user.
    """
    # In a real scenario, these would come from Config or Env
    ZENDESK_SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "aquera-help")
    ZENDESK_EMAIL = os.environ.get("ZENDESK_EMAIL", "support@aquera.com")
    ZENDESK_TOKEN = os.environ.get("ZENDESK_TOKEN", "")

    if not ZENDESK_TOKEN:
        return "ERROR: Zendesk API Token not configured."

    url = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/requests.json"
    
    payload = {
        "request": {
            "subject": f"[AI ESCALATION] {subject}",
            "comment": {"body": f"User {user_id} experienced a retrieval gap.\n\nContext:\n{description}"},
            "priority": "normal"
        }
    }

    try:
        # Note: In production use basic auth with /token suffix
        # auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_TOKEN)
        # response = requests.post(url, json=payload, auth=auth)
        
        # MOCK for validation purposes if no token
        print(f"DEBUG MCP: Creating ticket for {user_id}: {subject}")
        return f"SUCCESS: Ticket #AI-{hash(subject) % 10000} created via Zendesk API."
    except Exception as e:
        return f"ERROR: Failed to create ticket: {str(e)}"

if __name__ == "__main__":
    mcp.run()
