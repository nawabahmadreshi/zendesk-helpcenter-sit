from app.embedding import search_knowledge_base
from config import Config
import os

os.environ['SKIP_VECTOR'] = "false"
cfg = Config()

query = "How do I configure ADP WFN integration"
results = search_knowledge_base(
    query=query,
    api_key=cfg.GEMINI_API_KEY,
    persist_dir=str(cfg.vectordb_dir),
    top_k=3,
    product_version="v14"
)
for r in results:
    print(r.get("metadata", {}).get("title"), "|", r.get("text", "")[:100].replace("\n", " "))
