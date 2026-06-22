import os
import re
import time
import hashlib
import pathlib
import urllib.parse
import requests
import json
import shutil
from bs4 import BeautifulSoup
from openpyxl import Workbook
from dotenv import load_dotenv

load_dotenv()



import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STATE_FILE = ROOT / ".state" / "last_sync.txt"
SITE_DIR = ROOT / "site"


ZENDESK_SUBDOMAIN = os.environ["ZENDESK_SUBDOMAIN"].strip().replace("https://", "").replace("http://", "").replace(".zendesk.com", "")
ZENDESK_EMAIL = os.environ["ZENDESK_EMAIL"]
ZENDESK_API_TOKEN = os.environ["ZENDESK_API_TOKEN"]
ZENDESK_CATEGORY_ID = os.environ.get("ZENDESK_CATEGORY_ID", "").strip()
SITE_BASE = os.environ.get("SITE_BASE", "").rstrip("/")  # e.g. https://<owner>.github.io/<repo>

API_BASE = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/help_center"
HC_HOST = f"https://support.aquera.com"  # your public help center host
# If your HC host is different sometimes, you can use: f"https://{ZENDESK_SUBDOMAIN}.zendesk.com"

session = requests.Session()
session.auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)



STATE_JSON_FILE = ROOT / ".state" / "sync_state.json"

def read_sync_state() -> dict:
    if STATE_JSON_FILE.exists():
        try:
            return json.loads(STATE_JSON_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def write_sync_state(state: dict):
    STATE_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_JSON_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def read_last_sync() -> int:
    if STATE_FILE.exists():
        try:
            return int(STATE_FILE.read_text().strip())
        except Exception:
            pass
    return int(time.time()) - 7 * 24 * 3600


def write_last_sync(ts: int):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(ts))



def zendesk_get(url: str, params=None):
    r = session.get(url, params=params, timeout=90)
    if r.status_code >= 400:
        # Print Zendesk's error message to GitHub Actions logs
        try:
            print("Zendesk API error:", r.status_code, url)
            print("Response:", r.text[:2000])
        except Exception:
            pass
    r.raise_for_status()
    return r.json()


def paginate(url: str, key: str):
    out = []
    while url:
        data = zendesk_get(url, params={"per_page": 100})
        out.extend(data.get(key, []))
        url = data.get("next_page")
    return out


def get_sections_in_category(category_id: str):
    # /categories/{id}/sections.json
    url = f"{API_BASE}/categories/{category_id}/sections.json"
    return paginate(url, "sections")



def get_articles_in_section(section_id: int):
    url = f"{API_BASE}/sections/{section_id}/articles.json"
    try:
        return paginate(url, "articles")
    except requests.exceptions.HTTPError as e:
        # Fall back to locale endpoint (common: en-us)
        # If your locale differs, update LOCALE below.
        LOCALE = os.environ.get("ZENDESK_LOCALE", "en-us")
        url2 = f"{API_BASE}/{LOCALE}/sections/{section_id}/articles.json"
        try:
            return paginate(url2, "articles")
        except Exception:
            # As last resort: skip section instead of failing whole run
            print(f"Skipping section {section_id} due to repeated errors.")
            return []


def get_article(article_id: int):
    data = zendesk_get(f"{API_BASE}/articles/{article_id}.json")
    return data["article"]


def slug_from_article_html_url(html_url: str, article_id: int) -> str:
    """
    https://support.aquera.com/hc/en-us/articles/3804...-Ellucian-Banner-Entra-ID-Integration-Guide
    -> Ellucian-Banner-Entra-ID-Integration-Guide
    """
    if not html_url:
        return str(article_id)

    try:
        tail = html_url.split("/articles/")[-1]
        # tail like: 38040012222359-Ellucian-Banner-Entra-ID-Integration-Guide
        parts = tail.split("-", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()
        return str(article_id)
    except Exception:
        return str(article_id)


def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return name or "file"


def slugify_heading(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^a-z0-9\-]+", "", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t or "section"


def strip_zendesk_styles(soup: BeautifulSoup):
    # Remove embedded scripts/styles/links
    for tag in soup.find_all(["script", "style", "link"]):
        tag.decompose()

    # Strip inline style + zendesk theme attrs
    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)
        # keep class sometimes can help tables, but requirement is "wash zendesk styles"
        tag.attrs.pop("class", None)
        # keep existing ids; we will add missing ones
        # do not pop "id"


def absolutize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        return HC_HOST.rstrip("/") + url
    # relative URL; treat as relative to HC host root
    return HC_HOST.rstrip("/") + "/" + url



FAILED_ASSETS = set()

def download_asset(asset_url: str, dest_dir: pathlib.Path) -> str | None:
    """
    Downloads asset_url to dest_dir with stable filename.
    Returns the filename (relative to dest_dir) or None on failure.
    """
    if asset_url in FAILED_ASSETS:
        return None
    try:
        abs_url = absolutize_url(asset_url)
        parsed = urllib.parse.urlparse(abs_url)
        ext = pathlib.Path(parsed.path).suffix
        if not ext or len(ext) > 6:
            ext = ".bin"

        h = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:16]
        fname = f"{h}{ext}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        out_path = dest_dir / fname

        if out_path.exists():
            return fname

        # Try unauth first
        try:
            r = requests.get(abs_url, timeout=2)
            if r.status_code != 200:
                # fallback: try with zendesk session auth (sometimes assets are protected)
                r = session.get(abs_url, timeout=2)
            if r.status_code != 200:
                FAILED_ASSETS.add(asset_url)
                return None
        except Exception:
            FAILED_ASSETS.add(asset_url)
            return None

        out_path.write_bytes(r.content)
        return fname
    except Exception:
        FAILED_ASSETS.add(asset_url)
        return None



def add_heading_ids_and_collect(soup: BeautifulSoup):
    """
    Adds missing ids to headings, collects all headings data for Excel.
    Keeps existing ids.
    Returns list of dicts: {level, text, id}
    """
    used = set()
    headings = []

    for h in soup.find_all(re.compile(r"^h[1-6]$")):
        level = h.name.upper()
        text = h.get_text(" ", strip=True)

        if not text:
            continue

        existing_id = h.get("id")
        if existing_id:
            hid = existing_id.strip()
        else:
            base = slugify_heading(text)
            hid = base
            i = 2
            while hid in used:
                hid = f"{base}-{i}"
                i += 1
            h["id"] = hid

        used.add(hid)
        headings.append({"level": level, "text": text, "id": hid})

    return headings


def rewrite_links_and_images(soup: BeautifulSoup, slug_by_article_id: dict[int, str], assets_dir: pathlib.Path):
    """
    - Convert Zendesk article links to local folder links
    - Download images and rewrite to local assets/
    """
    # Links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue

        abs_href = absolutize_url(href) if not href.startswith("#") else href
        if abs_href.startswith("#"):
            continue

        # Look for /articles/<id>-<slug> in href
        if "/articles/" in abs_href:
            try:
                tail = abs_href.split("/articles/")[-1]
                frag = ""
                if "#" in tail:
                    tail, frag = tail.split("#", 1)
                if "?" in tail:
                    tail = tail.split("?", 1)[0]
                article_id_str = tail.split("-", 1)[0]
                if article_id_str.isdigit():
                    aid = int(article_id_str)
                    target_slug = slug_by_article_id.get(aid)
                    if target_slug:
                        new_href = f"../{target_slug}/"
                        if frag:
                            new_href += f"#{frag}"
                        a["href"] = new_href
            except Exception:
                pass

    # Images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue

        fname = download_asset(src, assets_dir)
        if fname:
            img["src"] = f"./assets/{fname}"
            # Remove srcset to prevent browser choosing remote candidates
            if img.has_attr("srcset"):
                del img["srcset"]


def page_template(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 40px; line-height: 1.55; }}
    .container {{ max-width: 980px; }}
    .meta {{ color:#666; font-size: 14px; margin-bottom: 12px; }}
    img {{ max-width: 100%; height: auto; }}
    pre, code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }}
    table {{ border-collapse: collapse; width: 100%; overflow-x: auto; display: block; }}
    td, th {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="meta">Synced from Zendesk Help Center</div>
    {body_html}
  </div>
</body>
</html>"""


def write_headings_excel(headings: list[dict], out_xlsx: pathlib.Path, page_url: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Headings"
    ws.append(["Heading", "Level", "ID", "URL"])

    for h in headings:
        hid = h["id"]
        url = f"{page_url}#{hid}" if page_url else f"#{hid}"
        ws.append([h["text"], h["level"], hid, url])

    out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_xlsx)


def main():
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    # Load sync state
    state = read_sync_state()

    # 1) Get all articles in the entire Help Center
    print("Fetching all articles in the entire Zendesk Help Center...")
    articles = paginate(f"{API_BASE}/articles.json", "articles")
    print(f"Retrieved {len(articles)} articles.")

    # Remove duplicates (some APIs can overlap) and map slugs
    seen_ids = set()
    full_articles = []
    slug_by_article_id: dict[int, str] = {}
    for a in articles:
        if a["id"] not in seen_ids:
            seen_ids.add(a["id"])
            full_articles.append(a)
            slug_by_article_id[a["id"]] = slug_from_article_html_url(a.get("html_url", ""), a["id"])

    # Track currently active article IDs to detect deletions
    current_article_ids = set()

    # 2) Render each article into folder/<slug>/index.html, download assets, headings.xlsx
    index_items = []
    processed_count = 0
    skipped_count = 0

    for a in full_articles:
        if not a.get("body"):
            continue

        aid = str(a["id"])
        current_article_ids.add(aid)

        slug = slug_by_article_id[a["id"]]
        folder = SITE_DIR / slug
        assets_dir = folder / "assets"
        out_html = folder / "index.html"
        out_xlsx = folder / "headings.xlsx"
        out_md = folder / f"{slug}.md"

        title = a.get("title", slug)

        # Check if the article is already processed and unchanged
        is_stale = True
        if aid in state:
            if (out_html.exists() and out_md.exists() and out_xlsx.exists() and
                    state[aid].get("updated_at") == a.get("updated_at") and
                    state[aid].get("slug") == slug):
                is_stale = False

        if not is_stale:
            skipped_count += 1
            index_items.append((title, slug))
            continue

        print(f"Syncing new/updated article {a['id']} - {title}...")
        processed_count += 1

        soup = BeautifulSoup(a["body"], "html.parser")

        strip_zendesk_styles(soup)

        # Prepend guide title to headings
        for h in soup.find_all(re.compile(r"^h[1-6]$")):
            h_text = h.get_text(strip=True)
            if h_text and not h_text.lower().startswith(title.lower()):
                h.clear()
                h.append(f"{title} - {h_text}")

        # Add heading ids + collect headings
        headings = add_heading_ids_and_collect(soup)

        # Rewrite links + download images
        rewrite_links_and_images(soup, slug_by_article_id, assets_dir)

        # Wrap in a page with title + back link
        body_html = f"<h1>{title}</h1>\n<p><a href=\"../index.html\">← Back to index</a></p>\n{str(soup)}"
        out_html.parent.mkdir(parents=True, exist_ok=True)
        out_html.write_text(page_template(title, body_html), encoding="utf-8")

        # Write index.md
        from app.processor import simple_html_to_md
        md_content = simple_html_to_md(f"<h1>{title}</h1>\n{str(soup)}")
        out_md.write_text(md_content, encoding="utf-8")

        # Excel URLs (absolute if SITE_BASE available)
        page_url = f"{SITE_BASE}/{slug}/" if SITE_BASE else ""
        write_headings_excel(headings, out_xlsx, page_url)

        # Save to state
        state[aid] = {
            "updated_at": a.get("updated_at"),
            "title": title,
            "slug": slug
        }

        index_items.append((title, slug))

    # 3) Handle deleted articles
    deleted_count = 0
    for aid in list(state.keys()):
        if aid not in current_article_ids:
            old_slug = state[aid].get("slug")
            if old_slug:
                old_folder = SITE_DIR / old_slug
                if old_folder.exists():
                    shutil.rmtree(old_folder)
                    print(f"Deleted local folder for removed article: {old_slug}")
            del state[aid]
            deleted_count += 1

    # 4) Build site index
    index_items.sort(key=lambda x: x[0].lower())
    links = "<ul>\n" + "\n".join([f'<li><a href="./{slug}/">{title}</a></li>' for title, slug in index_items]) + "\n</ul>"
    index_html = page_template(
        "Integrations",
        f"<h1>Integrations</h1>\n<p>All Help Center Categories</p>\n{links}"
    )
    (SITE_DIR / "index.html").write_text(index_html, encoding="utf-8")

    # Save state
    write_sync_state(state)
    write_last_sync(int(time.time()))
    print(f"\n✅ Sync complete. Processed: {processed_count}, Skipped: {skipped_count}, Deleted: {deleted_count}")


if __name__ == "__main__":
    main()

