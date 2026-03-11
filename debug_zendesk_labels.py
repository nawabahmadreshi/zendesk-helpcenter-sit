from __future__ import annotations
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# Load from .env explicitly
env_path = Path('.env')
load_dotenv(dotenv_path=env_path)

from app.zendesk_client import ZendeskClient

def main() -> None:
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN")
    email = os.environ.get("ZENDESK_EMAIL")
    token = os.environ.get("ZENDESK_API_TOKEN")
    
    if not all([subdomain, email, token]):
        print("Error: Missing Zendesk credentials in .env")
        return

    client = ZendeskClient(
        subdomain=subdomain,
        email=email,
        api_token=token,
        locale=os.environ.get("ZENDESK_LOCALE", "en-us"),
    )
    
    print(f"Searching for articles with 'integration_id_' label across ALL articles...")
    articles = client.list_articles()
    print(f"Total articles found: {len(articles)}")
    
    integration_id_matches = []
    
    for art in articles:
        lbls = art.get('label_names', []) or art.get('labels', []) or []
        for l in lbls:
            if str(l).startswith('integration_id_'):
                integration_id_matches.append((art['id'], art['title'], str(l), art.get('section_id')))
        
    print(f"\nArticles matched by 'integration_id_': {len(integration_id_matches)}")
    for m in integration_id_matches:
        print(f"- ID: {m[0]}, Title: {m[1]}")
        print(f"  Label: {m[2]}")
        print(f"  Section ID: {m[3]}")

if __name__ == "__main__":
    main()
