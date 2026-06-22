from fastmcp import FastMCP
from typing import Dict

mcp = FastMCP("AuthCRM")

# Mock database of user contexts
MOCK_USER_DB = {
    "anonymous": {
        "role": "guest",
        "product_version": "v14",
        "account_tier": "standard",
        "recent_tickets": []
    },
    "default_user": {
        "role": "admin",
        "product_version": "v11",
        "account_tier": "premium",
        "recent_tickets": ["#8821", "#8834"]
    }
}

@mcp.resource("user_context://{user_id}")
def get_user_context(user_id: str) -> Dict:
    """
    Returns authoritative user context (role, version, tier) for the given user ID.
    Used by the Orchestrator at the start of a session.
    """
    return MOCK_USER_DB.get(user_id, MOCK_USER_DB["anonymous"])

@mcp.tool()
def update_user_interaction(user_id: str, component_id: str):
    """
    Records an interaction for the user to help track mastery (authoritative backend).
    """
    # In a real app, this would write to a DB
    return f"Interaction recorded for {user_id} in {component_id}"

if __name__ == "__main__":
    mcp.run()
