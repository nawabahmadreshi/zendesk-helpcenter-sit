from app.agent import qa_agent
from config import Config
cfg = Config()
res = qa_agent("what are the steps?", page_context={"integration_id": "360010996873"}, ai_provider="gemini", api_key=cfg.GEMINI_API_KEY, fallback_mode="gemini", persist_dir=str(cfg.vectordb_dir), articles_dir=cfg.processed_dir/"articles")
print(res)
