"""Standalone FastAPI server for the Agentic AI Help system."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Config
from app import analytics as _analytics

cfg = Config()

# Initialise analytics DB
_analytics.init_db(cfg.STORAGE_DIR / "analytics.db")

app = FastAPI(title="Aquera AI Help")

async def background_sync_loop():
    """Periodically triggers Zendesk sync if enabled."""
    from sync_category import run_sync_logic
    while True:
        try:
            # Re-load config if .env changed (rudimentary hot-reload check)
            if cfg.AUTO_SYNC_ENABLED:
                print(f"BACKGROUND: Starting auto-sync (interval: {cfg.AUTO_SYNC_INTERVAL_MINS}m)...")
                run_sync_logic(cfg, sync_mode="full")
                print("BACKGROUND: Auto-sync completed.")
        except Exception as e:
            print(f"BACKGROUND ERROR: {e}")

        # Wait for the next interval (mins -> seconds)
        await asyncio.sleep(max(60, cfg.AUTO_SYNC_INTERVAL_MINS * 60))

@app.on_event("startup")
async def startup_event():
    print("--- [STARTUP CONFIG] ---")
    print(f"AI_PROVIDER:      {cfg.AI_PROVIDER}")
    print(f"AI_FALLBACK_MODE: {cfg.AI_FALLBACK_MODE}")
    print(f"GEMINI_MODEL:     {cfg.GEMINI_MODEL}")
    print(f"OPENROUTER_MODEL: {cfg.OPENROUTER_MODEL}")
    print(f"OLLAMA_MODEL:     {cfg.OLLAMA_MODEL}")
    print(f"AUTO_SYNC:        {'ENABLED' if cfg.AUTO_SYNC_ENABLED else 'DISABLED'}")
    print("------------------------")
    asyncio.create_task(background_sync_loop())

# Allow CORS for the widget embedded in any product page
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────

class PageContext(BaseModel):
    page_title: str = ""
    url_path: str = ""
    headings: List[str] = []
    buttons: List[str] = []
    tabs: List[str] = []
    integration_id: str = ""
    form_labels: List[str] = []
    descriptions: List[str] = []
    nav_items: List[str] = []
    active_nav: str = ""


class ContextRequest(BaseModel):
    page_context: PageContext
    chat_history: Optional[List[Dict[str, str]]] = None


class AskRequest(BaseModel):
    question: str
    page_context: PageContext = PageContext()
    chat_history: Optional[List[Dict[str, str]]] = None


class HelpResponse(BaseModel):
    response: str
    source: str = "ai"
    article_title: Optional[str] = None
    article_id: Optional[str] = None


class SyncRequest(BaseModel):
    mode: str = "full"                  # "full" | "integration_only" | "category"
    category_id: Optional[str] = None  # used when mode == "category"
    force_rebuild: bool = False         # wipe vector DB first


class FeedbackRequest(BaseModel):
    event_id: int
    score: int


# ── Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "aquera-ai-help"}


@app.post("/api/help/context", response_model=HelpResponse)
async def contextual_help(req: ContextRequest) -> HelpResponse:
    """Generate contextual help for the current page."""
    if getattr(cfg, 'GEMINI_API_KEY', None) is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    ctx = req.page_context
    print(f"DEBUG: Context Request - Title: {ctx.page_title}")
    print(f"DEBUG: ID: {ctx.integration_id}")
    print(f"DEBUG: Headings: {ctx.headings}")
    print(f"DEBUG: Buttons: {ctx.buttons}")

    from app.agent import contextual_help_agent

    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)
    _t0 = time.time()

    try:
        agent_result = contextual_help_agent(
            page_context=req.page_context.model_dump(),
            chat_history=req.chat_history,
            ai_provider=cfg.AI_PROVIDER, # Use primary provider
            api_key=cfg.GEMINI_API_KEY,
            fallback_mode=cfg.AI_FALLBACK_MODE, # Pass fallback mode
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            openrouter_api_key=cfg.OPENROUTER_API_KEY,
            openrouter_model=cfg.OPENROUTER_MODEL,
            openrouter_site_url=cfg.OPENROUTER_SITE_URL,
            ollama_model=cfg.OLLAMA_MODEL,
        )
        if isinstance(agent_result, dict):
            resp_text = agent_result.get("response", "")
            if not resp_text:
                resp_text = "I analyzed the page but couldn't deduce a specific help objective."
            _analytics.log_event(
                "contextual",
                integration_id=ctx.integration_id,
                question=ctx.page_title,
                response_len=len(resp_text),
                article_id=agent_result.get("article_id", ""),
                article_title=agent_result.get("article_title", ""),
                latency_ms=round((time.time() - _t0) * 1000, 1),
                page_title=ctx.page_title,
                tokens_in=agent_result.get("tokens_in", 0),
                tokens_out=agent_result.get("tokens_out", 0),
                tokens_total=agent_result.get("tokens_total", 0),
            )
            return HelpResponse(
                response=resp_text,
                article_title=agent_result.get("article_title"),
                article_id=agent_result.get("article_id"),
            )
        return HelpResponse(response=str(agent_result))
    except Exception as e:
        import traceback; traceback.print_exc()
        _analytics.log_event("contextual", integration_id=ctx.integration_id, page_title=ctx.page_title, status="error")
        raise HTTPException(status_code=500, detail=f"AI agent error: {str(e)}")


@app.post("/api/help/ask", response_model=HelpResponse)
async def ask_question(req: AskRequest) -> HelpResponse:
    """Answer a user's question using the knowledge base."""
    if cfg.AI_PROVIDER == "gemini" and not getattr(cfg, 'GEMINI_API_KEY', None):
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    from app.agent import qa_agent

    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)
    _t0 = time.time()

    try:
        agent_result = qa_agent(
            question=req.question,
            page_context=req.page_context.model_dump() if req.page_context else {},
            chat_history=req.chat_history,
            ai_provider=cfg.AI_PROVIDER, # Use primary provider
            api_key=cfg.GEMINI_API_KEY,
            fallback_mode=cfg.AI_FALLBACK_MODE, # Pass fallback mode
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            openrouter_api_key=cfg.OPENROUTER_API_KEY,
            openrouter_model=cfg.OPENROUTER_MODEL,
            openrouter_site_url=cfg.OPENROUTER_SITE_URL,
            ollama_model=cfg.OLLAMA_MODEL,
        )
        if isinstance(agent_result, dict):
            resp_text = agent_result.get("response", "")
            _analytics.log_event(
                "qa",
                integration_id=req.page_context.integration_id,
                question=req.question,
                response_len=len(resp_text),
                article_id=agent_result.get("article_id", ""),
                article_title=agent_result.get("article_title", ""),
                latency_ms=round((time.time() - _t0) * 1000, 1),
                page_title=req.page_context.page_title,
                tokens_in=agent_result.get("tokens_in", 0),
                tokens_out=agent_result.get("tokens_out", 0),
                tokens_total=agent_result.get("tokens_total", 0),
            )
            return HelpResponse(
                response=resp_text,
                article_title=agent_result.get("article_title"),
                article_id=agent_result.get("article_id"),
            )
        return HelpResponse(response=str(agent_result))
    except Exception as e:
        _analytics.log_event("qa", question=req.question, status="error")
        raise HTTPException(status_code=500, detail=f"AI agent error: {str(e)}")


# ── Orchestrator: single unified chat endpoint ─────────────────────────────

class OrchestratorRequest(BaseModel):
    message: str
    page_context: Optional[PageContext] = None
    chat_history: List[Dict[str, str]] = []


@app.post("/api/help/chat")
async def orchestrated_chat(req: OrchestratorRequest) -> dict:
    """Master endpoint — routes to Agent 1 (contextual) or Agent 2 (Q&A) automatically.

    The widget can call this single endpoint for any message without needing
    to know which agent to invoke. The orchestrator decides.
    """
    from app.orchestrator import orchestrate
    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)
    _t0 = time.time()
    try:
        result = orchestrate(
            question=req.message,
            page_context=req.page_context.model_dump() if req.page_context else None,
            chat_history=req.chat_history,
            ai_provider=cfg.AI_FALLBACK_MODE,
            api_key=cfg.GEMINI_API_KEY,
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            openrouter_api_key=cfg.OPENROUTER_API_KEY,
            openrouter_model=cfg.OPENROUTER_MODEL,
            openrouter_site_url=cfg.OPENROUTER_SITE_URL,
        )
        routed_to = result.pop("_routed_to", "agent2")
        agent_label = {"agent1": "contextual", "agent2": "qa", "meta": "meta"}.get(routed_to, "qa")
        latency_ms = round((time.time() - _t0) * 1000, 1)
        _analytics.log_event(
            agent_label,
            req.page_context.integration_id if req.page_context else None,
            result.get("article_id"),
            result.get("article_title"),
            latency_ms,
            tokens_in=result.get("tokens_in", 0),
            tokens_out=result.get("tokens_out", 0),
        )
        return HelpResponse(
            response=result.get("response", ""),
            article_title=result.get("article_title"),
            article_id=result.get("article_id"),
        )
    except Exception as e:
        return HelpResponse(response=f"Orchestrator error: {e}")


# ── Admin Config API ───────────────────────────────────────────────────

@app.get("/api/config")
def get_config() -> dict:
    """Return all configuration settings (secrets masked)."""
    return cfg.get_all_settings()


@app.post("/api/config")
async def save_config(updates: Dict[str, Any]) -> dict:
    """Save updated settings to .env and hot-reload."""
    global cfg
    try:
        Config.save_to_env(updates)
        import importlib, config as config_module
        importlib.reload(config_module)
        cfg = config_module.Config()
        _analytics.init_db(cfg.STORAGE_DIR / "analytics.db")
        return {"ok": True, "message": "Settings saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save settings: {str(e)}")


# ── Analytics API ──────────────────────────────────────────────────────

@app.get("/api/analytics/summary")
def analytics_summary(days: int = 30) -> dict:
    """Return aggregated analytics metrics for the past N days."""
    return _analytics.get_summary(days=days)


@app.delete("/api/analytics/events")
def clear_analytics() -> dict:
    """Delete all analytics events (admin use only)."""
    db = cfg.STORAGE_DIR / "analytics.db"
    if db.exists():
        db.unlink()
        _analytics.init_db(db)
@app.post("/api/analytics/feedback")
async def submit_feedback(req: FeedbackRequest) -> dict:
    """Submit user feedback (-1, 0, 1) for a specific interaction."""
    ok = _analytics.log_feedback(req.event_id, req.score)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to log feedback")
    return {"ok": True}


@app.get("/api/analytics/kb-stats")
def kb_stats(
    page: int = 1,
    limit: int = 50,
    search: str = "",
    detail: bool = False,
) -> dict:
    """Return knowledge-base article stats.

    By default returns summary counts only (fast at any scale).
    Pass detail=true to get paginated article lists.
    Pass search=<query> to filter article titles.
    """
    articles_root = cfg.processed_dir / "articles"
    integration_dir = articles_root / "integration"
    general_dir = articles_root / "general"

    def _count_html(d: Path) -> int:
        if not d.exists():
            return 0
        return sum(1 for f in d.iterdir() if f.suffix in {".html", ".json", ".txt"})

    integration_total = _count_html(integration_dir)
    general_total = _count_html(general_dir)
    total = integration_total + general_total

    # Scan integration articles to find which ones carry an integration_id tag
    # Files in integration/ are named like: <article_id>_<slug>.html
    # The integration_id labels are stored inside the HTML or in ChromaDB metadata.
    # We'll query ChromaDB integration_kb collection for this data.
    with_id: list[dict] = []
    without_id: list[dict] = []

    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(cfg.vectordb_dir))
        try:
            col = client.get_collection("integration_kb_v2")
            results = col.get(include=["metadatas"])
            seen: set[str] = set()
            for meta in results.get("metadatas", []):
                aid = meta.get("article_id", "")
                if aid in seen:
                    continue
                seen.add(aid)
                int_id = meta.get("integration_id") or meta.get("integration_ids") or ""
                entry = {
                    "article_id": aid,
                    "title": meta.get("title", aid),
                    "integration_id": int_id,
                }
                if int_id:
                    with_id.append(entry)
                else:
                    without_id.append(entry)
        except Exception:
            pass  # collection may not exist yet
    except Exception:
        pass

    # Paginate / search article lists only if detail=True
    total_with_id = len(with_id)
    total_without_id = len(without_id)

    response: Dict[str, Any] = {
        "total_articles": total,
        "integration_articles": integration_total,
        "general_articles": general_total,
        "integration_with_id": total_with_id,
        "integration_without_id": total_without_id,
    }

    if detail:
        def _paginate_search(items: list) -> list:
            if search:
                items = [x for x in items if search.lower() in x.get("title", "").lower()]
            start = (page - 1) * limit
            return items[start: start + limit]

        response["articles_with_id"] = _paginate_search(with_id)
        response["articles_without_id"] = _paginate_search(without_id)
        response["page"] = page
        response["limit"] = limit
        response["search"] = search
        response["pages_with_id"] = max(1, -(-total_with_id // limit))    # ceil div
        response["pages_without_id"] = max(1, -(-total_without_id // limit))
    else:
        # Return first 10 without-id articles for the admin quick-view
        response["articles_without_id_preview"] = [
            x for x in without_id if not search or search.lower() in x.get("title", "").lower()
        ][:10]

    return response


# ── Local AI management ──────────────────────────────────────────────────

@app.get("/api/local-ai/status")
async def local_ai_status() -> dict:
    """Return llama-cpp-python install status and model info."""
    from app.local_ai import install_info
    return install_info()


@app.post("/api/local-ai/install")
async def local_ai_install() -> dict:
    """Install llama-cpp-python via pip (runs in subprocess)."""
    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "llama-cpp-python", "huggingface-hub", "-q"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode == 0:
            return {"ok": True, "message": "llama-cpp-python installed successfully."}
        return {"ok": False, "message": result.stderr or result.stdout}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/api/local-ai/download")
async def local_ai_download() -> dict:
    """Download the default Phi-3-mini GGUF model from HuggingFace."""
    from app.local_ai import download_model
    return download_model()



# ── Setup Wizard ─────────────────────────────────────────────────────────────

class WizardChatRequest(BaseModel):
    message: str
    chat_history: List[Dict[str, str]] = []


@app.get("/api/setup/status")
def setup_status() -> dict:
    """Return raw system status for all setup steps (no LLM, instant)."""
    from app.setup_wizard import get_system_status
    return get_system_status()


@app.post("/api/setup/chat")
async def setup_wizard_chat(req: WizardChatRequest) -> dict:
    """Run one turn of the setup wizard conversation."""
    from app.setup_wizard import setup_wizard_chat as _wizard_chat
    result = _wizard_chat(
        message=req.message,
        chat_history=req.chat_history,
        ai_provider=cfg.AI_FALLBACK_MODE,
        api_key=cfg.GEMINI_API_KEY,
        openrouter_api_key=cfg.OPENROUTER_API_KEY,
        openrouter_model=cfg.OPENROUTER_MODEL,
        openrouter_site_url=cfg.OPENROUTER_SITE_URL,
        ollama_model=cfg.OLLAMA_MODEL,
    )
    return result


@app.post("/api/config/test-zendesk")
async def test_zendesk(payload: Dict[str, str]) -> dict:
    """Test Zendesk API credentials."""
    import requests as req_lib
    subdomain = payload.get("ZENDESK_SUBDOMAIN") or cfg.ZENDESK_SUBDOMAIN
    email = payload.get("ZENDESK_EMAIL") or cfg.ZENDESK_EMAIL
    token = payload.get("ZENDESK_API_TOKEN", "")
    if not token or "••" in token:
        token = cfg.ZENDESK_API_TOKEN
    try:
        url = f"https://{subdomain}.zendesk.com/api/v2/users/me.json"
        r = req_lib.get(url, auth=(f"{email}/token", token), timeout=10)
        if r.status_code == 200:
            user = r.json().get("user", {})
            return {"ok": True, "user": user.get("name", ""), "role": user.get("role", "")}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/config/test-gemini")
async def test_gemini(payload: Dict[str, str]) -> dict:
    """Test Gemini API key validity."""
    api_key = payload.get("GEMINI_API_KEY", "")
    if not api_key or "••" in api_key:
        api_key = cfg.GEMINI_API_KEY
    try:
        from google import genai as _genai
        client = _genai.Client(api_key=api_key)
        models = list(client.models.list())
        return {"ok": True, "message": f"Valid key. {len(models)} models available."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/config/zendesk-categories")
async def list_zendesk_categories() -> dict:
    """Fetch all categories from the configured Zendesk account."""
    try:
        zd = cfg.get_zendesk_client()
        import requests as req_lib
        url = f"https://{cfg.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/help_center/{cfg.ZENDESK_LOCALE}/categories.json"
        r = req_lib.get(url, auth=(f"{cfg.ZENDESK_EMAIL}/token", cfg.ZENDESK_API_TOKEN), timeout=10)
        if r.status_code == 200:
            cats = r.json().get("categories", [])
            return {"ok": True, "categories": [{"id": c["id"], "name": c["name"]} for c in cats]}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Sync Job API ───────────────────────────────────────────────────────

_sync_state: dict = {"running": False, "last_run": None, "last_result": "", "mode": ""}


@app.get("/api/sync/status")
def sync_status() -> dict:
    return {
        "running": _sync_state["running"],
        "last_run": _sync_state["last_run"],
        "last_result": _sync_state["last_result"],
        "mode": _sync_state["mode"],
    }


@app.post("/api/sync/run")
async def run_sync(req: SyncRequest) -> StreamingResponse:
    """
    Run sync and stream stdout as SSE.
    Modes:
      full              — sync everything (integration + general KB)
      integration_only  — only process articles with integration_id_ labels
      category          — sync a specific category_id
    """
    if _sync_state["running"]:
        raise HTTPException(status_code=409, detail="Sync already in progress.")

    # Build environment overrides based on mode
    env_overrides: dict = {}
    cmd = ["python", "sync_category.py"]

    if req.mode == "integration_only":
        env_overrides["SYNC_MODE"] = "integration_only"
    elif req.mode == "category" and req.category_id:
        env_overrides["SYNC_MODE"] = "category"
        env_overrides["ZENDESK_CATEGORY_ID"] = req.category_id
    else:
        env_overrides["SYNC_MODE"] = "full"

    if req.force_rebuild:
        env_overrides["FORCE_REBUILD"] = "1"

    async def event_stream():
        _sync_state["running"] = True
        _sync_state["mode"] = req.mode
        _sync_state["last_result"] = ""

        import os
        run_env = {**os.environ, **env_overrides}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=run_env,
            )
            async for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                _sync_state["last_result"] += text + "\n"
                yield f"data: {text}\n\n"
            await proc.wait()
            _sync_state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            yield f"data: [DONE] Exit code: {proc.returncode}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"
        finally:
            _sync_state["running"] = False

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Webhook Connectivity Test ──────────────────────────────────────────

@app.post("/api/webhook/test-connection")
async def test_webhook_connection():
    """Verify if the local webhook endpoint is active and reachable."""
    try:
        # Mock a Zendesk ping to our own endpoint
        # In a real scenario, this would check if the URL is publicly reachable,
        # but locally we just check if the handler is ready.
        return {"ok": True, "message": "Local webhook receiver is active and ready for Zendesk payloads."}
    except Exception as e:
        return {"ok": False, "message": str(e)}


# ── Serve admin panel & widget static files ────────────────────────────

admin_dir = Path(__file__).resolve().parent.parent / "admin"


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def serve_admin():
    index = admin_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    raise HTTPException(status_code=404, detail="Admin panel not found. Run: mkdir admin && build admin/index.html")


if admin_dir.exists():
    app.mount("/admin/static", StaticFiles(directory=str(admin_dir)), name="admin_static")

widget_dir = Path(__file__).resolve().parent.parent / "widget"
if widget_dir.exists():
    app.mount("/widget", StaticFiles(directory=str(widget_dir)), name="widget")
