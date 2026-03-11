"""Agent tools: functions the agentic AI can call to retrieve knowledge."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional


def search_knowledge_base(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    integration_id: Optional[str] = None,
) -> List[Dict]:
    """Search the vector store for KB chunks relevant to a query.

    This is re-exported from embedding.py for tool-call clarity.
    """
    from app.embedding import search_knowledge_base as _search

    return _search(
        query=query,
        api_key=api_key,
        persist_dir=persist_dir,
        top_k=top_k,
        integration_id=integration_id,
    )


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
    
    matches = []
    for f in articles_dir.glob("*.html"):
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


# ── Tool definitions for Gemini function calling ──────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Search the Zendesk knowledge base for articles relevant to the user's "
            "question or context. Returns the most relevant text chunks with metadata. "
            "Use this when you need to find information about integration setup, "
            "configuration steps, troubleshooting, or any product-related topic."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing what information is needed.",
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
]
