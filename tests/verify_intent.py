import requests
import json
import time

def test_intent_classification():
    url = "http://localhost:8000/api/help/context"
    
    scenarios = [
        {
            "name": "Error Resolution Scenario",
            "context": {
                "page_title": "Active Directory Sync",
                "url_path": "/integrations/ad/sync",
                "active_errors": ["Invalid credentials", "Connection timeout"],
                "event_stream": [
                    {"type": "click", "text": "Save", "tag": "BUTTON", "timestamp": "2024-03-14T10:00:01"},
                    {"type": "click", "text": "Save", "tag": "BUTTON", "timestamp": "2024-03-14T10:00:03"},
                    {"type": "click", "text": "Save", "tag": "BUTTON", "timestamp": "2024-03-14T10:00:05"}
                ],
                "buttons": ["Save", "Cancel", "Test Connection"],
                "headings": ["Sync Settings", "Field Mapping"],
                "breadcrumbs": ["Integrations", "Microsoft", "AD"]
            },
            "expected_intent": "ErrorResolution"
        },
        {
            "name": "Setup Discovery Scenario",
            "context": {
                "page_title": "New Salesforce Integration",
                "url_path": "/integrations/salesforce/new",
                "active_errors": [],
                "event_stream": [
                    {"type": "focus", "placeholder": "Client ID", "timestamp": "2024-03-14T11:00:01"},
                    {"type": "focus", "placeholder": "Client Secret", "timestamp": "2024-03-14T11:00:10"}
                ],
                "buttons": ["Create", "Back"],
                "headings": ["OAuth Configuration"],
                "descriptions": ["Enter your Salesforce OAuth credentials to start the sync process."]
            },
            "expected_intent": "SetupDiscovery"
        }
    ]

    for scenario in scenarios:
        print(f"\nTesting Scenario: {scenario['name']}...")
        payload = {
            "page_context": scenario["context"],
            "chat_history": []
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                predicted = data.get("predicted_intent")
                print(f"✅ Received Response")
                print(f"   Predicted Intent: {predicted}")
                
                # Loose matching for testing resilience
                if scenario["expected_intent"].lower() == str(predicted).lower():
                    print(f"✅ Intent Match: SUCCESS")
                else:
                    print(f"❌ Intent Match: FAILED (Expected {scenario['expected_intent']})")
                
                print(f"   AI Response snippet: {data.get('response', '')[:100]}...")
            else:
                print(f"❌ API Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_intent_classification()
