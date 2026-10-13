'''
Every DOM lookup the applier needs, in one ranked list per target.

Provenance
----------
The new job search is server-driven: `data-sdui-screen="com.linkedin.sdui.flagshipnav.jobs.SemanticJobDetails"`,
and almost every class is a build hash that changes without notice. Three things
survive a rebuild, and the lists below are ordered by how much they can be trusted:

  1. **`data-view-name`** - LinkedIn's own instrumentation hook, and it still names
     things honestly. `job-search-job-card`, `job-apply-button`, `continue-unify`.
     It is *not* on the results page any more: the latest capture has zero of them
     in the document, so nothing that must work may lead with it.
  2. **`componentkey`** - names the component *and embeds the job id*:
     `job-card-component-ref-4473342199`, `JobDetails_AboutTheJob_4473342199`.
     Since `data-view-name` left the card, this is what a job card is identified by.
  3. **ARIA roles and labels** - a button that calls itself "Easy Apply to this job"
     is a better handle than its class.

What was verified against a live capture
----------------------------------------
`tools/capture_dom.py` was run against a logged-in account and the anchors marked
*verified* below were counted directly in the captured markup. The unverified ones
are from the classic UI or from other projects, and they are listed last on purpose.

Three findings from that capture shape this file more than the selector order does:

  * **The results list is virtualised** (`data-testid="lazy-column"`,
    `data-component-type="LazyColumn"`). Only the rows near the viewport exist, and
    they are recycled as you scroll, so a list of card elements must never be held
    across a scroll.
  * **Cards carry no apply button.** `apply_buttons=0` on all 25 captured cards. The
    apply control exists only on the focused job's details pane, so the flow is
    select a card first, then apply from the details pane.
  * **Pagination still exists** - `[data-testid="pagination-controls-list"]` with
    `button[aria-label="Page N"]`, three pages in the capture.

Repairing this file after the next LinkedIn change means adding one line to the top
of a list. It should never mean editing the crawler.
'''

# Verified: what the bot opens by default.
AI_SEARCH_URL = "https://www.linkedin.com/jobs/search-results/"

# Still served, and the fallback for an account the AI search is not rolled out to.
CLASSIC_SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={searchTerm}"

# The screen id the new search runs as, useful for confirming which UI loaded.
SDUI_SEARCH_SCREEN = "[data-sdui-screen='com.linkedin.sdui.flagshipnav.jobs.SemanticJobDetails']"
SDUI_SEARCH_SCREEN_ALT = "[data-sdui-screen^='com.linkedin.sdui.flagshipnav.jobs.']"

# componentkeys put the job id on the end of a stable prefix, which is the most
# reliable way to learn which job an element belongs to. Verified values:
# `job-card-component-ref-4473342199`, `JobDetails_AboutTheJob_4473342199`,
# `JobDetailsPeopleWhoCanHelpSlot_4473342199`, `JobMatchRef_4473342199`.
# `JobDetails` is deliberately prefix-only with no underscore, because the real keys
# split between `JobDetails_` and `JobDetailsPeopleWhoCanHelpSlot_`.
JOB_CARD_COMPONENTKEY = "[componentkey^='job-card-component-ref-']"
JOB_DETAILS_COMPONENTKEY = "[componentkey^='JobDetails_']"


# ---------------------------------------------------------------- results list

# Verified. `lazy-column` is the virtualised container the cards live in.
JOB_CARD = [
    # Verified, 25 on the captured page, and the only hook left on the card: the
    # `data-view-name` that used to sit on the wrapper is gone from the current
    # markup. The key is on the card twice - the `role="button"` div and the div
    # inside it - so a card list is deduped by job id (see jobcard.py).
    "div[componentkey^='job-card-component-ref-']",
    "div[data-view-name='job-search-job-card']",   # verified on the earlier capture
    "li[data-entity-urn]",
    "li[data-occludable-job-id]",                 # classic
    "li[data-job-id]",
    "div[data-job-id]",
    "li.jobs-search-results__list-item",          # classic
    "div.job-card-container",                     # classic
    "div.scaffold-layout__list-item",             # classic
    "div[data-test-id*='job-card']",
    "div[data-job-title]",
    "ul.jobs-search__results-list > li",
    "ul.scaffold-layout__list-container > li",
    ".jobs-search-results-list > li",
    ".job-search-card",
    "li.reusable-search__result-container",
    "div.job-search-card",
    "article.job-card",
    "div.artdeco-list__item[data-occludable-job-id]",
    "div.artdeco-card[data-job-id]",
    "[data-testid='job-card']",
    "[data-testid*='job-card']",
    "[class*='job-card']",
    "[class*='jobs-search-results'] li",
    "li[data-test-id*='job-card']",
    "div[data-view-name*='job-card']",
    "[role='listitem']:has(a[href*='/jobs/view/'])",
    "[role='listitem']",
    # AI search / SDUI variants seen in the wild.
    "div[data-testid='search-results__list-item']",
    "li[data-testid='search-results__list-item']",
    "div[data-testid='job-list-item']",
    "li[data-testid='job-list-item']",
    "[data-testid*='search-result']",
    "div[class*='jobs-search-results-list__item']",
    "li[class*='jobs-search-results-list__item']",
    # NOT `div[data-sdui-screen*='job']`: that attribute is on the *screen*
    # (`...jobs.SemanticJobDetails`) which wraps the whole page, so matching it
    # hands the applier the entire results view as if it were a single card.
    "[data-view-name*='job-search']",
    "li:has(a[href*='/jobs/view/'])",
    "article:has(a[href*='/jobs/view/'])",
]

# The clickable region of a card. On the new UI this is a `role="button"` div rather
# than a link, so the link selectors only apply to the focused job and to classic.
JOB_CARD_CLICKABLE = [
    "div[componentkey^='job-card-component-ref-']",   # verified
    "a[href*='/jobs/view/']",
    "a[data-tracking-control-name*='public_jobs_jserp-result']",  # classic
    "[data-testid*='job-card'] [role='button']",
    "[data-testid*='job-card'] button",
    "div[role='button'][tabindex='0']",
]

# Job ids come from here first. Verified values look like
# `job-card-component-ref-4473342199` and `JobDetails_AboutTheJob_4473342199`.
JOB_ID_COMPONENTKEYS = [
    "job-card-component-ref-",
    "JobDetails",
    "JobMatchRef_",
]

# Attributes a card *might* carry an id in. Empty on the new UI, kept for classic.
JOB_ID_ATTRIBUTES = ["data-job-id", "data-entity-urn", "data-occludable-job-id"]

RESULTS_LIST = [
    # Verified. Three `lazy-column`s are on the page (results, sidebar, details)
    # and only the results one carries this key, so it is listed first: `deep_find`
    # stops at the first selector that matches anywhere, and picking the wrong
    # column would scope the card search to a list that has no cards in it.
    "[data-testid='lazy-column'][componentkey='SearchResultsMainContent']",   # verified
    "[data-testid='lazy-column']",               # verified
    "[data-component-type='LazyColumn']",         # verified
    "div.jobs-search-results-list",               # classic
    "[data-test='results-list']",                 # classic
    "ol.jobs-search-results__list",               # classic
    "#jobs-search-results-main",                  # classic
    "main",
]

# Per-card text. These are **classic-UI fallbacks only**. The captured new card has
# no hook on any of its fields and puts them in `<p>` elements in a fixed order -
# title, company, location, "Posted N days ago" - but every selector below returns
# the *first* match, so on that card `div p` and `p` both hand back the title and
# the company and the location read as the job's name. `jobcard.read_card()` reads
# the paragraphs positionally for a new-UI card and only falls back to this list
# when the card is not one.
JOB_CARD_TITLE = [
    "p span",
    "h3.base-search-card__title",    # classic
    "div.base-search-card__title",   # classic
]
JOB_CARD_COMPANY = [
    "div p",
    "h4.base-search-card__subtitle",  # classic
    "div.base-search-card__subtitle",  # classic
]
JOB_CARD_LOCATION = [
    "p",
    "span.base-search-card__metadata",  # classic
]
JOB_CARD_POSTED = [
    "div span",
    "time",                             # classic
    "span.jobs-posted-ago",             # classic
]

# The little X on each card. Worth knowing about because it sits inside the card and
# a click aimed at the card can land on it instead.
JOB_CARD_DISMISS = [
    "button[data-view-name='dismiss-job']",  # verified
    "button[aria-label^='Dismiss']",
]


# ---------------------------------------------------------------- pagination

# Verified: a real paginated control with one button per page.
PAGINATION_LIST = [
    "[data-testid='pagination-controls-list']",
    "ul[aria-label*='Pagination']",
]
PAGINATION_PAGE = [
    "button[aria-label^='Page ']",   # verified, e.g. aria-label="Page 2"
    "button[data-testid^='pagination-indicator']",
]
# Verified: the page you are on is the one button whose aria-current is "true"; every
# other page button reads "false". Reading the active page off this is more reliable
# than counting clicks, which drift if a page turn is ever slow.
PAGINATION_CURRENT = [
    "button[aria-label^='Page '][aria-current='true']",
]
# Verified: the arrow after the list, which only exists while another page does.
PAGINATION_PREVIOUS = ["button[aria-label='Previous page']", "button[aria-label='Previous']"]
PAGINATION_NEXT = [
    "[data-testid='pagination-controls-next-button-visible']",   # verified
    "button[aria-label='Next page']",
    "button[aria-label='Next']",
]

# The new list also grows on scroll; this is for when it has not been scrolled yet.
LOAD_MORE = [
    "button[aria-label*='Load more results']",
    "button[data-tracking-control-name*='load_more']",
]


# ---------------------------------------------------------------- job details

DETAILS_PANE = [
    "[componentkey^='JobDetails_']",   # verified, several on the page
    "[componentkey='JobMatchRef_']",   # verified
    "div.jobs-search__details",
    "div.jobs-view",                   # classic
]

# Verified. The id is on the end of the componentkey, e.g.
# `JobDetails_AboutTheJob_4473342199`, and this element wraps the whole description.
JOB_DESCRIPTION = [
    "[componentkey^='JobDetails_AboutTheJob']",
    "div.jobs-box__html-content",   # classic
    "div.jobs-description__text",   # classic
    "div[data-test='job-description']",
]

JOB_ABOUT_COMPANY = [
    "[componentkey^='JobDetails_AboutTheCompany']",   # verified
]

JOB_PEOPLE_SLOT = [
    "[componentkey^='JobDetailsPeopleWhoCanHelpSlot']",   # verified
]

# The focused job's own title/company live near the top of the details pane. Not
# captured with a reliable hook, so they are read from the pane by position and text.
JOB_TITLE = [
    "[componentkey^='JobDetails_Header'] h1",
    "h1.jobs-top-card__title",   # classic
    "h1",
]
JOB_COMPANY = [
    "a[data-tracking-control-name*='company']",
    "a.topcard__org-name-link",   # classic
    "span.topcard__flavor",       # classic
]
JOB_POSTED = [
    "[componentkey^='JobDetails_Posted']",
    "span.jobs-posted-ago",   # classic
    "small.jobs-posted-ago",  # classic
]
JOB_SALARY = [
    "[componentkey*='Compensation']",
    "span.jobs-salary__inner",   # classic
]

# Close the focused job and go back to the list.
DETAILS_CLOSE = [
    "button[data-view-name='dismiss-job']",
    "button[aria-label^='Dismiss']",
]


# ---------------------------------------------------------------- easy apply

# Verified: one per focused job, `aria-label="Easy Apply to this job"`. Note that
# cards have none, so this is only present once a job is selected.
EASY_APPLY_BUTTON = [
    "button[data-view-name='job-apply-button'][aria-label*='Easy Apply']",  # verified
    "button[data-view-name='job-apply-button']",
    "button[aria-label*='Easy Apply']",
    "a[href*='openSDUIApplyFlow=true']",
    "button.jobs-apply-button",   # classic
]

# Verified that the in-app apply flow is still flagged by a URL parameter.
IN_APP_APPLY_LINK = ["a[href*='openSDUIApplyFlow=true']"]

EXTERNAL_APPLY_BUTTON = [
    "a[data-tracking-control-name*='apply-link-offsite']",
    "button[data-tracking-control-name*='apply-offsite']",
    "a.jobs-apply-button",   # classic
]

APPLY_BUTTON = EASY_APPLY_BUTTON + EXTERNAL_APPLY_BUTTON

# The flow's own buttons, by text and by view name. `continue-unify` is verified on
# the "Next" button.
APPLY_NEXT_BUTTON = [
    "button[data-view-name='continue-unify']",   # verified
    "button[data-view-name*='continue']",
]
APPLY_NEXT = ["Next", "Continue", "Review", "Submit application"]
# The same list without the submission: the forward button is not always called
# "Next" - the step before submission is labelled "Review", which the classic loop
# searched for by name - but "Submit application" is clicked exactly once, by the
# caller, after the review screen, so it must never answer a request for "Next".
APPLY_NEXT_STEPS = ["Next", "Continue", "Review"]
APPLY_SUBMIT = ["Submit application", "Submit"]
APPLY_DONE = ["Done"]
APPLY_DISCARD = ["Discard application", "Discard", "Delete", "Cancel"]

# The Easy Apply modal, verified against a capture taken with the form on screen: it
# is a native `<dialog data-testid="dialog">` in the top document, holding the header,
# the step's form and the flow's own buttons. A native dialog carries no `role`
# attribute, so `[role='dialog']` - which used to sit at the top of this list - never
# matched it, and the modal was reported as missing while it sat on screen. `body`
# stays here for the capture tool, which must always have something to write; newui
# drops it before searching because answering questions rooted at the page types into
# whatever has focus.
EASY_APPLY_MODAL = [
    "dialog[data-testid='dialog']",           # verified
    "dialog",                                 # verified: the tag alone is unique
    "div.jobs-easy-apply-modal",              # classic
    "[data-test='easy-apply-modal']",
    "[componentkey*='EasyApply']",
    "[componentkey*='Modal']",
    "[role='dialog']",
    "div[data-test-form-element]",
    "body",
]

# The form controls. The classic form marked every question with
# `data-test-form-element`; the SDUI form does not, so `runAiBot.answer_questions()`
# builds its XPath from these: each question is wrapped in a `easyApplyFieldFocus_*`
# key, except the two dropdowns (country code, email), which sit in a plain div
# alongside their own `<label for>`.
FORM_FIELD = [
    "div[componentkey^='easyApplyFieldFocus_']",   # verified (SDUI question)
    "div[data-test-form-element]",
    "div[data-test-single-line-text-form-component]",
    "div[data-test-text-entity-list-form-component]",
    "div[data-test-checkbox-form-component]",
    "div[data-test-combobox-form-component]",
]

RESUME_UPLOAD_INPUT = ["input[type='file']", "input[name='file']"]
RESUME_UPLOAD_BUTTON = [
    "button[data-tracking-control-name*='upload']",
    "label[for*='file']",
    "button[aria-label*='upload' i]",
]


# ---------------------------------------------------------------- filters

# Verified. The new UI's filters are pills and dropdowns whose labels read
# "Filter by <name>", and they resolve to URNs in the URL rather than being ticked
# in a modal. Search automation is deliberately out of scope for now, so these exist
# so the applier can *read* a prepared search, not to build one.
FILTER_CONTROL = [
    "div[aria-label^='Filter by']",                # verified, 44 on the captured page
    "button[aria-label^='Filter by']",
    "[data-view-name='search-filter-top-bar-select']",  # verified, still present
]
FILTER_DROPDOWN = [
    "[data-view-name='job-search-facet-dropdown']",  # verified
    "div[aria-label^='Filter by']",
]
FILTER_PILL = [
    "[data-view-name='job-search-facet-pill']",     # verified
]
ALL_FILTERS_BUTTON = [
    "[componentkey='SearchResults_AllFiltersButton']",   # verified
]
LOCATION_PICKER = [
    "[data-view-name='job-search-location-picker']",   # verified
]
SEARCH_BOX = [
    "[componentkey='semanticSearchBox']",   # verified
]