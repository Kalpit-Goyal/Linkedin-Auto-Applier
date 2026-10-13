'''
Reading job cards off the results list.

Kept separate from `runAiBot.py` because it is the part with the most moving pieces:
the results list re-renders as you scroll, the same job can appear twice, and the
card has to yield an id whichever way that page happens to carry one.

Where the job id actually is
----------------------------
On the new search a card carries **no id attribute at all**. The captured card is:

    <div role="button" tabindex="0" componentkey="job-card-component-ref-4473342199">
      <div componentkey="job-card-component-ref-4473342199"> ... </div>

- the key sits on the card itself and is repeated on the div inside it (the wrapper
  that used to carry `data-view-name="job-search-job-card"` is gone, which is why
  the card is now found by `componentkey`). so the id is the tail of a
  `componentkey`, and it is read off the element itself before its descendants.
  The same trick works for the details pane
  (`JobDetails_AboutTheJob_4473342199`, `JobMatchRef_4473342199`), which is why
  `id_from_componentkey()` is the first thing tried. The classic attributes and the
  `/jobs/view/` URL are still handled afterwards, for the classic UI.

Note the capture found **25 cards but no apply button on any of them** - the apply
control lives only on the focused job's details pane. So a card has to be selected
before it can be applied to.

Because the list is virtualised (`data-testid="lazy-column"`), the elements returned
here are only valid until the next scroll. Never hold on to them across one.
'''

import re

from config.settings import click_gap
from modules import selectors
from modules.helpers import print_lg
from modules.sdom import deep_find, deep_find_all, visible_text
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.webdriver import WebDriver


# `urn:li:jobPosting:4123456789`, which is what `data-entity-urn` and friends hold.
_JOB_URN = re.compile(r"urn:li:jobPosting:(\d+)")

# `/jobs/view/<anything>-4123456789`. The slug part is greedy and the id is anchored
# to the end of the path, because a lazy slug match stops at the first digit run and
# would pull "2" out of "/jobs/view/software-engineer-2-4123456789".
_JOB_VIEW_URL = re.compile(r"/jobs/view/[^/?#]*?-?(\d{6,})(?:[/?#]|$)")

# A componentkey's job id is always the trailing digit run, e.g.
# `job-card-component-ref-4473342199` or `JobDetails_AboutTheJob_4473342199`.
# Anchoring to the end matters: the other parts are hex-ish and can contain short
# digit runs, and only the id is at the end.
_COMPONENTKEY_TRAILING_ID = re.compile(r"(\d{6,})$")

# Six digits is a floor, not a guess at the real length: it is there to avoid
# latching onto a stray number in a slug ("remote-2", "level-3") if the optional
# slug part is ever missing.
_JOB_ID = re.compile(r"(\d{6,})")


def id_from_componentkey(value: str | None) -> str | None:
    '''
    The job id embedded in a `componentkey`, or None.

    Only a componentkey whose prefix is a known id-bearing one counts, so an
    unrelated key such as `SearchResults_AllFiltersButton` cannot produce a bogus id
    from whatever digits happen to end it.
    '''
    if not value:
        return None
    value = str(value).strip()
    if not any(value.startswith(prefix) for prefix in selectors.JOB_ID_COMPONENTKEYS):
        return None
    match = _COMPONENTKEY_TRAILING_ID.search(value)
    return match.group(1) if match else None


def id_from_text(value: str | None) -> str | None:
    '''
    Pulls a job id out of a componentkey, a URN or a view URL. Returns None if there
    isn't one.
    '''
    if not value:
        return None
    value = str(value)
    found = id_from_componentkey(value)
    if found:
        return found
    match = _JOB_URN.search(value) or _JOB_VIEW_URL.search(value)
    if match:
        return match.group(1)
    match = _JOB_ID.search(value)
    return match.group(1) if match else None


def extract_job_id(driver: WebDriver, card: WebElement) -> str | None:
    '''
    The job id for a card, or None if the card yields nothing usable.

    The order follows where the id actually lives: the card's own `componentkey`
    first, then a descendant's (the captured card repeats its key on the div inside
    it, and `find_elements` only looks at descendants, so a card that *is* the
    keyed element would otherwise yield nothing), then any id-bearing attribute,
    then the link. `get_dom_attribute` is used rather than `get_attribute` because
    it reports the literal DOM value instead of the property, which is what these
    are.
    '''
    try:
        found = id_from_componentkey(card.get_dom_attribute("componentkey"))
    except Exception:
        found = None
    if found:
        return found

    for selector in selectors.JOB_ID_COMPONENTKEYS:
        try:
            holders = card.find_elements(By.CSS_SELECTOR, f"[componentkey^='{selector}']")
        except Exception:
            continue
        for holder in holders:
            try:
                found = id_from_componentkey(holder.get_dom_attribute("componentkey"))
            except Exception:
                continue
            if found:
                return found

    for attribute in selectors.JOB_ID_ATTRIBUTES:
        try:
            raw = card.get_dom_attribute(attribute)
        except Exception:
            continue
        found = id_from_text(raw)
        if found:
            return found

    for selector in selectors.JOB_CARD_CLICKABLE:
        try:
            links = card.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for link in links:
            try:
                found = id_from_text(link.get_dom_attribute("href"))
            except Exception:
                continue
            if found:
                return found

    print_lg("A job card did not carry a job id in any known form.")
    return None


JOB_VIEW_BASE = "https://www.linkedin.com/jobs/view/"


def card_link(driver: WebDriver, card: WebElement) -> str | None:
    '''
    A view URL for the card, or None if the card yields neither a link nor an id.

    New-UI cards are `role="button"` divs with no `<a>` at all, so the URL is built
    from the job id when there is no link to read. `/jobs/view/<id>/` is a
    long-standing canonical form that redirects to the titled URL.
    '''
    for selector in selectors.JOB_CARD_CLICKABLE:
        try:
            links = card.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for link in links:
            try:
                href = link.get_dom_attribute("href")
            except Exception:
                continue
            if not href or "/jobs/view/" not in href:
                continue
            if href.startswith("/"):
                return driver.current_url.split("/jobs/")[0] + href
            return href

    job_id = extract_job_id(driver, card)
    return f"{JOB_VIEW_BASE}{job_id}/" if job_id else None


def _first_text(driver: WebDriver, card: WebElement, candidates: list[str]) -> str:
    for selector in candidates:
        try:
            parts = card.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for part in parts:
            text = visible_text(driver, part).strip()
            if text:
                return text
    return ""


# The captured card's title paragraph opens with a screen-reader label ending in
# "(Verified job)" and follows it with the visible title. Rendered together the two
# run into one string, so everything up to and including the label is dropped; when
# the label is not there the pattern does not match and the text is left alone.
_VERIFIED_JOB_LABEL = re.compile(r"^.*?\(Verified job\)\s*", re.IGNORECASE | re.DOTALL)


def _paragraphs(driver: WebDriver, card: WebElement) -> list[str]:
    '''The visible text of each `<p>` under the card, in document order, empties dropped.'''
    try:
        nodes = card.find_elements(By.CSS_SELECTOR, "p")
    except Exception:
        return []
    out = []
    for node in nodes:
        try:
            text = visible_text(driver, node).strip()
        except Exception:
            continue
        if text:
            out.append(text)
    return out


def _is_new_ui_card(card: WebElement) -> bool:
    '''
    True when this is the SDUI card rather than a classic one.

    The gate exists because the two are read differently: the captured SDUI card
    keeps its fields in `<p>` elements in a fixed order, and only a card carrying
    the job's `componentkey` has that shape. Everything else is read through the
    selector lists, which is what the classic markup needs.
    '''
    try:
        if id_from_componentkey(card.get_dom_attribute("componentkey")):
            return True
    except Exception:
        pass
    try:
        return bool(card.find_elements(By.CSS_SELECTOR, selectors.JOB_CARD_COMPONENTKEY))
    except Exception:
        return False


def _read_fields(driver: WebDriver, card: WebElement) -> tuple[str, str, str]:
    '''
    Title, company and location of a card.

    On the captured card those are the first three non-empty paragraphs, in that
    order. The selector lists cannot express that: every candidate in them returns
    the first match, and all three fields match the same first element, so reading
    the company and the location off the card used to hand back the job title for
    both. The classic markup has no such run of paragraphs, so it keeps the
    selector reading.
    '''
    if _is_new_ui_card(card):
        paragraphs = _paragraphs(driver, card)
        if len(paragraphs) >= 3:
            title = _VERIFIED_JOB_LABEL.sub("", paragraphs[0]).strip()
            return title or paragraphs[0], paragraphs[1], paragraphs[2]
    return (
        _first_text(driver, card, selectors.JOB_CARD_TITLE),
        _first_text(driver, card, selectors.JOB_CARD_COMPANY),
        _first_text(driver, card, selectors.JOB_CARD_LOCATION),
    )


def read_card(driver: WebDriver, card: WebElement) -> dict:
    '''
    Pulls the text and links a card can offer, tolerating any of them missing.

    A dead handle is called out before anything else, because it looks exactly like a
    card with nothing in it: every lookup raises and is swallowed, so the card reads
    as id-less and un-titled. The applier holds a whole pass of handles while it
    works, and a modal opening or a click remounts the list, which kills the rest of
    the pass - a different problem from a card that genuinely carries no id, and one
    that only the log can distinguish after the fact.
    '''
    try:
        card.get_dom_attribute("componentkey")
    except StaleElementReferenceException:
        print_lg("A stale card handle: the results list re-rendered during this pass, "
                 "so the cards left in it cannot be read.")
        return {"job_id": None, "link": "", "title": "", "company": "", "location": ""}
    title, company, location = _read_fields(driver, card)
    return {
        "job_id": extract_job_id(driver, card),
        "link": card_link(driver, card),
        "title": title,
        "company": company,
        "location": location,
    }


def collect_cards(driver: WebDriver, time: float = 5.0) -> list[WebElement]:
    '''
    Every job card currently rendered, in document order.

    Scoped to the results list when one can be found, because the same selectors
    also match cards inside other panels on the page. Frames are not searched: a
    job card has never rendered inside an iframe (the Easy Apply form does, and
    that is the only reason the traversal exists), and the permissive selectors
    further down the list happily match list items inside ad frames, which then
    show up as cards with no readable job id.
    '''
    results = deep_find(driver, selectors.RESULTS_LIST, time=2)
    root = results if results else None
    cards = deep_find(driver, selectors.JOB_CARD, time=time, root=root, frames=False, all_elements=True)
    if cards:
        return _dedupe_by_job_id(driver, cards)
    # Link fallback is only safe inside a located results container. Without one,
    # `/jobs/view/` links are sidebar/recommended jobs, not results to apply to, and
    # treating them as cards is what made the applier silently find nothing to do.
    if root is None:
        return []
    try:
        links = deep_find_all(driver, "a[href*='/jobs/view/']", time=2.0, root=root, frames=False)
        out = []
        seen = set()
        for link in links:
            jid = id_from_text(link.get_dom_attribute("href") or "")
            if not jid or jid in seen:
                continue
            seen.add(jid)
            out.append(_link_card_ancestor(link))
        if out:
            return out
    except Exception:
        pass
    return []


def _dedupe_by_job_id(driver: WebDriver, cards: list[WebElement]) -> list[WebElement]:
    '''
    One card per job id.

    JOB_CARD lists overlapping selectors (e.g. an exact and a `*=` variant both match
    the same element), and deep_find unions every selector under `all_elements`, so
    the same card can be returned several times. Cards with no readable id are kept
    as-is because they cannot be compared.
    '''
    out = []
    seen = set()
    for card in cards:
        jid = extract_job_id(driver, card)
        if not jid:
            out.append(card)
            continue
        if jid in seen:
            continue
        seen.add(jid)
        out.append(card)
    return out


def _link_card_ancestor(link: WebElement) -> WebElement:
    '''
    Closest ancestor of a job-view link that wraps exactly one job.

    Walks up while the ancestor still contains only this one job link, so a shared
    list container is never mistaken for a card. Returns the tightest ancestor, or
    the link itself if even its parent is ambiguous.
    '''
    best = link
    node = link
    for _ in range(12):
        try:
            parent = node.find_element(By.XPATH, "..")
            tag = parent.tag_name.lower()
        except Exception:
            break
        if tag in ("body", "html"):
            break
        # Ambiguous once more than one job link shares this ancestor.
        try:
            if len(parent.find_elements(By.CSS_SELECTOR, "a[href*='/jobs/view/']")) > 1:
                break
        except Exception:
            break
        try:
            cls = parent.get_attribute("class") or ""
            role = parent.get_attribute("role") or ""
        except Exception:
            cls, role = "", ""
        if role == "listitem" or "card" in cls:
            return parent
        best = parent
        node = parent
    return best


def visible_job_ids(driver: WebDriver) -> list[str]:
    '''Job ids for every card currently on screen, in order, without duplicates.'''
    found = []
    seen = set()
    for card in collect_cards(driver):
        job_id = extract_job_id(driver, card)
        if job_id and job_id not in seen:
            seen.add(job_id)
            found.append(job_id)
    return found


def scroll_for_more(driver: WebDriver) -> int:
    '''
    Scrolls the results list to the bottom and returns how many job ids are on
    screen afterwards.

    The new list grows on scroll rather than paginating, so the count is what tells
    the caller whether anything new actually arrived.
    '''
    before = len(visible_job_ids(driver))

    load_more = deep_find(driver, selectors.LOAD_MORE, time=1)
    if load_more:
        from modules.sdom import deep_click

        if deep_click(driver, load_more):
            print_lg("Clicked 'Load more results'.")
            from modules.helpers import sleep

            sleep(click_gap)

    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    except Exception:
        pass

    from modules.helpers import sleep

    sleep(2)
    return len(visible_job_ids(driver)) - before