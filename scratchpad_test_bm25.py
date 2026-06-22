import sys
import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
res = search_knowledge_base("Privacy Notice Cancellation", "dummy_key", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=20, product_version="v14")
for i, r in enumerate(res):
    title = r.get('metadata', {}).get('title', 'Unknown')
    chunk_index = r.get('metadata', {}).get('chunk_index', -1)
    text = r.get('text', '')[:100].replace('\n', ' ')
    print(f"{i+1}. [{r.get('score', 0):.4f}] {title} (Chunk {chunk_index}): {text}")
