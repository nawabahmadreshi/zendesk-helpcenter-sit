import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base, generate_hyde_query
topic = "Privacy Notice Cancellation"
hyde = generate_hyde_query(topic)
print("HyDE Query:", hyde)
res = search_knowledge_base(hyde, "dummy", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=5)
for r in res[:3]:
    print(r['metadata'].get('title', ''), "-", r['text'].split('\n')[1])
