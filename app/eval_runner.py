import time
import json
from typing import List, Dict, Any
from pathlib import Path
from app.eval_store import EvalStore, InteractionRecord
from app.agent import qa_agent
from config import Config

class GoldenSetRunner:
    """
    Automated harness for running 'Golden Set' evaluations against the RAG system.
    Logs results to EvalStore for RAGAS and performance analysis.
    """
    def __init__(self, api_key: str = ""):
        self.cfg = Config()
        self.api_key = api_key or getattr(self.cfg, 'GEMINI_API_KEY', "")
        self.store = EvalStore()
        self.persist_dir = str(self.cfg.vectordb_dir)
        self.articles_dir = self.cfg.processed_dir / "articles"

    def run_eval(self, test_cases: List[Dict[str, str]]):
        """
        Runs a list of test cases. 
        Each test case: {"question": "...", "expected_id": "..."}
        """
        print(f"--- Starting Evaluation Run ({len(test_cases)} cases) ---")
        
        for i, case in enumerate(test_cases):
            query = case.get("question")
            print(f"[{i+1}/{len(test_cases)}] Testing: {query[:50]}...")
            
            t0 = time.time()
            try:
                result = qa_agent(
                    question=query,
                    page_context={},
                    ai_provider=self.cfg.AI_PROVIDER,
                    api_key=self.api_key,
                    persist_dir=self.persist_dir,
                    articles_dir=self.articles_dir
                )
                latency = (time.time() - t0) * 1000
                
                # Log to EvalStore
                record = InteractionRecord(
                    query=query,
                    user_id="eval_runner",
                    crag_status=result.get("crag_status", "NONE"),
                    crag_score=result.get("crag_score"),
                    latency_ms=latency,
                    metadata={
                        "expected_id": case.get("expected_id"),
                        "actual_id": result.get("article_id")
                    }
                )
                self.store.log(record)
                
                status = result.get("crag_status", "NONE")
                print(f"  > Result: {status} | Latency: {latency:.1f}ms")
                
            except Exception as e:
                print(f"  > Error: {e}")

        print("--- Evaluation Run Complete ---")

if __name__ == "__main__":
    # Example Golden Set
    GOLDEN_SET = [
        {"question": "How do I setup a Zendesk integration?", "expected_id": "setup_guide"},
        {"question": "What is the deflect rate?", "expected_id": "analytics_guide"},
        {"question": "How to fix 404 error?", "expected_id": "troubleshooting_404"}
    ]
    
    runner = GoldenSetRunner()
    runner.run_eval(GOLDEN_SET)
