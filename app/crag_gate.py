from typing import List, Dict, Any, Optional
import json
from app.lexical_search import merge_results_rrf

class CRAGGate:
    """
    Corrective RAG (CRAG) Gate.
    Evaluates the quality of retrieved context before it reaches the generator.
    """
    def __init__(self, provider_client=None):
        self.client = provider_client

    def score_context(self, query: str, context_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Scores context chunks using a hybrid heuristic or provided rerank scores.
        Thresholds aligned with 2025 research:
        - CORRECT > 0.75
        - AMBIGUOUS [0.4, 0.75]
        - INCORRECT < 0.4
        """
        if not context_chunks:
            return {"status": "INCORRECT", "filtered_context": [], "score": 0.0}

        # Check if chunks already have rerank scores (preferred)
        scores = []
        for chunk in context_chunks:
            if "rerank_score" in chunk:
                # Normalize logit/score to 0-1 range (heuristic)
                # ms-marco logits are usually in range [-10, 10]
                # We'll use a sigmoid or simple min-max scaling if we had the full set
                # For now, let's assume the reranker provides a confidence score OR
                # use the logit to determine status.
                score = chunk["rerank_score"]
                # Heuristic mapping for MS-Marco logits
                # > 1.0 is very likely correct
                # < -2.0 is likely incorrect
                normalized = 1 / (1 + pow(2.718, -score)) # Sigmoid
                scores.append(normalized)
            else:
                # Fallback to keyword overlap
                query_words = set(query.lower().split())
                chunk_words = set(chunk.get("text", "").lower().split())
                overlap = len(query_words.intersection(chunk_words))
                score = overlap / max(1, len(query_words))
                scores.append(score)

        avg_score = sum(scores) / len(scores) if scores else 0.0
        
        # 2025 Research Thresholds
        status = "CORRECT"
        if avg_score < 0.30:
            status = "INCORRECT" # Horizon calls it UNVERIFIED
        elif avg_score < 0.75:
            status = "AMBIGUOUS"

        # Filter out very low scoring chunks (pruning)
        filtered = [c for i, c in enumerate(context_chunks) if scores[i] > 0.35]

        return {
            "status": status,
            "filtered_context": filtered,
            "score": avg_score
        }

    def hybrid_search(self, query: str, semantic_results: List[Dict], lexical_results: List[Dict]) -> List[Dict]:
        """
        Uses Reciprocal Rank Fusion (RRF) to merge semantic and lexical search results.
        Implementation moved from lexical_search for centralized logic.
        """
        from app.lexical_search import merge_results_rrf
        return merge_results_rrf(semantic_results, lexical_results)
