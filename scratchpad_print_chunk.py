import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
res = search_knowledge_base("Privacy Notice Cancellation", "dummy_key", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=10)
for i, r in enumerate(res[:2]):
    print(f"--- CHUNK {i+1} SCORED {r['score']} ---")
    print(r['text'])
