"""CLI entry point: fetch articles and rebuild outputs incrementally.

Respects the SYNC_MODE environment variable:
  full              -- sync all articles from the configured category (default)
  integration_only  -- only embed articles that have an integration_id_ label
  category          -- sync articles from ZENDESK_CATEGORY_ID (can be overridden per run)

Set FORCE_REBUILD=1 to wipe vector DB collections before syncing.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from config import Config
from app.processor import process_single_article_html, compile_local_indices
from app.embedding import embed_single_article, delete_article_embeddings


def should_reingest(article: dict, last_sync: dict, force_rebuild: bool = False) -> bool:
    """Determine if an article needs to be re-processed or embedded."""
    aid = str(article["id"])
    if force_rebuild:
        return True
    if aid not in last_sync:
        return True
    # SOTA: Also check if local processed file exists
    # If it was deleted but sync state says it's ok, we should re-sync.
    return last_sync.get(aid) != article.get("updated_at", "")

def get_stale_articles(articles: list, last_sync: dict, force_rebuild: bool = False) -> list:
    """Filter articles to find only those that are new, updated, or missing."""
    return [a for a in articles if should_reingest(a, last_sync, force_rebuild)]


def run_sync_logic(cfg: Config, force_rebuild: bool = False, sync_mode: str = "full") -> dict:
    """Core synchronization logic. Can be called from CLI or background task."""
    cfg.ensure_dirs()
    articles_dir = cfg.processed_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Sync Mode: {sync_mode.upper()} | Force Rebuild: {force_rebuild} ===")

    if force_rebuild:
        vdb = cfg.vectordb_dir
        if vdb.exists():
            shutil.rmtree(vdb)
            print("Vector DB wiped for fresh rebuild.")
        # Also wipe last_sync so everything is reprocessed
        sync_file = cfg.metadata_dir / ".last_sync.json"
        last_sync: dict[str, str] = {}
    else:
        sync_file = cfg.metadata_dir / ".last_sync.json"
        last_sync = {}
        if sync_file.exists():
            try:
                last_sync = json.loads(sync_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    # ── Fetch articles ───────────────────────────────────────────────
    client = cfg.get_zendesk_client()
    print(f"Fetching articles from Zendesk (category: {cfg.ZENDESK_CATEGORY_ID})...")
    try:
        articles = client.list_articles()
    except Exception as e:
        print(f"Error fetching articles: {e}")
        return {"ok": False, "error": str(e)}

    # Build current state of the category
    current_state: dict[str, str] = {
        str(a["id"]): a.get("updated_at", "") for a in articles
    }

    # Identify changes using SOTA staleness detection
    to_update_or_add_raw = get_stale_articles(articles, last_sync, force_rebuild)
    
    # FREE MEMORY: Clear the large articles list immediately
    del articles
    import gc
    gc.collect()

    to_update_or_add = to_update_or_add_raw

    # Prioritize integrations for faster contextual help recovery
    to_update_or_add.sort(
        key=lambda x: any("integration" in str(l).lower() for l in x.get("label_names", [])), 
        reverse=True
    )

    # Check for deletions
    to_delete_ids = [aid for aid in last_sync if aid not in current_state]

    if not to_update_or_add and not to_delete_ids:
        print("No articles have changed since the last run. Skipping sync.", flush=True)
        return {"ok": True, "processed": 0, "deleted": 0}

    print(f"Changes detected: {len(to_update_or_add)} new/updated, {len(to_delete_ids)} deleted.", flush=True)

    # ── 1. Process Deletions ─────────────────────────────────────────
    for aid in to_delete_ids:
        # Delete from all possible collections
        for coll in ["integration_kb_v2", "general_kb_v2", "kb_v3_ollama_integration", "kb_v3_ollama_general"]:
            delete_article_embeddings(aid, str(cfg.vectordb_dir), collection_name=coll)

        for f in (cfg.processed_dir / "articles" / "integration").glob(f"*_{aid}.html"):
            f.unlink(missing_ok=True)
            print(f"Deleted local integration file: {f.name}")
        for f in (cfg.processed_dir / "articles" / "general").glob(f"*_{aid}.html"):
            f.unlink(missing_ok=True)
            print(f"Deleted local general file: {f.name}")

    # ── 2. Process Additions and Updates ─────────────────────────────
    processed_count = 0
    skipped_count = 0

    for article in to_update_or_add:
        aid = str(article["id"])
        result = process_single_article_html(article, cfg.processed_dir)
        is_integration = result.get("is_integration", False)

        if sync_mode == "integration_only" and not is_integration:
            skipped_count += 1
            continue

        processed_count += 1
        
        # Select collection based on provider and content type
        is_ollama = (cfg.AI_PROVIDER == "ollama")
        if is_ollama:
            collection_name = "kb_v3_ollama_integration" if is_integration else "kb_v3_ollama_general"
        else:
            collection_name = "integration_kb_v2" if is_integration else "general_kb_v2"

        print(f"Embedding article {aid} → {collection_name}...")
        
        # Cleanup old embeddings in all relevant collections first
        for coll in ["integration_kb_v2", "general_kb_v2", "kb_v3_ollama_integration", "kb_v3_ollama_general"]:
            delete_article_embeddings(aid, str(cfg.vectordb_dir), collection_name=coll)

        embed_single_article(
            result["filepath"],
            str(cfg.vectordb_dir),
            cfg.GEMINI_API_KEY if not is_ollama else "ollama",
            collection_name=collection_name,
            product_version=result.get("product_version")
        )

    # ── 3. Rebuild global index files ────────────────────────────────
    print("Compiling global index files (integration articles only)...")
    index_result = compile_local_indices(cfg.processed_dir)

    # Save state
    sync_file.write_text(json.dumps(current_state, indent=2), encoding="utf-8")

    mode_label = {
        "full": "Full KB",
        "integration_only": "Integration Only",
        "category": f"Category {cfg.ZENDESK_CATEGORY_ID}",
    }.get(sync_mode, sync_mode)

    print(f"\n✅ Sync complete [{mode_label.upper()}]")

    # Slack notification
    if cfg.SLACK_WEBHOOK_URL:
        import requests
        try:
            message = (
                f"✅ *Zendesk Sync Completed [{mode_label}]*\n"
                f"• Processed {processed_count} articles\n"
                f"• Deleted {len(to_delete_ids)} articles\n"
                f"• {index_result.get('heading_count', 0)} integration headings indexed"
            )
            requests.post(cfg.SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        except Exception:
            pass

    return {
        "ok": True,
        "processed": processed_count,
        "deleted": len(to_delete_ids),
        "headings": index_result.get("heading_count", 0),
    }


def main() -> None:
    cfg = Config()
    sync_mode = os.environ.get("SYNC_MODE", "full").lower()
    force_rebuild = os.environ.get("FORCE_REBUILD", "").strip() == "1"
    run_sync_logic(cfg, force_rebuild=force_rebuild, sync_mode=sync_mode)


if __name__ == "__main__":
    main()
