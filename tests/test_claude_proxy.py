import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from app.agent import _run_claude_proxy_loop
from config import Config

def test_integration():
    print("🚀 Starting Claude Proxy Integration Test...")
    
    system_prompt = "You are a helpful assistant. If asked to search, use your tools."
    user_message = "Hello! Can you confirm you are connected via the Puter proxy? Also, what models are you aware of?"
    
    proxy_url = "http://localhost:8080/v1"
    persist_dir = "storage/vectordb"
    articles_dir = Path("storage/raw")
    
    try:
        result = _run_claude_proxy_loop(
            system_prompt=system_prompt,
            user_message=user_message,
            proxy_url=proxy_url,
            persist_dir=persist_dir,
            articles_dir=articles_dir
        )
        
        print("\n--- AGENT RESPONSE ---")
        print(result.get("response"))
        print("----------------------\n")
        
        if "response" in result and result["response"]:
            print("✅ TEST PASSED: Agent successfully communicated via proxy.")
        else:
            print("❌ TEST FAILED: Empty response or error.")
            
    except Exception as e:
        print(f"❌ TEST FAILED with error: {e}")

if __name__ == "__main__":
    test_integration()
