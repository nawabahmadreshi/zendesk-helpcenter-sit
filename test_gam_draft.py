from app.embedding import search_knowledge_base
import config as cfg

res = search_knowledge_base(
    query='GAM-Draft',
    api_key=None,
    persist_dir=str(cfg.vectordb_dir),
    top_k=50,
    integration_id=None,
    product_version='v14',
    article_filter=None
)

for r in res:
    print(r.get("metadata", {}).get("title", ""))
