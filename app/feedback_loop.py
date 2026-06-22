import json
from pathlib import Path
from typing import Dict

FEEDBACK_FILE = Path("storage/feedback.json")

def record_feedback(query: str, article_id: str, score: int):
    """
    Logs user feedback (e.g. clicks) to train the Learning-to-Rank system.
    Data format: { "search query": { "article_id": score } }
    """
    data = get_all_feedback()
    q = query.lower().strip()
    
    if q not in data:
        data[q] = {}
        
    data[q][article_id] = data[q].get(article_id, 0) + score
    
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_FILE.write_text(json.dumps(data, indent=2))

def get_all_feedback() -> Dict[str, Dict[str, int]]:
    """Reads the entire feedback database."""
    if FEEDBACK_FILE.exists():
        try:
            return json.loads(FEEDBACK_FILE.read_text())
        except Exception:
            return {}
    return {}

def get_boost_for_article(query: str, article_id: str) -> int:
    """Returns the historical score for a specific query-article pair."""
    data = get_all_feedback()
    q = query.lower().strip()
    return data.get(q, {}).get(article_id, 0)
