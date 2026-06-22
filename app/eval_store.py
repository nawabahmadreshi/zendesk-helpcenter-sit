import sqlite3
import json
import time
import hashlib
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict

@dataclass
class InteractionRecord:
    query: str
    user_id: str # anonymised SHA256 hash
    session_id: str = ""
    version: str = "v14" # 'v11' | 'v14'
    version_confidence: float = 0.0
    intent_class: str = "general" 
    retrieved_ids: List[str] = None # top-5 article IDs from reranker
    crag_status: str = "NONE" # CORRECT | AMBIGUOUS | UNVERIFIED
    crag_score: float = 0.0
    answer: str = ""
    retrieval_method: str = "hybrid" # vector, lexical, hybrid
    rating: Optional[int] = None # 1 (thumbs up) or -1 (thumbs down)
    implicit_close: Optional[bool] = None # closed panel < 5s = implicit negative
    latency_ms: Optional[int] = None
    # RAGAS Metrics (SOTA Polish)
    faithfulness: Optional[float] = None
    answer_relevance: Optional[float] = None
    context_precision: Optional[float] = None
    ts: float = 0.0

    def __post_init__(self):
        self.ts = time.time()
        # Anonymize user_id immediately
        self.user_id = hashlib.sha256(self.user_id.encode()).hexdigest()[:16]
        if self.retrieved_ids is None:
            self.retrieved_ids = []

class EvalStore:
    def __init__(self, db_path: str = 'eval.db'):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # SOTA: Enable WAL mode for high concurrency
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute('''CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, 
            user_id TEXT, 
            session_id TEXT, 
            version TEXT,
            version_confidence REAL, 
            intent_class TEXT,
            retrieved_ids TEXT, 
            crag_status TEXT, 
            crag_score REAL,
            query TEXT, 
            answer TEXT, 
            retrieval_method TEXT,
            rating INTEGER,
            implicit_close INTEGER, 
            latency_ms INTEGER,
            faithfulness REAL,
            relevance REAL,
            precision REAL
        )''')
        self.conn.commit()

    def log(self, rec: InteractionRecord):
        """Log a complete interaction to the evaluation store."""
        d = asdict(rec)
        # Serialize list of IDs
        d['retrieved_ids'] = json.dumps(d['retrieved_ids'])
        
        # Prepare values for insertion, skipping 'id' which is autoincrement
        columns = [
            'ts', 'user_id', 'session_id', 'version', 'version_confidence', 
            'intent_class', 'retrieved_ids', 'crag_status', 'crag_score', 
            'query', 'answer', 'retrieval_method', 'rating', 'implicit_close', 'latency_ms',
            'faithfulness', 'relevance', 'precision'
        ]
        values = [d.get(col) for col in columns]
        
        # Map RAGAS keys if they differ
        # (relevance vs answer_relevance, precision vs context_precision)
        # Actually our dataclass has faithfulness, answer_relevance, context_precision
        # DB has faithfulness, relevance, precision
        val_map = {
            'relevance': d.get('answer_relevance'),
            'precision': d.get('context_precision')
        }
        for i, col in enumerate(columns):
            if col in val_map:
                values[i] = val_map[col]

        placeholders = ','.join(['?'] * len(values))
        query = f"INSERT INTO interactions ({','.join(columns)}) VALUES ({placeholders})"
        
        cursor = self.conn.execute(query, values)
        self.conn.commit()
        return cursor.lastrowid
    
    def get_unrated_sample(self, n: int = 50) -> List[Dict]:
        """For RAGAS batch evaluation — sample recent unrated interactions."""
        self.conn.row_factory = sqlite3.Row
        rows = self.conn.execute(
            'SELECT * FROM interactions WHERE rating IS NULL ORDER BY ts DESC LIMIT ?', (n,)
        ).fetchall()
        return [dict(r) for r in rows]

    def deflection_rate(self, days: int = 7) -> float:
        """Calculate the percentage of queries resolved without requiring high-effort intervention."""
        cutoff = time.time() - days * 86400
        
        total_row = self.conn.execute(
            'SELECT COUNT(*) FROM interactions WHERE ts > ?', (cutoff,)
        ).fetchone()
        total = total_row[0] if total_row else 0
        
        # We define "unresolved" as anything marked UNVERIFIED by CRAG (low confidence)
        unverified_row = self.conn.execute(
            'SELECT COUNT(*) FROM interactions WHERE ts > ? AND crag_status = "UNVERIFIED"', 
            (cutoff,)
        ).fetchone()
        unverified = unverified_row[0] if unverified_row else 0
        
        if total == 0:
            return 100.0
            
        return round((1 - unverified / total) * 100, 1)

    def update_feedback(self, session_id: str, rating: int, implicit_close: bool = False):
        """Update an existing interaction with user feedback."""
        # Use simple update by session_id
        self.conn.execute(
            '''UPDATE interactions 
               SET rating = ?, implicit_close = ? 
               WHERE session_id = ?''',
            (rating, 1 if implicit_close else 0, session_id)
        )
        self.conn.commit()
