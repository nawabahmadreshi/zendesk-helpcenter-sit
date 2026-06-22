"""
FastMCP Server for the Aquera AI Help system.
Exposes core browser-grounded reasoning as standard MCP tools.
"""

import json
import time
from typing import Any, Dict, List, Optional
from pathlib import Path
from fastmcp import FastMCP

from config import Config
from app.agent import (
    contextual_help_agent, 
    proactive_analysis_agent, 
    classify_intent,
    IntentType
)
from app.user_model import UserModel

mcp = FastMCP("AqueraCopilot")
cfg = Config()
_user_model = UserModel(db_path=str(cfg.STORAGE_DIR / "user_model.db"))

@mcp.tool()
async def analyze_page(
    user_id: str,
    page_type: str,
    page_heading: str,
    page_url: str,
    fields: Optional[List[Dict[str, Any]]] = None,
    version: str = "v14",
    modal_title: Optional[str] = None,
    is_modal: bool = False
) -> Dict[str, Any]:
    """
    Proactively analyzes an Aquera page or modal on load.
    Returns a page summary, per-field hints, and logical quick actions.
    
    Args:
        user_id: Unique identifier for the current user.
        page_type: Type of page (e.g., 'setup', 'dashboard', 'logs').
        page_heading: The primary H1 or title visible on screen.
        page_url: The full URL path.
        fields: List of detected form fields (dict with label, id, etc.).
        version: Product version (default 'v14').
        modal_title: If a modal is open, its header text.
        is_modal: True if the context is a modal overlay.
    """
    page_name = modal_title or page_heading or page_type.replace('_', ' ').title()
    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)

    # Call the deep proactive agent
    agent_result = proactive_analysis_agent(
        page_context={
            "user_id": user_id,
            "page_type": page_type,
            "page_heading": page_heading,
            "page_url": page_url,
            "fields": fields or [],
            "version": version,
            "modal_title": modal_title,
            "is_modal": is_modal
        },
        ai_provider=cfg.AI_PROVIDER,
        api_key=cfg.GEMINI_API_KEY,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        fallback_mode=cfg.AI_FALLBACK_MODE
    )

    analysis_data = agent_result.get("analysis", {})
    raw = analysis_data.get("response", "{}")
    raw = raw.replace("```json", "").replace("```", "").strip()
    
    try:
        parsed = json.loads(raw)
    except:
        parsed = {
            "page_summary": f"Analyzing {page_name}...",
            "field_hints": {},
            "quick_actions": ["Read documentation"]
        }

    return {
        "page_title": page_name,
        "page_summary": parsed.get("page_summary", ""),
        "field_hints": parsed.get("field_hints", {}),
        "quick_actions": parsed.get("quick_actions", [])[:4],
        "crag_status": agent_result.get("crag_status", "NONE")
    }

@mcp.tool()
async def get_contextual_help(
    user_id: str,
    page_context_dict: Dict[str, Any],
    chat_history: Optional[List[Dict[str, str]]] = None,
    screenshot_b64: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generates a deep, browser-grounded response for a specific page state.
    Use this when the user is stuck or needs expert explanation of what they see.
    
    Args:
        user_id: Unique identifier for personalization.
        page_context_dict: Full dictionary of DOM/UI metadata (labels, buttons, etc.).
        chat_history: List of previous messages in this session.
        screenshot_b64: Optional Base64 JPEG for visual verification.
    """
    if getattr(cfg, 'GEMINI_API_KEY', None) is None:
        return {"error": "GEMINI_API_KEY not configured"}

    # Classify intent first (Vision-Grounded)
    predicted_intent = classify_intent(
        page_context=page_context_dict,
        api_key=cfg.GEMINI_API_KEY,
        screenshot_base64=screenshot_b64
    )

    articles_dir = cfg.processed_dir / "articles"
    persist_dir = str(cfg.vectordb_dir)
    
    # Mastery lookup
    component_id = page_context_dict.get("integration_id") or "general"
    mastery = _user_model.get_mastery(user_id, component_id)
    
    agent_result = contextual_help_agent(
        page_context=page_context_dict,
        chat_history=chat_history,
        ai_provider=cfg.AI_PROVIDER,
        api_key=cfg.GEMINI_API_KEY,
        fallback_mode=cfg.AI_FALLBACK_MODE,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        predicted_intent=predicted_intent,
        mastery_score=mastery,
        screenshot_base64=screenshot_b64,
        # OpenRouter params from config
        openrouter_api_key=cfg.OPENROUTER_API_KEY,
        openrouter_model=cfg.OPENROUTER_MODEL,
        openrouter_site_url=cfg.OPENROUTER_SITE_URL,
        openrouter_app_name=cfg.OPENROUTER_APP_NAME,
        claude_proxy_url=cfg.CLAUDE_PROXY_URL,
        ollama_model=cfg.OLLAMA_MODEL
    )

    return {
        "response": agent_result.get("response", "No response generated."),
        "article_title": agent_result.get("article_title"),
        "crag_status": agent_result.get("crag_status", "NONE"),
        "predicted_intent": predicted_intent,
        "predictive_hint": agent_result.get("predictive_hint")
    }

if __name__ == "__main__":
    mcp.run()
