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

def simple_html_to_md(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    # Convert headings
    for h in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
        level = int(h.name[1])
        h.insert_before('\n\n' + '#' * level + ' ')
        h.insert_after('\n\n')
    # Convert paragraphs
    for p in soup.find_all('p'):
        p.insert_before('\n\n')
        p.insert_after('\n\n')
    # Convert links
    for a in soup.find_all('a'):
        href = a.get('href', '')
        text = a.get_text(strip=True)
        a.replace_with(f"[{text}]({href})")
    # Convert bold
    for b in soup.find_all(['b', 'strong']):
        b.insert_before('**')
        b.insert_after('**')
    # Clean up whitespace
    text = soup.get_text()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
    soup = BeautifulSoup(raw_html, "html.parser")

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
        wrapper = BeautifulSoup("<div class='help-center-article'></div>", "html.parser")
        container = wrapper.div
        for child in list(soup.body.children):
            if isinstance(child, Tag):
                container.append(child)
        return wrapper

    return soup



def prepend_title_to_headings(soup: BeautifulSoup, title: str) -> None:
    if not title:
        return
    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        h_text = h.get_text(strip=True)
        if h_text and not h_text.lower().startswith(title.lower()):
            h.clear()
            h.append(f"{title} - {h_text}")




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



def render_clean_article_html(
    article: dict, 
    soup: BeautifulSoup, 
    product_version: Optional[str] = None,
    field_id: Optional[str] = None,
    doc_type: Optional[str] = None
) -> str:
    title = article.get("title", "")
    html = BeautifulSoup("<article></article>", "html.parser")
    root = html.article
    root["data-article-id"] = str(article["id"])
    root["data-article-slug"] = article.get("slug", "")
    if product_version:
        root["data-version"] = product_version
    if field_id:
        root["data-field-id"] = field_id
    if doc_type:
        root["data-doc-type"] = doc_type
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



def process_single_article_html(article: dict, output_dir: Path) -> dict:
    """Processes a single article into HTML, routing to either integration/ or general/ folders."""
    labels = article.get("label_names", []) or article.get("labels", [])
    integration_id_label = next((l for l in labels if l.startswith("integration_id_")), None)
    
    # Extract version label (e.g., v11, v14.2)
    version_label = next((l for l in labels if re.match(r'^v\d+(\.\d+)*$', l, re.I)), None)
    
    # Extract advanced metadata (World-Class Roadmap)
    field_id = next((l.replace("field_id_", "") for l in labels if l.startswith("field_id_")), None)
    doc_type = next((l.replace("doc_type_", "") for l in labels if l.startswith("doc_type_")), None)

    is_integration = bool(integration_id_label)
    folder_name = "integration" if is_integration else "general"
    
    target_dir = output_dir / "articles" / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    # Use integration label if present, otherwise just prefix with 'general_kb_'
    file_prefix = integration_id_label if is_integration else "general_kb"

    raw_html = extract_body_html(article)
    soup = clean_article_html(raw_html)
    prepend_title_to_headings(soup, article.get("title", ""))
    old_to_new, rows = assign_heading_ids(soup, article)
    
    # FRESH SOUP: Re-parse to avoid corruption in complex DOMs
    soup = BeautifulSoup(str(soup), "html.parser")
    
    broken = rewrite_links(soup, old_to_new, article)

    cleaned_article_html = render_clean_article_html(article, soup, product_version=version_label)
    filename = f"{file_prefix}_{article['id']}.html"
    filepath = target_dir / filename
    filepath.write_text(cleaned_article_html, encoding="utf-8")

    md_filename = f"{file_prefix}_{article['id']}.md"
    md_filepath = target_dir / md_filename
    md_content = simple_html_to_md(cleaned_article_html)
    md_filepath.write_text(md_content, encoding="utf-8")

    return {
        "status": "processed", 
        "is_integration": is_integration,
        "html": cleaned_article_html, 
        "rows": rows if is_integration else [], # Don't index general KB rows
        "broken": broken if is_integration else [],
        "filepath": filepath,
        "md_filepath": md_filepath,
        "integration_id": integration_id_label or "global",
        "product_version": version_label
    }


def compile_local_indices(output_dir: Path) -> dict:
    """Rapidly rebuilds headings.json, excel, and global HTML guide from cached INTEGRATION HTML files.
    This safely protects the index from generic KB articles."""
    integration_dir = output_dir / "articles" / "integration"
    if not integration_dir.exists():
        return {"error": "Integration articles dir not found"}

    all_rows: List[HeadingRow] = []
    all_broken: List[BrokenAnchor] = []
    combined_articles: List[str] = []
    
    # We rebuild headings and anchors ONLY from the integration HTML files on disk
    for html_file in integration_dir.glob("*.html"):
        html_content = html_file.read_text(encoding="utf-8")
        combined_articles.append(html_content)
        
        soup = BeautifulSoup(html_content, "html.parser")
        article_elem = soup.find("article")
        if not article_elem:
            continue
            
        article_id = article_elem.get("data-article-id", "")
        article_slug = article_elem.get("data-article-slug", "")
        
        article_mock = {
            "id": article_id, 
            "slug": article_slug, 
            "title": soup.find("h1").get_text(strip=True) if soup.find("h1") else "",
            "html_url": ""  
        }
        
        heading_ids, rows = assign_heading_ids(soup, article_mock)
        broken = rewrite_links(soup, heading_ids, article_mock)
        
        all_rows.extend(rows)
        all_broken.extend(broken)

    combined_html = "\n\n".join(combined_articles)
    (output_dir / "guide.cleaned.html").write_text(combined_html, encoding="utf-8")
    write_json(output_dir / "headings.json", all_rows)
    write_excel(output_dir / "headings.xlsx", all_rows, all_broken)

    return {
        "integration_articles_processed": len(combined_articles),
        "heading_count": len(all_rows),
        "broken_anchor_count": len(all_broken),
    }


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
        prepend_title_to_headings(soup, article.get("title", ""))
        old_to_new, rows = assign_heading_ids(soup, article)
        broken = rewrite_links(soup, old_to_new, article)
        
        # Extract version label (e.g., v11, v14.2)
        version_label = next((l for l in labels if re.match(r'^v\d+(\.\d+)*$', l, re.I)), None)
        
        # Extract advanced metadata (World-Class Roadmap)
        field_id = next((l.replace("field_id_", "") for l in labels if l.startswith("field_id_")), None)
        doc_type = next((l.replace("doc_type_", "") for l in labels if l.startswith("doc_type_")), None)
        
        cleaned_article_html = render_clean_article_html(
            article, 
            soup, 
            product_version=version_label,
            field_id=field_id,
            doc_type=doc_type
        )
        
        # PREDICTABLE NAMING: Name the file using the integration_id label
        filename = f"{integration_id_label}_{article['id']}.html"
        md_filename = f"{integration_id_label}_{article['id']}.md"
            
        (articles_dir / filename).write_text(cleaned_article_html, encoding="utf-8")
        (articles_dir / md_filename).write_text(simple_html_to_md(cleaned_article_html), encoding="utf-8")
        
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
