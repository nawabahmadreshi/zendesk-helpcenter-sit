from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Request

from config import Config
from rebuild_outputs import build_category_outputs

cfg = Config()
cfg.ensure_dirs()

app = FastAPI(title="Zendesk Inline Help Sync")


def verify_signature(body: bytes, timestamp: str | None, signature: str | None) -> None:
    if not cfg.ZENDESK_WEBHOOK_SECRET:
        return
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Missing Zendesk signature headers")
    signed_payload = timestamp.encode("utf-8") + body
    digest = hmac.new(cfg.ZENDESK_WEBHOOK_SECRET.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Zendesk webhook signature")


def extract_article_id(payload: Dict[str, Any]) -> int:
    detail = payload.get("detail", {})
    event = payload.get("event", {})
    article_id = detail.get("id") or event.get("resource_id")
    if not article_id:
        raise HTTPException(status_code=400, detail="Unable to find article id in webhook payload")
    return int(article_id)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/zendesk/webhook")
async def zendesk_webhook(
    request: Request,
    x_zendesk_webhook_signature: str | None = Header(default=None),
    x_zendesk_webhook_signature_timestamp: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    verify_signature(body, x_zendesk_webhook_signature_timestamp, x_zendesk_webhook_signature)
    payload = await request.json()
    article_id = extract_article_id(payload)

    client = cfg.get_zendesk_client()
    if not client.article_belongs_to_category(article_id, cfg.ZENDESK_CATEGORY_ID):
        return {"ignored": True, "reason": "article not in target category", "article_id": article_id}

    articles = client.list_articles_in_category(cfg.ZENDESK_CATEGORY_ID)
    summary = build_category_outputs(articles, cfg.processed_dir)
    return {"ignored": False, "article_id": article_id, **summary}
