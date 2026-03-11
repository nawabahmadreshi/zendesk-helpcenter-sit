from __future__ import annotations

from typing import List, Optional

import requests


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, api_token: str, locale: str = "en-us"):
        self.base = f"https://{subdomain}.zendesk.com"
        self.locale = locale
        self.session = requests.Session()
        self.session.auth = (f"{email}/token", api_token)
        self.session.headers.update({"Content-Type": "application/json"})

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = self.session.get(f"{self.base}{path}", params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def get_article(self, article_id: int) -> dict:
        data = self._get(f"/api/v2/help_center/articles/{article_id}")
        return data["article"]

    def get_section(self, section_id: int) -> dict:
        data = self._get(f"/api/v2/help_center/sections/{section_id}")
        return data["section"]

    def list_articles(self) -> List[dict]:
        items: List[dict] = []
        url_path = "/api/v2/help_center/articles"
        params = {"per_page": 100}
        while True:
            data = self._get(url_path, params=params)
            items.extend(data.get("articles", []))
            next_page = data.get("next_page")
            if not next_page:
                break
            if next_page.startswith(self.base):
                url_path = next_page[len(self.base):]
            else:
                break
            params = None
        return items

    def list_articles_in_category(self, category_id: int) -> List[dict]:
        items: List[dict] = []
        url_path = f"/api/v2/help_center/categories/{category_id}/articles"
        params = {"per_page": 100}
        while True:
            data = self._get(url_path, params=params)
            items.extend(data.get("articles", []))
            next_page = data.get("next_page")
            if not next_page:
                break
            if next_page.startswith(self.base):
                url_path = next_page[len(self.base):]
            else:
                break
            params = None
        return items

    def article_belongs_to_category(self, article_id: int, target_category_id: int) -> bool:
        article = self.get_article(article_id)
        section = self.get_section(int(article["section_id"]))
        return int(section["category_id"]) == int(target_category_id)
