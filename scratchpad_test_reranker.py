import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
from app.reranker import rerank_results
res = search_knowledge_base("Privacy Notice Cancellation", "dummy_key", "/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync/data/vectordb", top_k=10)
for r in res[:5]:
    print(f"BM25: {r['metadata'].get('title')} - {r['text'][:60]}")

print("--- RERANKING ---")
reranked = rerank_results("Privacy Notice Cancellation", res[:10], top_n=5)
for i, r in enumerate(reranked):
    title = r.get('metadata', {}).get('title', 'Unknown')
    text = r.get('text', '')[:100].replace('\n', ' ')
    print(f"{i+1}. [{r.get('rerank_score', 0):.4f}] {title}: {text}")
