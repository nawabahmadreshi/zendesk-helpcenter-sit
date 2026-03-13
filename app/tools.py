"""Agent tools: functions the agentic AI can call to retrieve knowledge."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


def _get_collection_names() -> tuple[str, str]:
    """Return (integration_collection, general_collection) based on active AI_PROVIDER."""
    from config import Config
    cfg = Config()
    if cfg.AI_PROVIDER == "ollama":
        return "kb_v3_ollama_integration", "kb_v3_ollama_general"
    return "integration_kb_v2", "general_kb_v2"


def extract_integration_signals(page_context: Dict) -> str:
    """Extract app/product name signals from page context and build a composite search query.
    
    Looks at: page_title, url_path, headings, active_nav, descriptions
    Returns a rich query string like: 'ADP Workforce Now ServiceNow integration guide setup'
    """
    signals = []

    title = page_context.get("page_title", "").lower()
    
    # DETECT GALLERY/LIST PAGES: 
    # If we are in "Create Integration" or "Explore Templates", we are looking at a gallery.
    # In a gallery, matching a specific integration article is usually a mistake because
    # multiple different integration names (ADP, UKG, etc) appear as tiles.
    is_gallery = any(k in title for k in ["create integration", "explore templates", "gallery", "directory"])
    
    if is_gallery:
        return "Aquera create integration gallery guide"

    signals = []
    if page_context.get("page_title"):
        signals.append(page_context["page_title"])

    url_path = page_context.get("url_path", "")
    if url_path:
        # Extract readable words from URL path segments
        parts = re.sub(r'[/_\-]', ' ', url_path)
        parts = re.sub(r'\s+', ' ', parts).strip()
        if parts and parts not in signals:
            signals.append(parts)

    headings = page_context.get("headings", [])
    if headings:
        signals.extend(headings[:3])  # First 3 headings

    active_nav = page_context.get("active_nav", "")
    if active_nav and active_nav not in signals:
        signals.append(active_nav)

    # Also try to find "X to Y" or "X → Y" patterns (integration title pattern)
    full_text = " ".join(signals)
    arrow_pattern = re.search(r'([A-Z][\w\s]{2,30})(?:\s*(?:→|to|->)\s*)([A-Z][\w\s]{2,30})', full_text)
    if arrow_pattern:
        src = arrow_pattern.group(1).strip()
        tgt = arrow_pattern.group(2).strip()
        signals.insert(0, f"{src} to {tgt} integration guide")

    # Build the composite query
    composite = " ".join(dict.fromkeys(signals))  # deduplicate preserving order
    composite = composite[:400]  # keep it within limits
    return composite or title or "integration guide"


def search_integration_kb(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    integration_id: Optional[str] = None,
) -> List[Dict]:
    """Search solely the Integration context database with Neural Enhancements."""
    from app.embedding import (
        search_knowledge_base, 
        rewrite_query, 
        generate_hyde_query, 
        rerank_results
    )

    # 1. Neural Query Optimization
    optimized_query = rewrite_query(query, api_key)
    hyde_query = generate_hyde_query(query, api_key)

    # 2. Vector Retrieval (Search with both standard and HyDE queries)
    # We fetch more results than needed for reranking
    int_coll, _ = _get_collection_names()
    results_std = search_knowledge_base(
        query=optimized_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=integration_id, collection_name=int_coll
    )
    results_hyde = search_knowledge_base(
        query=hyde_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=integration_id, collection_name=int_coll
    )

    # Combine and deduplicate
    combined = []
    seen_texts = set()
    for res in results_std + results_hyde:
        if res["text"] not in seen_texts:
            combined.append(res)
            seen_texts.add(res["text"])

    # 3. LLM Reranking
    return rerank_results(query, combined, api_key, top_n=top_k)


def search_general_kb(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
) -> List[Dict]:
    """Search the expansive general knowledge base with Neural Enhancements."""
    from app.embedding import (
        search_knowledge_base, 
        rewrite_query, 
        generate_hyde_query, 
        rerank_results
    )

    # 1. Neural Optimization
    optimized_query = rewrite_query(query, api_key)
    hyde_query = generate_hyde_query(query, api_key)

    # 2. Multi-Vector Retrieval
    _, gen_coll = _get_collection_names()
    results_std = search_knowledge_base(
        query=optimized_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=None, collection_name=gen_coll
    )
    results_hyde = search_knowledge_base(
        query=hyde_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=None, collection_name=gen_coll
    )

    # Combine and deduplicate
    combined = []
    seen_texts = set()
    for res in results_std + results_hyde:
        if res["text"] not in seen_texts:
            combined.append(res)
            seen_texts.add(res["text"])

    # 3. LLM Reranking
    return rerank_results(query, combined, api_key, top_n=top_k)


def get_article_by_integration_id(
    integration_id: str,
    articles_dir: Path,
) -> Optional[Dict]:
    """Directly look up an article file by integration_id.

    Files are named like: integration_id_xxx_12345.html
    Returns the article text + metadata, or None if not found.
    """
    from bs4 import BeautifulSoup

    # fuzzy match: allow hyphen/underscore swap and case-insensitive check
    clean_id = integration_id.lower().replace("-", "_").replace("integration_id_", "")
    
    # Cast articles_dir to Path if it's a string
    if isinstance(articles_dir, str):
        articles_dir = Path(articles_dir)
        
    # The integration articles are now nested inside the 'integration' subdirectory
    integration_sub_dir = articles_dir / "integration"
    
    if not integration_sub_dir.exists():
        return None

    # We assume the filename convention uses integration_id
    # e.g., integration_id_12345.html or similar
    # In earlier versions it was something like <title>_<id>.html
    # so we glob the whole directory for simplicity.
    
    matches = []
    for f in integration_sub_dir.glob("*.html"):
        fname = f.name.lower().replace("-", "_")
        if fname.startswith(clean_id + "_") or fname.startswith("integration_id_" + clean_id + "_"):
            matches.append(f)

    if not matches:
        return None

    # Use the first match
    html_file = matches[0]
    html_content = html_file.read_text(encoding="utf-8")

    soup = BeautifulSoup(html_content, "lxml")
    article_tag = soup.find("article")
    article_id = article_tag.get("data-article-id", "") if article_tag else ""

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""

    # Get clean text
    text = soup.get_text(separator="\n", strip=True)

    return {
        "article_id": article_id,
        "integration_id": integration_id,
        "title": title,
        "text": text,
        "filename": html_file.name,
    }


def get_article_by_id(
    article_id: str,
    articles_dir: Path,
) -> Optional[Dict]:
    """Fetch the full article text and metadata for a specific article_id."""
    from bs4 import BeautifulSoup
    
    if isinstance(articles_dir, str):
        articles_dir = Path(articles_dir)
        
    # Search in both subdirectories
    for sub in ["integration", "general"]:
        sub_dir = articles_dir / sub
        if not sub_dir.exists():
            continue
            
        # Files are named like: [title]_[id].html or integration_id_[int_id]_[id].html
        # We look for the id at the end before .html
        for f in sub_dir.glob(f"*_{article_id}.html"):
            html_content = f.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_content, "lxml")
            
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else f.stem
            
            text = soup.get_text(separator="\n", strip=True)
            
            return {
                "article_id": article_id,
                "title": title,
                "text": text,
                "filename": f.name,
                "section": sub
            }
    return None


# ── Tool definitions for Gemini function calling ──────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_integration_kb",
        "description": (
            "Search the highly-curated UI integration guides for articles relevant to the user's "
            "question about the specific screen or feature they are looking at. "
            "Use this primarily when the user is asking about an integration_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing the step or integration feature.",
                },
                "integration_id": {
                    "type": "string",
                    "description": "Optional: Only search for articles related to this integration ID.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_general_kb",
        "description": (
            "Search the expansive Zendesk company knowledge base for general questions. "
            "Use this when the user is asking generic product questions, policy questions, "
            "or if the integration KB doesn't have the answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing what general information is needed.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 5).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_article_by_integration_id",
        "description": (
            "Fetch the full knowledge base article for a specific integration by its "
            "integration_id. Use this when the user is on a specific integration page "
            "and you know the integration_id. Returns the complete article text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "integration_id": {
                    "type": "string",
                    "description": "The integration ID (e.g., 'integration_id_adp_okta').",
                },
            },
            "required": ["integration_id"],
        },
    },
    {
        "name": "get_article_by_id",
        "description": (
            "Fetch the complete full-text article for a specific internal article_id. "
            "Use this when a search result gives you an article_id and you need the whole article context "
            "to give a better answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "The article ID (numeric string).",
                },
            },
            "required": ["article_id"],
        },
    },
]
