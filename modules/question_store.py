'''
Question-Answer Store for LinkedIn Easy Apply questions.

Maintains a local JSON database of previously encountered questions and their
answers. When the bot sees a question:

  1. Exact-match lookup in saved questions (approved + pending).
  2. Fuzzy / similarity match if no exact hit.
  3. If still nothing, AI answers (caller handles this) and saves the new
     question as "pending" for the user to review in the control panel.

The user can later approve, edit, or delete pending questions from the
control panel, turning them into trusted answers for future runs.
'''

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_STORE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "questions_db")
_STORE_FILE = os.path.join(_STORE_DIR, "saved_questions.json")

_EMPTY_STORE: dict = {"questions": []}


def _ensure_dir():
    os.makedirs(_STORE_DIR, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_store() -> dict:
    """Load the question store from disk. Returns an empty store on any error."""
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return copy_empty()


def copy_empty() -> dict:
    return {"questions": []}


def save_store(data: dict) -> None:
    """Persist the question store to disk."""
    _ensure_dir()
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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


def _normalise(text: str) -> str:
    """
    Lower-case, strip accents, remove punctuation/spaces, sort tokens.
    Returns a canonical form for fuzzy matching.
    """
    text = text.lower().strip()
    # Normalize unicode (e.g. accented chars)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    # Remove anything that isn't alphanumeric or space
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Tokenise, drop stop words, sort
    tokens = [t for t in text.split() if t and t not in _STOP_WORDS]
    tokens.sort()
    return " ".join(tokens)


def _token_set(text: str) -> set:
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
# Lookup
# ---------------------------------------------------------------------------

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
      3. Exact match among pending questions.
      4. Fuzzy match among pending questions.

    Returns (entry_dict, is_exact_match) or None.
    """
    store = load_store()
    questions = store.get("questions", [])
    if not questions:
        return None

    low_q = question_text.strip().lower()

    # --- Pass 1: exact match (approved first, then pending) ---
    approved = [q for q in questions if q.get("approved")]
    pending = [q for q in questions if not q.get("approved")]

    for bucket in (approved, pending):
        for entry in bucket:
            if entry.get("question", "").strip().lower() == low_q:
                if question_type is None or entry.get("question_type") == question_type:
                    return (entry, True)

    # --- Pass 2: fuzzy match (approved first, then pending) ---
    best_match = None
    best_score = 0.0

    for bucket in (approved, pending):
        for entry in bucket:
            score = similarity(question_text, entry.get("question", ""))
            if score > best_score and score >= min_similarity:
                if question_type is None or entry.get("question_type") == question_type:
                    best_score = score
                    best_match = entry

    if best_match:
        return (best_match, False)
    return None


# ---------------------------------------------------------------------------
# Save / update
# ---------------------------------------------------------------------------

def save_question(
    question_text: str,
    answer: str,
    question_type: str = "text",
    source: str = "ai_saved",
    approved: bool = False,
) -> dict:
    """
    Save a new question-answer pair. If the exact question already exists,
    update its answer. Returns the saved entry dict.
    """
    store = load_store()
    questions = store.get("questions", [])

    low_q = question_text.strip().lower()
    for entry in questions:
        if entry.get("question", "").strip().lower() == low_q:
            entry["answer"] = answer
            entry["question_type"] = question_type
            entry["source"] = source
            entry["updated_at"] = _now_iso()
            if approved:
                entry["approved"] = True
            save_store(store)
            return entry

    entry = {
        "question": question_text.strip(),
        "answer": answer,
        "question_type": question_type,
        "source": source,
        "approved": approved,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    questions.append(entry)
    store["questions"] = questions
    save_store(store)
    return entry


def approve_question(question_text: str) -> bool:
    """Mark a question as approved. Returns True if found and updated."""
    store = load_store()
    for entry in store.get("questions", []):
        if entry.get("question", "").strip().lower() == question_text.strip().lower():
            entry["approved"] = True
            entry["updated_at"] = _now_iso()
            save_store(store)
            return True
    return False


def approve_all_pending() -> int:
    """Approve all pending questions. Returns count of newly approved."""
    store = load_store()
    count = 0
    for entry in store.get("questions", []):
        if not entry.get("approved"):
            entry["approved"] = True
            entry["updated_at"] = _now_iso()
            count += 1
    if count:
        save_store(store)
    return count


def delete_question(question_text: str) -> bool:
    """Delete a question by exact text match. Returns True if deleted."""
    store = load_store()
    questions = store.get("questions", [])
    low_q = question_text.strip().lower()
    new_list = [q for q in questions if q.get("question", "").strip().lower() != low_q]
    if len(new_list) < len(questions):
        store["questions"] = new_list
        save_store(store)
        return True
    return False


def get_all_questions() -> list:
    """Return the full list of saved questions."""
    return load_store().get("questions", [])


def get_pending_questions() -> list:
    """Return questions awaiting approval."""
    return [q for q in load_store().get("questions", []) if not q.get("approved")]


def get_approved_questions() -> list:
    """Return approved questions."""
    return [q for q in load_store().get("questions", []) if q.get("approved")]


def update_question_answer(question_text: str, new_answer: str) -> bool:
    """Update the answer for an existing question. Returns True if updated."""
    store = load_store()
    for entry in store.get("questions", []):
        if entry.get("question", "").strip().lower() == question_text.strip().lower():
            entry["answer"] = new_answer
            entry["updated_at"] = _now_iso()
            save_store(store)
            return True
    return False
