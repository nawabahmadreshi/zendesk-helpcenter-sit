import time
from app.reranker import ReRanker

r = ReRanker()
query = "How do I configure ADP WFN integration?"
docs = [{"title": "Doc", "text": "Some sample text " * 10}] * 500

start = time.time()
r.rerank_results(query, docs, top_k=5)
end = time.time()
print(f"Time for 500 docs: {end - start:.2f}s")
