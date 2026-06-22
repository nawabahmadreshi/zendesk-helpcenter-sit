"""Agentic AI brain: contextual help and Q&A agents using OpenRouter with tool-calling."""

from __future__ import annotations

import re
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Removed genai imports

import openai
from openai import OpenAI
try:
    import google.genai
except ImportError:
    pass

from app.tools import (
    TOOL_DEFINITIONS,
    get_article_by_integration_id,
    search_integration_kb,
    search_general_kb,
    check_domain_reachability,
    extract_integration_signals,
    graph_compare_versions,
)
from app.workflows import WorkflowEngine
from app.user_model import UserModel
from app.crag_gate import CRAGGate
from app.graph_store import GraphStore
from config import Config

# PHASE 10+: Hierarchical Retrieval
try:
    from app.raptor import RaptorEngine
    from app.embedding import search_knowledge_base
except ImportError:
    pass

def _clean_agent_response(text: str) -> str:
    """Universal hygiene layer to strip unwanted AI thinking/fragments."""
    if not text:
        return ""
    # Strip common thought-process or JSON fragments that bleed into text
    text = re.sub(r'\{"name":.*?\}(?:\s*\}|)', '', text, flags=re.DOTALL)
    text = re.sub(r'\[\{"name":.*?\}\]', '', text, flags=re.DOTALL)
    text = re.sub(r'```(?:json|)\s*\{"name":.*?\}\s*```', '', text, flags=re.DOTALL)
    # Strip thinking tags if any (e.g. <thinking>...</thinking>)
    text = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Self-RAG: Parse and Enforce Reflection Tokens
    lower_text = text.lower()
    if "[critique: hallucination-risk]" in lower_text:
        return "The retrieved knowledge does not contain a definitive answer to this question. I have stopped generating to prevent hallucinations. Please try rewording your question or doing a broader search."
    
    text = re.sub(r'\[Critique: Relevant\]\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[Critique: Supported\]\s*', '', text, flags=re.IGNORECASE)
    
    return text.strip()


# ── Intent Intelligence ────────────────────────────────────────────────

class IntentType:
    SETUP_DISCOVERY = "SetupDiscovery"         # Learning how to configure a new integration
    ERROR_RESOLUTION = "ErrorResolution"      # Stuck on a validation or API error
    FIELD_DEFINITION = "FieldDefinition"      # Asking what a specific field does
    WORKFLOW_OPTIMIZATION = "WorkflowOptimization" # Looking for a faster way to finish 
    VERSION_COMPARISON = "VersionComparison"   # Asking about differences between v11/v14
    NAVIGATION_HELP = "NavigationHelp"         # Trying to find a specific menu
    ACTION_VALIDATION = "ActionValidation"     # Checking if it's safe to click 'Delete' or 'Sync'
    GENERAL_INQUIRY = "GeneralInquiry"         # Standard Q&A
    UNKNOWN = "Unknown"

# ── Predictive Intelligence ──────────────────────────────────────────

class PredictiveEngine:
    """Zero-click proactive assistance engine."""
    
    @staticmethod
    def predict_next_step(page_context: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """Predict the user's next likely logical field or action."""
        focused = page_context.get("focused_field", {})
        focused_id = focused.get("id", "") if focused else ""
        
        # Simple sequence mapping for Aquera Setup
        sequences = {
            "instance_url": {"next_id": "auth_type", "hint": "Next: Select your Authentication Method"},
            "auth_type": {"next_id": "api_key", "hint": "Next: Enter your API Key or Token"},
            "api_key": {"next_id": "client_id", "hint": "Next: Provide OAuth Client Credentials"},
            "client_id": {"next_id": "client_secret", "hint": "Next: Securely enter the Secret"},
            "client_secret": {"next_id": "save_btn", "hint": "Ready: Save and Test Connectivity"}
        }
        
        for key, val in sequences.items():
            if key in focused_id:
                return val
        return None

    @staticmethod
    def get_ghost_autocomplete(query: str) -> str:
        """Predict sentence completion for search box."""
        if not query or len(query) < 2: return ""
        
        q = query.lower().strip()
        completions = [
            "how to configure adp workforce now",
            "fix validation error on instance url",
            "where to find client secret in sfdc",
            "sync schedule best practices",
            "how do i rotate my api key",
            "setup okta saml integration",
            "manage user permissions in aquera",
            "view sync history logs",
            "troubleshoot oauth2 handshake"
        ]
        
        # Exact prefix match
        for c in completions:
            if c.startswith(q):
                return c[len(q):]
        
        # Word-based match (e.g. "adp" matches "how to configure adp...")
        for c in completions:
            if q in c and not c.startswith(q):
                # Suggest from the point of match for a "floating" ghost, 
                # but for simple UI we just do prefix matching for now.
                pass

        return ""

CONTEXTUAL_SYSTEM_PROMPT = """You are the Aquera Visual AI Co-Pilot.

Your goal is to provide INSTANT, CONTEXTUAL help by reading the user's screen like a human expert.

### CRITICAL: THE "UI IS TRUTH" DIRECTIVE
1. **Visual Reasoning First**: If NO internal guide (Knowledge Base) is found, DO NOT apologize. Use your "eyes" (the DOM scan and Screenshot) to explain the page.
2. **Reverse Engineering**: Look at the headings, field labels, and button texts. 
   - *Example*: If you see "Integration Name" and "Instance URL", explain that they are embarking on a new setup and need to name it and provide the target URL.
3. **Action Guidance**: Point out the primary action button (e.g., "Click the 'Save and Test' button once you've entered your API key").

### PHASE 1: VISUAL GROUNDING (THE "EYES")
- Use the attached SCREENSHOT to confirm layout.
- Reference spatial positions: "the blue button in the top right", "the field below the heading 'Authentication'".

### PHASE 2: DIAGNOSTIC INTELLIGENCE (THE "EARS")
- You are provided with the last 20 CONSOLE LOGS.
- If the user is facing an issue, search these logs for "ERROR", "Failed to fetch", or 401/403/500 status codes.
- Use these logs to explain WHY a save failed (e.g., "The logs show a '401 Unauthorized' error, which means your API token might be expired").

### OUTPUT FORMAT:
1. **Executive Summary**: A crisp, 2-3 sentence explanation of the current screen and its purpose.
2. **Actionable Step**: The single most logical next thing the user should do. 
3. **Deep Context (if applicable)**: If you found an error in the logs, explain it clearly.
4. **Visual Hint**: A grounded reference to what they are looking at.
"""

QA_SYSTEM_PROMPT = """You are an expert Aquera platform assistant. 

Your goal is to answer the user's question with surgical precision.

### CRITICAL: RESPONSE DIRECTIVE
- **PRIORITIZE KNOWLEDGE BASE**: If a 'Relevant Integration Guide' or 'ADAPTIVE KNOWLEDGE CONTEXT' is provided, you MUST use it as your primary source of truth. 
- **PINNED GUIDE ISOLATION**: If a "Relevant Integration Guide" is provided, you MUST restrict your answers STRICTLY to that document. If the document does not contain the answer, you MUST explicitly state: "I did not find that information in this guide. Would you like to go back to the results and search the entire knowledge base?" DO NOT guess or hallucinate external knowledge.
- **No Document? No Problem**: If the internal Knowledge Base search yields NO direct match, DO NOT APOLOGIZE. 
- **Use Visible Data**: Analyze the `PAGE CONTEXT` and `SCREENSHOT`. Use these "eyes" to explain what is happening on screen.
- **UI State Awareness**: Pay special attention to 'ACTIVE MODAL' or 'NAVIGATION MENU' sections. If a modal is open, focus your help ON the modal content.
- **Goal-Oriented**: Focus on what the user is currently doing (e.g., "You are setting up an integration; the 'Client ID' field is where you enter your unique application identifier").

### SELF-REFLECTION (Self-RAG)
Before answering, you must critically evaluate the provided context.
Output one of the following critique tokens at the very beginning of your response:
- `[Critique: Relevant]` if the context directly answers the question.
- `[Critique: Supported]` if your answer is fully supported by the text.
- `[Critique: Hallucination-Risk]` if the text is vague and you are tempted to guess.
If you output `[Critique: Hallucination-Risk]`, you MUST STOP and state: "The retrieved knowledge does not contain a definitive answer to this question." Do not attempt to answer it.

### SOURCE CITATION:
- ONLY include a "Source Reference" if you successfully found and used a Knowledge Base article.
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
    product_version: Optional[str] = None,
) -> Any:
    """Execute a tool call and return the result."""
    if function_name == "search_integration_kb":
        results = search_integration_kb(
            query=function_args.get("query", ""),
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=function_args.get("top_k", 5),
            integration_id=function_args.get("integration_id"),
            product_version=product_version,
        )
        return json.dumps(results, default=str)

    elif function_name == "search_general_kb":
        results = search_general_kb(
            query=function_args.get("query", ""),
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=function_args.get("top_k", 5),
            product_version=product_version,
        )
        return json.dumps(results, default=str)

    elif function_name == "graph_compare_versions":
        results = graph_compare_versions(
            version_a=function_args.get("version_a", ""),
            version_b=function_args.get("version_b", ""),
        )
        return results

    elif function_name == "get_article_by_id":
        from app.tools import get_article_by_id
        result = get_article_by_id(
            article_id=function_args.get("article_id", ""),
            articles_dir=articles_dir,
        )
        if result:
            return json.dumps(result, default=str)
        return json.dumps({"error": "Article not found for this article_id"})

    elif function_name == "get_article_by_integration_id":
        from app.tools import get_article_by_integration_id
        result = get_article_by_integration_id(
            integration_id=function_args.get("integration_id", ""),
            articles_dir=articles_dir,
        )
        if result:
             return json.dumps(result, default=str)
        
        # ── HORIZON: MCP FALLBACK ──
        # If not found locally, try live Zendesk fetch
        print("[DEBUG] Local article not found. Triggering Zendesk Live MCP Fetch...")
        from mcp_servers.zendesk_server import get_article as mcp_get_article
        mcp_res = mcp_get_article(function_args.get("integration_id", ""))
        
        # LOG RETRIEVAL GAP IF STILL NOT FOUND
        if not mcp_res or "error" in str(mcp_res).lower():
            from mcp_servers.analytics_server import report_retrieval_gap
            report_retrieval_gap(
                query=str(function_args.get("integration_id")), 
                integration_id=str(function_args.get("integration_id")),
                product_version=product_version or "unknown"
            )
            
        return json.dumps({"mcp_fallback": True, "content": mcp_res})

    elif function_name == "synthesize_data_processor":
        from app.dynamic_tools import synthesize_data_processor
        results = synthesize_data_processor(
            logic_code=function_args.get("logic_code", ""),
            context_data=function_args.get("context_data", []),
        )
        return json.dumps(results, default=str)

    elif function_name == "check_domain_reachability":
        from app.tools import check_domain_reachability
        result = check_domain_reachability(
            domain_or_url=function_args.get("domain_or_url", "")
        )
        return json.dumps({"reachability": result})

    return json.dumps({"error": f"Unknown tool: {function_name}"})


# ── Intent Classifier ─────────────────────────────────────────────────

def classify_intent(
    page_context: Dict[str, Any],
    api_key: str,
    ai_provider: str = "gemini",
    screenshot_base64: Optional[str] = None,
    **extra
) -> str:
    """Predict the user's intent class using Gemini 2.0 (Vision-Grounded)."""
    from google import genai
    from google.genai import types
    import base64

    # Build a condensed context for the classifier
    condensed_context = {
        "title": page_context.get("page_title"),
        "url": page_context.get("url_path"),
        "focused": page_context.get("focused_field"),
        "errors": page_context.get("active_errors"),
        "recent_events": [f"{e['type']} on {e.get('text', e.get('id', 'unknown'))}" for e in page_context.get("event_stream", [])[-5:]]
    }

    intent_prompt = f"""Identify the user's primary intent from the following Aquera UI context:
{json.dumps(condensed_context, indent=2)}

Choose EXACTLY ONE intent from this list:
- {IntentType.SETUP_DISCOVERY}: User is trying to set up or configure an integration.
- {IntentType.ERROR_RESOLUTION}: User is actively struggling with a visible error or repeated failed actions.
- {IntentType.FIELD_DEFINITION}: User is focused on or clicking into a specific field to understand it.
- {IntentType.WORKFLOW_OPTIMIZATION}: User is navigating around looking for better ways to do things.
- {IntentType.VERSION_COMPARISON}: User is asking or looking at version-specific details.
- {IntentType.NAVIGATION_HELP}: User is jumping between menus or breadcrumbs.
- {IntentType.ACTION_VALIDATION}: User is about to click a high-consequence button (Save, Delete, Sync).
- {IntentType.GENERAL_INQUIRY}: None of the above.

Response MUST only be the Intent string.
"""
    
    try:
        # We use a fast, low-temperature prompt for classification
        client = genai.Client(api_key=api_key)
        
        contents = [intent_prompt]
        if screenshot_base64:
            print("[DEBUG] Using Vision for intent classification.")
            if "," in screenshot_base64:
                header, encoded = screenshot_base64.split(",", 1)
                mime = header.split(";")[0].split(":")[1]
            else:
                encoded = screenshot_base64
                mime = "image/jpeg"
            
            img_bytes = base64.b64decode(encoded)
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

        response = client.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=contents,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=20
            )
        )
        predicted = response.text.strip()
        # Validate against known classes
        for attr in dir(IntentType):
            val = getattr(IntentType, attr)
            if isinstance(val, str) and val.lower() == predicted.lower():
                return val
        return IntentType.UNKNOWN
    except Exception as e:
        print(f"[ERROR] Intent classification failed: {e}")
        # Phase 2.1b: Heuristic Fallback for resilience (API downtime/quota)
        if page_context.get("active_errors"):
            return IntentType.ERROR_RESOLUTION
        
        events = page_context.get("event_stream", [])
        clicks = [e for e in events if isinstance(e, dict) and e.get("type") == "click"]
        last_clicks = clicks[-3:] if clicks else []
        if len(last_clicks) >= 2 and all("save" in str(c.get("text")).lower() for c in last_clicks):
            return IntentType.ERROR_RESOLUTION
            
        url = str(page_context.get("url_path", "")).lower()
        if "new" in url or "config" in url or "setup" in url:
            return IntentType.SETUP_DISCOVERY
            
        if last_clicks:
            text = str(last_clicks[-1].get("text", "")).lower()
            if any(k in text for k in ["what is", "help with", "define", "?", "how to"]):
                return IntentType.FIELD_DEFINITION
            if any(k in text for k in ["delete", "remove", "sync", "save", "update"]):
                return IntentType.ACTION_VALIDATION
            
        return IntentType.UNKNOWN


# ── Agent runners ──────────────────────────────────────────────────────

def contextual_help_agent(
    page_context: Dict[str, Any],
    ai_provider: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    chat_history: Optional[List[Dict[str, str]]] = None,
    fallback_mode: str = "gemini",
    predicted_intent: str = "Unknown",
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
    
    # MODAL AWARENESS (NEW)
    if page_context.get("is_modal_open"):
        modal_info = f"ACTIVE MODAL DETECTED: {page_context.get('modal_title', 'Unnamed Modal')}"
        structure_context.append(f"\n[URGENT: UI STATE]\n{modal_info}")
        print(f"DEBUG: Injecting Modal state into prompt: {modal_info}")
    
    # GROUP 3: FORMS & INPUTS
    input_context = []
    if page_context.get("form_labels"): input_context.append(f"Field Labels: {', '.join(page_context['form_labels'])}")
    if page_context.get("form_fields"):
        # NEW: Inject detailed metadata (IDs, types, placeholders) for deep reasoning
        fields_summary = []
        for f in page_context["form_fields"][:15]: # Up to 15 fields
            f_str = f"Label: {f.get('label', 'Unknown')} | ID: {f.get('id', '')} | Name: {f.get('name', '')} | Placeholder: {f.get('placeholder', '')}"
            fields_summary.append(f_str)
        input_context.append(f"Detailed Form Fields Metadata:\n- " + "\n- ".join(fields_summary))
    
    integration_id = page_context.get("integration_id")
    product_version = page_context.get("product_version")

    # GROUP 3.5: GRAPHSTORE LOOKUP
    graph_context = []
    try:
        cfg = Config()
        graph_db_path = cfg.STORAGE_DIR / "knowledge_graph.json"
        graph_store = GraphStore(storage_path=str(graph_db_path))
        graph_store.load()

        # Extract entities from integration_id and version
        if integration_id:
            rels = graph_store.get_relationships_for_entity(integration_id)
            if rels:
                graph_context.append(f"Relationships for '{integration_id}':")
                for rel in rels:
                    graph_context.append(f"- {rel['source']} --({rel['type']})--> {rel['target']}")
                    
        if graph_context:
            graph_context.insert(0, "GraphStore relational context found:")
    except Exception as e:
        print(f"DEBUG: GraphStore lookup failed: {e}")

    # GROUP 5: SOTA DIAGNOSTIC LOGS (NEW)
    diagnostic_context = []
    if page_context.get("logs"):
        logs = page_context["logs"][-20:] # Last 20
        for l in logs:
            diagnostic_context.append(f"[{l.get('ts', '')}] {l.get('level', 'info').upper()}: {l.get('text', '')}")

    # GROUP 6: ACTIONS (BUTTONS)
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

    # GROUP 6: EVENT STREAM (BEHAVIORAL CONTEXT)
    event_context = []
    if page_context.get("event_stream"):
        events = page_context["event_stream"][-7:] # Last 7 events
        event_summaries = []
        for e in events:
            time_offset = e.get("timestamp", "").split("T")[-1].split(".")[0]
            summary = f"[{time_offset}] {e.get('type').upper()}: "
            if e.get("type") == "click": summary += f"Target: {e.get('text', 'Unknown')} ({e.get('tag')})"
            elif e.get("type") == "focus": summary += f"Focused: {e.get('placeholder') or e.get('id') or 'field'}"
            elif e.get("type") == "input_change": summary += f"Input in {e.get('id')} (Len: {e.get('length')})"
            event_summaries.append(summary)
        event_context.append(f"RECENT CONTEXTUAL ACTIONS:\n- " + "\n- ".join(event_summaries))

    # GROUP 7: WORKFLOW INTELLIGENCE (PHASE 4)
    workflow_context = []
    current_node_id = "unknown"
    try:
        engine = WorkflowEngine()
        form_values = {f.get("id"): f.get("value") for f in page_context.get("form_fields", []) if f.get("id")}
        analysis = engine.analyze_progress(page_context.get("event_stream", []), form_values)
        current_node_id = analysis['current_node']
        workflow_context.append(f"Current Node: {current_node_id}")
        workflow_context.append(f"Advice: {analysis['advice']}")
        if analysis["skipped_nodes"]:
            workflow_context.append(f"SKIPPED STEPS: {', '.join(analysis['skipped_nodes'])}")
    except Exception as e:
        print(f"DEBUG: Workflow analysis failed: {e}")

    # GROUP 8: USER PERSONALIZATION (PHASE 5)
    personalization_context = []
    try:
        user_model = UserModel(db_path=str(Path(persist_dir).parent / "user_model.db"))
        user_id = page_context.get("user_id", "default_user")
        mastery = user_model.get_mastery(user_id, current_node_id)
        personalization_context.append(f"User Mastery for {current_node_id}: {mastery:.2f}")
        
        if mastery > 0.8:
            # Proactive Suppression: If user knows this, don't repeat basics.
            personalization_context.append("NOTICE: User is a MASTER of this step. Minimize introductory tips. Focus on advanced power-user advice if any.")
        
        # Record this interaction (implicit feedback)
        user_model.record_interaction(user_id, current_node_id)
    except Exception as e:
        print(f"DEBUG: Personalization failed: {e}")

    # GROUP 9: ERROR RISK HEAD (PHASE 5)
    error_risk_context = []
    if predicted_intent in ["ActionValidation", "ErrorResolution"]:
        # Heuristic check for mandatory fields missing in current node
        try:
            engine = WorkflowEngine()
            form_values = {f.get("id"): f.get("value") for f in page_context.get("form_fields", []) if f.get("id")}
            analysis = engine.analyze_progress(page_context.get("event_stream", []), form_values)
            if analysis["skipped_nodes"]:
                error_risk_context.append(f"CRITICAL RISK: User is attempting to {predicted_intent} but has skipped nodes: {', '.join(analysis['skipped_nodes'])}")
        except: pass

    # BUILD STRUCTURED TEMPLATE
    context_template = "--- VISUAL HIERARCHY TEMPLATE ---\n"
    context_template += f"[PREDICTED USER INTENT]\n- {predicted_intent}\n\n"
    if global_context: context_template += "[GLOBAL CONTEXT]\n- " + "\n- ".join(global_context) + "\n\n"
    if structure_context: context_template += "[PAGE LAYOUT]\n- " + "\n- ".join(structure_context) + "\n\n"
    if input_context: context_template += "[DATA INPUTS]\n- " + "\n- ".join(input_context) + "\n\n"
    
    if page_context.get("focused_field"):
        f = page_context["focused_field"]
        context_template += f"[CURRENTLY FOCUSED FIELD]\n- Label: {f.get('label')} | ID: {f.get('id')}\n\n"
    
    if page_context.get("active_errors"):
        context_template += "[ACTIVE ERRORS DETECTED]\n- " + "\n- ".join(page_context["active_errors"]) + "\n\n"

    if action_context: context_template += "[AVAILABLE ACTIONS]\n- " + "\n- ".join(action_context) + "\n\n"
    if text_context: context_template += "[ON-SCREEN INSTRUCTIONS]\n- " + "\n- ".join(text_context) + "\n\n"
    if event_context: context_template += "[EVENT STREAM]\n- " + "\n- ".join(event_context) + "\n\n"
    if workflow_context: context_template += "[WORKFLOW LIFECYCLE]\n- " + "\n- ".join(workflow_context) + "\n\n"
    if personalization_context: context_template += "[USER PERSONALIZATION]\n- " + "\n- ".join(personalization_context) + "\n\n"
    if diagnostic_context: context_template += "[SOTA DIAGNOSTIC LOGS]\n- " + "\n- ".join(diagnostic_context) + "\n\n"
    if graph_context: context_template += "[RELATIONAL CONTEXT]\n- " + "\n- ".join(graph_context) + "\n\n"
    if error_risk_context: context_template += "[ERROR RISK HEAD ANALYSIS]\n- " + "\n- ".join(error_risk_context) + "\n\n"
    
    context_template += "--- END TEMPLATE ---\n"
    if page_context.get("breadcrumbs"):
        context_template += "[BREADCRUMB PATH (Reverse Hierarchy)]\n- " + " > ".join(page_context["breadcrumbs"]) + "\n\n"
    
    context_template += "[GROUNDING SIGNALS]\n"
    if page_context.get("page_title"): context_template += f"- Page Subject: {page_context['page_title']}\n"
    if page_context.get("url_path"): context_template += f"- URL Path: {page_context['url_path']}\n"
    
    # Mastery-Aware Personalization
    if page_context.get("mastery_context"):
        mc = page_context["mastery_context"]
        context_template += f"- User Role: {mc.get('role', 'standard')}\n"
        context_template += f"- Mastery Level: {mc.get('mastery_level', 'novice')}\n"
        context_template += f"- Preferred Version: {mc.get('product_version', '')}\n"

    context_template += "\n"

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

    # === STEP 1: ADAPTIVE GROUNDING (PHASE 12) ===
    # Use Intent-Driven Routing to select the best knowledge signals
    article = None
    crag_status = "NONE"
    crag_score = 0.0
    signals = ""
    article_meta = {}
    integration_id = page_context.get("integration_id")
    product_version = page_context.get("product_version")

    try:
        from app.crag_gate import CRAGGate
        from app.tools import extract_integration_signals, search_integration_kb
        
        # ADAPTIVE: If broad intent, search with preference for summaries
        query_type = "technical"
        if predicted_intent in [IntentType.GENERAL_INQUIRY, IntentType.SETUP_DISCOVERY]:
            query_type = "overview"
            print(f"[DEBUG] Adaptive Routing -> Prioritizing RAPTOR Summaries (Intent: {predicted_intent})")

        signals = extract_integration_signals(page_context)
        print(f"[DEBUG] Searching KB with signals: '{signals[:100]}...'")
        
        integration_id = page_context.get("integration_id")
        product_version = page_context.get("product_version")

        import time
        t_start = time.time()
        
        search_results_json = search_integration_kb(
            query=signals,
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=30, # SOTA: Overfetch for reranking
            integration_id=integration_id,
            product_version=product_version,
            skip_rerank=True # Stage 1: Hybrid Retrieval
        )
        t_search = (time.time() - t_start) * 1000
        
        from mcp_servers.analytics_server import log_latency_metrics
        log_latency_metrics("retrieval_stage_1", t_search)
        
        candidates = json.loads(search_results_json) if isinstance(search_results_json, str) else search_results_json
        
        # Stage 2: Cross-Encoder Reranking
        t_rerank_start = time.time()
        from app.tools import rerank_chunks
        results = rerank_chunks(signals, candidates, top_k=5)
        t_rerank = (time.time() - t_rerank_start) * 1000
        print(f"DEBUG: Retrieval Stage 2 (Rerank) Took: {t_rerank:.2f}ms")
        
        if results and len(results) > 0:
            top = results[0]
            crag_gate = CRAGGate()
            # Pass all 5 to CRAG for consensus-style quality check
            t_crag_start = time.time()
            crag_res = crag_gate.score_context(signals, results)
            t_crag = (time.time() - t_crag_start) * 1000
            print(f"DEBUG: Retrieval Stage 3 (CRAG) Took: {t_crag:.2f}ms")
            
            crag_status = crag_res["status"]
            crag_score = crag_res.get("score", 0.0)
            print(f"DEBUG: CRAG STATUS: {crag_status}, SCORE: {crag_score:.4f}")
            
            if crag_status in ["CORRECT", "AMBIGUOUS"]:
                article = {
                    "title": top.get("metadata", {}).get("title") or top.get("title") or "Guide",
                    "text": top.get("text", ""),
                    "article_id": top.get("metadata", {}).get("article_id") or top.get("article_id")
                }
                print(f"DEBUG: Selected Grounding Article: {article['title']} (ID: {article['article_id']})")
            
            if crag_status == "INCORRECT":
                print(f"DEBUG: CRAG status INCORRECT. Reporting gap to Analytics MCP.")
                from mcp_servers.analytics_server import report_retrieval_gap
                report_retrieval_gap(signals, integration_id or "unknown", product_version or "unknown")
                
                from mcp_servers.zendesk_server import get_article as mcp_get_article
                mcp_res = mcp_get_article(integration_id or signals)
                if mcp_res and "error" not in str(mcp_res).lower():
                    article = {"title": "Zendesk Live Article", "text": str(mcp_res), "article_id": "mcp-live"}
                    crag_status = "CORRECT (MCP)"
    except Exception as e:
        print(f"DEBUG: Adaptive Grounding Error: {e}")

    if article:
        article_content = article['text']
        if len(article_content) > 5500:
            article_content = article_content[:5000] + "\n... [Remaining Guide Truncated for brevity] ..."

        user_message += f"\n\n--- ADAPTIVE KNOWLEDGE CONTEXT ({crag_status}) ---\nTitle: {article['title']}\nContent: {article_content}\n---\n"
        article_meta = {
            "article_title": article.get("title"),
            "article_id": article.get("article_id")
        }

    # === STEP 2: PREDICTIVE HINTS (BLOCK 4) ===
    predictive_hint = PredictiveEngine.predict_next_step(page_context)
    
    # Avoid duplicate keyword arguments if extra already contains it
    screenshot_base64 = extra.pop("screenshot_base64", page_context.get("screenshot"))
    
    return _route_agent_loop(
        ai_provider=ai_provider,
        system_prompt=CONTEXTUAL_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        fallback_mode=fallback_mode,
        screenshot_base64=screenshot_base64,
        product_version=product_version,
        crag_status=crag_status,
        crag_score=crag_score,
        signals=signals,
        initial_article_meta=article_meta,
        predictive_hint=predictive_hint,
        **extra  # Properly spread extra params so ollama_model, openrouter_api_key etc. are visible
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
    mastery_score: float = 0.0,
    **extra,
) -> Dict[str, Any]:
    """Answer a user's question using the knowledge base via OpenRouter."""
    print(f"[DEBUG] qa_agent called. Provider: {ai_provider}")
    # Build context string (Mirrors contextual_help_agent for consistency)
    structure_context = []
    if page_context.get("page_title"): structure_context.append(f"Title: {page_context['page_title']}")
    if page_context.get("integration_id"): structure_context.append(f"Integration ID: {page_context['integration_id']}")
    
    # NEW: Active Modal Awareness
    if page_context.get("is_modal_open"):
        modal_info = f"ACTIVE MODAL DETECTED: {page_context.get('modal_title', 'Unknown Modal')}"
        print(f"DEBUG QA: Injecting Modal state into prompt: {modal_info}")
        structure_context.append(modal_info)

    if page_context.get("form_labels"):
        structure_context.append(f"Visible Fields: {', '.join(page_context['form_labels'])}")
    
    # Contextual Actions (Click stream)
    event_context = []
    if page_context.get("event_stream"):
        events = page_context["event_stream"][-7:] # Consistent with contextual_help_agent
        event_summaries = []
        for e in events:
            summary = f"{e.get('type').upper()}: "
            if e.get("type") == "click": summary += f"Target: {e.get('text', 'Unknown')}"
            elif e.get("type") == "focus": summary += f"Field: {e.get('label') or 'field'}"
            event_summaries.append(summary)
        if event_summaries:
            event_context.append("RECENT USER ACTIONS:\n- " + "\n- ".join(event_summaries))

    # Diagnostic Logs (Parity)
    diagnostic_context = []
    if page_context.get("logs"):
        logs = page_context["logs"][-10:] # Last 10
        for l in logs:
            diagnostic_context.append(f"{l.get('level', 'info').upper()}: {l.get('text', '')}")

    # Personalization (Parity)
    personalization_context = []
    if mastery_score > 0.8:
        personalization_context.append("NOTICE: User is highly experienced. Provide concise, expert-level advice.")

    context_str = "\n".join(structure_context)
    if event_context:
        context_str += "\n\n" + "\n".join(event_context)
    if diagnostic_context:
        context_str += "\n\n[DIAGNOSTIC LOGS]\n- " + "\n- ".join(diagnostic_context)
    if personalization_context:
        context_str += "\n\n[USER PERSONALIZATION]\n- " + "\n- ".join(personalization_context)

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

    screenshot_base64 = page_context.get("screenshot")

    user_message = (
        f"USER QUESTION: {question}\n\n"
        f"PAGE CONTEXT SUMMARY:\n{context_str}\n\n"
        f"USER MASTERY: {mastery_score:.2f} (0.0=Newbie, 1.0=Expert)\n"
    )
    
    # PROACTIVE KNOWLEDGE RETRIEVAL:
    # 1. Pinned Article ID lookup
    # 2. Integration ID lookup
    # 3. Fall back to multi-signal semantic match
    article_id_ctx = page_context.get("article_id")
    integration_id = page_context.get("integration_id")
    product_version = page_context.get("product_version")
    articles_path = articles_dir or Path("storage/processed/articles")
    article = None

    if article_id_ctx:
        from app.tools import get_article_by_id
        article = get_article_by_id(article_id_ctx, articles_path)
    elif integration_id:
        from app.tools import get_article_by_integration_id
        article = get_article_by_integration_id(integration_id, articles_path)

    if not article and (page_context.get("page_title") or page_context.get("headings")):
        from app.tools import search_integration_kb, extract_integration_signals
        composite_query = extract_integration_signals(page_context)
        print(f"DEBUG QA: Auto-matching integration guide: '{composite_query[:80]}...'")
        search_results = search_integration_kb(
            query=composite_query,
            api_key=api_key,
            persist_dir=persist_dir,
            integration_id=None,
            product_version=product_version,
            top_k=30, # Overfetch
            skip_rerank=True
        )
        try:
            candidates = json.loads(search_results) if isinstance(search_results, str) else search_results
            from app.tools import rerank_chunks
            from app.crag_gate import CRAGGate
            
            # Stage 2: Rerank
            results = rerank_chunks(composite_query, candidates, top_k=5)
            
            if results:
                # Stage 3: CRAG
                crag_gate = CRAGGate()
                crag_res = crag_gate.score_context(composite_query, results)
                top = results[0]
                
                if crag_res["status"] in ["CORRECT", "AMBIGUOUS"]:
                    article = {
                        "title": top["metadata"]["title"],
                        "text": top["text"],
                        "article_id": top["metadata"]["article_id"]
                    }
                    print(f"DEBUG QA: SOTA auto-matched guide: '{article['title']}' ({crag_res['status']})")
        except Exception as e:
            print(f"DEBUG QA: SOTA Guide match error: {e}")

    if article:
        # DEFENSIVE: Use get() with defaults to avoid KeyError match failures
        article_title = article.get("title") or "Integration Guide"
        article_text = article.get("text") or "Information not available."
        article_id = article.get("article_id") or "kb-000"
        
        user_message += f"\nRelevant Integration Guide found and attached for grounding:\n---\nTitle: {article_title} (ID: {article_id})\nContent: {article_text[:6000]}\n---\n"
        print(f"DEBUG: Grounding context successfully attached to user message (Length: {len(article_text)})")

    # Cognitive Synergy: Long-term Context Memory
    if page_context.get("mastery_context"):
        mc = page_context["mastery_context"]
        user_message += (
            f"\n[USER PERSONALIZATION MEMORY]\n"
            f"- Preferred Working Mode: {mc.get('role', 'expert')}\n"
            f"- Historical Mastery: {mc.get('mastery_level', 'novice')}\n"
            f"- Continuity Hint: User has collaborated on {mc.get('product_version', 'v14')} before.\n"
        )
    
    # Proactive Support Automation: Escalation Suggestion
    # If CRAG status from a previous attempt was INCORRECT, or we couldn't find an article,
    # we inject a hint to the LLM to offer ticket drafting.
    if not article:
        user_message += "\n\n### [CRITICAL MISSION: NO KNOWLEDGE BASE MATCH]\n"
        user_message += "I couldn't find a direct guide for this specific screen in our internal documentation. \n"
        user_message += "**YOUR TASK**: Use the 'PAGE CONTEXT' (DOM) and the 'SCREENSHOT' specifically to explain what this page is for and what the user should do. \n"
        user_message += "Identify the main headings, the input fields, and the action buttons. Describe the logical flow (e.g., 'You are in the setup phase for X. You need to provide Y and then click Z'). \n"
        user_message += "DO NOT start with an apology. Be proactive and helpful as if you are looking at the screen with the user.\n"

    user_message += history_str

    return _route_agent_loop(
        ai_provider=ai_provider,
        system_prompt=QA_SYSTEM_PROMPT,
        user_message=user_message,
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        fallback_mode=fallback_mode,
        screenshot_base64=screenshot_base64,
        product_version=product_version,
        **extra
    )


import traceback

def _route_agent_loop(
    ai_provider: str,
    system_prompt: str,
    user_message: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    fallback_mode: str = "gemini",
    initial_article_meta: Optional[Dict[str, Any]] = None,
    product_version: Optional[str] = None,
    crag_status: str = "NONE",
    predictive_hint: Optional[Dict[str, str]] = None,
    ghost_autocomplete: Optional[str] = None,
    **extra,
) -> Dict[str, Any]:
    """Route to the appropriate AI backend, with smart auto-fallback support."""
    print(f"[SYSTEM] Routing request. Provider: {ai_provider.upper()}, Fallback: {fallback_mode.upper()}")

    errors: list = []
    # Always try a fallback chain if fallback_mode is auto
    if ai_provider == "auto":
        providers_to_try = ["gemini", "openrouter", "nvidia", "claude_proxy", "ollama", "local_ai"]
    elif fallback_mode == "auto":
        # SOTA: Hard-prioritize working local proxy to avoid timeout delays from cloud fallbacks
        all_ordered = ["claude_proxy", "gemini", "openrouter", "nvidia", "ollama", "local_ai"]
        providers_to_try = [ai_provider]
        for p in all_ordered:
            if p not in providers_to_try:
                providers_to_try.append(p)
    else:
        providers_to_try = [ai_provider]

    # Filter out excluded providers if specified
    exclude = extra.get("exclude_providers", [])
    if exclude:
        providers_to_try = [p for p in providers_to_try if p not in exclude]

    print(f"[DEBUG] Final provider list: {providers_to_try}")

    for prov in providers_to_try:
        t_start = time.time()
        try:
            print(f"DEBUG: Attempting provider: {prov.upper()}...")
            result = None
            
            if prov == "gemini":
                if not api_key:
                    raise ValueError("Gemini API key missing")
                screenshot = extra.get("screenshot_base64")
                result = _run_gemini_agent_loop(
                    system_prompt, 
                    user_message, 
                    api_key, 
                    persist_dir, 
                    articles_dir, 
                    product_version,
                    initial_article_meta,
                    screenshot_base64=screenshot,
                    model_id=extra.get("gemini_model")
                )
            
            elif prov in ("openrouter", "openai"):
                or_key = extra.get("openrouter_api_key", "")
                if not or_key:
                    or_key = Config().OPENROUTER_API_KEY
                if not or_key:
                    raise ValueError("OpenRouter API key missing")
                or_model = extra.get("openrouter_model")
                if not or_model:
                    or_model = Config().OPENROUTER_MODEL
                or_site  = extra.get("openrouter_site_url", "http://localhost:8000")
                result = _run_openrouter_agent_loop(system_prompt, user_message, or_key, or_model, or_site, persist_dir, articles_dir, product_version, initial_article_meta)
            
            elif prov == "ollama":
                ollama_model = extra.get("ollama_model", "qwen2.5-coder:7b")
                result = _run_ollama_agent_loop(system_prompt, user_message, ollama_model, persist_dir, articles_dir, product_version, initial_article_meta)
            
            elif prov == "nvidia":
                nv_key = extra.get("nvidia_api_key", "")
                if not nv_key:
                    nv_key = Config().NVIDIA_API_KEY
                if not nv_key:
                    raise ValueError("NVIDIA API key missing")
                nv_model = extra.get("nvidia_model", "nvidia/llama-3.1-nemotron-70b-instruct")
                result = _run_nvidia_agent_loop(system_prompt, user_message, nv_key, nv_model, persist_dir, articles_dir, initial_article_meta)
            
            elif prov == "claude_proxy":
                proxy_url = Config().CLAUDE_PROXY_URL
                result = _run_claude_proxy_loop(system_prompt, user_message, proxy_url, persist_dir, articles_dir, initial_article_meta)
            
            elif prov == "local_ai":
                local_url = Config().LOCAL_AI_BASE_URL
                local_model = Config().LOCAL_AI_MODEL
                result = _run_local_ai_agent_loop(system_prompt, user_message, local_url, local_model, persist_dir, articles_dir, product_version, initial_article_meta)
            
            # CRITICAL: Validate result for error strings that didn't raise exceptions
            if result and isinstance(result, dict) and result.get("response"):
                txt = str(result["response"]).lower()
                # Check for various error indicators in the response text itself
                if any(x in txt for x in ["429", "resource_exhausted", "quota exceeded", "api error", "quota_reached", "safety_violation"]):
                    print(f"DEBUG: Provider {prov.upper()} returned an error response. Continuing fallback...")
                    errors.append(f"{prov}: {result['response']}")
                    continue
                
                # If we got a real response (not just the "I analyzed the page but..." fallback if we have other providers)
                if len(providers_to_try) > 1 and prov == providers_to_try[0] and result["response"].startswith("I analyzed the page but"):
                     print(f"DEBUG: Provider {prov.upper()} returned generic fallback. Trying next provider for better depth...")
                     continue
                
                # --- NEW: PARSE PROACTIVE ACTION SUGGESTIONS OUT OF THE RESPONSE ---
                text = result["response"]
                if "---ACTION_SUGGESTIONS_START---" in text:
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

                # CRITICAL: Strip any raw JSON tool call blocks or thinking artifacts 
                # that some models leak into the text even during tool iteration.
                if text:
                    # Remove blocks starting with {"name": or [{"name":
                    text = re.sub(r'\{\s*"name"\s*:.*?\}(?:\s*\}|)', '', text, flags=re.DOTALL)
                    text = re.sub(r'\[\s*\{\s*"name"\s*:.*?\}\s*\]', '', text, flags=re.DOTALL)
                    # Remove markdown code blocks containing json tool calls
                    text = re.sub(r'```(?:json|)\s*\{\s*"name"\s*:.*?\}\s*```', '', text, flags=re.DOTALL)
                    text = text.strip()
                    
                    if not text:
                        print(f"DEBUG: Provider {prov.upper()} output only tool calls/empty text. Continuing fallback...")
                        errors.append(f"{prov}: output only tool calls/empty text")
                        continue

                    result["response"] = text

                print(f"DEBUG: Provider {prov.upper()} succeeded.")
                if isinstance(result, dict):
                    result["crag_status"] = crag_status
                    if predictive_hint: result["predictive_hint"] = predictive_hint
                    if ghost_autocomplete: result["ghost_autocomplete"] = ghost_autocomplete
                return result

        except Exception as e:
            err_msg = str(e)
            print(f"DEBUG: Provider {prov.upper()} raised exception: {err_msg}")
            print(f"DEBUG TRACEBACK:\n{traceback.format_exc()}")
            errors.append(f"{prov}: {err_msg}")
            # Continue to next provider in loop

    # Final resort: Local LLM (llama-cpp-python) if available
    try:
        from app.local_ai import chat as local_chat, is_ready
        if is_ready():
            print("DEBUG: Using local fallback...")
            res = local_chat(system_prompt, user_message)
            if initial_article_meta:
                res.update(initial_article_meta)
            return res
    except Exception: pass

    res = {
        "response": (
            "### AI Services Temporarily Limited\n"
            "I analyzed your screen, but all configured AI providers (Gemini, OpenRouter, NVIDIA, etc.) are currently at their quota limits or experiencing issues.\n\n"
            "**Common fixes:**\n"
            "- Check your API keys and credit balance.\n"
            "- Wait a few minutes for rate limits to reset.\n"
            "- Switch to a local model like Ollama if available.\n\n"
            "*Technical details for admin:* " + "; ".join(errors)
        )
    }
    if initial_article_meta:
        res.update(initial_article_meta)
    return res


def _run_claude_proxy_loop(
    system_prompt: str,
    user_message: str,
    proxy_url: str,
    persist_dir: str,
    articles_dir: Path,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
) -> Dict[str, Any]:
    """Execute agent loop via locally running Claude Proxy."""
    from openai import OpenAI
    
    # The proxy acts as an OpenAI-compatible endpoint
    client = OpenAI(
        api_key="sk-ant-proxy-local", # Dummy key for proxy
        base_url=proxy_url
    )

    # Build tools
    tools = []
    for td in TOOL_DEFINITIONS:
        params = td.get("parameters", {})
        props = params.get("properties", {})
        tools.append({
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
        })

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    last_article_meta = initial_article_meta or {}
    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model="claude-sonnet-4", # Correct ID for your proxy
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto",
            temperature=0.0
        )
        msg = resp.choices[0].message
        
        if not msg.tool_calls:
            return {"response": _clean_agent_response(msg.content), **last_article_meta}

        messages.append(msg)
        for tc in msg.tool_calls:
            func_name = tc.function.name
            args = json.loads(tc.function.arguments)
            print(f"DEBUG: Claude Proxy Tool Call -> {func_name}({args})")

            try:
                # Use centralized execution to ensure correct arguments (API keys, dirs, etc)
                # Note: sk-ant-proxy-local is the dummy key for our local proxy
                tool_result = _execute_tool_call(
                    function_name=func_name,
                    function_args=args,
                    api_key="sk-ant-proxy-local", 
                    persist_dir=persist_dir,
                    articles_dir=articles_dir,
                )
                
                # Track metadata for grounding
                try:
                    res_data = json.loads(tool_result)
                    if isinstance(res_data, list) and len(res_data) > 0:
                        top = res_data[0]
                        last_article_meta = {
                            "article_title": top.get("metadata", {}).get("title") or top.get("title"),
                            "article_id": top.get("metadata", {}).get("article_id") or top.get("article_id")
                        }
                    elif isinstance(res_data, dict):
                        last_article_meta = {
                            "article_title": res_data.get("title"),
                            "article_id": res_data.get("article_id")
                        }
                except: pass
            except Exception as e:
                print(f"ERROR in Claude Proxy tool call: {e}")
                tool_result = json.dumps({"error": str(e)})

            messages.append({"role": "tool", "tool_call_id": tc.id, "name": func_name, "content": tool_result})

    return {"response": "I reached the maximum reasoning steps without a final answer via Claude Proxy.", **last_article_meta}


def _run_openrouter_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
    model: str,
    site_url: str,
    persist_dir: str,
    articles_dir: Path,
    product_version: Optional[str] = None,
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
    tokens_in: int = 0
    tokens_out: int = 0

    for _ in range(max_iterations):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.0,
            max_tokens=1000, # Limit to avoid 402/quota pressure
        )
        usage = resp.usage
        if usage:
            tokens_in  += int(usage.prompt_tokens or 0)
            tokens_out += int(usage.completion_tokens or 0)

        choice = resp.choices[0]
        msg = choice.message

        # No tool calls → final answer
        if not msg.tool_calls:
            text: str = msg.content or ""
            # CRITICAL: Universal JSON/thinking stripping
            clean_text = _clean_agent_response(text)
            
            result = {
                "response": clean_text,
                "tokens_in": int(tokens_in),
                "tokens_out": int(tokens_out),
                "tokens_total": int(int(tokens_in) + int(tokens_out)),
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

            result = _execute_tool_call(
                function_name=fn_name,
                function_args=fn_args,
                api_key=api_key,
                persist_dir=persist_dir,
                articles_dir=articles_dir,
                product_version=product_version,
            )

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

    return {
        "response": "Agent reached max iterations.", 
        "tokens_in": int(tokens_in), 
        "tokens_out": int(tokens_out), 
        "tokens_total": int(int(tokens_in) + int(tokens_out))
    }




def _run_gemini_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    product_version: Optional[str] = None,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    screenshot_base64: Optional[str] = None,
    max_iterations: int = 5,
    model_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Execute the agent loop using Gemini via Google GenAI SDK with automatic retries."""
    from app.llm_utils import retry_with_backoff

    @retry_with_backoff(retries=0, base_delay=0.5)
    def _run_loop(screenshot_b64=screenshot_base64):
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=api_key)
        target_model = model_id or Config().GEMINI_MODEL

        tools = _build_gemini_tools()

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=tools,
            temperature=0.0
        )
        search_confidence = 1.0 # Default to high if no search done
        chat = client.chats.create(model=target_model, config=config)
        
        # NEW: Inject Multimodal Screenshot Part if available
        if screenshot_b64:
            import base64
            print("DEBUG: Attaching screenshot to Gemini conversation context.")
            try:
                # Format is usually data:image/jpeg;base64,/9j/...
                if "," in screenshot_b64:
                    header, encoded = screenshot_b64.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]
                else:
                    encoded = screenshot_b64
                    mime_type = "image/jpeg" # fallback
                    
                image_bytes = base64.b64decode(encoded)
                screenshot_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                
                # Send text + image
                response = chat.send_message([user_message, screenshot_part])
            except Exception as e:
                print(f"WARNING: Failed to decode/attach screenshot: {e}")
                response = chat.send_message(user_message)
        else:
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
                    product_version=product_version,
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
        except Exception as e:
            err_msg = str(e)
            print(f"DEBUG: Gemini final text extraction failed: {err_msg}")
            final_text = f"Gemini API Error (429/Quota): {err_msg}"

        if not final_text:
            final_text = "I analyzed the page but couldn't deduce a specific help objective based on the visible elements."

        # === BLOCK 2: SELF-CORRECTION (BYPASSED for speed) ===
        corrected_text = final_text
        reasoning_log = "Self-correction bypassed for performance."
        
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
            "response": _clean_agent_response(corrected_text),
            "reasoning_log": reasoning_log,
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "tokens_total": int(tokens_in + tokens_out),
            "confidence": float(search_confidence),
        }
        if last_article_meta:
            res.update(last_article_meta)
            
        # SOTA: Propagate metadata from kwargs if present
        if kwargs.get("crag_status"):
            res["crag_status"] = kwargs["crag_status"]
        if kwargs.get("crag_score") is not None:
            res["crag_score"] = kwargs["crag_score"]
        if kwargs.get("signals"):
            res["signals"] = kwargs["signals"]
            
        return res

    return _run_loop()


def _run_local_ai_agent_loop(
    system_prompt: str,
    user_message: str,
    base_url: str,
    model_id: str,
    persist_dir: str,
    articles_dir: Path,
    product_version: Optional[str] = None,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Universal local OpenAI-compatible agent loop (LocalAI, vLLM, etc)."""
    return _run_openai_style_local_loop(
        system_prompt=system_prompt,
        user_message=user_message,
        base_url=base_url,
        model_id=model_id,
        api_key="local-ai",
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        product_version=product_version,
        initial_article_meta=initial_article_meta,
        max_iterations=max_iterations,
        provider_name="local_ai",
        **kwargs
    )


def _run_ollama_agent_loop(
    system_prompt: str,
    user_message: str,
    model_id: str,
    persist_dir: str,
    articles_dir: Path,
    product_version: Optional[str] = None,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Execute the agent loop using local Ollama via specialized OpenAI runner."""
    from config import Config
    base_url = f"{Config().OLLAMA_BASE_URL}/v1"
    return _run_openai_style_local_loop(
        system_prompt=system_prompt,
        user_message=user_message,
        base_url=base_url,
        model_id=model_id,
        api_key="ollama",
        persist_dir=persist_dir,
        articles_dir=articles_dir,
        product_version=product_version,
        initial_article_meta=initial_article_meta,
        max_iterations=max_iterations,
        provider_name="ollama",
        **kwargs
    )


def _run_openai_style_local_loop(
    system_prompt: str,
    user_message: str,
    base_url: str,
    model_id: str,
    api_key: str,
    persist_dir: str,
    articles_dir: Path,
    product_version: Optional[str] = None,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
    provider_name: str = "local",
    **kwargs
) -> Dict[str, Any]:
    """Shared implementation for any local OpenAI-compatible API."""
    import json
    from openai import OpenAI
    
    client = OpenAI(base_url=base_url, api_key=api_key)
    tools = _build_ollama_tools()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]

    last_article_meta = initial_article_meta or {}
    
    print(f"DEBUG: Starting {provider_name} agent loop with model: {model_id} at {base_url}")
    for i in range(max_iterations):
        print(f"DEBUG: {provider_name} iteration {i+1}/{max_iterations}...")
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                tools=tools,
                temperature=0.0
            )
        except Exception as e:
            print(f"DEBUG: {provider_name} client error: {str(e)}")
            raise
        
        message = response.choices[0].message
        
        # Filter out None content so OpenAI SDK doesn't complain
        msg_dict = {"role": "assistant", "content": message.content or ""}
        
        if not message.tool_calls:
            messages.append(msg_dict)
            break

        print(f"DEBUG: {provider_name} calling {len(message.tool_calls)} tools...")
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
            
            result = _execute_tool_call(
                function_name=fn_name,
                function_args=fn_args,
                api_key=api_key,
                persist_dir=persist_dir,
                articles_dir=articles_dir,
                product_version=product_version,
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
        content = m.get("content")
        if m.get("role") == "assistant" and content:
            content_str = str(content).strip()
            # If it looks like raw JSON tool call, skip it for the final text
            if content_str.startswith("{") and '"name"' in content_str:
                continue
            if content_str.startswith("[") and '"name"' in content_str:
                continue
                
            final_text = _clean_agent_response(content_str)
            if final_text:
                break

    if not final_text:
        print(f"DEBUG: Entering sensor-aware fallback. User Message length: {len(user_message)}")
        page_title = last_article_meta.get("article_title") or "this setup"
        final_text = f"I've analyzed your screen and I can see you are currently in the **{page_title}** view. "
        
        headings = re.findall(r"Headings: (.*?)\n", user_message)
        if headings:
             first_heading = headings[0].split(',')[0].strip()
             final_text += f"You are working specifically within the **{first_heading}** section. "
        
        labels = re.findall(r"Label: (.*?) \|", user_message)
        if labels:
             final_text += f"I see important fields here like **{', '.join([l.strip() for l in labels[:3]])}**. "
        
        buttons = re.findall(r"Buttons: (.*?)\n", user_message)
        if buttons:
             primary_btn = buttons[0].split(',')[0].strip()
             final_text += f"\n\n**Next Logical Step**: You likely need to fill in these credentials and then click the **{primary_btn}** button to proceed. "

        # SOTA Diagnostics Fallback (Robust extraction)
        # Matches formats like "[23:05:01] ERROR: something" or "FATAL: message"
        diag_errors = re.findall(r"(?:ERROR|FATAL|CRITICAL): (.*?)(?:\n|$)", user_message, re.IGNORECASE)
        if diag_errors:
             print(f"DEBUG: Fallback found {len(diag_errors)} errors in logs.")
             final_text += f"\n\n🚨 **Diagnostic Alert**: I found a system error in your browser logs: *\"{diag_errors[-1].strip()}\"*. This might be impacting your experience."

        final_text += "\n\nHow can I help you complete this integration setup?"

    res = {"response": final_text, "_provider": provider_name}
    if last_article_meta:
        res.update(last_article_meta)
    
    # Propagate SOTA metadata
    if kwargs.get("crag_status"): res["crag_status"] = kwargs["crag_status"]
    if kwargs.get("crag_score") is not None: res["crag_score"] = kwargs["crag_score"]
    if kwargs.get("signals"): res["signals"] = kwargs["signals"]
    
    return res


def _run_nvidia_agent_loop(
    system_prompt: str,
    user_message: str,
    api_key: str,
    model: str,
    persist_dir: str,
    articles_dir: Path,
    initial_article_meta: Optional[Dict[str, Any]] = None,
    max_iterations: int = 5,
) -> Optional[Dict[str, Any]]:
    """Execute the agent loop using NVIDIA NIM (OpenAI-compatible)."""
    print(f"DEBUG: Starting NVIDIA NIM Agent Loop with model: {model}")
    
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        last_article_meta = initial_article_meta or {}

        # For now, we perform a single high-fidelity completion.
        # NVIDIA NIM models are exceptionally good at following complex system prompts.
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=2048
        )

        text = response.choices[0].message.content
        if not text:
            return None

        # Clean the response using our universal hygiene layer
        clean_text = _clean_agent_response(text)
        
        return {"response": clean_text, "article_meta": last_article_meta}

    except Exception as e:
        print(f"[Nvidia] Agent Loop Error: {e}")
        return None


def proactive_analysis_agent(
    page_context: Dict[str, Any],
    ai_provider: str,
    api_key: str = "",
    persist_dir: str = "",
    articles_dir: Optional[Path] = None,
    fallback_mode: str = "gemini",
    **extra,
) -> Dict[str, Any]:
    """
    Perform a deep, KB-grounded proactive analysis of the current page.
    Returns a structured dictionary matching PageContextResponse requirements.
    """
    print(f"[DEBUG] proactive_analysis_agent called. Provider: {ai_provider}")
    
    # 1. Extraction of Search Signals
    page_type = page_context.get("page_type", "")
    page_heading = page_context.get("page_heading", "")
    modal_title = page_context.get("modal_title", "")
    breadcrumb = page_context.get("breadcrumb", "")
    
    query_parts = []
    if modal_title: 
        query_parts.append(f"modal {modal_title}")
    if breadcrumb: 
        query_parts.append(f"navigation {breadcrumb}")
    if page_heading: 
        query_parts.append(page_heading)
    if page_type: 
        query_parts.append(page_type.replace("_", " "))
    
    # Priority weighting: Modal/Navigation first
    composite_query = " ".join(query_parts) if query_parts else "Aquera integration setup"
    
    # 2. Knowledge Retrieval (RAG)
    articles_path = articles_dir or Path("storage/processed/articles")
    article = None
    
    from app.tools import search_integration_kb, search_general_kb, rerank_chunks, get_article_by_integration_id
    from app.crag_gate import CRAGGate
    
    # SOTA: Direct Mapping (Speed Fix)
    integration_id = page_context.get("integration_id")
    direct_article = None
    if integration_id:
        print(f"DEBUG PROACTIVE: Attempting direct mapping for {integration_id}")
        direct_article = get_article_by_integration_id(integration_id, articles_path)
    
    candidates = []
    if direct_article:
        print(f"DEBUG PROACTIVE: Found direct mapping for {integration_id}")
        candidates = [direct_article]
    else:
        # Try integration KB first, then general
        search_results = search_integration_kb(
            query=composite_query,
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=20,
            skip_rerank=True,
            integration_id=integration_id
        )
        try:
            candidates = json.loads(search_results) if isinstance(search_results, str) else search_results
        except: pass
    
    if not candidates: # Only fallback to general KB if no candidates were found from direct or integration KB
        # Fallback to general KB
        search_results = search_general_kb(
            query=composite_query,
            api_key=api_key,
            persist_dir=persist_dir,
            top_k=10,
            skip_rerank=True
        )
        try:
            candidates = json.loads(search_results) if isinstance(search_results, str) else search_results
        except: pass
        
    # Rerank & CRAG
    crag_status = "NONE"
    articles = []
    if candidates:
        results = rerank_chunks(composite_query, candidates, top_k=5)
        if results:
            crag_gate = CRAGGate()
            crag_res = crag_gate.score_context(composite_query, results)
            crag_status = crag_res["status"]
            
            # Take Top 3 for broader context if they aren't rejected
            if crag_status in ["CORRECT", "AMBIGUOUS"]:
                for res in results[:3]:
                    articles.append({
                        "title": res["metadata"].get("title", "Article"),
                        "text": res["text"]
                    })
                print(f"DEBUG PROACTIVE: Rooted analysis in {len(articles)} snippets. Status: {crag_status}")

    # NEW: GraphStore Grounding (Authority Fix)
    graph_context = []
    try:
        from app.graph_store import GraphStore
        from config import Config
        cfg = Config()
        graph_db_path = cfg.STORAGE_DIR / "graph_store.json"
        store = GraphStore(storage_path=str(graph_db_path))
        store.load()
        
        product_version = page_context.get("product_version")
        lookup_id = integration_id or product_version or "Aquera"
        rels = store.get_relationships_for_entity(lookup_id)
        if rels:
            graph_context.append(f"Identified Relational Context for {lookup_id}:")
            for r in rels[:5]:
                graph_context.append(f"- {r['type'].upper()} -> {r['target']}")
    except Exception as e:
        print(f"DEBUG PROACTIVE: GraphStore skip: {e}")

    # 3. System Prompt Construction
    is_conservative = not articles or crag_status in ["INCORRECT", "THRESHOLD_REJECTED"]
    
    if is_conservative:
        print(f"DEBUG PROACTIVE: Activating Conservative Mode. Status: {crag_status}")
        system_prompt = '''You are the Aquera AI Visual Co-Pilot. You are an expert in the Aquera Identity Management & Provisioning platform. 
IMPORTANT: No specific documentation found for this page. Stay strictly grounded in the visible interface and the Aquera domain.
Aquera handles SCIM, User Provisioning, Identity Syncing, and Application Integrations.

Your goal is to be authoritative and helpful based ONLY on the visible UI:
1. **Visual Summary**: Describe the visible interface (e.g., "This is the Installed Applications dashboard for managing your identity syncs"). Mention that this is a landing page for managing multiple items.
2. **Field Guide**: Provide specific guidance for visible fields using Aquera's terminology.
3. **Aquera Actions**: Suggest safe next steps common in Aquera (e.g., "Add new application", "Check sync logs", "View integration status").

Respond ONLY as valid JSON:
{
  "page_summary": "...",
  "field_hints": {"Field Label": "generic hint", ...},
  "quick_actions": ["Action 1", "Action 2"]
}
'''
    else:
        system_prompt = '''You are the Aquera AI Senior Technical Expert & Visual Co-Pilot. Your goal is to provide deep, authoritative, and proactive contextual help.

When a user opens a page, you analyze the context and provide:
1. **Expert Summary**: Explain what the page does and its role in the Aquera ecosystem. Do not be generic; offer insight into best practices or non-obvious setup tips and why they matter. (Aim for 3-5 high-quality sentences).
2. **Actionable Field Guide**: For each field or element found, provide a specific, professional hint. Explain *how* to fill it or *why* it is important, leveraging the retrieved Knowledge Base if available. 
3. **Strategic Quick Actions**: Suggest 3-4 savvy next steps the user should take to progress their setup or troubleshoot efficiently.

Respond ONLY as valid JSON with this exact structure:
{
  "page_summary": "...",
  "field_hints": {"Field Label": "expert hint text", ...},
  "quick_actions": ["Strategic Action 1", "Strategic Action 2", ...]
}
IMPORTANT: 
- DO NOT be lazy. Be descriptive and helpful.
- DO NOT output section headers like "Page Sections" or "AI Analysis" in the text values.
- DO NOT use the phrase "📍 You are on" or mention "Aquera Admin" headers.
- If context from the Knowledge Base is provided, prioritize specific details from those articles over general knowledge.
- Be specific to Aquera — mention SCIM, provisioning, integrations where relevant. 
- DO NOT APOLOGIZE if documentation is missing; use the field names to deduce purpose.
'''

    # 4. User Message Construction
    fields = page_context.get("fields", [])
    field_descriptions = "Fields visible on this page:\n" + "\n".join(
        f"  - {f.get('label', 'Unnamed Field')}{' (required)' if f.get('required') else ''}"
        for f in fields
    )
    
    grounding_content = ""
    if articles:
        grounding_content = "\nRELEVANT DOCUMENTATION SNIPPETS:\n---\n"
        for i, art in enumerate(articles):
            grounding_content += f"Snippet {i+1} (Source: {art['title']}):\n{art['text'][:2000]}\n\n"
        grounding_content += "---\n"
    
    if graph_context:
        grounding_content += "\nGRAPHSTORE RELATIONAL CONTEXT:\n---\n"
        grounding_content += "\n".join(graph_context) + "\n---\n"

    nearby_text = page_context.get("nearby_text", "")
    visual_clues = f"Nearby visible text on page:\n{nearby_text[:1000]}\n" if nearby_text else ""
    
    user_message = f"""Page Name: {modal_title or page_heading or page_type}
URL: {page_context.get('page_url')}
{visual_clues}
{field_descriptions}
{grounding_content}

Provide a structured proactive analysis for this page."""

    # 5. Route to LLM
    # SOTA: Fast-Path Fallback (Latency Fix). 
    # For proactive background help, DO NOT fall back to slow local models (Ollama).
    # If Gemini fails, it will return a 'failed' response which the UI handles with a clean retry state.
    print(f"DEBUG PROACTIVE: Final routing with 'fast-path' fallback mode.")
    analysis_result = _route_agent_loop(
        system_prompt=system_prompt,
        user_message=user_message,
        ai_provider="gemini", # Prefer Gemini
        api_key=api_key,
        persist_dir=persist_dir,
        articles_dir=articles_path,
        fallback_mode="auto", # Allow other cloud fallbacks
        crag_status=crag_status,
        gemini_model=Config().GEMINI_FLASH_LITE_MODEL,
        **extra
    )
    
    return {
        "analysis": analysis_result,
        "crag_status": crag_status,
        "grounding_count": len(articles)
    }
