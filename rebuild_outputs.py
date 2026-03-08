"""Category-level aggregation: process all articles and write combined outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from openpyxl import Workbook

from process_article import (
    BrokenAnchor,
    HeadingRow,
    assign_heading_ids,
    clean_article_html,
    extract_body_html,
    render_clean_article_html,
    rewrite_links,
)


# ── output writers ─────────────────────────────────────────────────────

def write_json(path: Path, rows: List[HeadingRow]) -> None:
    payload = [row.__dict__ for row in rows]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_excel(path: Path, rows: List[HeadingRow], broken_links: List[BrokenAnchor]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "headings"
    ws.append([
        "article_id",
        "article_title",
        "article_slug",
        "article_url",
        "heading_level",
        "heading_tag",
        "heading_text",
        "heading_id",
        "absolute_path",
    ])
    for row in rows:
        ws.append([
            row.article_id,
            row.article_title,
            row.article_slug,
            row.article_url,
            row.heading_level,
            row.heading_tag,
            row.heading_text,
            row.heading_id,
            row.absolute_path,
        ])

    bad = wb.create_sheet("broken_anchors")
    bad.append(["article_id", "article_title", "source_href", "resolved_target", "reason"])
    for item in broken_links:
        bad.append([
            item.article_id,
            item.article_title,
            item.source_href,
            item.resolved_target,
            item.reason,
        ])
    wb.save(path)


# ── main orchestrator ──────────────────────────────────────────────────

def build_category_outputs(articles: Iterable[dict], output_dir: Path) -> dict:
    """Process every article in *articles* and write combined output files.

    Parameters
    ----------
    articles:
        Iterable of Zendesk article dicts.
    output_dir:
        Root directory for outputs (e.g. ``storage/processed``).

    Returns
    -------
    dict
        Summary with article count, heading count, and broken-anchor count.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    articles_dir = output_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[HeadingRow] = []
    all_broken: List[BrokenAnchor] = []
    articles_processed = 0

    for article in articles:
        labels = article.get("label_names", [])
        integration_id_label = next((l for l in labels if l.startswith("integration_id_")), None)
        
        # Skip articles that don't have the required label
        if not integration_id_label:
            continue

        raw_html = extract_body_html(article)
        soup = clean_article_html(raw_html)
        old_to_new, rows = assign_heading_ids(soup, article)
        broken = rewrite_links(soup, old_to_new, article)
        
        # This wrapper applies the <article> tag and keeps the sanitized HTML + injected IDs
        cleaned_article_html = render_clean_article_html(article, soup)
        
        filename = f"{integration_id_label}_{article['id']}.html"
            
        (articles_dir / filename).write_text(cleaned_article_html, encoding="utf-8")
        articles_processed += 1
        all_rows.extend(rows)
        all_broken.extend(broken)

    write_json(output_dir / "headings.json", all_rows)
    write_excel(output_dir / "headings.xlsx", all_rows, all_broken)

    return {
        "articles_processed": articles_processed,
        "heading_count": len(all_rows),
        "broken_anchor_count": len(all_broken),
        "output_dir": str(output_dir),
    }
