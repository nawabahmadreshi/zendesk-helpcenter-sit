import requests
import json
import time

API_URL = "http://localhost:8000/api/help/context"

def test_workflow_skip_detection():
    print("\n--- Testing Workflow Skip Detection ---")
    
    # Scenario: User is at "Auth" step but skipped "Basics" (#instance_url)
    payload = {
        "page_context": {
            "page_title": "Integration Setup",
            "url_path": "/admin/integrations/new",
            "form_fields": [
                {"id": "instance_url", "label": "Instance URL", "value": ""}, # EMPTY!
                {"id": "auth_type", "label": "Auth Type", "value": "API Key"},
                {"id": "api_key", "label": "API Key", "value": ""},
            ],
            "event_stream": [
                {"type": "focus", "target": "instance_url", "id": "instance_url", "timestamp": "2026-03-15T01:00:00Z"},
                {"type": "focus", "target": "api_key", "id": "api_key", "timestamp": "2026-03-15T01:00:10Z"}, # User skipped to API Key
            ],
            "integration_id": "integration_id_6c6a442f-3797-456e-29e6-a23da164c87f"
        },
        "chat_history": []
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ Predicted Intent: {data.get('predicted_intent')}")
        
        # We expect the AI to mention the skip or the missing instance_url in its response
        resp_text = data.get("response", "").lower()
        print(f"AI Response snippet: {data.get('response')[:150]}...")
        
        if "instance url" in resp_text or "skipped" in resp_text or "basics" in resp_text:
            print("✅ Skip detected and communicated in AI response.")
        else:
            print("❌ AI response did not clearly address the skipped step.")

    except Exception as e:
        print(f"❌ Test failed: {e}")

def test_workflow_happy_path():
    print("\n--- Testing Workflow Happy Path ---")
    
    # Scenario: User is at "Basics" and filled it out
    payload = {
        "page_context": {
            "page_title": "Integration Setup",
            "url_path": "/admin/integrations/new",
            "form_fields": [
                {"id": "instance_url", "label": "Instance URL", "value": "https://api.example.com"}, # FILLED
                {"id": "auth_type", "label": "Auth Type", "value": "API Key"},
            ],
            "event_stream": [
                {"type": "focus", "target": "instance_url", "id": "instance_url", "timestamp": "2026-03-15T01:00:00Z"},
                {"type": "input_change", "id": "instance_url", "length": 25},
            ],
            "integration_id": "integration_id_6c6a442f-3797-456e-29e6-a23da164c87f"
        },
        "chat_history": []
    }

    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ Predicted Intent: {data.get('predicted_intent')}")
        print(f"AI Response snippet: {data.get('response')[:150]}...")

    except Exception as e:
        print(f"❌ Test failed: {e}")

if __name__ == "__main__":
    test_workflow_skip_detection()
    test_workflow_happy_path()
