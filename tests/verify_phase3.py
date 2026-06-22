import requests
import json
import time

def test_phase3_action_generation():
    url = "http://localhost:8000/api/help/context"
    
    scenarios = [
        {
            "name": "Auto-Fill Scenario (SetupDiscovery)",
            "context": {
                "page_title": "Active Directory Sync Configuration",
                "url_path": "/integrations/ad/config",
                "active_errors": [],
                "event_stream": [
                    {"type": "focus", "id": "instance_url", "placeholder": "https://your-ad-server.com", "timestamp": "2024-03-15T10:00:01"}
                ],
                "form_fields": [
                    {"id": "instance_url", "label": "Instance URL", "placeholder": "https://your-ad-server.com", "value": ""},
                    {"id": "client_id", "label": "Client ID", "placeholder": "Enter your AD Client ID", "value": ""},
                    {"id": "client_secret", "label": "Client Secret", "placeholder": "Enter your Client Secret", "value": ""}
                ],
                "headings": ["General Information", "OAuth Settings"],
                "breadcrumbs": ["Integrations", "Microsoft", "AD"]
            },
            "expected_intent": "SetupDiscovery"
        },
        {
            "name": "Highlight Scenario (FieldDefinition)",
            "context": {
                "page_title": "Field Mapping: Salesforce",
                "url_path": "/integrations/sf/mapping",
                "active_errors": [],
                "event_stream": [
                    {"type": "click", "text": "What is External ID?", "tag": "SPAN", "timestamp": "2024-03-15T11:00:01"}
                ],
                "form_fields": [
                    {"id": "ext_id_field", "label": "External ID", "placeholder": "Select field for external ID", "value": ""}
                ],
                "headings": ["Mapping Settings"],
            },
            "expected_intent": "FieldDefinition"
        }
    ]

    for scenario in scenarios:
        print(f"\n--- Testing Scenario: {scenario['name']} ---")
        payload = {
            "page_context": scenario["context"],
            "chat_history": []
        }
        
        try:
            response = requests.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Predicted Intent: {data.get('predicted_intent')}")
                
                actions = data.get("action_suggestions")
                if actions and len(actions) > 0:
                    print(f"✅ Actions Generated: {len(actions)}")
                    for group in actions:
                        print(f"   Group: {group.get('label')}")
                        for step in group.get('steps', []):
                            print(f"     -> Step: {step.get('action')} on {step.get('target')}")
                else:
                    print(f"❌ No Actions Generated")
                
                print(f"   AI Response snippet: {data.get('response', '')[:100]}...")
            else:
                print(f"❌ API Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"❌ Request failed: {e}")

if __name__ == "__main__":
    test_phase3_action_generation()
