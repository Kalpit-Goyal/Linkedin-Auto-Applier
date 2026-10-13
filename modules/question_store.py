'''
Question-Answer Store for LinkedIn Easy Apply questions.

Uses SQLite for concurrent access safety and atomic writes.
Schema:
  CREATE TABLE IF NOT EXISTS qa(
    id INTEGER PRIMARY KEY, q_norm TEXT, q_raw TEXT, qtype TEXT, options_hash TEXT,
    answer TEXT, source TEXT, status TEXT DEFAULT 'pending',   -- pending/approved/rejected
    times_seen INT DEFAULT 1, last_job_id TEXT, created_at TEXT, updated_at TEXT,
    UNIQUE(q_norm, qtype, options_hash));
'''

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_STORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "questions_db")
_STORE_FILE = os.path.join(_STORE_DIR, "saved_questions.db")
_LEGACY_FILE = os.path.join(_STORE_DIR, "saved_questions.json")


# ---------------------------------------------------------------------------
# Text normalisation for similarity comparison
# ---------------------------------------------------------------------------

# Common words to strip when comparing questions
_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "to", "of",
    "in", "for", "on", "with", "at", "by", "from", "as", "into", "about",
    "this", "that", "it", "its", "i", "you", "your", "we", "our", "they",
    "their", "he", "she", "his", "her", "my", "me", "us", "them",
})

# Generic words that carry no discriminative signal (from answering.py)
_GENERIC = {
    "years", "experience", "work", "working", "many", "much", "how", "long",
    "what", "is", "your", "the", "in", "with", "for", "of", "to", "a", "an",
    "and", "or", "you", "have", "do", "does", "did", "can", "will", "would",
    "could", "should", "may", "might", "must", "need", "want", "please",
    "enter", "provide", "specify", "select", "choose", "option", "field",
    "question", "answer", "required", "optional", "this", "that", "it",
    "its", "our", "their", "my", "me", "us", "them", "he", "she", "his",
    "her", "we", "i",
}


def _normalise(text: str) -> str:
    """
    Lower-case, strip accents, remove punctuation/spaces, sort tokens.
    Returns a canonical form for fuzzy matching.
    """
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in _STOP_WORDS]
    tokens.sort()
    return " ".join(tokens)


def _token_set(text: str) -> set[str]:
    """Return the set of meaningful tokens from a question string."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if t and t not in _STOP_WORDS}


def similarity(a: str, b: str) -> float:
    """
    Jaccard-like similarity between two question strings.
    Returns a value in [0.0, 1.0] where 1.0 is a perfect match.
    """
    sa = _token_set(a)
    sb = _token_set(b)
    if not sa or not sb:
        return 0.0
    intersection = sa & sb
    union = sa | sb
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Database connection and schema
# ---------------------------------------------------------------------------

def _ensure_dir():
    os.makedirs(_STORE_DIR, exist_ok=True)


def _get_conn() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    _ensure_dir()
    conn = sqlite3.connect(_STORE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Initialize the database schema."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS qa(
                id INTEGER PRIMARY KEY,
                q_norm TEXT,
                q_raw TEXT,
                qtype TEXT,
                options_hash TEXT,
                answer TEXT,
                source TEXT,
                status TEXT DEFAULT 'pending',
                times_seen INT DEFAULT 1,
                last_job_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                UNIQUE(q_norm, qtype, options_hash)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_norm_type ON qa(q_norm, qtype)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qa_status ON qa(status)")
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrate_from_json():
    """One-time migration from the old JSON file to SQLite."""
    if not os.path.exists(_LEGACY_FILE):
        return
    try:
        with open(_LEGACY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        questions = data.get("questions", [])
        if not questions:
            return
        conn = _get_conn()
        try:
            for entry in questions:
                q_raw = entry.get("question", "").strip()
                if not q_raw:
                    continue
                q_norm = _normalise(q_raw)
                qtype = entry.get("question_type", "text")
                answer = entry.get("answer", "")
                source = entry.get("source", "migrated")
                approved = entry.get("approved", False)
                status = "approved" if approved else "pending"
                created_at = entry.get("created_at", _now_iso())
                updated_at = entry.get("updated_at", _now_iso())
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO qa
                        (q_norm, q_raw, qtype, options_hash, answer, source, status, times_seen, created_at, updated_at)
                        VALUES (?, ?, ?, '', ?, ?, ?, 1, ?, ?)
                    """, (q_norm, q_raw, qtype, answer, source, status, created_at, updated_at))
                except Exception:
                    pass
            conn.commit()
            # Rename the old file as backup
            os.rename(_LEGACY_FILE, _LEGACY_FILE + ".bak")
        finally:
            conn.close()
    except Exception:
        # Migration failed silently - the old file remains
        pass


# Initialize on import
_init_db()
_migrate_from_json()


# ---------------------------------------------------------------------------
# Public API (same function names as before for compatibility)
# ---------------------------------------------------------------------------

def load_store() -> dict:
    """Load the question store from disk. Returns an empty store on any error."""
    # Kept for compatibility - returns a dict-like structure
    return {"questions": get_all_questions()}


def copy_empty() -> dict:
    return {"questions": []}


def save_store(data: dict) -> None:
    """Persist the question store to disk. No-op for SQLite (writes are immediate)."""
    pass


def find_answer(
    question_text: str,
    question_type: Optional[str] = None,
    min_similarity: float = 0.4,
) -> Optional[tuple]:
    """
    Look up an answer for *question_text* in the store.

    Search order:
      1. Exact match (case-insensitive) among approved questions.
      2. Fuzzy match (>= min_similarity) among approved questions.

    Pending and rejected entries are ignored by default.

    Returns (entry_dict, is_exact_match) or None.
    """
    conn = _get_conn()
    try:
        low_q = question_text.strip().lower()
        q_norm = _normalise(question_text)

        # Pass 1: exact match on normalized text (approved only)
        sql = """
            SELECT * FROM qa
            WHERE q_norm = ? AND status = 'approved'
        """
        params = [q_norm]
        if question_type:
            sql += " AND qtype = ?"
            params.append(question_type)
        row = conn.execute(sql, params).fetchone()
        if row:
            entry = dict(row)
            return (entry, True)

        # Pass 2: fuzzy match (approved only)
        # We need to fetch candidates and compute similarity in Python
        sql = "SELECT * FROM qa WHERE status = 'approved'"
        params = []
        if question_type:
            sql += " AND qtype = ?"
            params.append(question_type)
        rows = conn.execute(sql, params).fetchall()

        best_match = None
        best_score = 0.0
        for row in rows:
            entry = dict(row)
            score = similarity(question_text, entry["q_raw"])
            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = entry

        if best_match:
            return (best_match, False)
        return None
    finally:
        conn.close()


def save_question(
    question_text: str,
    answer: str,
    question_type: str = "text",
    source: str = "ai_saved",
    approved: bool = False,
    options_hash: str = "",
) -> dict:
    """
    Save a new question-answer pair. If the exact question already exists
    (same normalized text, type, and options_hash), update its answer and
    increment times_seen. Returns the saved entry dict.
    """
    conn = _get_conn()
    try:
        q_raw = question_text.strip()
        q_norm = _normalise(q_raw)
        now = _now_iso()
        status = "approved" if approved else "pending"

        conn.execute("""
            INSERT INTO qa (q_norm, q_raw, qtype, options_hash, answer, source, status, times_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(q_norm, qtype, options_hash) DO UPDATE SET
                q_raw = excluded.q_raw,
                answer = excluded.answer,
                source = excluded.source,
                status = excluded.status,
                times_seen = qa.times_seen + 1,
                updated_at = excluded.updated_at
        """, (q_norm, q_raw, question_type, options_hash, answer, source, status, now, now))
        conn.commit()

        # Fetch the saved row
        row = conn.execute(
            "SELECT * FROM qa WHERE q_norm = ? AND qtype = ? AND options_hash = ?",
            (q_norm, question_type, options_hash)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def record(
    question_text: str,
    answer: str,
    question_type: str,
    options: list[str] | None = None,
    source: str = "profile_rule",
    approved: bool = False,
) -> dict:
    """
    Convenience helper to save an answer from any branch.
    Computes options_hash for select/radio questions.
    """
    import hashlib
    opts_hash = ""
    if options:
        normalized = "|".join(sorted(o.strip().lower() for o in options))
        opts_hash = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return save_question(question_text, answer, question_type, source, approved, opts_hash)


def approve_question(question_text: str) -> bool:
    """Mark a question as approved. Returns True if found and updated."""
    conn = _get_conn()
    try:
        q_norm = _normalise(question_text.strip())
        cur = conn.execute(
            "UPDATE qa SET status = 'approved', updated_at = ? WHERE q_norm = ?",
            (_now_iso(), q_norm)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def approve_all_pending() -> int:
    """Approve all pending questions. Returns count of newly approved."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE qa SET status = 'approved', updated_at = ? WHERE status = 'pending'",
            (_now_iso(),)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def reject_question(question_text: str) -> bool:
    """Mark a question as rejected. Returns True if found and updated."""
    conn = _get_conn()
    try:
        q_norm = _normalise(question_text.strip())
        cur = conn.execute(
            "UPDATE qa SET status = 'rejected', updated_at = ? WHERE q_norm = ?",
            (_now_iso(), q_norm)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def mark_job_answers_unverified(job_id: str) -> int:
    """Mark all answers used for a job as unverified (pending)."""
    conn = _get_conn()
    try:
        cur = conn.execute(
            "UPDATE qa SET status = 'pending', updated_at = ? WHERE last_job_id = ? AND status = 'approved'",
            (_now_iso(), job_id)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_question(question_text: str) -> bool:
    """Delete a question by exact text match. Returns True if deleted."""
    conn = _get_conn()
    try:
        q_norm = _normalise(question_text.strip())
        cur = conn.execute("DELETE FROM qa WHERE q_norm = ?", (q_norm,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_questions() -> list:
    """Return the full list of saved questions."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM qa ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_questions() -> list:
    """Return questions awaiting approval."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM qa WHERE status = 'pending' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_approved_questions() -> list:
    """Return approved questions."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM qa WHERE status = 'approved' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_question_answer(question_text: str, new_answer: str) -> bool:
    """Update the answer for an existing question. Returns True if updated."""
    conn = _get_conn()
    try:
        q_norm = _normalise(question_text.strip())
        cur = conn.execute(
            "UPDATE qa SET answer = ?, updated_at = ? WHERE q_norm = ?",
            (new_answer, _now_iso(), q_norm)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_last_job_id(question_text: str, job_id: str) -> bool:
    """Record which job this answer was used for."""
    conn = _get_conn()
    try:
        q_norm = _normalise(question_text.strip())
        cur = conn.execute(
            "UPDATE qa SET last_job_id = ?, updated_at = ? WHERE q_norm = ?",
            (job_id, _now_iso(), q_norm)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()