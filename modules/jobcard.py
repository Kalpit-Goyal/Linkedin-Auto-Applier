'''
Reading job cards off the results list.

Kept separate from `runAiBot.py` because it is the part with the most moving pieces:
the results list re-renders as you scroll, the same job can appear twice, and the
card has to yield an id whether it carries one in an attribute or only in its link.

Job ids are the stable part. LinkedIn identifies a posting as
`urn:li:jobPosting:4123456789`, and every view URL ends in the same digits
(`/jobs/view/senior-data-engineer-at-acme-4123456789`). Both of those formats have
been stable for years, unlike the class names around them, so an id is extracted
from them rather than from whatever the current markup happens to call itself.
'''

import re

from config.settings import click_gap
from modules import selectors
from modules.helpers import print_lg
from modules.sdom import deep_find, deep_find_all, visible_text
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.webdriver import WebDriver


# `urn:li:jobPosting:4123456789`, which is what `data-entity-urn` and friends hold.
_JOB_URN = re.compile(r"urn:li:jobPosting:(\d+)")

# `/jobs/view/<anything>-4123456789`. The slug part is greedy and the id is anchored
# to the end of the path, because a lazy slug match stops at the first digit run and
# would pull "2" out of "/jobs/view/software-engineer-2-4123456789".
_JOB_VIEW_URL = re.compile(r"/jobs/view/[^/?#]*?-?(\d{6,})(?:[/?#]|$)")

# Six digits is a floor, not a guess at the real length: it is there to avoid
# latching onto a stray number in a slug ("remote-2", "level-3") if the optional
# slug part is ever missing.
_JOB_ID = re.compile(r"(\d{6,})")


def id_from_text(value: str | None) -> str | None:
    '''
    Pulls a job id out of a URN or a view URL. Returns None if there isn't one.
    '''
    if not value:
        return None
    value = str(value)
    match = _JOB_URN.search(value) or _JOB_VIEW_URL.search(value)
    if match:
        return match.group(1)
    match = _JOB_ID.search(value)
    return match.group(1) if match else None


def extract_job_id(driver: WebDriver, card: WebElement) -> str | None:
    '''
    The job id for a card, or None if the card yields nothing usable.

    The card's own attributes are tried first, because an id attribute needs no
    interpretation, then the card's link. `get_dom_attribute` is used rather than
    `get_attribute` because it reports the literal DOM value instead of the
    property, which is what these attributes actually are.
    '''
    for attribute in selectors.JOB_ID_ATTRIBUTES:
        try:
            raw = card.get_dom_attribute(attribute)
        except Exception:
            continue
        found = id_from_text(raw)
        if found:
            return found

    for selector in selectors.JOB_CARD_LINK:
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


def card_link(driver: WebDriver, card: WebElement) -> str | None:
    '''The absolute view URL for a card, or None if it has no usable link.'''
    for selector in selectors.JOB_CARD_LINK:
        try:
            links = card.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for link in links:
            try:
                href = link.get_dom_attribute("href")
            except Exception:
                continue
            if not href:
                continue
            if href.startswith("/"):
                base = driver.current_url.split("/jobs/")[0]
                return base + href
            return href
    return None


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


def read_card(driver: WebDriver, card: WebElement) -> dict:
    '''Pulls the text and links a card can offer, tolerating any of them missing.'''
    return {
        "job_id": extract_job_id(driver, card),
        "link": card_link(driver, card),
        "title": _first_text(driver, card, selectors.JOB_CARD_TITLE),
        "company": _first_text(driver, card, selectors.JOB_CARD_COMPANY),
        "location": _first_text(driver, card, selectors.JOB_CARD_LOCATION),
    }


def collect_cards(driver: WebDriver, time: float = 5.0) -> list[WebElement]:
    '''
    Every job card currently rendered, in document order.

    Scoped to the results list when one can be found, because the same selectors
    also match cards inside other panels on the page.
    '''
    results = deep_find(driver, selectors.RESULTS_LIST, time=2)
    root = results if results else None
    cards = deep_find(driver, selectors.JOB_CARD, time=time, root=root, all_elements=True)
    return cards or []


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