"""Agentic AI brain: contextual help and Q&A agents using OpenRouter with tool-calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Removed genai imports

from app.tools import (
    TOOL_DEFINITIONS,
    get_article_by_integration_id,
    search_integration_kb,
    search_general_kb,
)
from config import Config


# ── System prompts ─────────────────────────────────────────────────────

CONTEXTUAL_SYSTEM_PROMPT = """You are a Proactive Action Co-Pilot for the Aquera platform.

Your goal is to explain the UI to the user AND identify tasks you can do for them automatically (like filling out forms) based entirely on the provided `VISUAL HIERARCHY TEMPLATE` and `INTEGRATION GUIDE`.

### PHASE 1: UI INGESTION & EXPLANATION
- Read the `VISUAL HIERARCHY TEMPLATE` and the optional `INTEGRATION GUIDE`.
- Explain the current screen state concisely. Focus on critical actions and required data inputs.
- Do NOT hallucinate elements that are not in the Visual Hierarchy.
- If you use the Integration Guide to explain an element, append `Source: [Article Title]` to your explanation.

### PHASE 2: PROACTIVE ACTION SUGGESTION (CRITICAL)
- Review the `[DATA INPUTS]` and `[FORM FIELDS]` in the Visual Hierarchy.
- If the Integration Guide provides clear instructions on what values to put into these fields (e.g., standard mapping names, default URLs, required flags), you MUST suggest an action to fill them out automatically.
- To suggest actions, you must append a STRICT JSON block at the very end of your response, wrapped exactly in `---ACTION_SUGGESTIONS_START---` and `---ACTION_SUGGESTIONS_END---`.

**JSON Format Rules:**
Your JSON must be an array of "Action Suggestion" objects. 
Each object has a `label` (what the button will say) and a `steps` array.
Each step must have `action` (e.g., "fill_form") and `target` (the CSS selector, preferably the #id or name attribute from the Form Fields data).

EXAMPLE JSON:
---ACTION_SUGGESTIONS_START---
[
  {
    "label": "Auto-fill Standard Mapping Fields",
    "steps": [
      { "action": "fill_form", "target": "#employee-id", "value": "workerID" },
      { "action": "fill_form", "target": "input[name='status']", "value": "Active" }
    ]
  }
]
---ACTION_SUGGESTIONS_END---

WARNING: ONLY suggest actions if you are highly confident based on the provided Integration Guide. Ensure the JSON is valid.
"""

QA_SYSTEM_PROMPT = """You are an expert Aquera platform assistant. 

Your goal is to answer the user's question accurately using the provided tools to search the Knowledge Base.

### CRITICAL RULES:
1. **Source Citation is MANDATORY**: If you use information from a search result or an article, you MUST include a "Source Reference" section at the very end of your response.
2. **Precision**: If you don't know the answer or the articles don't contain it, say so. Don't make things up.
3. **Format**: Your response should be helpful, well-structured markdown.

### SOURCE REFERENCE FORMAT:
At the bottom of your answer, add:
**Source Reference**: [Article Title] (ID: [Article ID])
"""

# ── OpenRouter tool schema ─────────────────────────────────────────────

def _build_gemini_tools() -> list:
    """Convert our tool definitions to Google GenAI tool format."""
    from google.genai import types
    tools = []
    for tool_def in TOOL_DEFINITIONS:
        tools.append(
            types.Tool(function_declarations=[
                types.FunctionDeclaration(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    parameters=tool_def["parameters"],
                )
            ])
        )
    return tools

def _build_ollama_tools() -> list:
    """Convert our tool definitions to OpenAI format for local Ollama."""
    tools = []
    for tool_def in TOOL_DEFINITIONS:
        tools.append({
            "type": "function",
            "function": {
                "name": tool_def["name"],
                "description": tool_def["description"],
                "parameters": tool_def["parameters"],
            }
        })
    return tools


def _execute_tool_call(
    function_name: str,
    function_args: Dict[str, Any],
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
) -> Any:
    """Execute a tool call and return the result."""
    if function_name == "search_integration_kb":
        results = search_integration_kb(
            query=function_args.get("query", ""),
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=function_args.get("top_k", 5),
            integration_id=function_args.get("integration_id"),
        )
        return json.dumps(results, default=str)

    elif function_name == "search_general_kb":
        results = search_general_kb(
            query=function_args.get("query", ""),
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=function_args.get("top_k", 5),
        )
        return json.dumps(results, default=str)

    elif function_name == "get_article_by_id":
        from app.tools import get_article_by_id
        result = get_article_by_id(
            article_id=function_args.get("article_id", ""),
            articles_dir=articles_dir,
        )
        if result:
            return json.dumps(result, default=str)
        return json.dumps({"error": "Article not found for this article_id"})

    return json.dumps({"error": f"Unknown tool: {function_name}"})


# ── Agent runners ──────────────────────────────────────────────────────

def contextual_help_agent(
    page_context: Dict[str, Any],
    ai_provider: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    chat_history: Optional[List[Dict[str, str]]] = None,
    fallback_mode: str = "gemini",
    **extra,
) -> Dict[str, Any]:
    """Generate contextual help for the current page using OpenRouter."""
    # GROUP 1: GLOBAL CONTEXT & PAGE ID
    global_context = []
    if page_context.get("page_title"): global_context.append(f"Title: {page_context['page_title']}")
    if page_context.get("url_path"): global_context.append(f"Path: {page_context['url_path']}")
    if page_context.get("active_nav"): global_context.append(f"Active Menu: {page_context['active_nav']}")
    if page_context.get("integration_id"): global_context.append(f"Integration ID: {page_context['integration_id']}")
    
    # GROUP 2: MAIN SECTIONS (TABS & HEADINGS & NAV)
    structure_context = []
    if page_context.get("tabs"): structure_context.append(f"Tabs: {', '.join(page_context['tabs'])}")
    if page_context.get("headings"): structure_context.append(f"Headings: {', '.join(page_context['headings'])}")
    if page_context.get("nav_items"): structure_context.append(f"Navigation Menus: {', '.join(page_context['nav_items'])}")
    
    # GROUP 3: FORMS & INPUTS
    input_context = []
    if page_context.get("form_labels"): input_context.append(f"Fields: {', '.join(page_context['form_labels'])}")
    
    # GROUP 4: ACTIONS (BUTTONS)
    action_context = []
    if page_context.get("buttons"):
        consequence_keywords = ["delete", "remove", "disconnect", "sync", "reset", "save", "publish"]
        flagged_buttons = [f"{b} [CRITICAL]" if any(k in str(b).lower() for k in consequence_keywords) else str(b) for b in page_context["buttons"]]
        action_context.append(f"Buttons: {', '.join(flagged_buttons)}")

    # GROUP 5: SCREEN INSTRUCTIONS / TEXT
    text_context = []
    if page_context.get("descriptions"):
        flagged_desc = [f"{d} [COMPLEX]" if len(str(d)) > 200 or "configure" in str(d).lower() else str(d) for d in page_context["descriptions"]]
        text_context.append(f"Visible Text: {'; '.join(flagged_desc)}")

    # BUILD STRUCTURED TEMPLATE
    context_template = "--- VISUAL HIERARCHY TEMPLATE ---\n"
    if global_context: context_template += "[GLOBAL CONTEXT]\n- " + "\n- ".join(global_context) + "\n\n"
    if structure_context: context_template += "[PAGE LAYOUT]\n- " + "\n- ".join(structure_context) + "\n\n"
    if input_context: context_template += "[DATA INPUTS]\n- " + "\n- ".join(input_context) + "\n\n"
    if action_context: context_template += "[AVAILABLE ACTIONS]\n- " + "\n- ".join(action_context) + "\n\n"
    if text_context: context_template += "[ON-SCREEN INSTRUCTIONS]\n- " + "\n- ".join(text_context) + "\n\n"
    context_template += "---------------------------------\n"

    # Include recent chat history for memory
    history_str = ""
    if chat_history:
        recent = chat_history[-4:]  # Last 4 turns
        history_parts = [f"{t.get('role', 'user')}: {t.get('content', '')}" for t in recent]
        history_str = "\n\n[SESSION MEMORY]\n" + "\n".join(history_parts)

    user_message = (
        "The user is viewing a page. Provide crisp contextual help based on the following structured visual layout:\n\n"
        + context_template
    )
    
    if history_str:
        user_message += history_str

    article_meta = {}
    integration_id = page_context.get("integration_id")
    article = None
    
    # === STEP 1: Try direct lookup via integration_id (if mapped) ===
    if integration_id:
        article = get_article_by_integration_id(integration_id, articles_dir)
    
    # === STEP 2: Smart multi-signal semantic match (no pre-mapped ID needed) ===
    if not article:
        from app.tools import search_integration_kb, extract_integration_signals
        import json

        # Build a rich composite query from ALL available context signals
        composite_query = extract_integration_signals(page_context)
        print(f"DEBUG: Auto-matching integration guide via composite query: '{composite_query[:100]}...'")
        
        # Search with higher top_k to improve recall
        search_results_json = search_integration_kb(
            query=composite_query,
            api_key=api_key,
            persist_dir=persist_dir,
            integration_id=None,  # Don't filter by ID — we want the best semantic match
            top_k=3
        )
        try:
            results = json.loads(search_results_json) if isinstance(search_results_json, str) else search_results_json
            if results and len(results) > 0:
                top_hit = results[0]
                score = top_hit.get("score", 1.0)
                # Only attach if the semantic score is decent (not a totally irrelevant result)
                if score < 1.5:  # ChromaDB distance — lower is better; 1.5 is a useful threshold
                    article = {
                        "title": top_hit["metadata"]["title"],
                        "text": top_hit["text"],
                        "article_id": top_hit["metadata"]["article_id"]
                    }
                    print(f"DEBUG: Auto-matched guide: '{article['title']}' (score={score:.3f})")
                else:
                    print(f"DEBUG: No confident guide match found (best score={score:.3f})")
        except Exception as e:
            print(f"DEBUG: Guide auto-match error: {e}")

    if article:
        # TRUNCATE content to ~5000 chars to avoid model limits while keeping core grounding
        article_content = article['text']
        if len(article_content) > 5500:
            article_content = article_content[:5000] + "\n... [Remaining Guide Truncated for brevity] ..."

        user_message += f"\n\n--- RELEVANT INTEGRATION GUIDE ATTACHED ---\nTitle: {article['title']}\nContent: {article_content}\n---\n"
        article_meta = {
            "article_title": article.get("title"),
            "article_id": article.get("article_id")
        }

    return _route_agent_loop(
        ai_provider=ai_provider,
        system_prompt=CONTEXTUAL_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        initial_article_meta=article_meta,
        fallback_mode=fallback_mode,
        **extra
    )


def qa_agent(
    question: str,
    page_context: Dict[str, Any],
    ai_provider: str,
    chat_history: Optional[List[Dict]] = None,
    api_key: str = "",
    persist_dir: str = "",
    articles_dir: Optional[Path] = None,
    fallback_mode: str = "gemini",
    **extra,
) -> Dict[str, Any]:
    """Answer a user's question using the knowledge base via OpenRouter."""
    # Build context string
    context_parts = []
    if page_context.get("page_title"):
        context_parts.append(f"Current page: {page_context['page_title']}")
    if page_context.get("integration_id"):
        context_parts.append(f"Integration ID: {page_context['integration_id']}")

    context_str = "\n".join(context_parts) if context_parts else "No specific page context."

    # Include recent chat history if available
    history_str = ""
    if chat_history:
        recent = chat_history[-4:]  # Last 4 turns
        history_parts = []
        for turn in recent:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            history_parts.append(f"{role}: {content}")
        history_str = "\n\nRecent conversation:\n" + "\n".join(history_parts)

    user_message = (
        f"User question: {question}\n\n"
        f"Page context:\n{context_str}\n"
    )
    
    # PROACTIVE KNOWLEDGE RETRIEVAL:
    # First try direct integration_id lookup, then fall back to multi-signal semantic match.
    integration_id = page_context.get("integration_id")
    articles_path = articles_dir or Path("storage/processed/articles")
    article = None

    if integration_id:
        from app.tools import get_article_by_integration_id
        article = get_article_by_integration_id(integration_id, articles_path)

    if not article and (page_context.get("page_title") or page_context.get("headings")):
        from app.tools import search_integration_kb, extract_integration_signals
        import json
        composite_query = extract_integration_signals(page_context)
        print(f"DEBUG QA: Auto-matching integration guide: '{composite_query[:80]}...'")
        search_results = search_integration_kb(
            query=composite_query,
            api_key=api_key,
            persist_dir=persist_dir,
            integration_id=None,
            top_k=2
        )
        try:
            results = json.loads(search_results) if isinstance(search_results, str) else search_results
            if results and results[0].get("score", 2.0) < 1.5:
                top = results[0]
                article = {
                    "title": top["metadata"]["title"],
                    "text": top["text"],
                    "article_id": top["metadata"]["article_id"]
                }
                print(f"DEBUG QA: Auto-matched guide: '{article['title']}'")
        except Exception as e:
            print(f"DEBUG QA: Guide match error: {e}")

    if article:
        user_message += f"\nRelevant Integration Guide found and attached for grounding:\n---\nTitle: {article['title']}\nContent: {article['text'][:4000]}\n---\n"

    user_message += history_str

    return _route_agent_loop(
        ai_provider=ai_provider,
        system_prompt=QA_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        fallback_mode=fallback_mode,
        **extra
    )


def _route_agent_loop(
    ai_provider: str,
    system_prompt: str,
    user_message: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    fallback_mode: str = "gemini",
    initial_article_meta: Optional[Dict[str, Any]] = None,
    **extra,
) -> Dict[str, Any]:
    """Route to the appropriate AI backend, with smart auto-fallback support."""
    print(f"DEBUG: Routing request. Provider: {ai_provider.upper()}, Fallback: {fallback_mode.upper()}")

    errors: list = []
    # Always try a fallback chain if provider is auto or explicitly gemini/ollama
    if ai_provider == "auto":
        providers_to_try = ["gemini", "ollama", "openrouter"]
    elif ai_provider == "ollama":
        providers_to_try = ["ollama", "gemini", "openrouter"]
    elif ai_provider == "gemini":
        providers_to_try = ["gemini", "ollama", "openrouter"]
    else:
        providers_to_try = [ai_provider]

    for prov in providers_to_try:
        try:
            print(f"DEBUG: Attempting provider: {prov.upper()}...")
            result = None
            
            if prov == "gemini":
                if not api_key:
                    raise ValueError("Gemini API key missing")
                result = _run_gemini_agent_loop(system_prompt, user_message, api_key, persist_dir, articles_dir, initial_article_meta)
            
            elif prov in ("openrouter", "openai"):
                or_key = extra.get("openrouter_api_key", "")
                if not or_key:
                    raise ValueError("OpenRouter API key missing")
                or_model = extra.get("openrouter_model", "mistralai/mistral-7b-instruct:free")
                or_site  = extra.get("openrouter_site_url", "http://localhost:8000")
                result = _run_openrouter_agent_loop(system_prompt, user_message, or_key, or_model, or_site, persist_dir, articles_dir, initial_article_meta)
            
            elif prov == "ollama":
                ollama_model = extra.get("ollama_model", "qwen2.5-coder:7b")
                result = _run_ollama_agent_loop(system_prompt, user_message, ollama_model, persist_dir, articles_dir, initial_article_meta)
            
            # CRITICAL: Validate result for error strings that didn't raise exceptions
            if result and isinstance(result, dict) and "response" in result:
                txt = str(result["response"]).lower()
                if "429" in txt or "resource_exhausted" in txt or "quota exceeded" in txt or "api error" in txt:
                    print(f"DEBUG: Provider {prov.upper()} returned an error response. Continuing fallback...")
                    errors.append(f"{prov}: {result['response']}")
                    continue
                
                # --- NEW: PARSE PROACTIVE ACTION SUGGESTIONS OUT OF THE RESPONSE ---
                text = result["response"]
                if "---ACTION_SUGGESTIONS_START---" in text:
                    import re
                    import json
                    action_pattern = r"---ACTION_SUGGESTIONS_START---\s*(.*?)\s*---ACTION_SUGGESTIONS_END---"
                    match = re.search(action_pattern, text, re.DOTALL)
                    if match:
                        json_str = match.group(1).strip()
                        if not json_str:
                            json_str = "[]" # Handle empty block securely
                        try:
                            actions = json.loads(json_str)
                            if isinstance(actions, list):
                                result["action_suggestions"] = actions
                                # Remove the raw JSON block from the text shown to the user
                                result["response"] = re.sub(action_pattern, "", text, flags=re.DOTALL).strip()
                                print(f"DEBUG: Successfully extracted {len(actions)} action suggestions.")
                        except json.JSONDecodeError as e:
                            print(f"WARNING: LLM output invalid format for ACTION_SUGGESTIONS JSON: {e}")
                            print(f"DEBUG Invalid JSON String: '{json_str}'")

                print(f"DEBUG: Provider {prov.upper()} succeeded.")
                return result

        except Exception as e:
            err_msg = str(e)
            print(f"DEBUG: Provider {prov.upper()} raised exception: {err_msg}")
            errors.append(f"{prov}: {err_msg}")
            # Continue to next provider in loop

    # Final resort: Local LLM (llama-cpp-python) if available
    try:
        from app.local_ai import chat as local_chat, is_ready
        if is_ready():
            print("DEBUG: Using local fallback...")
            return local_chat(system_prompt, user_message)
    except Exception: pass

    return {"response": f"All AI providers failed. Tried: {', '.join(providers_to_try)}. Errors: {'; '.join(errors)}"}


def _run_openrouter_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
    model: str,
    site_url: str,
    persist_dir: str,
    articles_dir: Path,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
) -> Dict[str, Any]:
    """Execute the agent loop via OpenRouter (OpenAI-compatible API).

    OpenRouter lets you access 100+ models (Mistral, Llama-3, Phi-3, etc.)
    with one API key, many with free tiers. Cheapest cloud option.
    """
    import json
    from openai import OpenAI

    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        default_headers={
            "HTTP-Referer": site_url,
            "X-Title": "Aquera AI Help",
        },
    )

    # Build tool definitions in OpenAI format
    tools = []
    for td in TOOL_DEFINITIONS:
        # tool_def['parameters'] is a dict like {'type': 'object', 'properties': {...}, 'required': [...]}
        params = td.get("parameters", {})
        props = params.get("properties", {})
        
        tool_schema = {
            "type": "function",
            "function": {
                "name": td["name"],
                "description": td["description"],
                "parameters": {
                    "type": "object",
                    "properties": {
                        k: {"type": v.get("type", "string"), "description": v.get("description", "")}
                        for k, v in props.items()
                    },
                    "required": params.get("required", []),
                },
            }
        }
        tools.append(tool_schema)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]

    last_article_meta = initial_article_meta or {}
    tokens_in = 0
    tokens_out = 0

    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.3,
        )
        usage = resp.usage
        if usage:
            tokens_in  += usage.prompt_tokens or 0
            tokens_out += usage.completion_tokens or 0

        choice = resp.choices[0]
        msg = choice.message

        # No tool calls → final answer
        if not msg.tool_calls:
            text = msg.content or ""
            result = {
                "response": text,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_total": tokens_in + tokens_out,
                "_provider": f"openrouter/{model}",
            }
            result.update(last_article_meta)
            return result

        # Process tool calls
        messages.append({"role": "assistant", "content": None, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]})

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            try:
                fn_args = json.loads(tc.function.arguments)
            except Exception:
                fn_args = {}

            result = _call_tool(fn_name, fn_args, articles_dir)

            # Track last article
            if fn_name in ("get_article_by_integration_id", "get_article_by_id"):
                try:
                    p = json.loads(result)
                    if "title" in p:
                        last_article_meta = {"article_title": p.get("title"), "article_id": p.get("article_id")}
                except Exception:
                    pass
            elif fn_name in ("search_integration_kb", "search_general_kb"):
                try:
                    p = json.loads(result)
                    if p:
                        last_article_meta = {
                            "article_title": p[0].get("metadata", {}).get("title"),
                            "article_id": p[0].get("metadata", {}).get("article_id"),
                        }
                except Exception:
                    pass

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return {"response": "Agent reached max iterations.", "tokens_in": tokens_in, "tokens_out": tokens_out, "tokens_total": tokens_in + tokens_out}


def _call_tool(fn_name: str, fn_args: dict, articles_dir: Path) -> str:
    """Dispatch a tool call and return the result as a JSON string."""
    import json
    try:
        if fn_name == "get_article_by_integration_id":
            result = get_article_by_integration_id(fn_args.get("integration_id", ""), articles_dir)
        elif fn_name == "get_article_by_id":
            from app.tools import get_article_by_id
            result = get_article_by_id(fn_args.get("article_id", ""), articles_dir)
        elif fn_name == "search_integration_kb":
            result = search_integration_kb(fn_args.get("query", ""), fn_args.get("top_k", 5), articles_dir)
        elif fn_name == "search_general_kb":
            result = search_general_kb(fn_args.get("query", ""), fn_args.get("top_k", 5), articles_dir)
        else:
            result = {"error": f"Unknown tool: {fn_name}"}
        return json.dumps(result, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _run_gemini_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
) -> Dict[str, Any]:
    """Execute the agent loop using Gemini via Google GenAI SDK with automatic retries."""
    from app.llm_utils import retry_with_backoff

    @retry_with_backoff(retries=0, base_delay=0.5)
    def _run_loop():
        import json
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=api_key)
        model_id = "gemini-2.0-flash-lite" # Optimized for free tier

        tools = _build_gemini_tools()

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            temperature=0.3
        )

        last_article_meta = initial_article_meta or {}
        search_confidence = 1.0 # Default to high if no search done
        chat = client.chats.create(model=model_id, config=config)
        response = chat.send_message(user_message)
        
        for _ in range(max_iterations):
            if not response.function_calls:
                break

            print(f"DEBUG: Gemini calling {len(response.function_calls)} tools...")
            
            tool_responses = []
            for fc in response.function_calls:
                fn_name = fc.name
                fn_args = {k: v for k, v in fc.args.items()} if hasattr(fc, 'args') and fc.args else {}
                
                print(f"DEBUG: Tool {fn_name} arguments: {json.dumps(fn_args)}")

                result = _execute_tool_call(
                    function_name=fn_name,
                    function_args=fn_args,
                    api_key=api_key,
                    persist_dir=persist_dir,
                    articles_dir=articles_dir,
                )

                # Track context updates and search confidence
                if fn_name in ["get_article_by_integration_id", "get_article_by_id"]:
                    try:
                        parsed = json.loads(result)
                        if "title" in parsed:
                            last_article_meta = {
                                "article_title": parsed.get("title"),
                                "article_id": parsed.get("article_id")
                            }
                    except: pass
                elif fn_name in ["search_integration_kb", "search_general_kb"]:
                    try:
                        parsed = json.loads(result)
                        if parsed and len(parsed) > 0:
                            last_article_meta = {
                                "article_title": parsed[0].get("metadata", {}).get("title"),
                                "article_id": parsed[0].get("metadata", {}).get("article_id")
                            }
                            # Lower confidence if the best search result has high distance
                            best_dist = parsed[0].get("distance", 0.0)
                            # Chroma cosine distance: 0.0 is perfect, 1.0 is unrelated
                            search_confidence = max(0.0, 1.0 - best_dist)
                        else:
                            search_confidence = 0.0
                    except: pass

                try:
                    result_dict = json.loads(result)
                    # The Google GenAI SDK expects a dictionary for FunctionResponse.
                    # If the tool returned a list (common for search), wrap it.
                    if isinstance(result_dict, list):
                        result_dict = {"results": result_dict}
                    elif not isinstance(result_dict, dict):
                        result_dict = {"output": str(result_dict)}
                except Exception as e:
                    print(f"DEBUG: Failed to parse tool result as JSON: {e}")
                    result_dict = {"output": str(result)}
                
                print(f"DEBUG: Final tool response dictionary for {fn_name}: {json.dumps(result_dict)[:200]}...")
                    
                tool_responses.append(
                    types.Part.from_function_response(
                        name=fn_name,
                        response=result_dict
                    )
                )

            response = chat.send_message(tool_responses)

        final_text = ""
        try:
            final_text = response.text
        except Exception:
            for part in response.candidates[0].content.parts:
                if part.text:
                    final_text += part.text

        if not final_text:
            final_text = "I analyzed the page but couldn't deduce a specific help objective based on the visible elements."

        # Extract token usage
        tokens_in = 0
        tokens_out = 0
        try:
            usage = response.usage_metadata
            tokens_in = getattr(usage, "prompt_token_count", 0) or 0
            tokens_out = getattr(usage, "candidates_token_count", 0) or 0
        except Exception:
            pass

        res = {
            "response": final_text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_total": tokens_in + tokens_out,
            "confidence": search_confidence,
        }
        if last_article_meta:
            res.update(last_article_meta)
        return res

    return _run_loop()


def _run_ollama_agent_loop(
    system_prompt: str,
    user_message: str,
    model_id: str,
    persist_dir: str,
    articles_dir: Path,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
) -> Dict[str, Any]:
    """Execute the agent loop using local Ollama via OpenAI SDK."""
    import json
    from openai import OpenAI
    
    # Point to local Ollama
    client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

    tools = _build_ollama_tools()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    last_article_meta = initial_article_meta or {}
    
    print(f"DEBUG: Starting Ollama agent loop with model: {model_id}")
    for i in range(max_iterations):
        print(f"DEBUG: Ollama iteration {i+1}/{max_iterations}...")
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                tools=tools,
                temperature=0.3
            )
        except Exception as e:
            print(f"DEBUG: Ollama client error: {str(e)}")
            raise
        
        message = response.choices[0].message
        print(f"DEBUG: Ollama message received. Tool calls: {bool(message.tool_calls)}")
        # Filter out None content so OpenAI SDK doesn't complain
        msg_dict = {"role": "assistant", "content": message.content or ""}
        
        if not message.tool_calls:
            messages.append(msg_dict)
            break

        print(f"DEBUG: Local AI calling {len(message.tool_calls)} tools...")
        msg_dict["tool_calls"] = []
        for fc in message.tool_calls:
            msg_dict["tool_calls"].append({
                "id": fc.id,
                "type": "function",
                "function": {
                    "name": fc.function.name,
                    "arguments": fc.function.arguments
                }
            })

        messages.append(msg_dict)

        for fc in message.tool_calls:
            fn_name = fc.function.name
            try:
                fn_args = json.loads(fc.function.arguments)
            except Exception:
                fn_args = {}
            
            print(f"DEBUG: Tool {fn_name} arguments: {json.dumps(fn_args)}")

            result = _execute_tool_call(
                function_name=fn_name,
                function_args=fn_args,
                api_key="ollama",
                persist_dir=persist_dir,
                articles_dir=articles_dir,
            )

            # Track context updates
            if fn_name in ["get_article_by_integration_id", "get_article_by_id"]:
                try:
                    parsed = json.loads(result)
                    if "title" in parsed:
                        last_article_meta = {
                            "article_title": parsed.get("title"),
                            "article_id": parsed.get("article_id")
                        }
                except: pass
            elif fn_name in ["search_integration_kb", "search_general_kb"]:
                try:
                    parsed = json.loads(result)
                    if parsed and len(parsed) > 0:
                        last_article_meta = {
                            "article_title": parsed[0].get("metadata", {}).get("title"),
                            "article_id": parsed[0].get("metadata", {}).get("article_id")
                        }
                except: pass

            messages.append({
                "role": "tool",
                "tool_call_id": fc.id,
                "name": fn_name,
                "content": result
            })

    final_text = ""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            final_text = m.get("content")
            break

    if not final_text:
        final_text = "I analyzed the page but couldn't deduce a specific help objective based on the visible elements."

    print(f"--- LOCAL LLM FINAL RESPONSE ---\n{final_text}\n-----------------------")
    
    res = {"response": final_text}
    if last_article_meta:
        res.update(last_article_meta)
    return res
