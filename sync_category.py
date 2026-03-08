"""CLI entry point: fetch all articles in the target category and rebuild outputs."""

from __future__ import annotations

from config import Config
from rebuild_outputs import build_category_outputs


def main() -> None:
    cfg = Config()
    cfg.ensure_dirs()

    client = cfg.get_zendesk_client()
    articles = client.list_articles_in_category(cfg.ZENDESK_CATEGORY_ID)

    result = build_category_outputs(articles, cfg.processed_dir)
    print(result)


if __name__ == "__main__":
    main()
