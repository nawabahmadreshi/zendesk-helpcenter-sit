import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.agent import contextual_help_agent
from app.ai_server import PageContext

def test_kb_grounding_and_modal_awareness():
    print(">>> Starting KB Grounding & Modal Awareness Verification...")
    
    # 1. Mock Page Context with Modal and Nav
    page_context = {
        "url": "https://aquera.com/connectors",
        "page_title": "Application Connectors",
        "headings": ["Directory", "Search"],
        "nav_items": ["Dashboard", "Connectors", "Logs", "Settings"],
        "is_modal_open": True,
        "modal_title": "Add New ServiceNow Connector",
        "integration_id": "servicenow_iam",
        "product_version": "v14"
    }
    
    user_query = "How do I configure the authentication settings for this ServiceNow connector?"
    
    print(f"Testing with Query: '{user_query}'")
    print(f"Active Modal: '{page_context['modal_title']}'")
    
    # 2. Run the agent (Internal prompt construction check)
    # We will use 'claude_proxy' but we are mostly interested in the DEBUG prints I added
    # regarding context injection.
    
    try:
        # We use a dummy API key for testing prompt construction logic
        # Note: This might actually call the LLM if the key is valid in .env
        response = contextual_help_agent(
            page_context=page_context,
            ai_provider="claude_proxy",
            api_key=os.getenv("GEMINI_API_KEY", "dummy_key"),
            persist_dir="./chroma_db",
            articles_dir=Path("./articles")
        )
        
        print("\n>>> AGENT RESPONSE (Summary):")
        print(response.get("text")[:500] if response.get("text") else "No response text")
        
        if "MODAL" in response.get("text", "").upper() or "SERVICENOW" in response.get("text", "").upper():
            print("\n[SUCCESS] AI seems aware of the modal/connector context!")
        else:
            print("\n[WARNING] AI might not be fully grounded in the provided context.")
            
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")

if __name__ == "__main__":
    test_kb_grounding_and_modal_awareness()
