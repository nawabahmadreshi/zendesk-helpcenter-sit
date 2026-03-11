"""Embedding pipeline: chunk articles, generate embeddings via Gemini, store in ChromaDB."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import List, Dict, Optional

from bs4 import BeautifulSoup


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


def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """Split text into overlapping word-based chunks."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


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

def get_chroma_collection(persist_dir: str):
    """Get or create the ChromaDB collection for KB articles.
    
    Uses ChromaDB's built-in sentence-transformer embeddings (local, no API needed).
    """
    import chromadb
    from chromadb.utils import embedding_functions

    client = chromadb.PersistentClient(path=persist_dir)
    # Use the default all-MiniLM-L6-v2 sentence-transformer (runs locally)
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    collection = client.get_or_create_collection(
        name="zendesk_kb",
        metadata={"hnsw:space": "cosine"},
        embedding_function=emb_fn,
    )
    return collection


def generate_embeddings(texts: List[str], api_key: str) -> List[List[float]]:
    """Generate embeddings locally using sentence-transformers via ChromaDB.
    
    No external API needed — all embedding happens on your machine.
    """
    from chromadb.utils import embedding_functions
    emb_fn = embedding_functions.DefaultEmbeddingFunction()
    return list(emb_fn(texts))


def embed_articles(articles_dir: Path, persist_dir: str, api_key: str) -> Dict:
    """Embed all processed article HTML files into ChromaDB.

    Reads articles from the processed articles directory,
    chunks them, generates embeddings, and stores in ChromaDB.

    Returns a summary dict.
    """
    collection = get_chroma_collection(persist_dir)

    # Find all article HTML files
    html_files = list(articles_dir.glob("*.html"))
    if not html_files:
        return {"articles_embedded": 0, "chunks_stored": 0}

    all_chunks = []
    for html_file in html_files:
        html_content = html_file.read_text(encoding="utf-8")

        # Extract metadata from the HTML article tag
        soup = BeautifulSoup(html_content, "lxml")
        article_tag = soup.find("article")
        article_id = article_tag.get("data-article-id", "") if article_tag else ""

        # Extract integration_id from filename (format: integration_id_xxx_12345.html)
        filename = html_file.stem
        integration_id = ""
        if filename.startswith("integration_id_"):
            # The filename is "integration_id_<uuid>_<article_id>"
            # We want "integration_id_<uuid>"
            parts = filename.rsplit("_", 1)
            if len(parts) == 2:
                integration_id = parts[0]

        # Extract title from h1
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else filename

        metadata = {
            "article_id": article_id,
            "title": title,
            "integration_id": integration_id,
            "url": "",
        }

        chunks = chunk_article(html_content, metadata)
        all_chunks.extend(chunks)

    if not all_chunks:
        return {"articles_embedded": len(html_files), "chunks_stored": 0}

    # Generate embeddings
    texts = [c["text"] for c in all_chunks]
    embeddings = generate_embeddings(texts, api_key)

    # Upsert into ChromaDB
    ids = [c["id"] for c in all_chunks]
    metadatas = [
        {
            "article_id": c["article_id"],
            "title": c["title"],
            "integration_id": c["integration_id"],
            "url": c["url"],
            "chunk_index": c["chunk_index"],
        }
        for c in all_chunks
    ]
    documents = texts

    # ChromaDB upsert handles duplicates automatically
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i : i + batch_size],
            embeddings=embeddings[i : i + batch_size],
            metadatas=metadatas[i : i + batch_size],
            documents=documents[i : i + batch_size],
        )

    return {
        "articles_embedded": len(html_files),
        "chunks_stored": len(all_chunks),
    }


def search_knowledge_base(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    integration_id: Optional[str] = None,
) -> List[Dict]:
    """Search the KB vector store for chunks relevant to the query.

    If integration_id is provided, results are scoped to that integration first.
    Embeddings are generated locally using sentence-transformers.
    """
    collection = get_chroma_collection(persist_dir)

    # Build where filter if integration_id is specified
    where_filter = None
    if integration_id:
        where_filter = {"integration_id": integration_id}

    # Let ChromaDB generate the query embedding using its built-in function
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"],
    )

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
