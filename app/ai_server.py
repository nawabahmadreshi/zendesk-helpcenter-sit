"""Standalone FastAPI server for the Agentic AI Help system."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import Config

cfg = Config()

app = FastAPI(title="Aquera AI Help")

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


# ── Endpoints ──────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "aquera-ai-help"}


@app.post("/api/help/context", response_model=HelpResponse)
async def contextual_help(req: ContextRequest) -> HelpResponse:
    """Generate contextual help for the current page."""
    if getattr(cfg, 'GEMINI_API_KEY', None) is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    # DEBUG LOGGING
    ctx = req.page_context
    print(f"DEBUG: Context Request - Title: {ctx.page_title}")
    print(f"DEBUG: ID: {ctx.integration_id}")
    print(f"DEBUG: Headings: {ctx.headings}")
    print(f"DEBUG: Buttons: {ctx.buttons}")
    
    from app.agent import contextual_help_agent

    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)

    try:
        agent_result = contextual_help_agent(
            page_context=req.page_context.model_dump(),
            chat_history=req.chat_history,
            api_key=cfg.GEMINI_API_KEY,  # Switch to Gemini
            persist_dir=persist_dir,
            articles_dir=articles_dir,
        )
        
        if isinstance(agent_result, dict):
            resp_text = agent_result.get("response", "")
            print(f"DEBUG: AI Contextual Help Result - Length: {len(resp_text)}")
            if not resp_text:
                print("WARNING: AI agent returned empty response!")
                resp_text = "I analyzed the page but couldn't deduce a specific help objective based on the visible elements."

            return HelpResponse(
                response=resp_text,
                article_title=agent_result.get("article_title"),
                article_id=agent_result.get("article_id")
            )
        return HelpResponse(response=str(agent_result))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI agent error: {str(e)}")


@app.post("/api/help/ask", response_model=HelpResponse)
async def ask_question(req: AskRequest) -> HelpResponse:
    """Answer a user's question using the knowledge base."""
    if getattr(cfg, 'GEMINI_API_KEY', None) is None:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    from app.agent import qa_agent

    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)

    try:
        agent_result = qa_agent(
            question=req.question,
            page_context=req.page_context.model_dump(),
            chat_history=req.chat_history,
            api_key=cfg.GEMINI_API_KEY,  # Switch to Gemini
            persist_dir=persist_dir,
            articles_dir=articles_dir,
        )
        if isinstance(agent_result, dict):
            return HelpResponse(
                response=agent_result.get("response", ""),
                article_title=agent_result.get("article_title"),
                article_id=agent_result.get("article_id")
            )
        return HelpResponse(response=str(agent_result))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI agent error: {str(e)}")


# ── Serve widget static files ─────────────────────────────────────────

widget_dir = Path(__file__).resolve().parent.parent / "widget"
if widget_dir.exists():
    app.mount("/widget", StaticFiles(directory=str(widget_dir)), name="widget")
