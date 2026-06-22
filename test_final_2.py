import os
os.environ["SKIP_VECTOR"] = "true"
from app.embedding import search_knowledge_base
from config import Config

query = "How do I configure ADP WFN integration?"
results = search_knowledge_base(
    query=query,
    api_key="test",
    persist_dir=str(Config().STORAGE_DIR),
    top_k=5
)

for i, r in enumerate(results):
    title = r.get("metadata", {}).get("title", "")
    text = r.get("text", "")
    score = r.get("rerank_score", 0)
    print(f"#{i+1} | Score: {score} | Title: {title}")
    print("Preview:", text.replace('\n', ' ')[:100])
