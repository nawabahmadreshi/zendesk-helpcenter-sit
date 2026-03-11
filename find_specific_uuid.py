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
    
    target_uuid = "b29f17f0-9e74-916c-d0a8-696547c92e80"
    print(f"Searching for articles related to UUID: {target_uuid} (checking labels, title, and body)...")
    
    articles = client.list_articles()
    print(f"Total articles scanned: {len(articles)}")
    
    matches = []
    
    for art in articles:
        found_in_labels = False
        lbls = art.get('label_names', []) or art.get('labels', []) or []
        for l in lbls:
            if target_uuid in str(l):
                found_in_labels = True
                break
        
        found_in_title = target_uuid in art.get('title', '')
        found_in_body = target_uuid in (art.get('body') or '')
        
        if found_in_labels or found_in_title or found_in_body:
            matches.append({
                'id': art['id'],
                'title': art['title'],
                'labels': lbls,
                'found_in_body': found_in_body,
                'section_id': art.get('section_id')
            })
            
    print(f"\nFound {len(matches)} matches:")
    for m in matches:
        print(f"- ID: {m['id']}, Title: {m['title']}")
        print(f"  Labels: {m['labels']}")
        print(f"  Found in body: {m['found_in_body']}")
        print(f"  Section ID: {m['section_id']}")

if __name__ == "__main__":
    main()
