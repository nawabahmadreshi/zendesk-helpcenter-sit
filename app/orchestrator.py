"""Master Orchestrator Agent (Agent 0).

Routes every incoming query to the correct sub-agent:
  - Agent 1: Contextual Help  (screen-specific, UI-aware)
  - Agent 2: Q&A Chat         (knowledge-base question answering)
  - Meta:    Orchestrator itself answers simple routing/capability questions

The orchestrator uses a tiny classification prompt (~60-80 tokens) to decide
which agent to invoke, then delegates and returns the result transparently.
The caller receives the same dict as if it called the agent directly, plus an
extra `_routed_to` key indicating which agent handled it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Classification prompt ───────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are a query router. Classify the user's message into ONE of:
- "contextual": asking about the current screen, UI elements, what a button does, what they're looking at
- "qa": a factual question about the product, a feature, how something works, troubleshooting
- "meta": asking what you can help with, greeting, or off-topic

Reply with ONLY one word: contextual, qa, or meta."""

_META_RESPONSE = (
    "I'm the Aquera AI assistant. I can help you with:\n\n"
    "- **Contextual Help** (Agent 1): Understanding any screen in the Aquera portal — "
    "just open the help panel and I'll explain what's on your screen.\n"
    "- **Q&A** (Agent 2): Answering questions about integrations, provisioning, "
    "configurations, and troubleshooting from the knowledge base.\n\n"
    "What would you like help with?"
)


# ── Public interface ────────────────────────────────────────────────────────

def orchestrate(
    question: str,
    page_context: Optional[Dict[str, Any]] = None,
    chat_history: Optional[List[Dict[str, str]]] = None,
    ai_provider: str = "gemini",
    api_key: str = "",
    persist_dir: str = "storage/vectordb",
    articles_dir: Optional[Path] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Classify the query and route to the appropriate agent.

    Args:
        question: The user's message / question.
        page_context: Current page context dict (if provided, biases toward contextual).
        chat_history: Previous messages in this conversation.
        ai_provider: Active AI provider name (passed through to sub-agents).
        api_key: Gemini API key (passed through).
        persist_dir: ChromaDB persist directory.
        articles_dir: Path to processed articles directory.
        **extra: Any additional provider kwargs (openrouter_api_key, etc.).

    Returns:
        Agent result dict with extra key ``_routed_to`` ('agent1'|'agent2'|'meta').
    """
    if articles_dir is None:
        from config import Config
        cfg = Config()
        articles_dir = cfg.processed_dir / "articles"

    # SOTA: Priority 3 - User Context MCP Discovery
    user_context = {}
    try:
        from mcp_servers.user_context_server import get_user_context
        user_id = extra.get("user_id", "default_user")
        user_context = get_user_context(user_id)
        print(f"[DEBUG] SOTA Orchestrator retrieved context for {user_id}: {user_context.get('role')}")
        # Merge with page_context
        if page_context is not None:
             page_context["mastery_context"] = user_context
    except Exception as e:
        print(f"[ERROR] User Context MCP failed: {e}")

    # Classify intent
    intent = _classify(question, page_context, ai_provider, api_key, **extra)

    if intent == "contextual" and page_context:
        from app.agent import contextual_help_agent
        result = contextual_help_agent(
            page_context=page_context,
            chat_history=chat_history or [],
            ai_provider=ai_provider,
            api_key=api_key,
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            **extra,
        )
        result["_routed_to"] = "agent1"
        return result

    elif intent == "meta":
        return {
            "response": _META_RESPONSE,
            "_routed_to": "meta",
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_total": 0,
        }

    else:
        # Default: Agent 2 Q&A
        from app.agent import qa_agent
        result = qa_agent(
            question=question,
            page_context=page_context or {},
            chat_history=chat_history or [],
            ai_provider=ai_provider,
            api_key=api_key,
            persist_dir=persist_dir,
            articles_dir=articles_dir,
            **extra,
        )
        result["_routed_to"] = "agent2"
        return result


# ── Private helpers ─────────────────────────────────────────────────────────

def _classify(
    question: str,
    page_context: Optional[Dict[str, Any]],
    ai_provider: str,
    api_key: str,
    **extra: Any,
) -> str:
    """Return 'contextual', 'qa', or 'meta' for the given question."""

    # Fast heuristics first (no LLM cost)
    q_lower = question.lower().strip()

    meta_triggers = {"hello", "hi", "hey", "what can you do", "help me", "what are you", "who are you"}
    if q_lower in meta_triggers or q_lower.startswith("what can"):
        return "meta"

    # If no page context at all, it can't be contextual
    if not page_context:
        return "qa"

    # Screen/UI keywords → contextual
    contextual_keywords = [
        "this page", "this screen", "this button", "this tab", "what is this",
        "what does this", "explain this", "i see", "current page", "what am i looking at",
        "what should i do", "what does it do", "this form", "this field",
    ]
    if any(kw in q_lower for kw in contextual_keywords):
        return "contextual"

    # Try a lightweight LLM classification
    try:
        classify_msg = f"User message: {question[:300]}"
        if page_context:
            classify_msg += f"\n\nCurrent page: {page_context.get('page_title', '')}"

        result = _run_classify_llm(classify_msg, ai_provider, api_key, **extra)
        cleaned = result.strip().lower().split()[0] if result.strip() else "qa"
        if cleaned in ("contextual", "qa", "meta"):
            return cleaned
    except Exception as e:
        print(f"[Orchestrator] Classification failed, defaulting to 'qa': {e}")

    return "qa"


def _run_classify_llm(
    user_message: str,
    ai_provider: str,
    api_key: str,
    **extra: Any,
) -> str:
    """Run a one-shot classification using the active AI provider."""

    # SOTA Phase 16 & 33: Try local AI first for intent routing (fastest & free)
    if ai_provider in ("auto", "local_only"):
        # 1. Internal llama-cpp-python
        try:
            from app.local_ai import is_ready, chat
            if is_ready():
                print("[DEBUG] Using Internal Local AI for intent classification...")
                res = chat(_CLASSIFY_SYSTEM, user_message, max_tokens=10, temperature=0)
                return res["response"].strip()
        except Exception as e:
            print(f"DEBUG: Internal Local AI classification failed: {e}")

        # 2. Local Ollama
        try:
            from config import Config
            cfg = Config()
            import requests
            print(f"[DEBUG] Trying Ollama for local intent classification at {cfg.OLLAMA_BASE_URL}...")
            payload = {
                "model": cfg.OLLAMA_MODEL,
                "prompt": f"{_CLASSIFY_SYSTEM}\n\n{user_message}",
                "stream": False,
                "options": {"temperature": 0, "num_predict": 10}
            }
            resp = requests.post(f"{cfg.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=5)
            if resp.ok:
                return resp.json().get("response", "").strip()
        except Exception as e:
             print(f"DEBUG: Ollama classification failed: {e}")

        # 3. LocalAI (OpenAI-compatible)
        try:
            from config import Config
            cfg = Config()
            from openai import OpenAI
            print(f"[DEBUG] Trying LocalAI for classification at {cfg.LOCAL_AI_BASE_URL}...")
            client = OpenAI(base_url=cfg.LOCAL_AI_BASE_URL, api_key="local-ai")
            resp = client.chat.completions.create(
                model=cfg.LOCAL_AI_MODEL,
                messages=[
                    {"role": "system", "content": _CLASSIFY_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=10,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"DEBUG: LocalAI classification failed: {e}")

    if ai_provider in ("gemini",) and api_key:
        try:
            import google.genai as genai
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{_CLASSIFY_SYSTEM}\n\n{user_message}",
            )
            return resp.text.strip()
        except Exception:
            pass

    if ai_provider in ("openrouter", "auto") and extra.get("openrouter_api_key"):
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=extra["openrouter_api_key"],
                base_url="https://openrouter.ai/api/v1",
            )
            resp = client.chat.completions.create(
                model=extra.get("openrouter_model", "mistralai/mistral-7b-instruct:free"),
                messages=[
                    {"role": "system", "content": _CLASSIFY_SYSTEM},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=10,
                temperature=0,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            pass

    return "qa"  # safe default
