import os
import time
import pathlib
import requests
from bs4 import BeautifulSoup

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / ".state" / "last_sync.txt"
SITE_DIR = ROOT / "site"
ARTICLES_DIR = SITE_DIR / "articles"

ZENDESK_SUBDOMAIN = os.environ["ZENDESK_SUBDOMAIN"]          # aquera
ZENDESK_EMAIL = os.environ["ZENDESK_EMAIL"]
ZENDESK_API_TOKEN = os.environ["ZENDESK_API_TOKEN"]

API_BASE = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/help_center"
HC_BASE  = f"https://{ZENDESK_SUBDOMAIN}.zendesk.com/hc"

session = requests.Session()
session.auth = (f"{ZENDESK_EMAIL}/token", ZENDESK_API_TOKEN)

def read_last_sync() -> int:
    if STATE_FILE.exists():
        return int(STATE_FILE.read_text().strip())
    # first run: last 7 days
    return int(time.time()) - 7 * 24 * 3600

def write_last_sync(ts: int):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(ts))

def zendesk_get(url: str, params=None):
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()

def list_changed_articles(start_time: int):
    # Incremental export: articles changed since start_time
    data = zendesk_get(f"{API_BASE}/incremental/articles.json", params={"start_time": start_time})
    return data.get("articles", []), data.get("end_time", int(time.time()))

def get_article(article_id: int):
    data = zendesk_get(f"{API_BASE}/articles/{article_id}.json")
    return data["article"]

def wash_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for tag in soup.find_all(["script", "style", "link"]):
        tag.decompose()

    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)
        tag.attrs.pop("class", None)
        tag.attrs.pop("id", None)

    return str(soup)

def rewrite_links_to_local(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        # absolute HC links -> local
        if href.startswith(HC_BASE) and "/articles/" in href:
            tail = href.split("/articles/")[-1]
            aid = tail.split("-")[0].split("?")[0].split("#")[0]
            if aid.isdigit():
                a["href"] = f"./{aid}.html"

        # relative HC links -> local
        if href.startswith("/hc/") and "/articles/" in href:
            tail = href.split("/articles/")[-1]
            aid = tail.split("-")[0].split("?")[0].split("#")[0]
            if aid.isdigit():
                a["href"] = f"./{aid}.html"

    return str(soup)

def template(title: str, body: str, back_href: str) -> str:
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 40px; line-height: 1.55; }}
    .container {{ max-width: 980px; }}
    .meta {{ color:#666; font-size: 14px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="meta">Synced from Zendesk Help Center</div>
    <h1>{title}</h1>
    <p><a href="{back_href}">← Back</a></p>
    {body}
  </div>
</body>
</html>"""

def main():
    last_sync = read_last_sync()
    changed, end_time = list_changed_articles(last_sync)

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    index_links = []

    for item in changed:
        a = get_article(item["id"])
        if not a.get("body"):
            continue

        aid = str(a["id"])
        title = a.get("title", aid)

        body = wash_html(a["body"])
        body = rewrite_links_to_local(body)

        (ARTICLES_DIR / f"{aid}.html").write_text(template(title, body, "../index.html"), encoding="utf-8")
        index_links.append((title, f"articles/{aid}.html"))

    # build/refresh index using current files (simple approach)
    # NOTE: for first run you may want a full export; you can switch to /articles.json initially.
    links_html = "<ul>\n" + "\n".join([f'<li><a href="{h}">{t}</a></li>' for t, h in sorted(index_links)]) + "\n</ul>"
    (SITE_DIR / "index.html").write_text(template("Articles", links_html, "./index.html").replace("← Back", ""), encoding="utf-8")

    write_last_sync(end_time)
    print(f"Updated {len(index_links)} articles.")

if __name__ == "__main__":
    main()
