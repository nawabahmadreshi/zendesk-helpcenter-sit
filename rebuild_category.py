from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from app.processor import build_category_outputs
from app.zendesk_client import ZendeskClient


def main() -> None:
    category_id = int(os.environ["ZENDESK_CATEGORY_ID"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "output"))
    client = ZendeskClient(
        subdomain=os.environ["ZENDESK_SUBDOMAIN"],
        email=os.environ["ZENDESK_EMAIL"],
        api_token=os.environ["ZENDESK_API_TOKEN"],
        locale=os.environ.get("ZENDESK_LOCALE", "en-us"),
    )
    articles = client.list_articles_in_category(category_id)
    result = build_category_outputs(articles, output_dir)
    print(result)


if __name__ == "__main__":
    main()
