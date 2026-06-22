import os
import json
import bm25s
from pathlib import Path
from typing import List, Dict, Any

class LexicalIndex:
    def __init__(self, index_dir: str):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.retriever = None
        self.corpus = []
        self.metadata = []

    def add_documents(self, chunks: List[Dict[str, Any]]):
        """Add new chunks to the lexical index."""
        for chunk in chunks:
            self.corpus.append(chunk["text"])
            # Store metadata separately to retrieve after search
            self.metadata.append({
                "id": chunk["id"],
                "article_id": chunk["article_id"],
                "title": chunk["title"],
                "integration_id": chunk["integration_id"],
                "product_version": chunk.get("product_version", ""),
                "url": chunk.get("url", ""),
                "field_id": chunk.get("field_id", ""),
                "doc_type": chunk.get("doc_type", "")
            })

    def build_and_save(self):
        """Build the BM25 index and save to disk."""
        if not self.corpus:
            return
        
        # Tokenize the corpus
        corpus_tokens = bm25s.tokenize(self.corpus, stopwords="en")
        
        # Create the retriever and index the corpus
        self.retriever = bm25s.BM25(corpus=self.corpus)
        self.retriever.index(corpus_tokens)
        
        # Save the index
        self.retriever.save(self.index_dir, corpus=self.corpus)
        
        # Save metadata
        with open(self.index_dir / "metadata.json", "w") as f:
            json.dump(self.metadata, f)

    def load(self):
        """Load the index from disk."""
        if not (self.index_dir / "params.index.json").exists():
            return False
            
        self.retriever = bm25s.BM25.load(self.index_dir, load_corpus=True)
        
        with open(self.index_dir / "metadata.json", "r") as f:
            self.metadata = json.load(f)
        return True

    def search(self, query: str, top_k: int = 5, product_version: str = None) -> List[Dict[str, Any]]:
        """Search the lexical index and return results with metadata."""
        if not self.retriever:
            if not self.load():
                return []
        
        query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
        results, scores = self.retriever.retrieve(query_tokens, k=top_k, show_progress=False, n_threads=1)
        
        search_results = []
        # results[0] because we only passed one query
        for i, match_text in enumerate(results[0]):
            score = float(scores[0][i])
            # Find the original index in the corpus
            # BM25S retrieve returns the documents themselves, we need to map back to metadata
            # For simplicity, we assume the order in results matches the retriever's view
            # In a real implementation, we'd use doc_ids if supported or store the index
            
            # Since BM25S retrieve returns the content, we find the first match in our metadata
            # This is a bit slow for large corpora but works for now.
            # Optimization: The retriever should return indices.
            
            # Let's get the doc indices from the retriever if possible
            # BM25S retrieve actually returns (indices, scores) if we don't pass corpus to load
            
            pass # See below for better search implementation using indices
            
        return search_results

    def search_with_indices(self, query: str, top_k: int = 10, product_version: str = None, article_filter: str = None) -> List[Dict[str, Any]]:
        """Search using indices for faster metadata mapping."""
        if not self.retriever:
            if not self.load():
                return []
        
        query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
        # If filtering, we must fetch ALL results to guarantee the filtered chunks aren't buried
        fetch_k = len(self.metadata) if article_filter else top_k
        idx, scores = self.retriever.retrieve(query_tokens, k=min(fetch_k, len(self.metadata)), return_as="tuple", show_progress=False, n_threads=1)
        
        search_results = []
        for i, doc_info in enumerate(idx[0]):
            if isinstance(doc_info, dict):
                doc_idx = doc_info["id"]
                doc_text = doc_info["text"]
            else:
                doc_idx = doc_info
                if isinstance(self.retriever.corpus, dict):
                    # Find the list and get index
                    for k, v in self.retriever.corpus.items():
                        if isinstance(v, list) and doc_idx < len(v):
                            doc_text = v[doc_idx]
                            break
                else:
                    doc_text = self.retriever.corpus[doc_idx]
                
            meta = self.metadata[doc_idx]
            
            # Version filtering
            if product_version and meta.get("product_version") and meta.get("product_version") != product_version:
                continue
                
            # Article filtering
            if article_filter and meta.get("article_id") != article_filter:
                # Debug print only once per doc_idx
                if i < 5:
                    print(f"DEBUG LEXICAL: skipping doc_idx={doc_idx}, meta article_id={meta.get('article_id')}, expected={article_filter}")
                continue
                
            search_results.append({
                "id": meta["id"],
                "text": doc_text,
                "score": float(scores[0][i]),
                "metadata": meta
            })
            
            if len(search_results) >= top_k:
                break
            
        return search_results

def merge_results_rrf(vector_results: List[Dict], lexical_results: List[Dict], k: int = 60) -> List[Dict]:
    """Merge results using Reciprocal Rank Fusion."""
    scores = {}
    
    # helper to track merged metadata
    meta_map = {}

    for rank, res in enumerate(vector_results):
        doc_id = res["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        meta_map[doc_id] = res

    for rank, res in enumerate(lexical_results):
        doc_id = res["id"]
        scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank + 1)
        if doc_id not in meta_map:
            meta_map[doc_id] = res

    # Sort by RRF score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
    
    merged = []
    for doc_id in sorted_ids:
        item = meta_map[doc_id]
        item["rrf_score"] = scores[doc_id]
        merged.append(item)
        
    return merged
