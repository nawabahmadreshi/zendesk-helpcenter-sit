#!/usr/bin/env python3
"""
CLI Query Utility to search the local knowledge base guides using Hybrid Search (ChromaDB + BM25)
and generate strictly grounded answers via the active LLM provider.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

# Prepend project root to sys.path to allow app imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv()

from config import Config
from app.embedding import get_chroma_collection
from app.lexical_search import LexicalIndex, merge_results_rrf
from app.reranker import rerank_results
from app.llm_utils import run_simple_llm_call

def search_hybrid(query: str, top_k: int = 5) -> list:
    cfg = Config()
    persist_dir = str(cfg.vectordb_dir)
    collection_name = "site_md_kb"
    
    # 1. Fetch from Vector DB (ChromaDB)
    v_results = []
    if os.environ.get("SKIP_VECTOR") != "true":
        try:
            collection = get_chroma_collection(persist_dir, collection_name=collection_name)
            # Generate embedding using Chroma's configured embedding function
            query_embedding = collection._embedding_function([query])[0]
            
            vector_res = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k * 10,
                include=["metadatas", "documents", "distances"]
            )
            
            if vector_res["ids"] and vector_res["ids"][0]:
                for i in range(len(vector_res["ids"][0])):
                    v_results.append({
                        "id": vector_res["ids"][0][i],
                        "text": vector_res["documents"][0][i],
                        "score": 1.0 - vector_res["distances"][0][i],
                        "metadata": vector_res["metadatas"][0][i]
                    })
        except Exception as e:
            print(f"[Warning] Vector search failed or collection not populated: {e}")
    else:
        print("[Info] Skipping vector search (lexical search only)")

    # 2. Fetch from BM25 Lexical Index
    l_results = []
    try:
        lexical_dir = cfg.STORAGE_DIR / "site_lexical_index"
        lex_index = LexicalIndex(str(lexical_dir))
        l_results = lex_index.search_with_indices(query, top_k=top_k * 10)
    except Exception as e:
        print(f"[Warning] Lexical search failed or index not populated: {e}")

    # 3. Merge results using Reciprocal Rank Fusion (RRF)
    merged = merge_results_rrf(v_results, l_results)

    # Filter out GEP results if query does not contain GEP
    if "gep" not in query.lower():
        merged = [
            r for r in merged 
            if "gep" not in r.get("metadata", {}).get("title", "").lower() 
            and "gep" not in r.get("metadata", {}).get("integration_id", "").lower()
        ]

    # Apply setup intent boosting
    intent_keywords = {"prerequisite", "prerequisites", "configure", "setup", "configuration", "install", "create", "add"}
    has_setup_intent = any(kw in query.lower() for kw in intent_keywords)
    if has_setup_intent:
        for r in merged:
            title_lower = r.get("metadata", {}).get("title", "").lower()
            slug_lower = r.get("metadata", {}).get("integration_id", "").lower()
            if "configuration guide" in title_lower or "setup guide" in title_lower or "config" in slug_lower or "setup" in slug_lower:
                r["score"] = r.get("score", 0) * 1.5
                if "rrf_score" in r:
                    r["rrf_score"] = r["rrf_score"] * 1.5

    # Apply exact title boost
    normalized_query = query.lower().replace("-", " ").replace(" ", "")
    for r in merged:
        title = r.get("metadata", {}).get("title", "")
        if title:
            normalized_title = title.lower().replace("-", " ").replace(" ", "")
            if normalized_title in normalized_query:
                r["score"] = r.get("score", 0) * 2.0
                if "rrf_score" in r:
                    r["rrf_score"] = r["rrf_score"] * 2.0

    # Re-sort merged by score or rrf_score
    merged = sorted(merged, key=lambda x: x.get("rrf_score", x.get("score", 0)), reverse=True)

    # 4. Optional: Rerank results
    try:
        reranked = rerank_results(query, merged, top_k=top_k)
        return reranked
    except Exception:
        return merged[:top_k]

def query_knowledge_base(question: str):
    print(f"\n🔍 Searching for: '{question}'...")
    results = search_hybrid(question, top_k=5)
    
    if not results:
        print("\n❌ No matching details found in the knowledge base indices.")
        print("Please run `python scripts/index_all_md.py` first to index your markdown files.")
        return

    print(f"📄 Found {len(results)} relevant guide sections. Preparing grounded answer...")

    # Build context from retrieved chunks
    context_blocks = []
    sources = []
    seen_sources = set()
    
    for i, res in enumerate(results):
        meta = res.get("metadata", {})
        title = meta.get("title", "Guide Section")
        url = meta.get("url", "")
        slug = meta.get("integration_id", "unknown")
        
        source_label = f"[{i+1}] Guide: {title} (File: site/{slug}/{slug}.md)"
        context_blocks.append(f"--- SOURCE {i+1} ---\nTitle: {title}\nPath: site/{slug}/\nContent:\n{res['text']}")
        
        if slug not in seen_sources:
            sources.append((title, f"site/{slug}/{slug}.md"))
            seen_sources.add(slug)

    context_str = "\n\n".join(context_blocks)

    # Construct the strictly-grounded prompt
    prompt = (
        f"Answer the user's question using ONLY the provided facts from the knowledge base context below. "
        f"Do NOT use any outside information or make assumptions. "
        f"If the answer cannot be found in the provided context, state: 'I cannot find this information in the knowledge base.'\n\n"
        f"CONTEXT:\n"
        f"=========================================\n"
        f"{context_str}\n"
        f"=========================================\n\n"
        f"QUESTION: {question}\n\n"
        f"Answer:"
    )

    system_instruction = (
        "You are a strict, factual QA assistant for internal product guides. "
        "You must ground your answers 100% in the provided context. "
        "If the answer is not contained in the context, explicitly say: 'I cannot find this information in the knowledge base.' "
        "Do not extrapolate or assume details outside the text."
    )

    try:
        # Generate the response using our unified LLM interface
        response = run_simple_llm_call(
            prompt=prompt,
            system_instruction=system_instruction,
            max_tokens=600,
            temperature=0.0  # Zero temperature for deterministic grounding
        )
        
        # Display the result
        print("\n==================== ANSWER ====================")
        print(response)
        print("================================================\n")
        
        print("📚 Grounding Sources:")
        for title, path in sources:
            print(f"- {title} (Path: [link](file://{ROOT}/{path}))")
        print()

    except Exception as e:
        print(f"\n❌ Failed to generate answer from LLM: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Interactive mode
        print("=== Knowledge Base QA Query Interface ===")
        while True:
            try:
                question = input("\nQuery (or 'q' to quit): ").strip()
                if not question or question.lower() == 'q':
                    break
                query_knowledge_base(question)
            except KeyboardInterrupt:
                break
    else:
        question = " ".join(sys.argv[1:])
        query_knowledge_base(question)
