#!/usr/bin/env python3
"""
Robust End-to-End QA Test Suite (v2)
=======================================
All searches now go through the running server's HTTP API.
This avoids the ChromaDB exclusive-lock conflict that occurs when
two processes try to open the same persistent database simultaneously.

Suites:
  1. Hybrid Search Accuracy  (via /api/help/search)
  2. Semantic/HyDE Discovery (conceptual queries, no exact keywords)
  3. Self-RAG Safety Gate    (unit test — no server needed)
  4. Section Precision       (via /api/help/search)
  5. Performance Benchmarks  (latency of /api/help/search)
"""
import sys, time, json, requests
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path("/Users/nawabahmad/Desktop/Downloads 2/zendesk-inline-help-sync")
sys.path.insert(0, str(ROOT))
load_dotenv()

BASE_URL  = "http://localhost:8000"
TIMEOUT   = 90   # seconds — allows for HyDE + reranker cold-start

# ── ANSI colours ─────────────────────────────────────────────────────────
GREEN  = "\033[92m"; RED    = "\033[91m"; YELLOW = "\033[93m"
CYAN   = "\033[96m"; BOLD   = "\033[1m";  RESET  = "\033[0m"

def banner(t): 
    print(f"\n{BOLD}{CYAN}{'='*62}\n  {t}\n{'='*62}{RESET}\n")

def pass_lbl(): return f"{GREEN}✅ PASS{RESET}"
def fail_lbl(): return f"{RED}❌ FAIL{RESET}"
def warn_lbl(): return f"{YELLOW}⚠️  WARN{RESET}"

totals = {"passed": 0, "failed": 0, "warned": 0, "skipped": 0}

def rec(k): totals[k] += 1

# ── Server health check ───────────────────────────────────────────────────
def server_alive() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/", timeout=5)
        return r.status_code < 500
    except Exception:
        return False

def api_search(query: str, integration_id: str = "") -> dict:
    """Call the full hybrid search pipeline through the live server."""
    payload = {
        "question": query,
        "page_context": {
            "title": "QA Test",
            "url": f"{BASE_URL}/test",
            "integration_id": integration_id,
            "product_version": ""
        }
    }
    resp = requests.post(f"{BASE_URL}/api/help/search", json=payload, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()

# ── SUITE 1: Hybrid Search Accuracy ──────────────────────────────────────
HYBRID_CASES = [
    {"query": "ADP Workforce Now prerequisites",              "must_contain": "adp workforce now"},
    {"query": "Guest Account Management Setup Guide",         "must_contain": "guest account"},
    {"query": "BambooHR employees to Active Directory users", "must_contain": "bamboohr"},
    {"query": "Email Templates configuration",                "must_contain": "orchestration"},
    {"query": "Microsoft 365 service account setup",          "must_contain": "microsoft 365"},
    {"query": "Okta SAML integration prerequisites",          "must_contain": "okta"},
    {"query": "Dayforce employees to Active Directory",       "must_contain": "dayforce"},
    {"query": "GEP procurement connector setup",              "must_contain": "gep"},
]

def suite_hybrid(alive: bool):
    banner("SUITE 1 — Hybrid Search Accuracy (Full Pipeline)")
    if not alive:
        print(f"  {warn_lbl()}  Server not running — skipping (start with: python main.py)")
        for _ in HYBRID_CASES: rec("skipped")
        return

    hits1 = hits3 = 0
    for case in HYBRID_CASES:
        q, must = case["query"], case["must_contain"].lower()
        try:
            t0 = time.time()
            data = api_search(q)
            elapsed = time.time() - t0
            results = data.get("results", [])
            # Build ranked title list
            titles = [r.get("article_title", "").lower() for r in results[:3]]
            top = titles[0] if titles else ""
            rank1 = must in top
            rank3 = any(must in t for t in titles)

            if rank1:
                hits1 += 1; hits3 += 1; rec("passed")
                label = f"{pass_lbl()} @ Rank 1"
            elif rank3:
                hits3 += 1; rec("warned")
                label = f"{warn_lbl()} @ Rank 2/3"
            else:
                rec("failed")
                label = fail_lbl()

            print(f"  {label}  [{q[:52]}]  ({elapsed:.1f}s)")
            print(f"           Top: {top or '(no results)'}")
        except requests.exceptions.Timeout:
            rec("warned")
            print(f"  {warn_lbl()}  [{q}] — TIMEOUT (>{TIMEOUT}s)")
        except Exception as e:
            rec("failed")
            print(f"  {fail_lbl()}  [{q}] — {e}")

    print(f"\n  Hit@1 = {hits1}/{len(HYBRID_CASES)}   Hit@3 = {hits3}/{len(HYBRID_CASES)}")

# ── SUITE 2: Semantic / HyDE Conceptual Discovery ────────────────────────
SEMANTIC_CASES = [
    {"query": "way to bring in new employees",                "must_contain": "onboard"},
    {"query": "connect HR system to identity provider",       "must_contain": "connector"},
    {"query": "single sign-on setup",                         "must_contain": "okta"},
    {"query": "employee directory sync to cloud",             "must_contain": "active directory"},
    {"query": "automate user provisioning from payroll",      "must_contain": "integration"},
]

def suite_semantic(alive: bool):
    banner("SUITE 2 — Semantic / HyDE Conceptual Discovery")
    if not alive:
        print(f"  {warn_lbl()}  Server not running — skipping")
        for _ in SEMANTIC_CASES: rec("skipped")
        return

    for case in SEMANTIC_CASES:
        q, must = case["query"], case["must_contain"].lower()
        try:
            t0 = time.time()
            data = api_search(q)
            elapsed = time.time() - t0
            results = data.get("results", [])
            titles = [r.get("article_title", "").lower() for r in results[:3]]
            # Also check chunk text for semantic matches
            chunks = [r.get("chunk_text", "").lower() for r in results[:3]]
            hit = any(must in t for t in titles) or any(must in c for c in chunks)
            label = pass_lbl() if hit else fail_lbl()
            rec("passed" if hit else "failed")
            top = titles[0] if titles else "(no results)"
            print(f"  {label}  [{q[:52]}]  ({elapsed:.1f}s)")
            print(f"           Top: {top}")
        except requests.exceptions.Timeout:
            rec("warned")
            print(f"  {warn_lbl()}  [{q}] — TIMEOUT (>{TIMEOUT}s)")
        except Exception as e:
            rec("failed")
            print(f"  {fail_lbl()}  [{q}] — {e}")

# ── SUITE 3: Self-RAG Safety Gate (unit test — no server needed) ──────────
def suite_self_rag():
    banner("SUITE 3 — Self-RAG Safety Gate (Unit Tests)")
    from app.agent import _clean_agent_response

    cases = [
        {
            "name": "Hallucination-Risk response is BLOCKED",
            "input": "[Critique: Hallucination-Risk] The docs don't say, but typically you would...",
            "check": lambda o: "hallucination" in o.lower() or "definitive answer" in o.lower(),
        },
        {
            "name": "Relevant critique token is STRIPPED cleanly",
            "input": "[Critique: Relevant] The Client ID is found under Settings > API Access.",
            "check": lambda o: "[Critique:" not in o and "Client ID" in o,
        },
        {
            "name": "Supported critique token is STRIPPED cleanly",
            "input": "[Critique: Supported] Navigate to Settings, then click API Keys.",
            "check": lambda o: "[Critique:" not in o and "Settings" in o,
        },
        {
            "name": "Thinking tags are STRIPPED",
            "input": "<thinking>Let me reason...</thinking>Here is the answer.",
            "check": lambda o: "<thinking>" not in o and "Here is the answer" in o,
        },
    ]

    for c in cases:
        cleaned = _clean_agent_response(c["input"])
        ok = c["check"](cleaned)
        label = pass_lbl() if ok else fail_lbl()
        rec("passed" if ok else "failed")
        print(f"  {label}  {c['name']}")
        print(f"           Output: {cleaned[:80]}")

# ── SUITE 4: Section Precision ────────────────────────────────────────────
SECTION_CASES = [
    {"query": "Email Templates",          "must_in_chunk": "email"},
    {"query": "ADP Workforce Now prereq", "must_in_chunk": "prerequisite"},
    {"query": "OAuth authentication",     "must_in_chunk": "oauth"},
]

def suite_section_precision(alive: bool):
    banner("SUITE 4 — Section Precision (Correct Section Extracted)")
    if not alive:
        print(f"  {warn_lbl()}  Server not running — skipping")
        for _ in SECTION_CASES: rec("skipped")
        return

    for case in SECTION_CASES:
        q, must = case["query"], case["must_in_chunk"].lower()
        try:
            data = api_search(q)
            results = data.get("results", [])
            top_chunk = results[0].get("chunk_text", "").lower() if results else ""
            top_section = results[0].get("section", "").lower() if results else ""
            hit = must in top_chunk or must in top_section
            label = pass_lbl() if hit else warn_lbl()
            rec("passed" if hit else "warned")
            # Show the SECTION header if present
            sec_preview = ""
            for line in top_chunk.split("\n"):
                if "section:" in line.lower():
                    sec_preview = line.strip()
                    break
            print(f"  {label}  [{q}]")
            print(f"           Section: {sec_preview or top_chunk[:60] + '...'}")
        except Exception as e:
            rec("failed")
            print(f"  {fail_lbl()}  [{q}] — {e}")

# ── SUITE 5: Performance Benchmarks ──────────────────────────────────────
PERF_LIMIT = 15.0   # seconds — realistic for HyDE + reranker first call
PERF_QUERIES = [
    "Email Templates",
    "ADP Workforce Now prerequisites",
    "Guest Account Management",
]

def suite_performance(alive: bool):
    banner("SUITE 5 — Performance Benchmarks (via HTTP API)")
    if not alive:
        print(f"  {warn_lbl()}  Server not running — skipping")
        for _ in PERF_QUERIES: rec("skipped")
        return

    for q in PERF_QUERIES:
        try:
            t0 = time.time()
            api_search(q)
            elapsed = time.time() - t0
            ok = elapsed < PERF_LIMIT
            label = pass_lbl() if ok else warn_lbl()
            rec("passed" if ok else "warned")
            speed = f"{elapsed:.2f}s" + (" 🚀" if ok else " 🐢")
            print(f"  {label}  [{q}]  {speed}")
        except Exception as e:
            rec("failed")
            print(f"  {fail_lbl()}  [{q}] — {e}")

# ── MAIN ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n{BOLD}{'='*62}")
    print("  AQUERA AI — ROBUST QA TEST SUITE v2")
    print("  Pipeline: Hybrid(BM25+Vector) + HyDE + RAPTOR + Self-RAG")
    print(f"{'='*62}{RESET}")

    alive = server_alive()
    status = f"{GREEN}ONLINE{RESET}" if alive else f"{RED}OFFLINE{RESET}"
    print(f"\n  Server status: {status} ({BASE_URL})")
    if not alive:
        print(f"  {YELLOW}TIP: Start the server with `python main.py` for full test coverage.{RESET}")

    suite_hybrid(alive)
    suite_semantic(alive)
    suite_self_rag()
    suite_section_precision(alive)
    suite_performance(alive)

    banner("FINAL RESULTS")
    t = sum(totals.values())
    p, f, w, s = totals["passed"], totals["failed"], totals["warned"], totals["skipped"]
    rate = (p / (t - s) * 100) if (t - s) > 0 else 0

    print(f"  Total tests   : {t}")
    print(f"  {GREEN}Passed        : {p}{RESET}")
    print(f"  {YELLOW}Warnings      : {w}{RESET}")
    print(f"  {RED}Failed        : {f}{RESET}")
    print(f"  Skipped       : {s}  (server offline)")
    print(f"  {BOLD}Pass Rate     : {rate:.1f}%  (excl. skipped){RESET}")
    print()

    if rate >= 80:
        print(f"  {GREEN}{BOLD}🎉  EXCELLENT — Pipeline is healthy and robust!{RESET}")
    elif rate >= 60:
        print(f"  {YELLOW}{BOLD}⚠️   ACCEPTABLE — Some improvements still needed.{RESET}")
    else:
        print(f"  {RED}{BOLD}🚨  CRITICAL — Pipeline needs attention!{RESET}")
    print()
