import os
import json
from pathlib import Path
from dotenv import load_dotenv
from app.agent import contextual_help_agent
from config import Config

# Load environment variables
load_dotenv()
cfg = Config()

def verify_mapping():
    integration_id = "b29f17f0-9e74-916c-d0a8-696547c92e80"
    
    # Mock page context for an integration page
    page_context = {
        "page_title": "ADP Workforce Now Integration",
        "url_path": f"/integrations/{integration_id}",
        "integration_id": integration_id,
        "headings": ["Configuration", "Field Mapping"],
        "form_labels": ["Instance URL", "Admin Username", "Client ID"],
        "buttons": ["Save Configuration", "Test Connection"]
    }
    
    api_key = cfg.GEMINI_API_KEY
    or_key = cfg.OPENROUTER_API_KEY
    
    persist_dir = str(cfg.vectordb_dir)
    articles_dir = cfg.processed_dir / "articles"

    print(f"--- [VERIFICATION] Testing Integration ID: {integration_id} ---")
    print(f"Context Integration ID: {page_context['integration_id']}")
    print(f"Using AI Provider: {cfg.AI_PROVIDER}")
    
    try:
        result = contextual_help_agent(
            page_context=page_context,
            ai_provider=cfg.AI_PROVIDER,
            api_key=api_key,
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            fallback_mode=cfg.AI_FALLBACK_MODE,
            openrouter_api_key=or_key,
            openrouter_model=cfg.OPENROUTER_MODEL,
            openrouter_site_url=cfg.OPENROUTER_SITE_URL
        )
        
        print("\n--- AI RESPONSE ---")
        print(result.get("response"))
        print("\n--- METADATA ---")
        print(f"Article Matched: {result.get('article_title')} (ID: {result.get('article_id')})")
        
        if result.get("article_id") == "38425341228183":
            print("✅ SUCCESS: Correct article ID matched.")
        elif result.get("article_id"):
            print(f"⚠️ WARNING: Matched different article ID: {result.get('article_id')}")
        else:
            print("❌ FAILURE: No article mapping found for this ID.")
            
    except Exception as e:
        print(f"Error during verification: {e}")

if __name__ == "__main__":
    verify_mapping()
