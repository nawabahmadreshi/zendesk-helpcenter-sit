"""
Reranker with Contextual Compression
=====================================
Phase 3 of the SOTA optimization plan.

Techniques implemented:
1. Cross-Encoder Reranking (ms-marco-MiniLM-L-12-v2 — upgraded from L-6)
2. Contextual Compression: Strips sentences from chunks that are not relevant to the query,
   reducing LLM context noise and latency. Based on the 2024 RAG Compression research.
"""
from typing import List, Dict, Any
import re

# Minimum cross-encoder score for a sentence to survive compression
COMPRESSION_THRESHOLD = 0.2

class ReRanker:
    """
    Reranks a list of candidate context chunks against a user query 
    using a Cross-Encoder model.
    
    Now includes Contextual Compression: before returning results, 
    the reranker scores each sentence within a chunk and filters out
    low-relevance sentences to reduce noise passed to the LLM.
    """
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"):
        """
        Using L-12 (12-layer) model instead of L-6 for significantly higher 
        precision at ~2x the compute cost — still sub-second on CPU.
        """
        try:
            import torch
            from sentence_transformers import CrossEncoder
            self._has_torch = True
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = CrossEncoder(model_name, device=self.device)
            print(f"DEBUG: Reranker loaded on {self.device} using {model_name}")
        except ImportError:
            print("WARNING: torch or sentence_transformers not installed. Reranker disabled.")
            self._has_torch = False
            self.model = None

    def compress_chunk(self, query: str, chunk_text: str) -> str:
        """
        Contextual Compression: Split the chunk into sentences, score each
        sentence against the query, and return only the relevant sentences.
        
        This is the key innovation from the 2024 LangChain ContextualCompression research.
        """
        if not self.model or not chunk_text:
            return chunk_text

        # Preserve the SECTION: header lines — never compress these away
        lines = chunk_text.split("\n")
        header_lines = []
        content_lines = []
        for line in lines:
            if line.startswith("DOCUMENT:") or line.startswith("SECTION:") or line.startswith("SUMMARY:") or line.startswith("ABSTRACT:"):
                header_lines.append(line)
            else:
                content_lines.append(line)
        
        content_text = "\n".join(content_lines).strip()
        if not content_text:
            return chunk_text

        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', content_text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        
        if len(sentences) <= 2:
            # Too short to compress — just return as-is
            return chunk_text

        try:
            # Score each sentence against the query
            pairs = [[query, sent] for sent in sentences]
            scores = self.model.predict(pairs)
            
            # Keep sentences above the threshold
            kept = [sentences[i] for i, score in enumerate(scores) if score > COMPRESSION_THRESHOLD]
            
            # Fallback: if everything is filtered out, keep the top 3 sentences
            if not kept:
                top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:3]
                kept = [sentences[i] for i in sorted(top_indices)]
                
        except Exception as e:
            print(f"DEBUG: Compression failed, returning full chunk: {e}")
            return chunk_text

        compressed_content = " ".join(kept)
        header_block = "\n".join(header_lines)
        
        if header_block:
            return f"{header_block}\n{compressed_content}"
        return compressed_content

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_k: int = 5, compress: bool = False) -> List[Dict[str, Any]]:
        """
        Takes a query and candidate documents, returning the top_k most relevant chunks.
        If compress=True, applies Contextual Compression to each chunk before returning.
        """
        if not candidates or not self.model:
            return candidates[:top_k] if candidates else []
            
        # Prepare pairs for the model: [query, doc_text]
        pairs = [[query, c.get("text", "")] for c in candidates]
        
        # Get relevance scores from cross-encoder
        scores = self.model.predict(pairs)
        
        # Combined candidates with their scores
        for i, candidate in enumerate(candidates):
            candidate["score"] = float(scores[i])
            candidate["rerank_score"] = float(scores[i])
            
        # Sort by rerank score descending
        ranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
        top = ranked[:top_k]

        # Apply contextual compression to the top results if requested
        if compress:
            for chunk in top:
                original_text = chunk.get("text", "")
                chunk["original_text"] = original_text  # Preserve original for "View Exact Section"
                chunk["text"] = self.compress_chunk(query, original_text)

        return top

_GLOBAL_RERANKER = None

def rerank_results(query: str, candidates: List[Dict[str, Any]], api_key: str = "", top_n: int = 5, compress: bool = False, **kwargs) -> List[Dict[str, Any]]:
    """Compatibility wrapper for ReRanker using a global singleton."""
    global _GLOBAL_RERANKER
    if _GLOBAL_RERANKER is None:
        print("DEBUG: Initializing Global ReRanker (First Run)...")
        _GLOBAL_RERANKER = ReRanker()
    return _GLOBAL_RERANKER.rerank(query, candidates, top_k=top_n, compress=compress)

def compress_context(query: str, text: str) -> str:
    """Convenience function to compress a single text against a query."""
    global _GLOBAL_RERANKER
    if _GLOBAL_RERANKER is None:
        _GLOBAL_RERANKER = ReRanker()
    return _GLOBAL_RERANKER.compress_chunk(query, text)
