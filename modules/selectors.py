'''
Every DOM lookup the applier needs, in one ranked list per target.

Why this file exists
--------------------
The new job search is server-driven, so class names are build hashes that change
without notice and have to be treated as unusable. What does survive is:

  * **semantic anchors** - `componentkey="JobDetails_AboutTheJob"` and similar.
    These name the thing they render rather than how it looks, which makes them the
    anchors worth trusting.
  * **ARIA roles and labels** - a button that says "Easy Apply" in its
    `aria-label` is a better handle than its hashed class.
  * **documented data attributes** - `data-job-id`, `data-entity-urn`.

So each entry below is an *ordered* list, most-trustworthy first, and the lookup
walks it in order. That ordering is the point: when LinkedIn rebuilds something,
repairing it means adding one line at the top of a list here, instead of
re-teaching the crawler about a new page.

Every list ends with the classic-UI selector where one exists, so a page still
served by the old markup keeps working.

How to keep this accurate
-------------------------
LinkedIn is still rolling the new search out gradually, and accounts are served
different variants, so do not trust these lists blindly. Run
`python tools/capture_dom.py` and add whatever the capture shows is actually there.
'''

# Landing on the new search. Kept here so the URL lives with the rest of the
# knowledge about the new UI rather than being sprinkled through runAiBot.py.
AI_SEARCH_URL = "https://www.linkedin.com/jobs/search-results/"

# Still reachable while the retirement is in progress, and the escape hatch if the
# AI search is not served to a given account.
CLASSIC_SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={searchTerm}"


# A job card in the results list. The first three are identity-based and therefore
# the most durable; the class-based ones are what the capture showed for the
# classic list.
JOB_CARD = [
    "li[data-job-id]",
    "li[data-entity-urn]",
    "div[data-job-id]",
    "li[data-occludable-job-id]",
    "div.job-card-container",
    "li.jobs-search-results__list-item",
    "div.jobs-search-results__list-item",
    "div.scaffold-layout__list-item",
]

# The clickable link on a card, used both to read the job id and to open the job.
JOB_CARD_LINK = [
    "a[href*='/jobs/view/']",
    "a[data-tracking-control-name*='public_jobs_jserp-result']",
    "a.jobs-search-results__card-link",
    "a.base-card__full-link",
    "a.base-search-card__full-link",
]

# Attributes a card may carry the job id in, most reliable first. Tried before
# falling back to parsing the link, because an id attribute needs no guessing.
JOB_ID_ATTRIBUTES = ["data-job-id", "data-entity-urn", "data-id", "data-occludable-job-id"]

# The results list itself, used to confirm a search has actually loaded and to know
# where to scroll for more.
RESULTS_LIST = [
    "div.jobs-search-results-list",
    "[data-test='results-list']",
    "ol.jobs-search-results__list",
    "ul.jobs-search-results__list",
    "section[data-test='search-results']",
    "#jobs-search-results-main",
    "main",
]

# Per-card text, for the blacklists and for reporting.
JOB_CARD_TITLE = [
    "div.base-search-card__title",
    "h3.base-search-card__title",
    "div.jobs-search-results__list-item-title",
    "[componentkey*='JobCardTitle']",
    "h3",
]
JOB_CARD_COMPANY = [
    "div.base-search-card__subtitle",
    "div.base-search-card__subtitle a",
    "h4.base-search-card__subtitle",
    "[componentkey*='JobCardCompany']",
    "h4",
]
JOB_CARD_LOCATION = [
    "span.base-search-card__metadata",
    "div.job-search-card__location",
    "[componentkey*='JobCardLocation']",
    "span.base-main-card__metadata",
]
JOB_CARD_POSTED = [
    "time",
    "span.base-search-card__metadata time",
    "[componentkey*='JobCardPosted']",
]


# ---------------------------------------------------------------- job details

# The details pane that opens beside the list. Everything else is read from here.
DETAILS_PANE = [
    "div.jobs-search__details",
    "section.jobs-search__details",
    "[componentkey^='JobDetails_']",
    "div[data-test='job-details']",
    "div.jobs-view",
]

JOB_DESCRIPTION = [
    "div.jobs-box__html-content",              # classic
    "div.jobs-description__text",              # classic
    "[componentkey^='JobDetails_AboutTheJob'] div",
    "[componentkey^='JobDetails_AboutTheJob']",
    "div[data-test='job-description']",
    "#job-details",
]

JOB_TITLE = [
    "[componentkey^='JobDetails_Header'] h1",
    "[componentkey^='JobDetails_Header'] h2",
    "h1.jobs-top-card__title",
    "h2.jobs-top-card__title",
    "h1",
]

JOB_COMPANY = [
    "[componentkey^='JobDetails_Header'] a[data-tracking-control-name*='company']",
    "a.topcard__org-name-link",
    "span.topcard__flavor",
    "a[data-tracking-control-name*='public_jobs_topcard_org_name']",
]

JOB_POSTED = [
    "span.jobs-posted-ago",
    "small.jobs-posted-ago",
    "[componentkey*='JobDetails_Posted']",
    "span[aria-label*=' ago']",
]

JOB_SALARY = [
    "[componentkey*='JobDetails_Compensation']",
    "span.jobs-salary__inner",
    "div.jobs-salary",
]

JOB_HR_LINK = [
    "[componentkey^='JobDetailsPeopleWhoCanHelpSlot'] a",
    "a[data-tracking-control-name*='public_jobs_topcard_seeWhoCanHelp']",
    "div.topcard__org-name a",
]

JOB_ON_SITE_LINK = [
    "[componentkey*='JobDetails_ApplyLink'] a",
    "a[data-tracking-control-name*='apply-link-offsite']",
    "a.jobs-topcard__link",
]

# Buttons that advance or finish the Easy Apply flow, by the text on them. The new
# UI still labels these, so text matching is more durable here than any class.
APPLY_NEXT = ["Next", "Continue", "Submit application", "Review", "Done"]
APPLY_DISCARD = ["Discard", "Delete", "Cancel"]


# ---------------------------------------------------------------- easy apply

# The apply control on the details pane or the card. Note the second entry: LinkedIn
# flags its in-app flow with a URL parameter, which is sturdier than any class.
EASY_APPLY_BUTTON = [
    "button[aria-label*='Easy Apply']",
    "a[href*='openSDUIApplyFlow=true']",
    "button[data-tracking-control-name*='public_jobs_apply-link-offsite_sign-up-modal']",
    "button.jobs-apply-button",
    "button[data-tracking-control-name*='apply']",
]

EXTERNAL_APPLY_BUTTON = [
    "a[data-tracking-control-name*='apply-link-offsite']",
    "button[data-tracking-control-name*='apply-offsite']",
    "button.jobs-apply-button",
    "a.jobs-apply-button",
]

APPLY_BUTTON = EASY_APPLY_BUTTON + EXTERNAL_APPLY_BUTTON

# The Easy Apply modal. `jobs-easy-apply-modal` is the classic class and is gone from
# the new markup, so the componentkey prefixes carry the weight here.
EASY_APPLY_MODAL = [
    "div.jobs-easy-apply-modal",
    "[data-test='easy-apply-modal']",
    "[componentkey*='EasyApplyModal']",
    "[componentkey*='EasyApply']",
    "div[data-test-form-element]",
    "[role='dialog']",
]

# Form controls. `data-id` is what the classic form used to identify a field and
# `runAiBot.answer_questions()` matches on it, so it stays first.
FORM_FIELD = [
    "div[data-test-form-element]",
    "div[data-test-single-line-text-form-component]",
    "div[data-test-text-entity-list-form-component]",
    "div[data-test-checkbox-form-component]",
    "div[data-test-combobox-form-component]",
]

RESUME_UPLOAD_INPUT = ["input[type='file']", "input[name='file']"]

# The button that opens the file chooser, which is what actually has to be clicked.
RESUME_UPLOAD_BUTTON = [
    "button[data-tracking-control-name*='upload']",
    "label[for*='file']",
    "button[aria-label*='upload' i]",
    "button:has(input[type='file'])",
]


# ---------------------------------------------------------------- progression

# The new list grows as you scroll rather than paginating, so "load more" is the
# thing to look for, with the numbered links kept as a fallback.
LOAD_MORE = [
    "button[aria-label*='Load more results']",
    "button[data-tracking-control-name*='load_more']",
    "a[data-tracking-control-name*='load_more']",
    "button[aria-label*='load more' i]",
]

PAGINATION_NEXT = [
    "button[aria-label='Next']",
    "a[aria-label='Next']",
    "button[data-tracking-control-name*='next']",
]