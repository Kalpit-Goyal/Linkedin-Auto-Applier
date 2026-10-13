'''
Answer resolution pipeline for LinkedIn Easy Apply questions.

This module replaces the if/elif chains in runAiBot.answer_questions with a single
resolve_answer() function that runs in a fixed priority order:

1. Profile rules (word-boundary regex on the question label)
2. Exact match in the store (approved entries only)
3. Strict fuzzy match (content words only, Jaccard >= 0.85)
4. AI with options and field type (constrained prompt)
5. Skip or pause - never a random pick
'''

from __future__ import annotations

import re
from typing import Optional

from config.questions import (
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
    confidence_level,
    linkedin_headline,
    linkedin_summary,
    cover_letter,
    country,
    state,
    zipcode,
    user_information_all,
    experience_map,
    skip_job_if_unanswered,
)
from config.secrets import use_AI
from modules.question_store import find_answer as qa_find, save_question as qa_save
from modules.ai.connections import answer_question as ai_answer_question


# -----------------------------------------------------------------------------
# Generic words that carry no discriminative signal for fuzzy matching
# -----------------------------------------------------------------------------
GENERIC = {
    "years",
    "experience",
    "work",
    "working",
    "many",
    "much",
    "how",
    "long",
    "what",
    "is",
    "your",
    "the",
    "in",
    "with",
    "for",
    "of",
    "to",
    "a",
    "an",
    "and",
    "or",
    "you",
    "have",
    "do",
    "does",
    "did",
    "can",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "need",
    "want",
    "please",
    "enter",
    "provide",
    "specify",
    "select",
    "choose",
    "option",
    "field",
    "question",
    "answer",
    "required",
    "optional",
    "this",
    "that",
    "it",
    "its",
    "our",
    "their",
    "my",
    "me",
    "us",
    "them",
    "he",
    "she",
    "his",
    "her",
    "we",
    "i",
}


def _token_set(text: str) -> set[str]:
    """Return lowercase alphanumeric tokens from text, minus GENERIC words."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t and t not in GENERIC}


def safe_similarity(a: str, b: str) -> float:
    """
    Jaccard similarity on content words only.

    Returns a value in [0.0, 1.0]. Requires both sets to be non-empty.
    """
    ca, cb = _token_set(a), _token_set(b)
    if not ca or not cb:
        return 0.0
    inter = ca & cb
    union = ca | cb
    return len(inter) / len(union)


def _extract_skill_from_label(label: str) -> Optional[str]:
    """
    Parse the skill after 'experience with/in' in the question label.

    Examples:
        "How many years of experience do you have with Python?" -> "python"
        "Do you have experience in Java?" -> "java"
    """
    label_lower = label.lower()
    for kw in ("experience with", "experience in", "years of experience with", "years of experience in"):
        idx = label_lower.find(kw)
        if idx != -1:
            # Get the word(s) after the keyword
            after = label_lower[idx + len(kw):].strip()
            # Take first word (could be extended to multi-word skills)
            skill = after.split()[0] if after else None
            if skill:
                return skill.rstrip("?.,;")
    return None


def _profile_answer(label: str, question_type: str, options: list[str] | None = None) -> Optional[str]:
    """
    Rule-based answers from the user's profile config.

    Uses word-boundary matching (re.search(r"\bword\b", label)) to avoid
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

    # Contact
    if has_word("phone") or has_word("mobile"):
        return phone_number
    if has_word("email"):
        return linkedIn  # fallback, could add email field
    if has_word("linkedin"):
        return linkedIn
    if has_word("website") or has_word("blog") or has_word("portfolio") or (has_word("link") and not has_word("linkedin")):
        return website

    # Address
    if has_word("street"):
        return street
    if has_word("city") and not has_word("university") and not has_word("college"):
        return current_city
    if has_word("state") or has_word("province"):
        return state
    if has_word("zip") or has_word("postal") or (has_word("code") and not has_word("source")):
        return zipcode
    if has_word("country"):
        return country
    if has_word("address") or has_word("location"):
        return current_city

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

    # Yes/No questions with standard answers
    if has_word("yes") or has_word("no"):
        # Will be handled by option matching in select/radio
        pass

    return None


def _options_hash(options: list[str] | None) -> str:
    """Create a hash of the option set for select/radio validation."""
    if not options:
        return ""
    import hashlib
    normalized = "|".join(sorted(o.strip().lower() for o in options))
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def resolve_answer(
    label: str,
    question_type: str,
    options: list[str] | None = None,
    job_description: str | None = None,
    ai_client=None,
) -> tuple[str | None, str]:
    """
    Resolve an answer for a question in priority order.

    Returns:
        (answer, source) where source is one of:
        - "profile_rule"
        - "store_exact"
        - "store_fuzzy"
        - "ai"
        - "skip"
        - "pause"
    """
    # 1. Profile rules (word-boundary regex)
    profile_ans = _profile_answer(label, question_type, options)
    if profile_ans is not None:
        # For select/radio, validate against current options
        if question_type in ("select", "radio") and options:
            # Try to match the profile answer to an option
            matched = _match_option(profile_ans, options)
            if matched:
                return matched, "profile_rule"
            # Profile answer doesn't match any option - fall through
        else:
            return str(profile_ans), "profile_rule"

    # 2. Exact match in store (approved only)
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
                    # Option set changed - don't reuse
                    pass
                else:
                    matched = _match_option(stored_answer, options)
                    if matched:
                        return matched, "store_exact"
            else:
                return stored_answer, "store_exact"

    # 3. Strict fuzzy match (content words only, >= 0.85)
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

    # 4. AI with constrained prompt
    if use_AI and ai_client:
        try:
            ai_answer = ai_answer_question(
                ai_client,
                label,
                options=options,
                question_type=question_type,
                job_description=job_description,
                user_information_all=user_information_all,
            )
            if ai_answer and isinstance(ai_answer, str) and ai_answer.strip():
                cleaned = ai_answer.strip()
                # For select/radio, must match an option exactly
                if question_type in ("select", "radio") and options:
                    matched = _match_option(cleaned, options)
                    if matched:
                        return matched, "ai"
                else:
                    return cleaned, "ai"
        except Exception:
            pass  # Fall through to skip/pause

    # 5. Skip or pause - never random
    if skip_job_if_unanswered:
        return None, "skip"
    else:
        return None, "pause"


def _match_option(answer: str, options: list[str]) -> Optional[str]:
    """Match an answer to one of the allowed options."""
    if not options:
        return None
    # Exact match
    for opt in options:
        if answer == opt:
            return opt
    # Case-insensitive
    low = answer.lower()
    for opt in options:
        if low == opt.lower():
            return opt
    # Substring (either direction)
    for opt in options:
        if opt.lower() in low or low in opt.lower():
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


def record_answer(
    label: str,
    answer: str,
    question_type: str,
    options: list[str] | None = None,
    source: str = "profile_rule",
    approved: bool = False,
) -> None:
    """
    Save a question-answer pair to the store.

    Called from every branch (select, radio, checkbox, text, textarea, prefilled).
    """
    opts_hash = _options_hash(options) if options else ""
    qa_save(
        label,
        answer,
        question_type=question_type,
        source=source,
        approved=approved,
        options_hash=opts_hash,
    )