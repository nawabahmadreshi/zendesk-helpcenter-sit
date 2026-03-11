"""CLI entry point: fetch all articles in the target category and rebuild outputs."""

from __future__ import annotations

import json

from config import Config
from app.processor import build_category_outputs


def main() -> None:
    cfg = Config()
    cfg.ensure_dirs()

    client = cfg.get_zendesk_client()
    print("Fetching all articles for processing...")
    articles = client.list_articles()

    sync_file = cfg.metadata_dir / ".last_sync.json"
    last_sync: dict[str, str] = {}
    if sync_file.exists():
        try:
            last_sync = json.loads(sync_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Build current state of the category
    current_state: dict[str, str] = {
        str(a["id"]): a.get("updated_at", "") for a in articles
    }

    # Determine if any article's updated_at timestamp changed
    has_changes = False
    for aid, updated_at in current_state.items():
        if last_sync.get(aid) != updated_at:
            has_changes = True
            break
            
    # Check for deletions (present in last_sync but not in current_state)
    if not has_changes and any(aid not in current_state for aid in last_sync):
        has_changes = True

    if not has_changes:
        print("No articles have changed since the last run. Skipping sync.")
        return

    print(f"Changes detected. Processing {len(articles)} articles...")
    result = build_category_outputs(articles, cfg.processed_dir)
    print(result)

    # Save the new state only if the build succeeds
    sync_file.write_text(json.dumps(current_state, indent=2), encoding="utf-8")

    # Embed articles into vector store for AI Help (if Gemini key is configured)
    if cfg.GEMINI_API_KEY:
        try:
            from app.embedding import embed_articles

            articles_dir = cfg.processed_dir / "articles"
            embed_result = embed_articles(
                articles_dir=articles_dir,
                persist_dir=str(cfg.vectordb_dir),
                api_key=cfg.GEMINI_API_KEY,
            )
            print(f"✨ AI embeddings updated: {embed_result}")
        except Exception as e:
            print(f"⚠️  Failed to update AI embeddings: {e}")
    else:
        print("ℹ️  Skipping AI embeddings (GEMINI_API_KEY not set)")

    # Send Slack Notification if configured
    if cfg.SLACK_WEBHOOK_URL:
        import requests
        try:
            message = (
                f"✅ *Zendesk Sync Completed*\n"
                f"• Processed {result.get('articles_processed', 0)} integration articles\n"
                f"• Indexed {result.get('heading_count', 0)} headings\n"
                f"• Found {result.get('broken_anchor_count', 0)} broken links"
            )
            resp = requests.post(
                cfg.SLACK_WEBHOOK_URL, 
                json={"text": message}, 
                headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
            print("Successfully sent Slack notification.")
        except Exception as e:
            print(f"Failed to send Slack notification: {e}")


if __name__ == "__main__":
    main()
