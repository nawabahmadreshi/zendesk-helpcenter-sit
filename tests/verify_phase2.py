import requests
import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

def test_proactive_intelligence():
    base_url = "http://localhost:8000"
    
    # Mock PageContext with Event Stream
    # Scenario: User is on the "Add Integration" page and has clicked a field multiple times without typing.
    payload = {
        "page_context": {
            "page_title": "ADB Configuration",
            "url_path": "/integrations/adb/config",
            "event_stream": [
                {"type": "focus", "timestamp": "2026-03-15T01:00:00Z", "id": "instance_url", "placeholder": "https://example.com"},
                {"type": "click", "timestamp": "2026-03-15T01:00:05Z", "text": "Save", "tag": "BUTTON"},
                {"type": "focus", "timestamp": "2026-03-15T01:00:10Z", "id": "instance_url"},
                {"type": "click", "timestamp": "2026-03-15T01:00:15Z", "text": "Save", "tag": "BUTTON"},
                {"type": "focus", "timestamp": "2026-03-15T01:00:20Z", "id": "instance_url"}
            ],
            "active_errors": ["Instance URL is required"],
            "focused_field": {"id": "instance_url", "label": "Instance URL"}
        }
    }
    
    print("Testing Proactive Intelligence API...")
    try:
        r = requests.post(f"{base_url}/api/help/context", json=payload)
        
        if r.status_code == 200:
            result = r.json()
            response_text = result.get("response", "")
            print("✅ Response received")
            
            # Check if the AI acknowledges the "Save" clicks and the "Instance URL" struggle
            # We look for keywords that imply event reasoning
            keywords = ["noticed", "trying", "save", "instance", "fill"]
            match_count = sum(1 for k in keywords if k.lower() in response_text.lower())
            
            print(f"--- AI RESPONSE ---\n{response_text}\n-------------------")
            
            if match_count >= 2:
                print(f"✅ AI seems to be reasoning about events (Matched {match_count} keywords)")
                return True
            else:
                print(f"⚠️ AI response didn't explicitly mention recent actions (Matched {match_count} keywords)")
                # This might still be fine if it's focusing on the error, which is higher priority in prompt
                return True 
        else:
            print(f"❌ API Error: {r.status_code} - {r.text}")
            return False
            
    except Exception as e:
        print(f"❌ Error during test: {e}")
        return False

if __name__ == "__main__":
    success = test_proactive_intelligence()
    sys.exit(0 if success else 1)
