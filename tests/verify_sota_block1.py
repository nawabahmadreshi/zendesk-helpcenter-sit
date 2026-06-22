import sys
import os
from pathlib import Path

# Add root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from app.reranker import ReRanker, rerank_results
from app.crag_gate import CRAGGate
import json

def test_reranker():
    print("--- Testing Cross-Encoder Reranker ---")
    query = "How do I configure ADP integration?"
    candidates = [
        {"id": "1", "text": "This article explains how to set up the ADP Workforce Now integration in detail."},
        {"id": "2", "text": "ADP is a payroll processing company. They offer many services."},
        {"id": "3", "text": "ServiceNow integration guide for beginners."},
    ]
    
    ranked = rerank_results(query, candidates, top_n=3)
    for i, res in enumerate(ranked):
        print(f"Rank {i+1} (ID: {res['id']}): {res.get('rerank_score'):.4f} - {res['text'][:50]}...")
    
    assert ranked[0]["id"] == "1", "Top result should be the most relevant one"
    print("✅ Reranker Test Passed")

def test_crag_gate_thresholds():
    print("\n--- Testing 2025 CRAG Thresholds ---")
    gate = CRAGGate()
    query = "ADP setup"
    
    # 1. High Score (CORRECT)
    high_chunks = [{"text": "ADP setup guide configuration", "rerank_score": 2.5}] # Logit 2.5 -> normalized ~0.92
    res_high = gate.score_context(query, high_chunks)
    print(f"High Score Status: {res_high['status']} (Score: {res_high['score']:.2f})")
    assert res_high["status"] == "CORRECT"
    
    # 2. Medium Score (AMBIGUOUS)
    mid_chunks = [{"text": "ADP mentions payroll", "rerank_score": 0.5}] # Logit 0.5 -> normalized ~0.62
    res_mid = gate.score_context(query, mid_chunks)
    print(f"Mid Score Status: {res_mid['status']} (Score: {res_mid['score']:.2f})")
    assert res_mid["status"] == "AMBIGUOUS"
    
    # 3. Low Score (INCORRECT)
    low_chunks = [{"text": "Service Now is a different tool", "rerank_score": -2.0}] # Logit -2.0 -> normalized ~0.12
    res_low = gate.score_context(query, low_chunks)
    print(f"Low Score Status: {res_low['status']} (Score: {res_low['score']:.2f})")
    assert res_low["status"] == "INCORRECT"
    
    print("✅ CRAG Gate Thresholds Verified")

def test_mcp_fallback_imports():
    print("\n--- Testing MCP Import Boundaries ---")
    try:
        from mcp_servers.zendesk_server import get_article
        from mcp_servers.user_context_server import get_user_context
        print("✅ MCP Server Imports Verified")
    except ImportError as e:
        print(f"❌ MCP Import Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    try:
        test_reranker()
        test_crag_gate_thresholds()
        test_mcp_fallback_imports()
        print("\n🚀 ALL SOTA BLOCK 1 TESTS PASSED")
    except Exception as e:
        print(f"\n❌ TEST SUITE FAILED: {str(e)}")
        sys.exit(1)
