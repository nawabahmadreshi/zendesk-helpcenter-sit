"""Lightweight analytics event store backed by SQLite.

Events are stored at `storage/analytics.db`.
Each AI interaction is logged with full token usage, latency, and article metadata.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional


_DB_PATH: Optional[Path] = None


def init_db(db_path: Path) -> None:
    global _DB_PATH
    _DB_PATH = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            REAL    NOT NULL,
                agent         TEXT    NOT NULL,            -- 'contextual' | 'qa'
                integration_id TEXT,
                question      TEXT,
                response_len  INTEGER DEFAULT 0,
                article_id    TEXT,
                article_title TEXT,
                latency_ms    REAL    DEFAULT 0,
                page_title    TEXT,
                tokens_in     INTEGER DEFAULT 0,
                tokens_out    INTEGER DEFAULT 0,
                tokens_total  INTEGER DEFAULT 0,
                status        TEXT    DEFAULT 'ok',
                confidence    REAL    DEFAULT 0.0,         -- AI confidence score (0.0 - 1.0)
                feedback      INTEGER DEFAULT 0,           -- -1 (down), 0 (none), 1 (up)
                provider      TEXT,
                component_id  TEXT,
                crag_status   TEXT
            )
        """)
        # Migrate: add token columns if DB existed before this version
        for col, typedef in [
            ("tokens_in",  "INTEGER DEFAULT 0"),
            ("tokens_out", "INTEGER DEFAULT 0"),
            ("tokens_total","INTEGER DEFAULT 0"),
            ("confidence", "REAL DEFAULT 0.0"),
            ("feedback",   "INTEGER DEFAULT 0"),
            ("provider",   "TEXT"),
            ("component_id", "TEXT"),
            ("crag_status",  "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE events ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # column already exists

        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_agent ON events(agent)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_integration ON events(integration_id)")


@contextmanager
def _connect() -> Generator[sqlite3.Connection, None, None]:
    assert _DB_PATH is not None, "analytics.init_db() not called"
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class Analytics:
    """Wrapper for analytics functions for class-based use in ai_server."""
    def init_db(self, db_path: Path):
        return init_db(db_path)

    def log_event(self, agent, **kwargs):
        return log_event(agent, **kwargs)
    
    def log_feedback(self, event_id: int, score: int):
        return log_feedback(event_id, score)

    def get_summary(self, days: int = 30):
        return get_summary(days)

def log_event(
    agent: str,
    *,
    integration_id: str = "",
    question: str = "",
    response_len: int = 0,
    article_id: str = "",
    article_title: str = "",
    latency_ms: float = 0.0,
    page_title: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_total: int = 0,
    status: str = "ok",
    confidence: float = 0.0,
    provider: str = "",
    component_id: str = "",
    crag_status: str = "",
) -> None:
    if _DB_PATH is None:
        return
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO events
                   (ts, agent, integration_id, question, response_len,
                    article_id, article_title, latency_ms, page_title,
                    tokens_in, tokens_out, tokens_total, status, confidence,
                    provider, component_id, crag_status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    time.time(),
                    agent,
                    integration_id or None,
                    (question or "")[:500],
                    response_len,
                    article_id or None,
                    article_title or None,
                    latency_ms,
                    page_title or None,
                    tokens_in,
                    tokens_out,
                    tokens_total or (tokens_in + tokens_out),
                    status,
                    confidence,
                    provider,
                    component_id,
                    crag_status,
                ),
            )
    except Exception as e:
        print(f"ANALYTICS ERROR: Failed to log event: {e}")


def log_feedback(event_id: int, score: int) -> bool:
    """Submit user feedback for a specific event (-1, 0, 1)."""
    if _DB_PATH is None:
        return False
    try:
        with _connect() as conn:
            conn.execute(
                "UPDATE events SET feedback = ? WHERE id = ?",
                (score, event_id)
            )
            return True
    except Exception as e:
        print(f"ANALYTICS ERROR: Failed to log feedback: {e}")
        return False


def get_summary(days: int = 30) -> dict:
    if _DB_PATH is None or not _DB_PATH.exists():
        return _empty_summary()

    since = time.time() - days * 86400

    with _connect() as conn:
        # Totals
        row = conn.execute(
            """SELECT COUNT(*) as total, AVG(latency_ms) as avg_lat,
                      SUM(tokens_in) as sum_in, SUM(tokens_out) as sum_out,
                      SUM(tokens_total) as sum_total
               FROM events WHERE ts >= ?""",
            (since,),
        ).fetchone()
        total = row["total"] or 0
        avg_lat = round(row["avg_lat"] or 0, 1)
        tokens_in_total = row["sum_in"] or 0
        tokens_out_total = row["sum_out"] or 0
        tokens_grand = row["sum_total"] or 0

        # By agent
        agent_rows = conn.execute(
            """SELECT agent, COUNT(*) as cnt,
                      SUM(tokens_in) as t_in, SUM(tokens_out) as t_out, SUM(tokens_total) as t_total
               FROM events WHERE ts >= ? GROUP BY agent""",
            (since,),
        ).fetchall()
        by_agent = {r["agent"]: {
            "count": r["cnt"],
            "tokens_in": r["t_in"] or 0,
            "tokens_out": r["t_out"] or 0,
            "tokens_total": r["t_total"] or 0,
        } for r in agent_rows}

        # Errors
        err = conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE ts >= ? AND status='error'", (since,)
        ).fetchone()["cnt"] or 0

        # Top integrations
        top_integrations = [
            {"integration_id": r["integration_id"], "count": r["cnt"],
             "tokens_total": r["t"] or 0}
            for r in conn.execute(
                """SELECT integration_id, COUNT(*) as cnt, SUM(tokens_total) as t
                   FROM events WHERE ts >= ? AND integration_id IS NOT NULL
                   GROUP BY integration_id ORDER BY cnt DESC LIMIT 10""",
                (since,),
            ).fetchall()
        ]

        # Top articles
        top_articles = [
            {"article_id": r["article_id"], "title": r["article_title"],
             "count": r["cnt"], "tokens_total": r["t"] or 0}
            for r in conn.execute(
                """SELECT article_id, article_title, COUNT(*) as cnt, SUM(tokens_total) as t
                   FROM events WHERE ts >= ? AND article_id IS NOT NULL
                   GROUP BY article_id ORDER BY cnt DESC LIMIT 10""",
                (since,),
            ).fetchall()
        ]

        # Daily queries + tokens
        daily = conn.execute(
            """SELECT strftime('%Y-%m-%d', datetime(ts,'unixepoch')) as day,
                      COUNT(*) as cnt, SUM(tokens_total) as t
               FROM events WHERE ts >= ?
               GROUP BY day ORDER BY day""",
            (since,),
        ).fetchall()
        queries_per_day = [{"day": r["day"], "count": r["cnt"], "tokens": r["t"] or 0}
                           for r in daily]

        # Hourly (last 24 h)
        since_24h = time.time() - 86400
        hourly = conn.execute(
            """SELECT strftime('%H:00', datetime(ts,'unixepoch')) as hour,
                      COUNT(*) as cnt, SUM(tokens_total) as t
               FROM events WHERE ts >= ?
               GROUP BY hour ORDER BY hour""",
            (since_24h,),
        ).fetchall()
        queries_per_hour = [{"hour": r["hour"], "count": r["cnt"], "tokens": r["t"] or 0}
                            for r in hourly]

        # Token usage per day (last 30 d)
        token_per_day = [
            {
                "day": r["day"],
                "tokens_in": r["tin"] or 0,
                "tokens_out": r["tout"] or 0,
                "tokens_total": r["t"] or 0
            }
            for r in conn.execute(
                """SELECT strftime('%Y-%m-%d', datetime(ts,'unixepoch')) as day,
                          SUM(tokens_in) as tin, SUM(tokens_out) as tout, SUM(tokens_total) as t
                   FROM events WHERE ts >= ? GROUP BY day ORDER BY day""",
                (since,),
            ).fetchall()
        ]

        # Recent events (last 20)
        recent = [
            {
                "ts": r["ts"], "agent": r["agent"],
                "integration_id": r["integration_id"],
                "question": r["question"],
                "article_title": r["article_title"],
                "latency_ms": r["latency_ms"],
                "page_title": r["page_title"],
                "tokens_in": r["tokens_in"] or 0,
                "tokens_out": r["tokens_out"] or 0,
                "tokens_total": r["tokens_total"] or 0,
                "status": r["status"],
            }
            for r in conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT 20"
            ).fetchall()
        ]

    return {
        "period_days": days,
        "total_queries": total,
        "avg_latency_ms": avg_lat,
        "errors": err,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "tokens_grand_total": tokens_grand,
        "by_agent": by_agent,
        "top_integrations": top_integrations,
        "top_articles": top_articles,
        "queries_per_day": queries_per_day,
        "queries_per_hour": queries_per_hour,
        "token_per_day": token_per_day,
        "recent_events": recent,
    }


def _empty_summary() -> dict:
    return {
        "period_days": 30, "total_queries": 0, "avg_latency_ms": 0, "errors": 0,
        "tokens_in_total": 0, "tokens_out_total": 0, "tokens_grand_total": 0,
        "by_agent": {}, "top_integrations": [], "top_articles": [],
        "queries_per_day": [], "queries_per_hour": [], "token_per_day": [],
        "recent_events": [],
    }
