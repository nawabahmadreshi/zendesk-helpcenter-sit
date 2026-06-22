from app.embedding import search_knowledge_base
import config as cfg

res = search_knowledge_base(
    query="GAM",
    api_key=cfg.GEMINI_API_KEY,
    persist_dir=str(cfg.vectordb_dir),
    top_k=20,
    integration_id=None,
    product_version=None,
    article_filter=None
)
for r in res:
    title = r.get("metadata", {}).get("title", "")
    score = r.get("score", 0)
    print(f"Title: {title} | Score: {score}")
