"""Embedding pipeline: chunk articles, generate embeddings via Gemini, store in ChromaDB."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Dict, Optional, Any

import chromadb
from bs4 import BeautifulSoup
from chromadb import Documents, EmbeddingFunction, Embeddings
from google import genai

from config import Config
from app.llm_utils import retry_with_backoff


# ── chunking ───────────────────────────────────────────────────────────

def _strip_html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving paragraph breaks."""
    soup = BeautifulSoup(html, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 200) -> List[str]:
    """Split text into overlapping sections, trying to respect paragraph/sentence boundaries."""
    if len(text) <= chunk_size:
        return [text]

    # Simple recursive-ish splitter
    separators = ["\n\n", "\n", ". ", " "]
    
    def split_rec(txt: str, seps: List[str]) -> List[str]:
        if len(txt) <= chunk_size:
            return [txt]
        
        sep = seps[0] if seps else " "
        next_seps = seps[1:] if len(seps) > 1 else []
        
        parts = txt.split(sep)
        chunks = []
        curr = ""
        for p in parts:
            if curr and len(curr) + len(sep) + len(p) > chunk_size:
                chunks.append(curr)
                curr = p
            else:
                curr = (curr + sep + p) if curr else p
            
            if len(curr) > chunk_size and next_seps:
                # Sub-split
                sub = split_rec(curr, next_seps)
                if sub:
                    chunks.extend(sub[:-1])
                    curr = sub[-1]
        
        if curr:
            chunks.append(curr)
        return chunks

    return split_rec(text, separators)


def chunk_article(article_html: str, article_metadata: Dict) -> List[Dict]:
    """Convert a cleaned article HTML into chunks with metadata.

    Returns a list of dicts with keys: text, article_id, title, integration_id, url, chunk_index
    """
    text = _strip_html_to_text(article_html)
    if not text.strip():
        return []

    chunks = _chunk_text(text)
    result = []
    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(
            f"{article_metadata.get('article_id', '')}_{i}".encode()
        ).hexdigest()
        result.append({
            "id": chunk_id,
            "text": chunk,
            "article_id": str(article_metadata.get("article_id", "")),
            "title": article_metadata.get("title", ""),
            "integration_id": article_metadata.get("integration_id", ""),
            "url": article_metadata.get("url", ""),
            "chunk_index": i,
        })
    return result


# ── embedding + storage ────────────────────────────────────────────────

class OllamaEmbeddingFunction(EmbeddingFunction):
    """Custom ChromaDB embedding function using Ollama's embeddings API."""
    def __init__(self, base_url: str, model_name: str = "nomic-embed-text"):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    def __call__(self, input: Documents) -> Embeddings:
        import requests
        embeddings = []
        for text in input:
            try:
                response = requests.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                    timeout=30
                )
                response.raise_for_status()
                embeddings.append(response.json()["embedding"])
            except Exception as e:
                print(f"Ollama Embedding Error: {e}")
                # Fallback to zero vector of expected size (e.g. 768 for nomic)
                embeddings.append([0.0] * 768)
        return embeddings


def get_chroma_collection(persist_dir: str, collection_name: Optional[str] = None):
    """Get or create the appropriate ChromaDB collection based on AI provider."""
    cfg = Config()
    client = chromadb.PersistentClient(path=persist_dir)
    
    # Auto-select based on provider if not explicitly named
    if not collection_name:
        if cfg.AI_PROVIDER == "ollama":
            # Default to general, but sync_category.py will explicitly use both
            collection_name = "kb_v3_ollama_general"
        else:
            collection_name = "general_kb_v2"

    if cfg.AI_PROVIDER == "ollama":
        emb_fn = OllamaEmbeddingFunction(
            base_url=cfg.OLLAMA_BASE_URL,
            model_name=cfg.OLLAMA_EMBED_MODEL
        )
    else:
        emb_fn = GeminiEmbeddingFunction(api_key=cfg.GEMINI_API_KEY)
    
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=emb_fn,
    )
    return collection


def generate_embeddings(texts: List[str], api_key: str) -> List[List[float]]:
    """Generate embeddings locally using Gemini via ChromaDB function."""
    emb_fn = GeminiEmbeddingFunction(api_key=api_key)
    return list(emb_fn(texts))


def delete_article_embeddings(article_id: str, persist_dir: str, collection_name: str = "kb_v2_gemini") -> bool:
    """Delete all chunks for a specific article from a specific ChromaDB collection."""
    collection = get_chroma_collection(persist_dir, collection_name)
    try:
        # ChromaDB supports deleting exactly by looking up the metadata key
        collection.delete(where={"article_id": str(article_id)})
        return True
    except Exception as e:
        print(f"Error deleting embeddings for article {article_id} in {collection_name}: {e}")
        return False


def embed_single_article(html_file: Path, persist_dir: str, api_key: str, collection_name: Optional[str] = None) -> Dict:
    """Embed a single processed article HTML file into the appropriate ChromaDB collection."""
    collection = get_chroma_collection(persist_dir, collection_name)

    if not html_file.exists():
        return {"chunks_stored": 0, "error": f"File not found: {html_file.name}"}

    html_content = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "lxml")
    
    article_tag = soup.find("article")
    article_id = article_tag.get("data-article-id", "") if article_tag else ""

    filename = html_file.stem
    integration_id = "global"
    if filename.startswith("integration_id_"):
        parts = filename.rsplit("_", 1)
        if len(parts) == 2:
            integration_id = parts[0]

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else filename

    metadata = {
        "article_id": article_id,
        "title": title,
        "integration_id": integration_id,
        "url": "",
    }

    chunks = chunk_article(html_content, metadata)
    if not chunks:
        return {"chunks_stored": 0}

    # Embeddings are handled by ChromaDB using the custom embedding function
    ids = [c["id"] for c in chunks]
    metadatas = [
        {
            "article_id": c["article_id"],
            "title": c["title"],
            "integration_id": c["integration_id"],
            "url": c["url"],
            "chunk_index": c["chunk_index"],
        }
        for c in chunks
    ]
    texts = [c["text"] for c in chunks]

    collection.upsert(
        ids=ids,
        metadatas=metadatas,
        documents=texts,
    )

    return {"chunks_stored": len(chunks)}


def search_knowledge_base(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    integration_id: Optional[str] = None,
    collection_name: Optional[str] = None,
) -> List[Dict]:
    """Search the specified KB vector store for chunks relevant to the query.

    If integration_id is provided, results are scoped to that integration first.
    """
    collection = get_chroma_collection(persist_dir, collection_name)

    # Build where filter if integration_id is specified
    where_filter = None
    if integration_id:
        where_filter = {"integration_id": integration_id}

    # Let ChromaDB generate the query embedding using its built-in function
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        print(f"CRITICAL SEARCH ERROR (Embedding likely limited): {e}")
        # Return empty results so the agent can still try to help using UI context
        return []

    # Format results
    formatted = []
    if results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            formatted.append({
                "text": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })

    return formatted
def rewrite_query(query: str, api_key: str = "") -> str:
    """Use configured LLM to expand a shorthand/vague query into a descriptive search term."""
    from app.llm_utils import run_simple_llm_call
    try:
        prompt = (
            f"Transform the following user help-desk query into a high-fidelity, descriptive search term "
            f"that would better match a technical knowledge base article. Do not answer the question, "
            f"just provide the optimized search string.\n\n"
            f"Query: {query}\n\n"
            f"Optimized Search String:"
        )
        optimized = run_simple_llm_call(
            prompt=prompt,
            system_instruction="You are a Search Optimization Expert.",
            max_tokens=100
        )
        return optimized if optimized else query
    except Exception as e:
        print(f"Query Rewriting Error: {e}")
        return query


def generate_hyde_query(query: str, api_key: str = "") -> str:
    """Generate a hypothetical 'ideal' answer chunk (HyDE) to use for semantic search."""
    from app.llm_utils import run_simple_llm_call
    try:
        prompt = (
            f"Generate a brief, factual, and technical paragraph that answers the following query. "
            f"This paragraph will be used for semantic similarity search in a knowledge base.\n\n"
            f"Query: {query}\n\n"
            f"Hypothetical Answer Paragraph:"
        )
        hyde_ans = run_simple_llm_call(
            prompt=prompt,
            system_instruction="You are a Technical Documentation Writer.",
            max_tokens=300
        )
        return hyde_ans if hyde_ans else query
    except Exception as e:
        print(f"HyDE Error: {e}")
        return query


def rerank_results(query: str, results: List[Dict], api_key: str = "", top_n: int = 3) -> List[Dict]:
    """Use LLM as a re-ranker (Cross-Encoder style) to score and filter the best chunks."""
    if not results:
        return []

    from app.llm_utils import run_simple_llm_call
    try:
        # Prepare the context for reranking
        context_items = []
        for i, res in enumerate(results):
            text = res.get("text", "")[:500] # Limit chunk size for reranking
            context_items.append(f"[{i}] {text}")
        
        context_str = "\n\n".join(context_items)
        
        prompt = (
            f"Given the user query: '{query}'\n\n"
            f"Rank the following knowledge base chunks by how well they answer or provide relevant "
            f"context for the query. Return a comma-separated list of ONLY the indices (e.g., 0, 2, 1) "
            f"ordered from most relevant to least relevant.\n\n"
            f"Chunks:\n{context_str}\n\n"
            f"Ordered Indices:"
        )
        
        indices_str = run_simple_llm_call(
            prompt=prompt,
            system_instruction="You are a Document Ranking Expert.",
            max_tokens=50
        )
        
        # Parse indices like "0, 2, 1"
        import re
        parsed_indices = [int(idx) for idx in re.findall(r'\d+', indices_str)]
        
        reranked = []
        seen_indices = set()
        for idx in parsed_indices:
            if idx < len(results) and idx not in seen_indices:
                reranked.append(results[idx])
                seen_indices.add(idx)
        
        # Add any missing results at the end just in case LLM missed some
        for i, res in enumerate(results):
            if i not in seen_indices:
                reranked.append(res)
                
        return reranked[:top_n]
    except Exception as e:
        print(f"Reranking Error: {e}")
        return results[:top_n]
