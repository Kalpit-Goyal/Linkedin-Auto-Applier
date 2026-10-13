'''
Centralized profile values for answer resolution.

All user-provided personal/config values live here so modules/answering.py
can import them without depending on runAiBot.py or config/personals.py directly.
'''

# Import from the canonical locations
from config.personals import (
    first_name,
    middle_name,
    last_name,
    phone_number,
    current_city,
    street,
    state,
    zipcode,
    country,
    ethnicity,
    gender,
    disability_status,
    veteran_status,
)
from config.questions import (
    years_of_experience,
    require_visa,
    us_citizenship,
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
    recent_employer,
    experience_map,
    skip_job_if_unanswered,
    email_address,  # New: dedicated email field
)

# Full name computed from parts
full_name = f"{first_name} {middle_name} {last_name}".strip() if middle_name else f"{first_name} {last_name}".strip()

# Aliases for backward compatibility
email = email_address

__all__ = [
    "first_name", "middle_name", "last_name", "full_name",
    "phone_number", "current_city", "street", "state", "zipcode", "country",
    "ethnicity", "gender", "disability_status", "veteran_status",
    "years_of_experience", "require_visa", "us_citizenship",
    "notice_period", "notice_period_months", "notice_period_weeks",
    "desired_salary", "current_ctc", "desired_salary_monthly", "current_ctc_monthly",
    "desired_salary_lakhs", "current_ctc_lakhs",
    "linkedIn", "website", "email", "email_address",
    "confidence_level", "linkedin_headline", "linkedin_summary", "cover_letter",
    "recent_employer", "experience_map", "skip_job_if_unanswered",
]