"""Autonomous Discovery Agent (Agent 4).

Analyzes interaction history from analytics.db to identify knowledge gaps, 
missing documentation, or poor-performing integration mappings.
"""

from __future__ import annotations

import collections
from typing import List, Dict, Any, Optional
from pathlib import Path

from config import Config
from google import genai
from app import analytics

class DiscoveryAgent:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)

    def analyze_gaps(self, days: int = 7) -> Dict[str, Any]:
        """Query analytics and generate a Knowledge Gap Report."""
        summary = analytics.get_summary(days=days)
        events = summary.get("recent_events", [])
        
        # Filter for "Low Quality" signals:
        # 1. Negative feedback
        # 2. Low confidence (< 0.4)
        # 3. Explicit error status
        failures = []
        for e in events:
            is_fail = (
                e.get("feedback") == -1 or 
                e.get("confidence", 1.0) < 0.4 or 
                e.get("status") == "error"
            )
            if is_fail:
                failures.append({
                    "question": e.get("question"),
                    "page": e.get("page_title"),
                    "integration": e.get("integration_id"),
                    "feedback": e.get("feedback"),
                    "confidence": e.get("confidence")
                })

        if not failures:
            return {"ok": True, "message": "No significant knowledge gaps identified in the recent period."}

        # Cluster failures by topic using Gemini/fallback
        from app.llm_utils import run_simple_llm_call
        try:
            prompt = (
                f"You are the Aquera AI Knowledge Architect. I will provide a list of search failures "
                f"or low-confidence user queries. Your task is to analyze these and identify "
                f"recurring patterns or specific gaps in our knowledge base.\n\n"
                f"FAILURES:\n{failures}\n\n"
                f"Generate a Knowledge Gap Report with:\n"
                f"1. **Summary of Gaps**: What common topics are users asking about that we can't answer?\n"
                f"2. **Specific Recommendations**: What 3-5 new Zendesk articles should be created?\n"
                f"3. **Integration Mappings**: Are there specific integration IDs that are consistently failing?\n\n"
                f"Report Format: Markdown"
            )
            
            report_text = run_simple_llm_call(
                prompt=prompt,
                system_instruction="You are a Knowledge Management Architect.",
                max_tokens=1000
            )
            
            return {
                "ok": True,
                "failure_count": len(failures),
                "report": report_text,
                "raw_failures": failures[:10]
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

def run_periodic_discovery():
    """CLI entry point for background discovery jobs."""
    cfg = Config()
    if not cfg.GEMINI_API_KEY:
        print("Discovery Error: No API Key")
        return
        
    discovery = DiscoveryAgent(cfg.GEMINI_API_KEY)
    report = discovery.analyze_gaps()
    print("--- AUTOMATED DISCOVERY REPORT ---")
    if report.get("ok"):
        print(report.get("report"))
    else:
        print(f"Error: {report.get('error')}")

if __name__ == "__main__":
    run_periodic_discovery()
