"""Agentic AI brain: contextual help and Q&A agents using OpenRouter with tool-calling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# Removed genai imports

from app.tools import (
    TOOL_DEFINITIONS,
    get_article_by_integration_id,
    search_knowledge_base,
)
from config import Config


# ── System prompts ─────────────────────────────────────────────────────

CONTEXTUAL_SYSTEM_PROMPT = """You are a Contextual System UI Analyzer. 

Your reasoning is governed by a strict TWO-PHASE mechanism. You must deduce the user's objective based on the VISUAL HIERARCHY TEMPLATE provided to you.

### PHASE 1: UI INGESTION (Primary Source)
- You must read the `VISUAL HIERARCHY TEMPLATE`.
- Identify the core workflow stage based on the `[GLOBAL CONTEXT]` and `[PAGE LAYOUT]`.
- Identify the most critical elements based on `[AVAILABLE ACTIONS]` and `[DATA INPUTS]`. 
- **CRITICAL RULE 1**: Prioritize explaining irreversible actions (`[CRITICAL]` buttons) or complex form fields FIRST.
- **CRITICAL RULE 2**: You MUST explicitly describe the purpose of the main screen AND also allocate bullet points to explain the available `Navigation Menus` and `Tabs` visible to the user.

### PHASE 2: KNOWLEDGE FALLBACK (Secondary Source)
- An `INTEGRATION GUIDE` may be appended at the end of the prompt. 
- You may ONLY quote or reference the Integration Guide if the live UI elements are unclear, or if you need deep technical context on a specific field present on the screen.
- If the live text on screen contradicts the guide, the live text WINS. Do NOT hallucinate elements that are not in the Visual Hierarchy.

### RESPONSE FORMAT:
- Provide a concise summary of the CURRENT screen state (under 50 words).
- Provide exactly 5 bullet points.
- Format: **[Prioritised Element from UI]**: [Smart explanation of its role in the current workflow step].
- At the end, include exactly: `Source: [Article Title]` ONLY if you actively used the attached guide.
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

def _build_tools() -> list:
    """Convert our tool definitions to OpenAI/OpenRouter tool format."""
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
    if function_name == "search_knowledge_base":
        results = search_knowledge_base(
            query=function_args.get("query", ""),
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=function_args.get("top_k", 5),
            integration_id=function_args.get("integration_id"),
        )
        return json.dumps(results, default=str)

    elif function_name == "get_article_by_integration_id":
        result = get_article_by_integration_id(
            integration_id=function_args.get("integration_id", ""),
            articles_dir=articles_dir,
        )
        if result:
            # Truncate very long articles to avoid token limits
            if len(result.get("text", "")) > 8000:
                result["text"] = result["text"][:8000] + "\n\n[... article truncated for brevity ...]"
            return json.dumps(result, default=str)
        return json.dumps({"error": "Article not found for this integration_id"})

    return json.dumps({"error": f"Unknown tool: {function_name}"})


# ── Agent runners ──────────────────────────────────────────────────────

def contextual_help_agent(
    page_context: Dict[str, Any],
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    chat_history: Optional[List[Dict[str, str]]] = None,
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
    
    if integration_id:
        article = get_article_by_integration_id(integration_id, articles_dir)
    
    if not article and page_context.get("page_title"):
        from app.tools import search_knowledge_base
        # Pass missing api_key and persist_dir
        search_results_json = search_knowledge_base(
            query=page_context["page_title"], 
            api_key=api_key,
            persist_dir=persist_dir,
            integration_id=integration_id, 
            top_k=1
        )
        import json
        try:
            results = json.loads(search_results_json)
            if results and len(results) > 0:
                top_hit = results[0]
                article = {
                    "title": top_hit["metadata"]["title"],
                    "text": top_hit["content"],
                    "article_id": top_hit["metadata"]["article_id"]
                }
        except:
            pass

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

    return _run_agent_loop(
        system_prompt=CONTEXTUAL_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        initial_article_meta=article_meta
    )


def qa_agent(
    question: str,
    page_context: Dict[str, Any],
    chat_history: Optional[List[Dict]] = None,
    api_key: str = "",
    persist_dir: str = "",
    articles_dir: Optional[Path] = None,
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
    # If we have an integration_id, fetch the article immediately to provide better grounding.
    integration_id = page_context.get("integration_id")
    if integration_id:
        from app.tools import get_article_by_integration_id
        article = get_article_by_integration_id(integration_id, articles_dir or Path("storage/processed/articles"))
        if article:
            user_message += f"\nRelevant Integration Guide found and attached for grounding:\n---\nTitle: {article['title']}\nContent: {article['text']}\n---\n"
    
    user_message += history_str

    return _run_agent_loop(
        system_prompt=QA_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir or Path("storage/processed/articles"),
    )


def _run_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
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
    model_id = "kimi-k2.5:cloud" 

    tools = _build_tools()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    try:
        last_article_meta = initial_article_meta or {}
        
        for _ in range(max_iterations):
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                tools=tools,
                temperature=0.3
            )
            
            message = response.choices[0].message
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
                    api_key=api_key,
                    persist_dir=persist_dir,
                    articles_dir=articles_dir,
                )

                # Track context updates
                if fn_name == "get_article_by_integration_id":
                    try:
                        parsed = json.loads(result)
                        if "title" in parsed:
                            last_article_meta = {
                                "article_title": parsed.get("title"),
                                "article_id": parsed.get("article_id")
                            }
                    except: pass
                elif fn_name == "search_knowledge_base":
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

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"response": f"AI error during local analysis: {str(e)}"}
