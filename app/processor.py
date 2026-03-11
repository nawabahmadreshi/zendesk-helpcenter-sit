from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from openpyxl import Workbook


HEADING_TAGS = {f"h{i}" for i in range(1, 7)}
REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    ".article-votes",
    ".article-relatives",
    ".article-comments",
    ".article-subscribe",
    ".share",
    ".article-more-questions",
    ".breadcrumbs",
    ".article-sidebar",
    "nav",
    "footer",
]
UNWANTED_ATTRS = {
    "style",
    "data-test-id",
    "data-test-selector",
    "loading",
    "decoding",
    "srcset",
    "sizes",
    "fetchpriority",
}


@dataclass
class HeadingRow:
    article_id: int
    article_title: str
    article_slug: str
    article_url: str
    heading_level: int
    heading_tag: str
    heading_text: str
    heading_id: str
    absolute_path: str


@dataclass
class BrokenAnchor:
    article_id: int
    article_title: str
    source_href: str
    resolved_target: str
    reason: str



def slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^a-z0-9\-_]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"



def article_prefix(article: dict) -> str:
    return slugify(article.get("slug") or article.get("title") or str(article["id"]))



def extract_body_html(article: dict) -> str:
    return article.get("body") or article.get("html_body") or article.get("content") or ""



def clean_article_html(raw_html: str) -> BeautifulSoup:
    soup = BeautifulSoup(raw_html, "lxml")

    for selector in REMOVE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            if attr in UNWANTED_ATTRS or attr.startswith("data-"):
                del tag.attrs[attr]
        classes = [c for c in tag.get("class", []) if not c.startswith("zendesk")]
        if classes:
            tag["class"] = classes
        elif "class" in tag.attrs:
            del tag.attrs["class"]

    if soup.body:
        wrapper = BeautifulSoup("<div class='help-center-article'></div>", "lxml")
        container = wrapper.div
        for child in list(soup.body.children):
            if isinstance(child, Tag):
                container.append(child)
        return wrapper

    return soup



def assign_heading_ids(soup: BeautifulSoup, article: dict) -> Tuple[Dict[str, str], List[HeadingRow]]:
    prefix = article_prefix(article)
    seen: defaultdict[str, int] = defaultdict(int)
    old_to_new: Dict[str, str] = {}
    rows: List[HeadingRow] = []
    article_url = article.get("html_url") or ""

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        text = " ".join(heading.get_text(" ", strip=True).split())
        base = slugify(text)
        key = f"{prefix}-{base}"
        seen[key] += 1
        new_id = key if seen[key] == 1 else f"{key}-{seen[key]}"
        old_id = heading.get("id")
        if old_id:
            old_to_new[old_id] = new_id
        heading["id"] = new_id
        level = int(heading.name[1])
        rows.append(
            HeadingRow(
                article_id=int(article["id"]),
                article_title=article.get("title", ""),
                article_slug=article.get("slug", ""),
                article_url=article_url,
                heading_level=level,
                heading_tag=heading.name,
                heading_text=text,
                heading_id=new_id,
                absolute_path=f"{article_url}#{new_id}" if article_url else f"#{new_id}",
            )
        )
    return old_to_new, rows



def rewrite_links(soup: BeautifulSoup, old_to_new: Dict[str, str], article: dict) -> List[BrokenAnchor]:
    broken: List[BrokenAnchor] = []
    valid_ids = {tag.get("id") for tag in soup.find_all(True) if tag.get("id")}
    article_title = article.get("title", "")
    article_id = int(article["id"])

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue
        if href.startswith("#"):
            original = href[1:]
            replacement = old_to_new.get(original, original)
            anchor["href"] = f"#{replacement}"
            if replacement not in valid_ids:
                broken.append(
                    BrokenAnchor(article_id, article_title, href, anchor["href"], "Missing local heading target")
                )
        elif "#" in href and not href.lower().startswith(("mailto:", "tel:", "javascript:")):
            parsed = urlparse(href)
            fragment = parsed.fragment
            if fragment:
                replacement = old_to_new.get(fragment, fragment)
                rebuilt = parsed._replace(fragment=replacement).geturl()
                anchor["href"] = rebuilt
    return broken



def render_clean_article_html(article: dict, soup: BeautifulSoup) -> str:
    title = article.get("title", "")
    html = BeautifulSoup("<article></article>", "lxml")
    root = html.article
    root["data-article-id"] = str(article["id"])
    root["data-article-slug"] = article.get("slug", "")
    title_tag = html.new_tag("h1")
    title_tag.string = title
    title_tag["id"] = f"{article_prefix(article)}-title"
    root.append(title_tag)

    source = soup.body or soup.div or soup
    for child in list(source.children):
        if isinstance(child, Tag):
            root.append(child)

    return str(root)



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



def build_category_outputs(articles: Iterable[dict], output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    articles_dir = output_dir / "articles"
    articles_dir.mkdir(parents=True, exist_ok=True)

    all_rows: List[HeadingRow] = []
    all_broken: List[BrokenAnchor] = []
    combined_articles: List[str] = []
    skipped_count = 0

    for article in articles:
        labels = article.get("label_names", []) or article.get("labels", [])
        integration_id_label = next((l for l in labels if l.startswith("integration_id_")), None)
        
        # STRICT POLICY: Skip articles without an integration_id label
        if not integration_id_label:
            skipped_count += 1
            continue

        raw_html = extract_body_html(article)
        soup = clean_article_html(raw_html)
        old_to_new, rows = assign_heading_ids(soup, article)
        broken = rewrite_links(soup, old_to_new, article)
        
        cleaned_article_html = render_clean_article_html(article, soup)
        
        # PREDICTABLE NAMING: Name the file using the integration_id label
        filename = f"{integration_id_label}_{article['id']}.html"
            
        (articles_dir / filename).write_text(cleaned_article_html, encoding="utf-8")
        combined_articles.append(cleaned_article_html)
        all_rows.extend(rows)
        all_broken.extend(broken)

    combined_html = "\n\n".join(combined_articles)
    (output_dir / "guide.cleaned.html").write_text(combined_html, encoding="utf-8")
    write_json(output_dir / "headings.json", all_rows)
    write_excel(output_dir / "headings.xlsx", all_rows, all_broken)

    return {
        "articles_processed": len(combined_articles),
        "articles_skipped": skipped_count,
        "heading_count": len(all_rows),
        "broken_anchor_count": len(all_broken),
        "output_dir": str(output_dir),
    }
