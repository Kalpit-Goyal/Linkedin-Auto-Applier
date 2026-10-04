'''
Driving the new (server-driven) job search UI.

Scope: everything that touches the DOM for the new search, and nothing else. No
config, no counters, no CSV, no dialogs - those stay in `runAiBot.py`. Keeping this
split means the selectors can be exercised against a fake driver, and that a failure
here can never corrupt the applied-jobs history.

The flow this module supports, and why it is shaped this way
-----------------------------------------------------------
The capture established three facts that dictate the shape of everything below.

1. **Cards carry no apply button** (0 of 25 on the captured page). The apply control
   exists only once a job is selected, so a job has to be opened before it can be
   applied to. Hence `select_card()` before anything else.

2. **The card's job id is the tail of a `componentkey`**
   (`job-card-component-ref-4473342199`). That is also a precise way to confirm the
   details pane belongs to the card we just clicked: the pane repeats the id in
   `JobDetails_AboutTheJob_4473342199`, so `select_card()` can check that the pane
   it opened is the one it meant to open, rather than trusting that a click landed.

3. **The results list is virtualised** (`data-testid="lazy-column"`). Card elements
   are recycled as you scroll, so a card is read, acted on, and dropped before
   anything scrolls. `list_cards()` exists to be called again, never cached.

Search automation is deliberately out of scope: the caller is expected to have set
up the search already, filters included.
'''

from time import sleep
import re

from modules import jobcard, selectors
from modules.helpers import print_lg
from modules.sdom import deep_click, deep_find, deep_find_by_text, visible_text
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver


APPLY_EASY = "easy"
APPLY_EXTERNAL = "external"
APPLY_NONE = "none"
APPLY_ALREADY = "already"

# The capture tool falls back to <body> so it always has something to write. The bot
# must not: <body> is not a modal, and answering questions against the whole page
# would type into whatever happened to have focus.
MODAL_CANDIDATES = [s for s in selectors.EASY_APPLY_MODAL if s != "body"]

# "Posted 3 days ago" and "Posted just now" are dates; a bare "Posted" is a heading.
POSTED_LINE = re.compile(r"^posted\s+\S", re.IGNORECASE)


# ---------------------------------------------------------------- results list


def results_ready(driver: WebDriver, time: float = 15.0) -> bool:
    '''True once at least one job card is on screen.'''
    cards = deep_find(driver, selectors.JOB_CARD, time=time, all_elements=True)
    if not cards:
        print_lg("No job cards found. Is the results list still loading, or does this search have no results?")
        return False
    return True


def open_results(driver: WebDriver, url: str = selectors.AI_SEARCH_URL) -> None:
    '''Navigates to a prepared search. Building that URL is the caller's job.'''
    print_lg(f"Opening the prepared search:\n{url}")
    driver.get(url)


def list_cards(driver: WebDriver, time: float = 5.0) -> list:
    '''
    Job cards currently rendered, in order.

    Re-read on every call on purpose: the list is virtualised, so a list held across
    a scroll would point at elements LinkedIn has already reused for other jobs.
    '''
    return jobcard.collect_cards(driver, time=time)


# ---------------------------------------------------------------- selecting a job


def select_card(driver: WebDriver, card, time: float = 8.0) -> bool:
    '''
    Opens a card's details pane, and confirms it is the pane for *that* job.

    The confirmation matters because the list re-renders and a click can land late or
    nowhere. Without it, the previous job's details stay on screen and every later
    step - apply, submit, log - would act on the wrong posting. The pane carries the
    job id in its own `componentkey`, so this is an exact check rather than a sleep.
    '''
    job_id = jobcard.extract_job_id(driver, card)
    if not job_id:
        print_lg("Could not read a job id from this card.")
        return False

    clickable = deep_find(driver, selectors.JOB_CARD_CLICKABLE, time=1, root=card)
    if not clickable:
        print_lg(f"Could not find a clickable region on job {job_id}.")
        return False

    if not deep_click(driver, clickable):
        try:
            clickable.click()
        except Exception as e:
            print_lg(f"Could not open job {job_id}: {e}")
            return False

    if _details_belong_to(driver, job_id, time):
        return True

    # The scripted pointer dispatch is sometimes ignored. A real click is the
    # fallback that LinkedIn's own handlers respond to.
    try:
        clickable.click()
    except Exception:
        pass
    return _details_belong_to(driver, job_id, time)


def _details_belong_to(driver: WebDriver, job_id: str, time: float) -> bool:
    '''True when the details pane on screen is showing the given job.'''
    waited = 0.0
    step = 0.5
    while waited <= time:
        panes = deep_find(driver, selectors.DETAILS_PANE, time=0, all_elements=True)
        for pane in panes or []:
            try:
                key = pane.get_dom_attribute("componentkey") or ""
            except Exception:
                continue
            if jobcard.id_from_componentkey(key) == job_id:
                return True
        sleep(step)
        waited += step

    open_id = focused_job_id(driver)
    if open_id and open_id != job_id:
        print_lg(f"Clicked job {job_id} but the pane is showing {open_id} instead.")
    else:
        print_lg(f"Job {job_id} was clicked but its details pane never confirmed.")
    return False


def focused_job_id(driver: WebDriver) -> str | None:
    '''The job id of whatever is currently open in the details pane, if anything.'''
    panes = deep_find(driver, selectors.DETAILS_PANE, time=1, all_elements=True)
    for pane in panes or []:
        try:
            key = pane.get_dom_attribute("componentkey") or ""
        except Exception:
            continue
        found = jobcard.id_from_componentkey(key)
        if found:
            return found
    return None


def close_details(driver: WebDriver) -> None:
    '''Closes the details pane so the list is fully visible again.'''
    button = deep_find(driver, selectors.DETAILS_CLOSE, time=1)
    if button:
        deep_click(driver, button)


# ---------------------------------------------------------------- pagination


def current_page(driver: WebDriver) -> int | None:
    '''
    Which page the results are on, read off the pagination control.

    Verified: the page you are on is the one button with `aria-current="true"`, and
    every other page button reads `"false"`. Reading the control beats counting clicks,
    which drift the moment a page turn is slow and the next click lands on the same page.
    '''
    buttons = deep_find(driver, selectors.PAGINATION_CURRENT, time=1, all_elements=True)
    for button in buttons or []:
        number = _page_number(button)
        if number:
            return number

    # Same rule, without leaning on the dedicated selector: whichever page button is
    # flagged as the current one.
    for button in deep_find(driver, selectors.PAGINATION_PAGE, time=0, all_elements=True) or []:
        try:
            if (button.get_dom_attribute("aria-current") or "").strip().lower() == "true":
                return _page_number(button)
        except Exception:
            continue
    return None


def go_to_next_page(driver: WebDriver, page: int, time: float = 6.0) -> bool:
    '''
    Turns to page + 1, and confirms the turn happened.

    Returns False at the end of the results, which is a normal stop rather than a
    failure - the caller should finish, not retry.
    '''
    button = deep_find(
        driver,
        [f"button[aria-label='Page {page + 1}']"] + selectors.PAGINATION_NEXT,
        time=2,
    )
    if not button:
        return False
    if not deep_click(driver, button):
        return False

    sleep(2)
    landed = current_page(driver)
    if landed is not None and landed != page + 1:
        print_lg(f"Asked for page {page + 1} but the control still reads {landed}.")
        return False
    return True


def _page_number(button) -> int | None:
    try:
        label = button.get_dom_attribute("aria-label") or ""
    except Exception:
        return None
    digits = re.search(r"\d+", label)
    return int(digits.group()) if digits else None


# ---------------------------------------------------------------- reading a job


def read_details(driver: WebDriver) -> dict:
    '''
    What the details pane can tell us about the open job.

    The description, company blurb, people slot and comp all have verified
    componentkeys. The title and company do not - the capture found no hook on
    either - so they are absent here and the caller falls back to the card, where
    both were readable. Inventing a selector would be worse than admitting the gap.
    '''
    def text_of(candidates) -> str:
        found = deep_find(driver, candidates, time=2)
        return visible_text(driver, found).strip() if found else ""

    return {
        "job_id": focused_job_id(driver),
        "description": text_of(selectors.JOB_DESCRIPTION),
        "about_company": text_of(selectors.JOB_ABOUT_COMPANY),
        "people": text_of(selectors.JOB_PEOPLE_SLOT),
        "salary": text_of(selectors.JOB_SALARY),
    }


def read_posted_date(driver: WebDriver) -> str:
    '''
    The "Posted N days ago" line for the open job.

    In the capture this is a plain `div > span` with no data attribute, so it is
    matched on the shape of the words rather than on a selector. "Posted" on its own
    is a section heading and does not count; a posting age must follow it, as in
    "Posted 3 days ago" or "Posted just now". Anything else is ignored rather than
    guessed at, because this ends up in the CSV as the date a job was listed.
    '''
    pane = deep_find(driver, selectors.JOB_DESCRIPTION, time=2)
    if not pane:
        return "Unknown"
    try:
        for node in pane.find_elements(By.CSS_SELECTOR, "span"):
            text = visible_text(driver, node).strip()
            if POSTED_LINE.match(text):
                return text
    except Exception:
        pass
    return "Unknown"


# ---------------------------------------------------------------- applying


def apply_mode(driver: WebDriver) -> str:
    '''
    How this job can be applied to: Easy Apply, off-site, already applied, or not.

    The verified button comes first because it is the only thing seen on a real job;
    the URL-based hints are fallbacks for layouts that have not been captured.
    '''
    if deep_find(driver, selectors.EASY_APPLY_BUTTON, time=1):
        return APPLY_EASY
    if deep_find(driver, selectors.IN_APP_APPLY_LINK, time=0):
        return APPLY_EASY
    if deep_find(driver, selectors.EXTERNAL_APPLY_BUTTON, time=1):
        return APPLY_EXTERNAL

    # Nothing to click. Either already applied, or closed for applications.
    if deep_find(driver, ["button[aria-label*='Applied' i]", "text=Apply applied"], time=0):
        return APPLY_ALREADY
    return APPLY_NONE


def open_easy_apply(driver: WebDriver, time: float = 10.0):
    '''
    Opens the Easy Apply modal and returns it, or False if it never appeared.

    Verified: the button is `button[data-view-name="job-apply-button"]` and exists
    only on a selected job. The modal's own markup is *not* verified, so it is found
    through the registry's ranked candidates - minus the `<body>` fallback - and the
    caller is expected to confirm the flow's own controls are inside it.
    '''
    button = deep_find(driver, selectors.EASY_APPLY_BUTTON, time=3)
    if not button:
        print_lg("No Easy Apply button on this job.")
        return False

    if not deep_click(driver, button):
        try:
            button.click()
        except Exception as e:
            print_lg(f"Could not click Easy Apply: {e}")
            return False

    modal = deep_find(driver, MODAL_CANDIDATES, time=time)
    if not modal:
        print_lg("Easy Apply was clicked but no modal appeared.")
        return False

    print_lg("Easy Apply modal opened.")
    return modal


def refind_modal(driver: WebDriver, time: float = 4.0):
    '''
    Re-acquires the modal, which the flow replaces as it moves between steps.

    Between the resume step, the questions and the review screen LinkedIn swaps the
    dialog's contents, and the element handle captured at the start can go stale. The
    previous handle is kept as a fallback so a failed re-find does not throw away a
    modal that is still on screen.
    '''
    return deep_find(driver, MODAL_CANDIDATES, time=time)


def advance(driver: WebDriver, root, label: str, time: float = 4.0) -> bool:
    '''
    Clicks one of the flow's buttons by label, e.g. "Next" or "Submit application".

    `continue-unify` is tried first for "Next" because that view name is verified;
    text matching covers the buttons whose markup has not been seen yet.
    '''
    if label.lower().startswith("next"):
        button = deep_find(driver, selectors.APPLY_NEXT_BUTTON, time=1, root=root)
        if button:
            return deep_click(driver, button)

    button = find_by_label(driver, label, root=root, time=time)
    return bool(button) and deep_click(driver, button)


def find_by_label(driver: WebDriver, label: str, root=None, time: float = 4.0):
    '''Finds a button, span or link by its visible text, across shadow roots and frames.'''
    return deep_find_by_text(driver, label, time=time, root=root, tags=("button", "span", "a"))


def discard_application(driver: WebDriver, root=None, actions=None) -> None:
    '''
    Backs out of an application without submitting it.

    The confirm dialog's buttons are matched by text because the dialog is one of the
    pieces of this flow whose markup has not been captured. `actions` is the caller's
    existing ActionChains, passed in rather than built here, so this module stays
    free of driver setup.
    '''
    if actions is not None:
        try:
            from selenium.webdriver.common.keys import Keys

            actions.send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

    found = find_by_label(driver, "Discard", root=root, time=1)
    if not found:
        found = deep_find_by_text(driver, "Discard", time=1, exact=False, tags=("button", "span"))
    if found:
        deep_click(driver, found)
    else:
        print_lg("No Discard button found; the application may still be open.")
    sleep(1)