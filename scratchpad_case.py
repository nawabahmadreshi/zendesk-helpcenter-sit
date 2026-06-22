import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
res1 = search_knowledge_base("Privacy Notice Cancellation", "dummy", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=5)
res2 = search_knowledge_base("privacy notice cancellation", "dummy", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=5)
print("Query 1 top hit:", res1[0]['text'].split('\n')[1])
print("Query 2 top hit:", res2[0]['text'].split('\n')[1])
