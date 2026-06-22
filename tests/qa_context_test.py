import sys
import os
import json
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.agent import qa_agent
from app.ai_server import PageContext

def test_qa_modal_and_click_awareness():
    print(">>> Starting QA Modal & Click Awareness Verification...")
    
    # 1. Mock Page Context with Click Event and Open Modal
    page_context = {
        "url": "https://aquera.com/connectors",
        "page_title": "Application Connectors",
        "is_modal_open": True,
        "modal_title": "Create New Integration",
        "event_stream": [
            {"type": "click", "text": "Create Integration", "tag": "BUTTON", "timestamp": "2026-03-20T17:10:00Z"},
            {"type": "focus", "label": "Integration Name", "id": "name_field", "timestamp": "2026-03-20T17:10:05Z"}
        ],
        "integration_id": "generic_rest",
        "product_version": "v14"
    }
    
    question = "I clicked create but nothing happened. Am I in the right place?"
    
    print(f"Testing with Question: '{question}'")
    
    try:
        # We call qa_agent. We are looking for the print statements I added.
        # Specifically: "DEBUG QA: Injecting Modal state into prompt: ..."
        response = qa_agent(
            question=question,
            page_context=page_context,
            ai_provider="claude_proxy",
            api_key=os.getenv("GEMINI_API_KEY", "dummy_key"),
            persist_dir="./chroma_db",
            articles_dir=Path("./articles")
        )
        
        print("\n>>> AGENT RESPONSE (Summary):")
        print(response.get("response", "No response text")[:500])
        
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")

if __name__ == "__main__":
    test_qa_modal_and_click_awareness()
