import json
import hashlib
from typing import List, Dict, Any, Optional
from pathlib import Path
from app.llm_utils import run_simple_llm_call
from config import Config

# Max chunks to send at once for summarization (avoid overwhelming the LLM)
RAPTOR_CLUSTER_SIZE = 6

class RaptorEngine:
    """
    Recursive Abstractive Processing for Tree-Organized Retrieval (RAPTOR).
    Builds a MULTI-LEVEL hierarchical tree of summaries over knowledge base chunks.
    
    Level 0: Leaf chunks (raw article sections, stored by embed_single_article)
    Level 1: Cluster summaries (groups of related sections from same article)
    Level 2: Document-level abstract (all Level 1 summaries merged into one)
    
    This mirrors the original RAPTOR paper (Sarthi et al., 2024).
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.cfg = Config()

    def _summarize_group(self, chunks: List[Dict[str, Any]], level: int) -> Dict[str, Any]:
        """
        Summarizes a group of related chunks into a single 'Parent Chunk' at a given tree level.
        """
        if not chunks:
            return {}

        combined_text = "\n\n".join([c.get("text", "") for c in chunks])
        
        # Level-specific summarization tone
        if level == 1:
            instruction = (
                "You are a Technical Documentation Summarizer. Generate a comprehensive, technically dense summary "
                "for the following group of documentation sections. Extract core configurations, field requirements, "
                "and version-specific constraints. Be concise but complete."
            )
        else:
            instruction = (
                "You are a Knowledge Architect. Generate a high-level abstract that summarizes what this entire guide is about. "
                "Include the guide's purpose, primary audience, and the top-level topics it covers. "
                "This abstract will be used to answer broad, conceptual questions."
            )
        
        prompt = (
            f"CHUNKS TO SUMMARIZE:\n{combined_text[:6000]}\n\n"
            f"SUMMARY:"
        )
        
        summary_text = run_simple_llm_call(
            prompt=prompt,
            system_instruction=instruction,
            max_tokens=800 if level == 1 else 400
        )

        if not summary_text:
            return {}

        child_ids = sorted([c["id"] for c in chunks])
        summary_id = hashlib.md5(f"raptor_l{level}_{'_'.join(child_ids[:5])}".encode()).hexdigest()

        first_meta = chunks[0]
        title_prefix = "SECTION SUMMARY" if level == 1 else "DOCUMENT ABSTRACT"
        
        return {
            "id": summary_id,
            "text": f"{title_prefix}: {first_meta.get('title', 'Knowledge Cluster')}\n\n{summary_text}",
            "article_id": first_meta.get("article_id", "multi"),
            "title": first_meta.get("title", "Knowledge Cluster"),
            "integration_id": first_meta.get("integration_id", "global"),
            "product_version": first_meta.get("product_version", ""),
            "doc_type": f"raptor_level_{level}",
            "hierarchy_level": level,
            "child_ids": json.dumps(child_ids[:10]),  # Store as JSON string for ChromaDB
            "url": first_meta.get("url", ""),
            "chunk_index": -level,  # Negative to distinguish from leaf chunks
        }

    def build_tree_for_article(self, article_chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Takes leaf chunks for a single article and builds a MULTI-LEVEL summary tree.
        
        Returns all Level 1 + Level 2 summary chunks to be stored alongside leaf chunks.
        """
        if not article_chunks or len(article_chunks) <= 1:
            return []

        all_summaries = []

        # === LEVEL 1: Cluster chunks into groups and summarize each group ===
        level1_summaries = []
        for i in range(0, len(article_chunks), RAPTOR_CLUSTER_SIZE):
            cluster = article_chunks[i : i + RAPTOR_CLUSTER_SIZE]
            if len(cluster) < 2:
                continue  # Skip trivially small clusters
            summary = self._summarize_group(cluster, level=1)
            if summary:
                level1_summaries.append(summary)
                all_summaries.append(summary)

        # === LEVEL 2: Summarize all Level 1 summaries into a single document abstract ===
        if len(level1_summaries) >= 2:
            doc_abstract = self._summarize_group(level1_summaries, level=2)
            if doc_abstract:
                all_summaries.append(doc_abstract)

        return all_summaries

    def build_category_summaries(self, all_articles: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Takes list of all articles (each being a list of chunks) and creates multi-level summaries.
        """
        summaries = []
        for article_chunks in all_articles:
            art_summaries = self.build_tree_for_article(article_chunks)
            summaries.extend(art_summaries)
            
        return summaries
