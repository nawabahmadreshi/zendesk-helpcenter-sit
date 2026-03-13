"""Setup Wizard Agent (Agent 3).

A conversational agent that guides new users through complete system setup.
It maintains conversation state client-side (history sent with each request)
and uses internal tool calls to actually perform setup actions.

Steps:
  1. Zendesk Credentials  → test connection
  2. Knowledge Base Sync  → run full sync
  3. AI Provider          → test API key
  4. Widget Setup         → show embed snippet
  5. Health Check         → verify both agents respond
  6. 🎉 Live!

The wizard checks system_status() at the start of every response to know
exactly which steps are done, and picks up where the user left off.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── System prompt ────────────────────────────────────────────────────────────

WIZARD_SYSTEM_PROMPT = """You are the Aquera AI Setup Wizard. Your job is to guide the user through setting up the Aquera AI Help System step by step until it is fully live.

You have access to tools that let you CHECK the current configuration status and TRIGGER setup actions. Use them before responding so you always know the exact system state.

SETUP STEPS (in order):
1. **Zendesk Credentials** — configured subdomain, email, API token
2. **Knowledge Base Sync** — at least one sync has been run (articles exist)
3. **AI Provider** — a valid API key is configured (Gemini, OpenRouter, or local)
4. **Widget Setup** — user has the embed snippet ready
5. **Health Check** — both Agent 1 and Agent 2 respond correctly
6. **🎉 Live!** — all steps complete

BEHAVIOR:
- Always start by checking what's already done via check_setup_status tool.
- Acknowledge completed steps briefly, then focus on the next incomplete step.
- Give exact instructions for incomplete steps (copy-paste commands, links, form values).
- When the user completes a step, call the verify_* tool to confirm it actually worked.
- Be encouraging, concise, and action-oriented. No waffle.
- When all steps are done, celebrate and show the final embed snippet.

If the user asks off-topic questions, briefly answer then redirect to setup.
"""


# ── Tool definitions ─────────────────────────────────────────────────────────

WIZARD_TOOLS = [
    {
        "name": "check_setup_status",
        "description": "Check the current setup status for all 5 setup steps. Returns a dict with ok/fail for each step.",
        "parameters": {},
    },
    {
        "name": "verify_zendesk",
        "description": "Test the currently saved Zendesk credentials by making a real API call.",
        "parameters": {},
    },
    {
        "name": "verify_ai_provider",
        "description": "Test the currently configured AI provider (Gemini/OpenRouter/local) with a simple ping.",
        "parameters": {},
    },
    {
        "name": "trigger_sync",
        "description": "Trigger a full knowledge base sync from Zendesk. Returns job status.",
        "parameters": {
            "mode": {
                "type": "string",
                "description": "Sync mode: 'full' or 'integration'. Default: 'full'",
            }
        },
    },
    {
        "name": "get_embed_snippet",
        "description": "Get the JavaScript widget embed snippet for the user to copy into their app.",
        "parameters": {},
    },
    {
        "name": "test_agents",
        "description": "Run a quick health check on both Agent 1 and Agent 2 to verify they respond.",
        "parameters": {},
    },
]


# ── Tool implementations ─────────────────────────────────────────────────────

def _tool_check_setup_status() -> dict:
    """Return current status for all setup steps."""
    from config import Config
    cfg = Config()

    import requests

    status: Dict[str, Any] = {}

    # Step 1: Zendesk
    zd_ok = bool(cfg.ZENDESK_SUBDOMAIN and cfg.ZENDESK_EMAIL and cfg.ZENDESK_API_TOKEN)
    status["zendesk_configured"] = zd_ok

    # Step 2: Sync (check if any articles exist)
    articles_dir = cfg.processed_dir / "articles"
    integration_dir = articles_dir / "integration"
    general_dir = articles_dir / "general"
    article_count = 0
    for d in (integration_dir, general_dir):
        if d.exists():
            article_count += sum(1 for f in d.iterdir() if f.suffix in {".html", ".json", ".txt"})
    status["sync_done"] = article_count > 0
    status["article_count"] = article_count

    # Step 3: AI Provider
    gemini_ok = bool(cfg.GEMINI_API_KEY and not cfg.GEMINI_API_KEY.startswith("••"))
    openrouter_ok = bool(cfg.OPENROUTER_API_KEY and not cfg.OPENROUTER_API_KEY.startswith("••"))
    local_ok = False
    try:
        from app.local_ai import is_ready
        local_ok = is_ready()
    except Exception:
        pass
    status["ai_configured"] = gemini_ok or openrouter_ok or local_ok
    status["ai_provider"] = cfg.AI_FALLBACK_MODE

    # Step 4: Widget — always considered "ready" once AI is up (just show snippet)
    status["widget_ready"] = status["ai_configured"] and status["sync_done"]

    # Step 5: Health check — try calling /health
    try:
        r = requests.get("http://localhost:8000/health", timeout=3)
        status["server_healthy"] = r.status_code == 200
    except Exception:
        status["server_healthy"] = False

    status["all_done"] = all([
        status["zendesk_configured"],
        status["sync_done"],
        status["ai_configured"],
        status["server_healthy"],
    ])

    return status


def _tool_verify_zendesk() -> dict:
    from config import Config
    import requests as req_lib
    cfg = Config()
    try:
        url = f"https://{cfg.ZENDESK_SUBDOMAIN}.zendesk.com/api/v2/users/me.json"
        r = req_lib.get(url, auth=(f"{cfg.ZENDESK_EMAIL}/token", cfg.ZENDESK_API_TOKEN), timeout=10)
        if r.status_code == 200:
            user = r.json().get("user", {})
            return {"ok": True, "user": user.get("name"), "role": user.get("role")}
        return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _tool_verify_ai() -> dict:
    from config import Config
    cfg = Config()
    mode = cfg.AI_FALLBACK_MODE

    if mode in ("gemini",) and cfg.GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=cfg.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-2.0-flash")
            r = model.generate_content("Reply with OK only.", generation_config={"max_output_tokens": 5})
            return {"ok": True, "provider": "gemini", "response": r.text.strip()}
        except Exception as e:
            return {"ok": False, "provider": "gemini", "error": str(e)}

    if mode in ("openrouter", "auto") and cfg.OPENROUTER_API_KEY:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=cfg.OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
            r = client.chat.completions.create(
                model=cfg.OPENROUTER_MODEL,
                messages=[{"role": "user", "content": "Reply OK only."}],
                max_tokens=5,
            )
            return {"ok": True, "provider": "openrouter", "response": r.choices[0].message.content}
        except Exception as e:
            return {"ok": False, "provider": "openrouter", "error": str(e)}

    if mode in ("local", "embedded"):
        try:
            from app.local_ai import is_ready
            if is_ready():
                return {"ok": True, "provider": "local"}
            return {"ok": False, "provider": "local", "error": "Model not downloaded yet"}
        except Exception as e:
            return {"ok": False, "provider": "local", "error": str(e)}

    return {"ok": False, "error": "No AI provider configured"}


def _tool_trigger_sync(mode: str = "full") -> dict:
    try:
        import requests
        r = requests.post(
            "http://localhost:8000/api/sync/run",
            json={"mode": mode, "force_rebuild": False},
            timeout=10,
        )
        return r.json() if r.ok else {"ok": False, "error": r.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _tool_get_embed_snippet() -> dict:
    return {
        "snippet": """<!-- Aquera AI Help Widget -->
<script>
  (function() {
    var script = document.createElement('script');
    script.src = 'http://localhost:8000/widget.js';
    script.async = true;
    document.head.appendChild(script);
  })();
</script>""",
        "note": "Replace 'localhost:8000' with your production server URL before deploying.",
    }


def _tool_test_agents() -> dict:
    try:
        import requests
        ctx = {"page_title": "Health Check", "url": "https://example.com", "headings": [], "buttons": []}
        r1 = requests.post(
            "http://localhost:8000/api/help/contextual_help",
            json={"page_context": ctx, "chat_history": []},
            timeout=15,
        )
        r2 = requests.post(
            "http://localhost:8000/api/help/ask",
            json={"question": "What is Aquera?", "page_context": ctx, "chat_history": []},
            timeout=15,
        )
        return {
            "agent1": {"ok": r1.status_code == 200, "status": r1.status_code},
            "agent2": {"ok": r2.status_code == 200, "status": r2.status_code},
        }
    except Exception as e:
        return {"agent1": {"ok": False, "error": str(e)}, "agent2": {"ok": False, "error": str(e)}}


def _dispatch_tool(tool_name: str, tool_args: dict) -> str:
    """Dispatch a wizard tool call and return result as JSON string."""
    try:
        if tool_name == "check_setup_status":
            result = _tool_check_setup_status()
        elif tool_name == "verify_zendesk":
            result = _tool_verify_zendesk()
        elif tool_name == "verify_ai_provider":
            result = _tool_verify_ai()
        elif tool_name == "trigger_sync":
            result = _tool_trigger_sync(tool_args.get("mode", "full"))
        elif tool_name == "get_embed_snippet":
            result = _tool_get_embed_snippet()
        elif tool_name == "test_agents":
            result = _tool_test_agents()
        else:
            result = {"error": f"Unknown tool: {tool_name}"}
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Main wizard function ─────────────────────────────────────────────────────

def setup_wizard_chat(
    message: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    ai_provider: str = "gemini",
    api_key: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    """Run one turn of the setup wizard conversation.

    Args:
        message: The user's latest message.
        chat_history: Full conversation history (role/content dicts).
        ai_provider: AI provider to use for the wizard itself.
        api_key: Gemini API key if using Gemini.
        **extra: OpenRouter / Ollama kwargs.

    Returns:
        dict with 'response' text and '_wizard_status' dict.
    """
    history = list(chat_history or [])

    # Build OpenAI-compatible tool schemas
    tools = [
        {
            "type": "function",
            "function": {
                "name": td["name"],
                "description": td["description"],
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": v.get("type", "string"), "description": v.get("description", "")}
                                  for k, v in td.get("parameters", {}).items()},
                    "required": [],
                },
            }
        }
        for td in WIZARD_TOOLS
    ]

    messages = [{"role": "system", "content": WIZARD_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})

    # Route to the appropriate LLM
    response_text = _run_wizard_llm(messages, tools, ai_provider, api_key, **extra)

    # Also return current status so the UI can update the checklist
    try:
        wizard_status = _tool_check_setup_status()
    except Exception:
        wizard_status = {}

    return {
        "response": response_text,
        "_wizard_status": wizard_status,
    }


def _run_wizard_llm(
    messages: list,
    tools: list,
    ai_provider: str,
    api_key: str,
    **extra: Any,
) -> str:
    """Run the wizard agent loop with tool-calling. Returns final text."""

    if ai_provider in ("gemini",) and api_key:
        return _wizard_gemini(messages, api_key)

    # OpenAI-compatible (OpenRouter, Ollama, local fallback)
    return _wizard_openai_compat(messages, tools, ai_provider, api_key, **extra)


def _wizard_gemini(messages: list, api_key: str, max_iter: int = 5) -> str:
    """Run wizard loop via Gemini (google.genai new SDK) with simulated tool calling and retries."""
    from app.llm_utils import retry_with_backoff

    @retry_with_backoff(retries=3, base_delay=3.0)
    def call_gemini(full_prompt: str) -> str:
        import google.genai as genai
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=full_prompt.strip(),
        )
        return response.text.strip()

    try:
        # We use a simple conversational approach: include tool descriptions and results as text
        # since the new SDK function-calling API is async-first and complex to wire synchronously here.
        # The wizard system prompt already instructs the model to call tools by name.
        system_text = messages[0]["content"]
        history_text = ""
        for m in messages[1:]:
            prefix = "User" if m["role"] == "user" else "Assistant"
            history_text += f"{prefix}: {m['content']}\n\n"

        # Auto-call check_setup_status and inject result so AI always knows current state
        status_json = _dispatch_tool("check_setup_status", {})
        injected = (
            f"{system_text}\n\n"
            f"[CURRENT SYSTEM STATUS]:\n{status_json}\n\n"
            f"[TOOL RESULTS FORMAT]: When you need to run a tool, I will run it for you. Just ask."
        )

        full_prompt = injected + "\n\n" + history_text
        return call_gemini(full_prompt)
    except Exception as e:
        if "429" in str(e) or "resource_exhausted" in str(e).lower():
            return "Setup wizard is currently experiencing high demand (Gemini Rate Limit). I'm automatically retrying, but if this persists, please wait a minute and try again."
        return f"Setup wizard error (Gemini): {e}"


def _wizard_openai_compat(
    messages: list,
    tools: list,
    ai_provider: str,
    api_key: str,
    max_iter: int = 5,
    **extra: Any,
) -> str:
    """Run wizard loop via OpenAI-compatible API (OpenRouter, Ollama, etc.)."""
    try:
        from openai import OpenAI

        or_key = extra.get("openrouter_api_key", api_key)
        or_model = extra.get("openrouter_model", "mistralai/mistral-7b-instruct:free")

        if ai_provider in ("openrouter",) or or_key.startswith("sk-or"):
            client = OpenAI(
                api_key=or_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={"HTTP-Referer": extra.get("openrouter_site_url", "http://localhost:8000")},
            )
        else:
            ollama_url = extra.get("ollama_base_url", "http://localhost:11434")
            client = OpenAI(api_key="ollama", base_url=f"{ollama_url}/v1")
            or_model = extra.get("ollama_model", "phi3:mini")

        curr_messages = list(messages)
        for _ in range(max_iter):
            resp = client.chat.completions.create(
                model=or_model,
                messages=curr_messages,
                tools=tools,
                temperature=0.3,
            )
            choice = resp.choices[0]
            msg = choice.message
            if not msg.tool_calls:
                return msg.content or ""

            curr_messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                result = _dispatch_tool(tc.function.name, args)
                curr_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        return "I've reached my thinking limit. Please try again."
    except Exception as e:
        return f"Setup wizard error: {e}"


# ── Quick system status (no LLM) ─────────────────────────────────────────────

def get_system_status() -> Dict[str, Any]:
    """Return raw system status dict. Used by the /api/setup/status endpoint."""
    return _tool_check_setup_status()
