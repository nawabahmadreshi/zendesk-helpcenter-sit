"""Agent tools: functions the agentic AI can call to retrieve knowledge."""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import Config
from app.graph_store import GraphStore

def _get_collection_names() -> tuple[str, str]:
    """Return (integration_collection, general_collection) based on active AI_PROVIDER."""
    from config import Config
    cfg = Config()
    if cfg.AI_PROVIDER == "ollama":
        return "kb_v3_ollama_integration", "kb_v3_ollama_general"
    return "kb_v3_integration_gemini", "kb_v3_gemini"


def rerank_chunks(query: str, candidates: List[Dict], top_k: int = 5) -> List[Dict]:
    """
    Stage 1: Reduce top-30 ChromaDB+BM25 candidates to top-5.
    Scores (query, chunk_text) pairs jointly — far more accurate than cosine sim.
    Calls standardized app.reranker.rerank_results.
    """
    if not candidates:
        return []
    from app.reranker import rerank_results
    return rerank_results(query, candidates, top_n=top_k)


def extract_integration_signals(page_context: Dict) -> str:
    """Extract app/product name signals from page context and build a composite search query.
    
    Looks at: clicked_card (highest priority), page_title, url_path, headings, active_nav, descriptions
    Returns a rich query string like: 'ADP Workforce Now ServiceNow integration guide setup'
    """
    signals = []

    # ── HIGHEST PRIORITY: clicked_card (set when user clicks a specific integration card) ──
    clicked_card = page_context.get("clicked_card", "")
    if clicked_card:
        # The user clicked a specific integration — use its name as the primary signal.
        # Append "integration guide setup" to help the vector search find the right article.
        return f"{clicked_card} integration guide setup configuration"

    title = page_context.get("page_title", "").lower()
    
    is_gallery = any(k in title for k in ["create integration", "explore templates", "gallery", "directory"])
    
    if is_gallery:
        # For galleries, sample up to 5 visible integration titles to help grounding
        gall_signals = ["Aquera integration library directory"]
        if page_context.get("headings"):
            gall_signals.extend(page_context["headings"][:5])
        return " ".join(gall_signals)

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

    # NEW: Navigation & Modal Awareness
    nav_items = page_context.get("nav_items", [])
    if nav_items:
        signals.extend(nav_items[:5]) # Top 5 nav items for grounding

    if page_context.get("is_modal_open") and page_context.get("modal_title"):
        signals.insert(0, f"MODAL: {page_context['modal_title']}") # High priority signal

    # NEW: Error-Aware Signals
    # If there are active errors, include them in the search query to find troubleshooting info
    active_errors = page_context.get("active_errors", [])
    if active_errors:
        for err in active_errors[:2]: # Top 2 errors
            signals.append(err)
            signals.append("troubleshooting")

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
    product_version: Optional[str] = None,
    **kwargs
) -> List[Dict]:
    """Search solely the Integration context database with Neural Enhancements."""
    from app.embedding import (
        search_knowledge_base, 
        rewrite_query, 
        generate_hyde_query, 
        rerank_results
    )

    # 1. Neural Query Optimization (RESTORED for accuracy)
    optimized_query = rewrite_query(query, api_key)
    hyde_query = generate_hyde_query(query, api_key)

    # 2. Vector Retrieval
    # We fetch more results than needed for reranking
    int_coll, _ = _get_collection_names()
    results_std = search_knowledge_base(
        query=optimized_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=integration_id, product_version=product_version, collection_name=int_coll
    )
    results_hyde = search_knowledge_base(
        query=hyde_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=integration_id, product_version=product_version, collection_name=int_coll
    )

    # 3. Lexical Retrieval (BM25)
    from app.lexical_search import LexicalIndex, merge_results_rrf
    from config import Config
    cfg = Config()
    lex_index = LexicalIndex(str(cfg.lexical_index_dir))
    lex_results = lex_index.search_with_indices(query=query, top_k=top_k * 2, product_version=product_version)

    # 4. Hybrid Merge (RRF)
    # Combine std and hyde vector results first
    vector_combined = []
    v_seen = set()
    for res in results_std + results_hyde:
        if res["text"] not in v_seen:
            vector_combined.append(res)
            v_seen.add(res["text"])
    
    hybrid_merged = merge_results_rrf(vector_combined, lex_results)

    # 5. Neural Reranking + Contextual Compression (SOTA Phase 3)
    # compress=True strips irrelevant sentences from each chunk, reducing noise to the LLM.
    if kwargs.get("skip_rerank"):
        return hybrid_merged
    return rerank_results(query, hybrid_merged, api_key, top_n=top_k, compress=True)


def search_general_kb(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    product_version: Optional[str] = None,
    **kwargs
) -> List[Dict]:
    """Search the expansive general knowledge base with Neural Enhancements."""
    from app.embedding import (
        search_knowledge_base, 
        rewrite_query, 
        generate_hyde_query, 
        rerank_results
    )

    # 1. Neural Optimization (RESTORED for accuracy)
    optimized_query = rewrite_query(query, api_key)
    hyde_query = generate_hyde_query(query, api_key)

    # 2. Multi-Vector Retrieval
    _, gen_coll = _get_collection_names()
    results_std = search_knowledge_base(
        query=optimized_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=None, product_version=product_version, collection_name=gen_coll
    )
    results_hyde = search_knowledge_base(
        query=hyde_query, api_key=api_key, persist_dir=persist_dir, 
        top_k=top_k * 2, integration_id=None, product_version=product_version, collection_name=gen_coll
    )

    # Combine and deduplicate
    combined = []
    seen_texts = set()
    for res in results_std + results_hyde:
        if res["text"] not in seen_texts:
            combined.append(res)
            seen_texts.add(res["text"])

    # 3. Neural Reranking + Contextual Compression (SOTA Phase 3)
    if kwargs.get("skip_rerank"):
        return combined
    return rerank_results(query, combined, api_key, top_n=top_k, compress=True)


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

    soup = BeautifulSoup(html_content, "html.parser")
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
        
    # Handle site_ prefix (from lexical index)
    if article_id.startswith("site_"):
        try:
            from config import Config
            cfg = Config()
            meta_file = cfg.lexical_index_dir / "metadata.json"
            if meta_file.exists():
                import json
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta_list = json.load(f)
                    if isinstance(meta_list, list):
                        for meta in meta_list:
                            if meta.get("article_id") == article_id:
                                url = meta.get("url")
                                if url and Path(url).exists():
                                    html_content = Path(url).read_text(encoding="utf-8")
                                    soup = BeautifulSoup(html_content, "html.parser")
                                    main_content = soup.find("article") or soup.find(class_="md-content") or soup
                                    title = meta.get("title", article_id)
                                    text = main_content.get_text(separator="\n", strip=True)
                                    
                                    # Create a clean HTML version for the viewer if we can
                                    if main_content.name == "article" or "md-content" in main_content.get("class", []):
                                        clean_html = str(main_content)
                                    else:
                                        clean_html = html_content
                                        
                                    return {
                                        "title": title,
                                        "text": text,
                                        "html": clean_html,
                                        "section": "Integration",
                                        "url": url
                                    }
        except Exception as e:
            print(f"Error loading site article {article_id}: {e}")

    # Search in both subdirectories
    for sub in ["integration", "general"]:
        sub_dir = articles_dir / sub
        if not sub_dir.exists():
            continue
            
        # Files are named like: [title]_[id].html or integration_id_[int_id]_[id].html
        # We look for the id at the end before .html
        for f in sub_dir.glob(f"*_{article_id}.html"):
            html_content = f.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_content, "html.parser")
            
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else f.stem
            
            text = soup.get_text(separator="\n", strip=True)
            
            return {
                "article_id": article_id,
                "title": title,
                "text": html_content, # Return full HTML for viewer
                "plain_text": text,
                "filename": f.name,
                "section": sub
            }
    return None


def check_domain_reachability(domain_or_url: str) -> str:
    """Check if a domain or URL is reachable via a simple HEAD request.
    
    Useful for troubleshooting connection, domain, or certificate errors
    when a user provides integration settings.
    """
    import requests
    target = domain_or_url.strip()
    if not target.startswith("http"):
        target = "https://" + target
        
    try:
        # 5s timeout, don't verify SSL for quick health check (AI may want to report cert errors)
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.head(target, timeout=5, allow_redirects=True, verify=False)
        if response.status_code < 400:
            return f"✅ REACHABLE: {target} (Status: {response.status_code})"
        else:
            return f"⚠️ UNREACHABLE: {target} (Status: {response.status_code})"
    except requests.exceptions.SSLError as e:
        return f"❌ SSL ERROR: The domain {target} is reachable but has invalid or expired certificates."
    except requests.exceptions.ConnectionError:
        return f"❌ CONNECTION ERROR: Could not resolve or connect to {target}."
    except Exception as e:
        return f"❌ ERROR: {target} check failed: {str(e)}"


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
    {
        "name": "check_domain_reachability",
        "description": (
            "Verify if a specific domain or URL (e.g., 'yourcompany.service-now.com') is "
            "reachable over the network. Use this when a user is troubleshooting "
            "connection errors or providing integration settings that you want to validate."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "domain_or_url": {
                    "type": "string",
                    "description": "The domain name or full URL to check (e.g., 'google.com').",
                },
            },
            "required": ["domain_or_url"],
        },
    },
    {
        "name": "graph_compare_versions",
        "description": (
            "Advanced GraphRAG tool: Compare relationships and features between two product versions. "
            "Use this for multi-hop relationship queries like comparing feature differences between versions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "version_a": {
                    "type": "string",
                    "description": "The first version name (e.g., 'v14').",
                },
                "version_b": {
                    "type": "string",
                    "description": "The second version name (e.g., 'v15').",
                },
            },
            "required": ["version_a", "version_b"],
        },
    },
    {
        "name": "synthesize_data_processor",
        "description": (
            "Generate and execute a custom Python script to process retrieved knowledge fragments. "
            "Use this for complex data extraction, multi-article comparison, or mathematical aggregation "
            "that standard search tools cannot handle. You MUST define an 'execute(data)' function."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "logic_code": {
                    "type": "string",
                    "description": "The Python code for the processor. Must define 'execute(data)'.",
                },
                "context_data": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "The data fragments (articles/graph nodes) to process.",
                },
            },
            "required": ["logic_code", "context_data"],
        },
    },
]
def graph_compare_versions(version_a: str, version_b: str) -> str:
    """
    Advanced GraphRAG tool: Compare relationships and features between two product versions.
    Uses the NodeRAG knowledge graph to identify added, removed, or changed integrations.
    """
    from app.graph_store import GraphStore
    cfg = Config()
    graph_db_path = cfg.STORAGE_DIR / "graph_store.json"
    store = GraphStore(storage_path=str(graph_db_path))
    
    try:
        store.load()
        rels_a = store.get_relationships_for_entity(version_a)
        rels_b = store.get_relationships_for_entity(version_b)
        
        # Simple set-based comparison of targets (features/integrations)
        targets_a = {r["target"] for r in rels_a}
        targets_b = {r["target"] for r in rels_b}
        
        diff = {
            "version_a": version_a,
            "version_b": version_b,
            "only_in_a": list(targets_a - targets_b),
            "only_in_b": list(targets_b - targets_a),
            "common": list(targets_a & targets_b),
            "summary": f"Comparison between {version_a} and {version_b} complete. Found {len(targets_b - targets_a)} new features in {version_b}."
        }
        return json.dumps(diff, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Graph comparison failed: {str(e)}"})
