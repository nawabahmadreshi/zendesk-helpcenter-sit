from app.embedding import search_knowledge_base
from config import Config
import time

cfg = Config()

queries = [
    "How do I configure ADP WFN?",
    "ADP Workforce Now",
    "Azure communication services setup",
    "Jira service management",
    "Front configuration guide user permissions",
    "How do I generate an API token for Zendesk?"
]

print("\n=== EXTENSIVE QA SESSION ===")
for q in queries:
    print(f"\nQuery: '{q}'")
    start = time.time()
    results = search_knowledge_base(q, api_key=cfg.GEMINI_API_KEY, top_k=3, persist_dir="storage/site_lexical_index")
    elapsed = time.time() - start
    print(f"Time: {elapsed:.2f}s")
    for i, r in enumerate(results):
        title = r.get("metadata", {}).get("title", "Unknown")
        score = r.get("score", 0.0)
        print(f"  {i+1}. {title} (Score: {score:.2f})")
