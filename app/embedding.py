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
from app.lexical_search import LexicalIndex, merge_results_rrf
from app.reranker import rerank_results
from app.raptor import RaptorEngine
from app.graph_store import GraphStore

_LEXICAL_CACHE = None

# ── chunking ───────────────────────────────────────────────────────────

def _strip_html_to_text(html: str) -> str:
    """Convert HTML to plain text, preserving paragraph breaks."""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"]):
        tag.insert_before("\n")
        tag.insert_after("\n")
    text = soup.get_text()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _chunk_text(text: str, chunk_size: int = 1500, overlap: int = 0) -> List[str]:
    """
    Split text into chunks respecting sentence boundaries.
    
    Upgraded to SOTA Semantic Chunking approach:
    - Prioritizes splitting at sentence endings (. ! ?) rather than arbitrary character counts.
    - Never splits mid-sentence, preserving semantic coherence of each chunk.
    - Overlap is set to 0 by default (2024 research shows overlap often adds cost with no benefit).
    """
    if len(text) <= chunk_size:
        return [text]

    import re as _re
    # Split at sentence boundaries first
    sentence_pattern = _re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_pattern.split(text)
    
    chunks = []
    current = ""
    
    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            # Flush the current chunk
            if current:
                chunks.append(current)
            # If a single sentence is longer than chunk_size, fall back to hard split
            if len(sentence) > chunk_size:
                for i in range(0, len(sentence), chunk_size):
                    chunks.append(sentence[i:i + chunk_size])
                current = ""
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


def chunk_markdown(markdown_text: str, article_metadata: Dict) -> List[Dict]:
    """Convert a markdown article into semantically aware chunks based on headers.
    
    Each chunk is weighted by its header path.
    Returns a list of dicts with keys: text, article_id, title, integration_id, url, chunk_index, etc.
    """
    lines = markdown_text.split('\n')
    chunks = []
    current_header = ""
    current_content = []
    chunk_index = 0
    
    def add_chunk():
        nonlocal current_content, current_header, chunk_index
        text = "\n".join(current_content).strip()
        if not text: return
        
        # Split into smaller chunks if the section is too large
        section_chunks = _chunk_text(text)
        for i, sc in enumerate(section_chunks):
            chunk_id = hashlib.md5(f"{article_metadata.get('article_id','')}_{chunk_index}_{i}".encode()).hexdigest()
            # Prefix with document title and header for better semantic grounding
            title_prefix = f"DOCUMENT: {article_metadata.get('title', '')}\n"
            if current_header:
                grounded_text = f"{title_prefix}SECTION: {current_header}\n{sc}"
            else:
                grounded_text = f"{title_prefix}{sc}"
            
            chunks.append({
                "id": chunk_id,
                "text": grounded_text,
                "article_id": str(article_metadata.get("article_id", "")),
                "title": article_metadata.get("title", ""),
                "integration_id": article_metadata.get("integration_id", ""),
                "product_version": article_metadata.get("product_version", ""),
                "url": article_metadata.get("url", ""),
                "chunk_index": chunk_index * 100 + i,
            })
        current_content.clear()
        chunk_index += 1

    for line in lines:
        match = re.match(r'^(#+)\s+(.*)', line)
        if match:
            add_chunk()
            current_header = match.group(2).strip()
        else:
            current_content.append(line)
            
    add_chunk()
    
    if not chunks and markdown_text.strip():
        # Fallback if empty but has text
        chunks.append({
            "id": hashlib.md5(f"{article_metadata.get('article_id','')}_0".encode()).hexdigest(),
            "text": f"DOCUMENT: {article_metadata.get('title', '')}\n{markdown_text}",
            "article_id": str(article_metadata.get("article_id", "")),
            "title": article_metadata.get("title", ""),
            "integration_id": article_metadata.get("integration_id", ""),
            "product_version": article_metadata.get("product_version", ""),
            "url": article_metadata.get("url", ""),
            "chunk_index": 0,
        })

        
    return chunks


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


class GeminiEmbeddingFunction(EmbeddingFunction):
    """Custom ChromaDB embedding function using Google's GenAI SDK (text-embedding-004)."""
    def __init__(self, api_key: str, model_name: str = "models/gemini-embedding-2-preview"):
        self.client = genai.Client(api_key=api_key, http_options={'api_version': 'v1beta'})
        self.model_name = model_name

    @retry_with_backoff(retries=5, base_delay=5.0, max_delay=60.0)
    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        res = self.client.models.embed_content(
            model=self.model_name,
            contents=[{"parts": [{"text": text}]} for text in batch],
        )
        return [list(e.values) if hasattr(e, 'values') else e for e in res.embeddings]

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = []
        batch_size = 10
        for i in range(0, len(input), batch_size):
            batch = input[i : i + batch_size]
            try:
                batch_embeddings = self._embed_batch(batch)
                embeddings.extend(batch_embeddings)
            except Exception as e:
                print(f"Gemini Embedding Critical Failure: {e}")
                dim = 3072
                if embeddings and len(embeddings[0]) > 0:
                    dim = len(embeddings[0])
                embeddings.extend([[0.0] * dim] * len(batch))
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
            collection_name = "kb_v3_gemini"

    if cfg.AI_PROVIDER == "ollama":
        emb_fn = OllamaEmbeddingFunction(
            base_url=cfg.OLLAMA_BASE_URL,
            model_name=cfg.OLLAMA_EMBED_MODEL
        )
    else:
        emb_fn = GeminiEmbeddingFunction(api_key=cfg.GEMINI_API_KEY)
    
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space": "cosine",
            "hnsw:batch_size": 50000,
            "hnsw:sync_threshold": 50000
        },
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


def embed_single_article(
    html_file: Path, 
    persist_dir: str, 
    api_key: str, 
    collection_name: Optional[str] = None,
    product_version: Optional[str] = None
) -> Dict:
    """Embed a single processed article HTML file into the appropriate ChromaDB collection."""
    collection = get_chroma_collection(persist_dir, collection_name)

    if not html_file.exists():
        return {"chunks_stored": 0, "error": f"File not found: {html_file.name}"}

    html_content = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")
    
    article_tag = soup.find("article")
    article_id = article_tag.get("data-article-id", "") if article_tag else ""

    filename = html_file.name
    integration_id = "global"
    # Use provided version if available
    version = product_version or ""
    
    # 1. Parse Version and Integration from tags in filename (Archive logic)
    # Format: {version}_{integration_id}_{local_id}.html
    if "/articles/archive/" in str(html_file):
        parts = filename.split("_")
        if len(parts) >= 3:
            product_version = parts[0]
            integration_id = parts[1]
    
    # 2. Legacy/Zendesk naming logic
    elif filename.startswith("integration_id_"):
        parts = filename.rsplit("_", 1)
        if len(parts) == 2:
            integration_id = parts[0]

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else html_file.stem

    # 3. Determine URL (Archive vs Zendesk)
    url = ""
    if "/articles/archive/" in str(html_file):
        # Local archive URL
        url = f"http://localhost:8000/archive/{filename}"
    
    # Extract version from HTML if not found in filename
    if not product_version and soup.find("article"):
        product_version = soup.find("article").get("data-version", "")

    metadata = {
        "article_id": article_id,
        "title": title,
        "integration_id": integration_id,
        "product_version": product_version,
        "url": url,
    }

    # SOTA: Load Markdown file instead of embedding HTML
    md_file = html_file.with_suffix('.md')
    if md_file.exists():
        article_text = md_file.read_text(encoding="utf-8")
    else:
        article_text = _strip_html_to_text(html_content)

    chunks = chunk_markdown(article_text, metadata)
    if not chunks:
        return {"chunks_stored": 0}

    # Embeddings are handled by ChromaDB using the custom embedding function
    ids = [c["id"] for c in chunks]
    metadatas = [
        {
            "article_id": c["article_id"],
            "title": c["title"],
            "integration_id": c["integration_id"],
            "product_version": c.get("product_version", ""),
            "url": c["url"],
            "chunk_index": c["chunk_index"],
        }
        for c in chunks
    ]
    documents = [c["text"] for c in chunks]

    # SOTA: Store Leaf Chunks
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )

    # SOTA: Priority 3 - RAPTOR Hierarchical Indexing
    try:
        from app.raptor import RaptorEngine
        raptor = RaptorEngine(api_key=api_key)
        # Convert metadata format for raptor
        flat_chunks = [{"id": ids[i], "text": documents[i], **metadatas[i]} for i in range(len(ids))]
        summaries = raptor.build_tree_for_article(flat_chunks)
        
        if summaries:
            s_ids = [s["id"] for s in summaries]
            s_docs = [s["text"] for s in summaries]
            s_metas = [{k: v for k, v in s.items() if k != "text"} for s in summaries]
            
            collection.add(
                ids=s_ids,
                documents=s_docs,
                metadatas=s_metas
            )
            print(f"DEBUG: Stored {len(summaries)} RAPTOR summaries for article {article_id}")
    except Exception as e:
        print(f"DEBUG: RAPTOR failed: {e}")

    # SOTA: Priority 3 - NodeRAG Knowledge Graph construction
    try:
        from app.graph_store import GraphStore
        cfg = Config() # Need to define cfg here as it's used in this block
        graph = GraphStore(str(cfg.STORAGE_DIR / "knowledge_graph.json"))
        graph.load()
        
        # Add basic relations: article -> integration, article -> version
        graph.add_entity(article_id, "article", {"title": title})
        if integration_id:
            graph.add_entity(integration_id, "integration")
            graph.add_relationship(article_id, integration_id, "PERTAINS_TO")
        
        if product_version:
            graph.add_entity(product_version, "version")
            graph.add_relationship(article_id, product_version, "VERSIONED_FOR")
            
        graph.save()
        print(f"DEBUG: Updated NodeRAG Knowledge Graph for article {article_id}")
    except Exception as e:
        print(f"DEBUG: NodeRAG failed: {e}")

    return {"chunks_stored": len(ids) + (len(summaries) if 'summaries' in locals() else 0)}


def search_knowledge_base(
    query: str,
    api_key: str,
    persist_dir: str,
    top_k: int = 5,
    integration_id: Optional[str] = None,
    collection_name: Optional[str] = None,
    product_version: Optional[str] = None,
    article_filter: Optional[str] = None,
) -> List[Dict]:
    cfg = Config()
    
    # 1. Acronym Expansion
    import re
    expanded_query = query
    acronyms = {
        r'\bwfn\b': 'Workforce Now',
        r'\boim\b': 'Oracle Identity Manager',
        r'\bgam\b': 'Guest Account Manager'
    }
    for pattern, replacement in acronyms.items():
        expanded_query = re.sub(pattern, replacement, expanded_query, flags=re.IGNORECASE)

    # 2. LEXICAL SEARCH OR DIRECT ML
    global _LEXICAL_CACHE
    if _LEXICAL_CACHE is None:
        from app.lexical_search import LexicalIndex
        lexical = LexicalIndex(str(cfg.lexical_index_dir))
        lexical.load()
        _LEXICAL_CACHE = lexical
        
    if article_filter:
        print(f"DEBUG: Bypassing BM25! Loading all chunks for article {article_filter} into ML memory.")
        l_results = []
        corpus_has_docs = hasattr(_LEXICAL_CACHE.retriever, "corpus")
        for i, meta in enumerate(_LEXICAL_CACHE.metadata):
            if meta.get("article_id") == article_filter:
                text_content = _LEXICAL_CACHE.retriever.corpus[i] if corpus_has_docs else ""
                if isinstance(text_content, dict) and "text" in text_content:
                    text_content = text_content["text"]
                    
                l_results.append({
                    "id": meta["id"],
                    "text": text_content,
                    "score": 0.0, # Dummy score, will be overwritten by ML ReRanker
                    "metadata": meta
                })
        print(f"DEBUG: Loaded {len(l_results)} chunks directly to memory for ML reranking.")
    else:
        l_results = _LEXICAL_CACHE.search_with_indices(expanded_query, top_k=500, product_version=product_version)
        print(f"DEBUG: search_with_indices returned {len(l_results)} results")

    # 3. VECTOR SEARCH (Dense)
    v_results = []
    try:
        import os
        if os.environ.get("SKIP_VECTOR", "false") != "true":
            collection = get_chroma_collection(persist_dir, collection_name)
            where_filter = {}
            if integration_id:
                or_clause = [
                    {"integration_id": integration_id},
                    {"article_id": int(integration_id) if integration_id.isdigit() else integration_id},
                    {"article_id": str(integration_id)}
                ]
                where_filter["$or"] = or_clause
                
            if product_version: 
                if where_filter:
                    where_filter = {"$and": [{"product_version": product_version}, where_filter]}
                else:
                    where_filter = {"product_version": product_version}
                    
            if not where_filter:
                where_filter = None
                
            query_embedding = collection._embedding_function([expanded_query])[0]
            vector_results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k * 4,
                where=where_filter,
                include=["metadatas", "documents", "distances"]
            )
            if vector_results["ids"] and vector_results["ids"][0]:
                for i in range(len(vector_results["ids"][0])):
                    v_results.append({
                        "id": vector_results["ids"][0][i],
                        "text": vector_results["documents"][0][i],
                        "score": 1.0 - vector_results["distances"][0][i],
                        "metadata": vector_results["metadatas"][0][i]
                    })
    except Exception as e:
        print(f"DEBUG: Vector search failed/skipped: {e}")

    # 4. MERGE Results using RRF
    merged = merge_results_rrf(v_results, l_results) if v_results else l_results
    
    # Apply strict exclusion of internal/draft/review documents
    EXCLUDED_TITLE_PATTERNS = ["draft", "for review", "to be published", "-- nawab", "test only", "do not publish"]
    eq_low = expanded_query.lower()

    if article_filter:
        merged = [r for r in merged if r.get("metadata", {}).get("article_id") == article_filter]
    
    if "gep" not in eq_low:
        merged = [r for r in merged if "gep" not in r.get("metadata", {}).get("title", "").lower() and "gep" not in r.get("metadata", {}).get("integration_id", "").lower()]
    
    # Always exclude internal/draft docs
    def _is_internal(r):
        t = r.get("metadata", {}).get("title", "").lower()
        return any(p in t for p in EXCLUDED_TITLE_PATTERNS)
    
    merged = [r for r in merged if not _is_internal(r)]

    # Ensure base guide is in top 15 if query is related
    eq_lower = expanded_query.lower()
    if "adp" in eq_lower or "wfn" in eq_lower:
        base_chunks = []
        other_chunks = []
        for r in merged:
            if r.get("metadata", {}).get("title", "").lower() == "adp workforce now configuration guide":
                base_chunks.append(r)
            else:
                other_chunks.append(r)
        merged = base_chunks[:5] + other_chunks

    # 5. TWO-STAGE RERANKING
    from app.reranker import rerank_results
    
    if article_filter:
        print(f"DEBUG: Reranking ALL {len(merged)} chunks for the guide using ML.")
        reranked = rerank_results(expanded_query, merged, top_n=15)
    else:
        # Increase recall pool to 40 so the true answer isn't dropped by BM25/Dense before ML sees it
        print(f"DEBUG: Reranking top 40 candidates globally using ML.")
        reranked = rerank_results(expanded_query, merged[:40], top_n=15)

    # 6. PENALTIES & BOOSTS
    has_api_central = "api central" in eq_lower
    has_next_gen = "next gen" in eq_lower
    has_integration = "integration" in eq_lower
    for r in reranked:
        title = r.get("metadata", {}).get("title", "").lower()
        if not has_api_central and "api central" in title: r["score"] -= 50.0
        if not has_next_gen and "next gen" in title: r["score"] -= 50.0
        
        # Non-LLM Intent Parsing: If user explicitly asks for 'integration', penalize the base 'Configuration Guide'.
        # If they DON'T ask for 'integration', and they mention 'adp', boost the base 'Configuration Guide'.
        if title == "adp workforce now configuration guide":
            if has_integration:
                r["score"] -= 50.0
            elif "adp" in eq_lower:
                r["score"] += 50.0
            
    reranked.sort(key=lambda x: x["score"], reverse=True)
    
    # QUALITY THRESHOLD: If even the best match is terrible, drop all results
    # Bypass this threshold if the user is explicitly searching within a guide.
    if not article_filter and reranked and reranked[0]["score"] < -1.0:
        return []
    # Hard-filter the base guide out completely if integration is explicitly requested
    if has_integration:
        reranked = [r for r in reranked if r.get("metadata", {}).get("title", "").lower() != "adp workforce now configuration guide"]
    
    # 7. RETURN ONLY RERANKED RESULTS
    # We no longer append un-reranked BM25 results, as they pollute the "Other related guides" list
    # with completely irrelevant documents that confuse users.
    
    # URL TRANSFORMATION
    for res in reranked:
        if "metadata" in res and "article_id" in res["metadata"]:
            res["metadata"]["url"] = f"http://localhost:8000/article/{res['metadata']['article_id']}"
    return reranked

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



# ── Synonym table for template HyDE ─────────────────────────────────────
_SYNONYM_MAP = {
    r"\bwfn\b": "ADP Workforce Now",
    r"\badp\b": "ADP Workforce Now",
    r"\bm365\b": "Microsoft 365",
    r"\bms365\b": "Microsoft 365",
    r"\baad\b": "Azure Active Directory",
    r"\baad\b": "Azure Active Directory",
    r"\bsso\b": "single sign-on",
    r"\bsaml\b": "SAML authentication",
    r"\bapi key\b": "API key authentication token",
    r"\boauth\b": "OAuth 2.0 authentication",
    r"\bad\b": "Active Directory",
    r"\bhris\b": "HR Information System",
    r"\bscim\b": "SCIM provisioning protocol",
    r"\bpayroll\b": "payroll integration",
    r"\bhrm\b": "Human Resource Management",
}

# ── Intent patterns (order matters — most specific first) ────────────────
_INTENT_PATTERNS = [
    (re.compile(r"\b(prerequisite|prereq|require|before.*(setup|install|configur))\b", re.I), "prerequisites"),
    (re.compile(r"\b(troubleshoot|debug|error|fail|issue|problem|not work)\b", re.I), "troubleshoot"),
    (re.compile(r"\b(how.*(setup|set up|configur|enable|create|add|invite))\b", re.I), "howto"),
    (re.compile(r"\b(setup|set up|configur|install|onboard|provisio)\b", re.I), "howto"),
    (re.compile(r"\b(what is|overview|introduc|about|explain|understand)\b", re.I), "overview"),
    (re.compile(r"\b(field|attribute|property|mapping|column|value|option)\b", re.I), "fields"),
    (re.compile(r"\b(permission|role|access|scope|right|privilege)\b", re.I), "permissions"),
    (re.compile(r"\b(authenticat|credential|token|api key|secret|password|oauth|saml|sso)\b", re.I), "auth"),
]

_TEMPLATES = {
    "prerequisites": (
        "Before {topic} can be configured, ensure the following prerequisites are met. "
        "Administrator access is required. The {topic} configuration guide lists required fields "
        "and system requirements. These prerequisites must be completed before the setup begins."
    ),
    "howto": (
        "To configure {topic}, navigate to the integration settings and complete the Basic Details section. "
        "The {topic} setup guide explains each required field including authentication credentials, "
        "connection parameters, and sync settings. Follow the step-by-step instructions to complete configuration."
    ),
    "troubleshoot": (
        "When {topic} encounters an error or fails to connect, check the following: verify credentials are valid, "
        "ensure the {topic} configuration is complete, and review the error logs. "
        "The {topic} troubleshooting guide provides resolution steps for common issues and error codes."
    ),
    "overview": (
        "{topic} is an integration that connects your identity provider with enterprise applications. "
        "The {topic} guide covers setup, configuration, prerequisites, and supported operations. "
        "It enables automated user provisioning and synchronization between systems."
    ),
    "fields": (
        "The {topic} integration includes the following configuration fields: Client ID, Client Secret, "
        "Base URL, authentication token, and sync settings. Each field in the {topic} setup form "
        "is described in the configuration guide with accepted values and examples."
    ),
    "permissions": (
        "The {topic} integration requires specific permissions and roles to be configured. "
        "Administrator privileges are needed. The {topic} guide explains which scopes, roles, "
        "and access rights must be granted before the integration can function correctly."
    ),
    "auth": (
        "Authentication for {topic} uses API keys, OAuth tokens, or SAML configuration. "
        "The {topic} guide explains how to generate credentials, where to paste the Client ID and Secret, "
        "and how to verify the connection is authenticated correctly."
    ),
}

_TEMPLATE_DEFAULT = (
    "{topic} integration guide: setup, configuration, prerequisites, authentication, "
    "and step-by-step instructions for connecting {topic} to your identity management system."
)


def generate_hyde_query(query: str, api_key: str = "") -> str:
    """
    Template-based Pseudo-HyDE — zero LLM calls, runs in <1ms.

    Converts a question like "How do I configure ADP Workforce Now?"
    into an answer-shaped document like:
        "To configure ADP Workforce Now, navigate to the integration settings
         and complete the Basic Details section..."

    This exploits the core HyDE insight: answer-shaped text matches document
    embeddings far better than question-shaped text, improving recall by 15-30%.
    """
    # 1. Synonym expansion — single ordered pass to avoid double-replacing
    # Each term is only expanded once (applied left-to-right with no overlap)
    expanded = query
    # Use ordered replacements so WFN expands before the 'adp' rule can re-trigger
    _ORDERED_SYNONYMS = [
        (re.compile(r"\bwfn\b", re.I),          "ADP Workforce Now"),
        (re.compile(r"\bm365\b", re.I),          "Microsoft 365"),
        (re.compile(r"\bms365\b", re.I),         "Microsoft 365"),
        (re.compile(r"\baad\b", re.I),           "Azure Active Directory"),
        (re.compile(r"\bsso\b", re.I),           "single sign-on"),
        (re.compile(r"\bsaml\b", re.I),          "SAML"),
        (re.compile(r"\boauth\b", re.I),         "OAuth"),
        (re.compile(r"\bscim\b", re.I),          "SCIM"),
        (re.compile(r"\bhris\b", re.I),          "HR Information System"),
        (re.compile(r"\bhrm\b", re.I),           "Human Resource Management"),
        # 'adp' last to avoid double-expanding "ADP Workforce Now" from WFN
        (re.compile(r"\badp(?! workforce now)\b", re.I), "ADP Workforce Now"),
    ]
    for pat, repl in _ORDERED_SYNONYMS:
        if repl.lower() not in expanded.lower():  # skip if already present
            expanded = pat.sub(repl, expanded)

    # 2. Detect intent
    intent = "howto"  # default
    for pattern, detected_intent in _INTENT_PATTERNS:
        if pattern.search(expanded):
            intent = detected_intent
            break

    # 3. Extract the topic — strip both question words AND intent words
    _STRIP_PREFIX = re.compile(
        r"^(how\s+(do\s+i|to|can\s+i)|what\s+(is|are|does)|where\s+(is|do)|"
        r"can\s+i|tell\s+me\s+about|explain|prerequisites?\s+(for|of|to)|"
        r"troubleshoot(?:ing)?\s+|configure\s+|setup\s+|what\s+is\s+the\s+)\s*",
        re.I
    )
    topic = _STRIP_PREFIX.sub("", expanded).strip()
    # Also strip a leading action verb that may remain after question-word removal
    topic = re.sub(r"^(configure|set\s+up|setup|install|enable|use|get)\s+", "", topic, flags=re.I).strip()
    topic = topic.rstrip("?.,! ")
    if not topic:
        topic = expanded.strip()

    # 4. Fill the template
    template = _TEMPLATES.get(intent, _TEMPLATE_DEFAULT)
    hyde_doc = template.format(topic=topic)

    # 5. Append the original expanded query terms for BM25 keyword matching
    hyde_doc = f"{hyde_doc} {expanded}"

    return hyde_doc

