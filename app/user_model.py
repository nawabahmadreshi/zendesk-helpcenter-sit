import sqlite3
import os
import json
from datetime import datetime
from pathlib import Path

class UserModel:
    """
    Tracks user interactions and calculates "Mastery Scores" for UI components.
    Uses SQLite for persistence.
    """
    def __init__(self, db_path: str = "storage/user_model.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interaction_scores (
                    user_id TEXT,
                    component_id TEXT,
                    interaction_count INTEGER DEFAULT 0,
                    last_interaction TIMESTAMP,
                    mastery_score REAL DEFAULT 0.0,
                    PRIMARY KEY (user_id, component_id)
                )
            """)
            conn.commit()

    def record_interaction(self, user_id: str, component_id: str):
        """Increments interaction count and updates mastery score."""
        with sqlite3.connect(self.db_path) as conn:
            # 1. Update counts
            conn.execute("""
                INSERT INTO interaction_scores (user_id, component_id, interaction_count, last_interaction)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(user_id, component_id) DO UPDATE SET
                    interaction_count = interaction_count + 1,
                    last_interaction = excluded.last_interaction
            """, (user_id, component_id, datetime.now().isoformat()))
            
            # 2. Re-calculate mastery (10 interactions = 100%)
            conn.execute("""
                UPDATE interaction_scores
                SET mastery_score = MIN(1.0, interaction_count / 10.0)
                WHERE user_id = ? AND component_id = ?
            """, (user_id, component_id))
            conn.commit()

    def record_feedback(self, user_id: str, component_id: str, is_helpful: bool):
        """Adjusts mastery score based on explicit 'Not Helpful' signals."""
        with sqlite3.connect(self.db_path) as conn:
            if not is_helpful:
                # If NOT helpful, penalize mastery (maybe user isn't a master or advice was wrong)
                conn.execute("""
                    UPDATE interaction_scores
                    SET mastery_score = MAX(0.0, mastery_score - 0.2)
                    WHERE user_id = ? AND component_id = ?
                """, (user_id, component_id))
            else:
                # If helpful, boost mastery faster
                conn.execute("""
                    UPDATE interaction_scores
                    SET mastery_score = MIN(1.0, mastery_score + 0.1)
                    WHERE user_id = ? AND component_id = ?
                """, (user_id, component_id))
            conn.commit()

    def get_mastery(self, user_id: str, component_id: str) -> float:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT mastery_score FROM interaction_scores WHERE user_id = ? AND component_id = ?", (user_id, component_id))
            row = cursor.fetchone()
            return row[0] if row else 0.0

    def get_all_mastery(self, user_id: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT component_id, mastery_score FROM interaction_scores WHERE user_id = ?", (user_id,))
            return {row[0]: row[1] for row in cursor.fetchall()}
