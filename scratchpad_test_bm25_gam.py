import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
query = "Adding an Organization"
res = search_knowledge_base(query, "dummy", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=15)
for r in res[:5]:
    print(r.get('score', 0), "-", r['text'].split('\n')[1])
