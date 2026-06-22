from app.embedding import search_knowledge_base
from config import Config
import os
os.environ['SKIP_VECTOR'] = "true"
cfg = Config()

query = "How do I configure ADP WFN integration"
results = search_knowledge_base(
    query=query,
    api_key=cfg.GEMINI_API_KEY,
    persist_dir=str(cfg.vectordb_dir),
    top_k=50,
    product_version="v14"
)
for r in results:
    text = r.get("text", "").split('\n')[1] if '\n' in r.get("text", "") else ""
    if "ADP WFN" in text:
        print(text, "| score:", r.get("score"))
