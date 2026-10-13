'''
Answer resolution pipeline for LinkedIn Easy Apply questions.

This module replaces the if/elif chains in runAiBot.answer_questions with a single
resolve_answer() function that runs in a fixed priority order:

1. Bank lookup (config/question_bank.yaml) - explicit answers win
2. Exact match in store (approved entries only, with options_hash)
3. Strict fuzzy match (content words only, Jaccard >= 0.85 via safe_similarity)
4. Profile rules (word-boundary regex on the question label)
5. Skip or pause - never a random pick

The AI branch has been removed - use_AI can stay but langchain is not imported here.
'''

from __future__ import annotations

import re
import yaml
from pathlib import Path
from typing import Optional

from config.profile import (
    years_of_experience,
    require_visa,
    us_citizenship,
    veteran_status,
    disability_status,
    gender,
    phone_number,
    street,
    current_city,
    full_name,
    first_name,
    middle_name,
    last_name,
    recent_employer,
    notice_period,
    notice_period_months,
    notice_period_weeks,
    desired_salary,
    current_ctc,
    desired_salary_monthly,
    current_ctc_monthly,
    desired_salary_lakhs,
    current_ctc_lakhs,
    linkedIn,
    website,
    email_address,
    confidence_level,
    linkedin_headline,
    linkedin_summary,
    cover_letter,
    country,
    state,
    zipcode,
    ethnicity,
    experience_map,
    skip_job_if_unanswered,
)
from modules.question_store import find_answer as qa_find, record as qa_record, safe_similarity


# -----------------------------------------------------------------------------
# Question Bank (config/question_bank.yaml) - checked FIRST so explicit answers win
# -----------------------------------------------------------------------------
_BANK_PATH = Path(__file__).parent.parent / "config" / "question_bank.yaml"
_BANK: list[dict] | None = None


def _load_bank() -> list[dict]:
    global _BANK
    if _BANK is not None:
        return _BANK
    if _BANK_PATH.exists():
        with open(_BANK_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        _BANK = data if isinstance(data, list) else []
    else:
        _BANK = []
    return _BANK


def _check_bank(label: str, question_type: str, options: list[str] | None = None) -> Optional[str]:
    """Check the question bank for an explicit answer."""
    low_label = label.lower()
    for entry in _load_bank():
        pattern = entry.get("pattern")
        if not pattern:
            continue
        if re.search(pattern, low_label, re.IGNORECASE):
            # Check question type matches
            entry_type = entry.get("question_type")
            if entry_type and entry_type != question_type:
                continue
            # Check options match if provided
            if options:
                entry_opts = entry.get("options") or []
                if entry_opts:
                    # Normalize and compare
                    norm_current = {o.strip().lower() for o in options}
                    norm_entry = {o.strip().lower() for o in entry_opts}
                    if norm_current != norm_entry:
                        continue
            answer = entry.get("answer")
            if answer:
                return answer
    return None


# -----------------------------------------------------------------------------
# Generic words that carry no discriminative signal for fuzzy matching
# -----------------------------------------------------------------------------
GENERIC = {
    "years", "experience", "work", "working", "many", "much", "how", "long",
    "what", "is", "your", "the", "in", "with", "for", "of", "to", "a", "an",
    "and", "or", "you", "have", "do", "does", "did", "can", "will", "would",
    "could", "should", "may", "might", "must", "need", "want", "please",
    "enter", "provide", "specify", "select", "choose", "option", "field",
    "question", "answer", "required", "optional", "this", "that", "it",
    "its", "our", "their", "my", "me", "us", "them", "he", "she", "his",
    "her", "we", "i", "do you", "have you", "are you",
}


def _token_set(text: str) -> set[str]:
    """Return lowercase alphanumeric tokens from text, minus GENERIC words."""
    tokens = re.findall(r"[a-z0-9.+#/]+", text.lower())
    return {t for t in tokens if t and t not in GENERIC}


# Re-export safe_similarity from question_store (content words only, GENERIC stripped)
# from modules.question_store import safe_similarity


def _extract_skill_from_label(label: str) -> Optional[str]:
    """
    Parse the skill after 'experience with/in/using' in the question label.
    
    Examples:
        "How many years of experience do you have with Python?" -> "python"
        "Do you have experience in Java?" -> "java"
        "Experience using Node.js?" -> "node"
    """
    label_lower = label.lower()
    # Match patterns like: experience with X, experience in X, experience using X
    match = re.search(r"(?:with|in|using)\s+([A-Za-z0-9.+#/ ]+?)(?:\?|$)", label_lower)
    if match:
        skill = match.group(1).strip()
        # Normalize: remove dots, 'js' suffix, lowercase
        skill = skill.replace(".", "").replace(" ", "_")
        if skill.endswith("_js"):
            skill = skill[:-3]
        elif skill.endswith("js"):
            skill = skill[:-2]
        return skill
    return None


def _profile_answer(label: str, question_type: str, options: list[str] | None = None) -> Optional[str]:
    """
    Rule-based answers from the user's profile config.
    
    Uses word-boundary matching (re.search(r"\\bword\\b", label)) to avoid
    false positives like "city" matching "cityname".
    """
    low = label.lower()

    def has_word(word: str) -> bool:
        return bool(re.search(rf"\b{re.escape(word)}\b", low))

    # Sponsorship / visa
    if has_word("sponsorship") or has_word("visa"):
        return require_visa

    # Citizenship / eligibility
    if has_word("citizenship") or has_word("employment eligibility"):
        return us_citizenship

    # Veteran / protected
    if has_word("veteran") or has_word("protected veteran"):
        return veteran_status

    # Disability
    if has_word("disability") or has_word("handicapped"):
        return disability_status

    # Gender / sex
    if has_word("gender") or (has_word("sex") and not has_word("sexual")):
        return gender

    # Ethnicity
    if has_word("ethnicity") or has_word("race"):
        return ethnicity

    # Contact
    if has_word("phone") or has_word("mobile"):
        return phone_number
    if has_word("email"):
        return email_address or linkedIn
    if has_word("linkedin"):
        return linkedIn
    if has_word("website") or has_word("blog") or has_word("portfolio") or (has_word("link") and not has_word("linkedin")):
        return website

    # Address
    if has_word("street"):
        return street
    if has_word("city") and not has_word("university") and not has_word("college"):
        return current_city if current_city else None  # Let caller handle fallback
    if has_word("state") or has_word("province"):
        return state
    if has_word("zip") or has_word("postal") or (has_word("code") and not has_word("source")):
        return zipcode
    if has_word("country"):
        return country
    if has_word("address") or has_word("location"):
        return current_city if current_city else None

    # Name
    if has_word("signature") or has_word("legal name") or has_word("full name"):
        return full_name
    if has_word("name"):
        if has_word("first") and not has_word("last"):
            return first_name
        if has_word("middle") and not has_word("last"):
            return middle_name
        if has_word("last") and not has_word("first"):
            return last_name
        if has_word("employer"):
            return recent_employer
        return full_name

    # Notice period
    if has_word("notice"):
        if has_word("month"):
            return notice_period_months
        if has_word("week"):
            return notice_period_weeks
        return notice_period

    # Salary / compensation
    if has_word("salary") or has_word("compensation") or has_word("ctc") or has_word("pay"):
        is_current = has_word("current") or has_word("present")
        if has_word("month"):
            return current_ctc_monthly if is_current else desired_salary_monthly
        if has_word("lakh") or has_word("lakh"):
            return current_ctc_lakhs if is_current else desired_salary_lakhs
        return current_ctc if is_current else desired_salary

    # Experience (years) - check skill-specific map first
    if has_word("experience") or has_word("years"):
        skill = _extract_skill_from_label(label)
        if skill and skill in experience_map:
            return str(experience_map[skill])
        # For Yes/No experience questions, answer Yes if years > 0
        if options and len(options) == 2:
            opt_low = {o.lower().strip() for o in options}
            if opt_low == {"yes", "no"} or opt_low == {"y", "n"}:
                default_years = experience_map.get("default", int(years_of_experience))
                return "Yes" if default_years > 0 else "No"
        return str(experience_map.get("default", years_of_experience))

    # Confidence / scale
    if has_word("scale") and has_word("1") and has_word("10"):
        return confidence_level

    # Headline / summary / cover letter
    if has_word("headline"):
        return linkedin_headline
    if has_word("summary"):
        return linkedin_summary
    if has_word("cover") and has_word("letter"):
        return cover_letter

    # Source / how did you hear
    if (has_word("hear") or has_word("come across")) and has_word("this") and (has_word("job") or has_word("position")):
        return "https://github.com/GodsScion/Auto_job_applier_linkedIn"

    # Proficiency
    if has_word("proficiency"):
        return "Professional"

    return None


def _options_hash(options: list[str] | None) -> str:
    """Create a hash of the option set for select/radio validation."""
    if not options:
        return ""
    import hashlib
    normalized = "|".join(sorted(o.strip().lower() for o in options))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _match_option(answer: str, options: list[str]) -> Optional[str]:
    """Match an answer to one of the allowed options - exact/alias first, then whole-word substring."""
    if not options:
        return None
    
    # Exact match
    for opt in options:
        if answer == opt:
            return opt
    
    # Case-insensitive exact
    low = answer.lower()
    for opt in options:
        if low == opt.lower():
            return opt
    
    # Alias matches (common variations)
    alias_map = {
        "yes": ["yes", "y", "true", "agree", "i do", "i have"],
        "no": ["no", "n", "false", "disagree", "i don't", "i do not", "not applicable"],
        "decline": ["decline", "prefer not", "not wish", "don't wish", "not want"],
    }
    for canonical, aliases in alias_map.items():
        if low in aliases:
            for opt in options:
                if opt.lower() in aliases:
                    return opt
    
    # Whole-word substring (either direction)
    for opt in options:
        opt_low = opt.lower()
        if opt_low in low or low in opt_low:
            return opt
    
    # Numeric closeness for number-like options
    closest = _closest_numeric_option(answer, options)
    if closest:
        return closest
    
    return None


def _closest_numeric_option(answer: str, options: list[str]) -> Optional[str]:
    """Find the option with the numerically closest value."""
    import re
    m = re.search(r"[\d,]+\.?\d*", answer.replace(",", ""))
    if not m:
        return None
    try:
        wanted = float(m.group())
    except ValueError:
        return None
    best, best_gap = None, None
    for opt in options:
        m2 = re.search(r"[\d,]+\.?\d*", opt.replace(",", ""))
        if not m2:
            continue
        try:
            val = float(m2.group())
        except ValueError:
            continue
        gap = abs(val - wanted)
        if best_gap is None or gap < best_gap:
            best, best_gap = opt, gap
    return best


def resolve_answer(
    label: str,
    question_type: str,
    options: list[str] | None = None,
    job_description: str | None = None,
    job_link: str | None = None,
) -> tuple[str | None, str]:
    """
    Resolve an answer for a question in priority order.
    
    Returns:
        (answer, source) where source is one of:
        - "bank" (question_bank.yaml)
        - "store_exact"
        - "store_fuzzy"
        - "profile_rule"
        - "skip"
        - "pause"
    """
    # 1. Bank lookup (explicit answers win)
    bank_ans = _check_bank(label, question_type, options)
    if bank_ans is not None:
        return bank_ans, "bank"
    
    # 2. Exact match in store (approved only, with options_hash)
    qa_result = qa_find(label, question_type=question_type, min_similarity=1.0)
    if qa_result:
        entry, exact = qa_result
        if entry.get("approved") and exact:
            stored_answer = entry["answer"]
            # For select/radio, validate option set matches
            if question_type in ("select", "radio") and options:
                stored_hash = entry.get("options_hash", "")
                current_hash = _options_hash(options)
                if stored_hash and stored_hash != current_hash:
                    pass  # Option set changed - don't reuse
                else:
                    matched = _match_option(stored_answer, options)
                    if matched:
                        return matched, "store_exact"
            else:
                return stored_answer, "store_exact"
    
    # 3. Strict fuzzy match (content words only, >= 0.85) - uses safe_similarity
    qa_result = qa_find(label, question_type=question_type, min_similarity=0.85)
    if qa_result:
        entry, exact = qa_result
        if entry.get("approved") and not exact:
            stored_answer = entry["answer"]
            if question_type in ("select", "radio") and options:
                stored_hash = entry.get("options_hash", "")
                current_hash = _options_hash(options)
                if stored_hash and stored_hash != current_hash:
                    pass
                else:
                    matched = _match_option(stored_answer, options)
                    if matched:
                        return matched, "store_fuzzy"
            else:
                return stored_answer, "store_fuzzy"
    
    # 4. Profile rules (word-boundary regex)
    profile_ans = _profile_answer(label, question_type, options)
    if profile_ans is not None:
        if question_type in ("select", "radio") and options:
            matched = _match_option(profile_ans, options)
            if matched:
                return matched, "profile_rule"
        else:
            return str(profile_ans), "profile_rule"
    
    # 5. Skip or pause - never random
    if skip_job_if_unanswered:
        # Log unanswered question for daily review
        _log_unanswered(label, question_type, options, job_link)
        return None, "skip"
    else:
        return None, "pause"


def _log_unanswered(label: str, question_type: str, options: list[str] | None, job_link: str | None) -> None:
    """Log unanswered questions to questions_db/unanswered.csv for daily review."""
    import csv
    from datetime import datetime
    
    log_path = Path(__file__).parent.parent / "questions_db" / "unanswered.csv"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check if already logged
    key = f"{label.strip().lower()}|{question_type}"
    seen = set()
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seen.add(f"{row['question'].strip().lower()}|{row['question_type']}")
    
    if key in seen:
        return
    
    row = {
        "timestamp": datetime.now().isoformat(),
        "question": label.strip(),
        "question_type": question_type,
        "options": "|".join(options) if options else "",
        "job_link": job_link or "",
    }
    
    file_exists = log_path.exists()
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def record_answer(
    label: str,
    answer: str,
    question_type: str,
    options: list[str] | None = None,
    source: str = "profile_rule",
    approved: bool = False,
) -> dict:
    """
    Save a question-answer pair to the store.
    
    Called from every branch (select, radio, checkbox, text, textarea, prefilled).
    Preserves existing status unless explicitly approving.
    """
    opts_hash = _options_hash(options) if options else ""
    
    # For approved answers, keep approved=True; for others, use source flag
    status = "approved" if approved else ("pending" if source in ("profile_rule", "store_exact", "store_fuzzy") else "pending")
    
    # If this is an update to an existing approved answer, keep approved=True
    if approved:
        status = "approved"
    
    return qa_record(
        label,
        answer,
        question_type=question_type,
        options=options,
        source=source,
        approved=approved,
    )