'''
Tests for reading job cards off the results list.

The regexes matter most here: a job id that comes back wrong would be written into
the applied-jobs CSV as if it were a real application, and a job id that comes back
as `None` makes the bot skip a job silently. Both failure modes are pinned down
below against the URL and URN formats LinkedIn actually uses.
'''

import pytest

from modules import jobcard, selectors


# ---------------------------------------------------------------- componentkeys

@pytest.mark.parametrize(
    "value,expected",
    [
        # Exactly what the capture found on real cards.
        ("job-card-component-ref-4473342199", "4473342199"),
        # The same trick on the details pane.
        ("JobDetails_AboutTheJob_4473342199", "4473342199"),
        ("JobDetails_AboutTheCompany_4473342199", "4473342199"),
        ("JobDetailsPeopleWhoCanHelpSlot_4473342199", "4473342199"),
        ("JobMatchRef_4473342199", "4473342199"),
    ],
)
def test_job_ids_are_read_out_of_componentkeys(value, expected):
    assert jobcard.id_from_componentkey(value) == expected
    assert jobcard.id_from_text(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        # Real componentkeys from the capture that carry no job id.
        "SearchResults_AllFiltersButton",
        "SearchResultsMainContent",
        "semanticSearchBox",
        "JobsSearchFilters",
        "searchResultsHeaderComponent",
        # A uuid componentkey: short hex runs that must not be mistaken for an id.
        "87799865-a64e-4c8c-9d87-a4dda5c5cf0a",
        "auto-component-00352c33-1014-4ba7-b0ff-da7d202c8de1",
    ],
)
def test_componentkeys_without_a_job_id_yield_nothing(value):
    assert jobcard.id_from_componentkey(value) is None


def test_a_componentkey_prefix_without_a_trailing_id_is_rejected():
    assert jobcard.id_from_componentkey("job-card-component-ref-") is None


class ComponentKeyCard:
    '''A new-UI card: a role="button" div whose componentkey carries the job id.'''

    def __init__(self, job_id, clickable=True):
        self.job_id = job_id
        self.clickable = clickable

    def get_dom_attribute(self, name):
        return None

    def find_elements(self, by, selector):
        if not self.clickable or not self.job_id:
            return []
        prefix = selector.split("^='")[-1].rstrip("']") if "^='" in selector else ""
        if prefix == "job-card-component-ref-":
            return [FakeKey("job-card-component-ref-" + self.job_id)]
        return []


class FakeKey:
    def __init__(self, componentkey):
        self.componentkey = componentkey

    def get_dom_attribute(self, name):
        return self.componentkey if name == "componentkey" else None


def test_a_new_style_card_resolves_its_id_from_the_componentkey():
    '''The captured markup has no data-job-id and no data-entity-urn at all.'''
    card = ComponentKeyCard("4473342199")
    assert jobcard.extract_job_id(None, card) == "4473342199"


def test_a_new_style_card_without_an_id_reports_none_rather_than_guessing():
    assert jobcard.extract_job_id(None, ComponentKeyCard(None)) is None


# ---------------------------------------------------------------- id extraction


@pytest.mark.parametrize(
    "value,expected",
    [
        # The URN forms, as they appear in data-entity-urn and similar attributes.
        ("urn:li:jobPosting:4123456789", "4123456789"),
        ("urn:li:jobPosting:4123456789,4123456790", "4123456789"),
        # View URLs. The slug part is present, absent, or has no dash in it.
        ("https://www.linkedin.com/jobs/view/senior-data-engineer-at-acme-4123456789", "4123456789"),
        ("https://www.linkedin.com/jobs/view/4123456789", "4123456789"),
        ("/jobs/view/data-analyst-4123456789?refId=abc", "4123456789"),
        ("/jobs/view/software-engineer-2-4123456789/", "4123456789"),
        # A bare id.
        ("4123456789", "4123456789"),
    ],
)
def test_job_ids_are_pulled_out_of_every_known_form(value, expected):
    assert jobcard.id_from_text(value) == expected


@pytest.mark.parametrize("value", [None, "", "https://www.linkedin.com/jobs/view/", "not-a-link", "  "])
def test_values_without_a_job_id_return_none(value):
    assert jobcard.id_from_text(value) is None


def test_a_url_with_no_digits_yields_nothing_rather_than_a_wrong_number():
    '''A slug like "remote-2" must not be mistaken for a job id.'''
    assert jobcard.id_from_text("https://www.linkedin.com/jobs/view/remote-2") is None


def test_short_numbers_are_rejected():
    assert jobcard.id_from_text("12345") is None


class FakeCard:
    '''A job card exposing the attribute and link lookups `extract_job_id` uses.'''

    def __init__(self, attributes=None, links=None):
        self.attributes = attributes or {}
        self.links = links or {}

    def get_dom_attribute(self, name):
        return self.attributes.get(name)

    def get_attribute(self, name):
        return self.attributes.get(name)

    def find_elements(self, by, selector):
        href = self.links.get(selector)
        return [FakeLink(href)] if href else []


class FakeLink:
    def __init__(self, href):
        self.href = href

    def get_dom_attribute(self, name):
        return self.href if name == "href" else None

    def get_attribute(self, name):
        return self.href if name == "href" else None


def test_an_attribute_id_is_preferred_over_parsing_the_link():
    card = FakeCard(
        attributes={"data-job-id": "4123456789"},
        links={selectors.JOB_CARD_CLICKABLE[0]: "/jobs/view/999"},
    )
    assert jobcard.extract_job_id(None, card) == "4123456789"


def test_the_most_trustworthy_attribute_wins():
    '''
    `data-job-id` outranks the legacy `data-occludable-job-id`, so a card carrying
    both must resolve to the one the registry lists first.
    '''
    card = FakeCard(attributes={"data-occludable-job-id": "4123456789", "data-job-id": "1111111111"})
    assert jobcard.extract_job_id(None, card) == "1111111111"


def test_the_link_is_used_when_no_attribute_carries_an_id():
    card = FakeCard(links={selectors.JOB_CARD_CLICKABLE[0]: "/jobs/view/analyst-4123456789"})
    assert jobcard.extract_job_id(None, card) == "4123456789"


def test_a_card_with_no_id_anywhere_returns_none():
    assert jobcard.extract_job_id(None, FakeCard()) is None


def test_an_underspecified_attribute_does_not_stop_the_next_candidate():
    card = FakeCard(
        attributes={"data-id": "some-opaque-token"},
        links={selectors.JOB_CARD_CLICKABLE[0]: "/jobs/view/analyst-4123456789"},
    )
    assert jobcard.extract_job_id(None, card) == "4123456789"


def test_an_attribute_that_raises_does_not_stop_the_search():
    class Hostile(FakeCard):
        def get_dom_attribute(self, name):
            if name == "data-job-id":
                raise RuntimeError("stale element reference")
            return None

    card = Hostile(links={selectors.JOB_CARD_CLICKABLE[0]: "/jobs/view/analyst-4123456789"})
    assert jobcard.extract_job_id(None, card) == "4123456789"


def test_relative_card_links_are_made_absolute():
    class Driver:
        current_url = "https://www.linkedin.com/jobs/search-results/?keywords=python"

    card = FakeCard(links={selectors.JOB_CARD_CLICKABLE[0]: "/jobs/view/analyst-4123456789"})
    assert jobcard.card_link(Driver(), card) == "https://www.linkedin.com/jobs/view/analyst-4123456789"


def test_absolute_card_links_are_left_alone():
    class Driver:
        current_url = "https://www.linkedin.com/jobs/search-results/"

    url = "https://www.linkedin.com/jobs/view/analyst-4123456789?x=1"
    card = FakeCard(links={selectors.JOB_CARD_CLICKABLE[0]: url})
    assert jobcard.card_link(Driver(), card) == url


def test_a_card_with_no_link_returns_none():
    class Driver:
        current_url = "https://www.linkedin.com/jobs/search-results/"

    assert jobcard.card_link(Driver(), FakeCard()) is None


# ---------------------------------------------------------------- dedupe


def test_a_job_shown_twice_is_only_counted_once():
    driver = FakeCardDriver(
        cards=[
            FakeCard(attributes={"data-job-id": "4123456789"}),
            FakeCard(attributes={"data-job-id": "4123456790"}),
            FakeCard(attributes={"data-job-id": "4123456789"}),
        ]
    )
    assert jobcard.visible_job_ids(driver) == ["4123456789", "4123456790"]


class FakeCardDriver:
    '''Just enough driver for the card-enumeration helpers.'''

    def __init__(self, cards, grows_on_scroll=None):
        self.cards = cards
        self.grows_on_scroll = grows_on_scroll or []
        self.current_url = "https://www.linkedin.com/jobs/search-results/"
        self.executed = []

    def find_elements(self, by, selector):
        if selector == selectors.JOB_CARD[0]:
            return list(self.cards)
        return []

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            raise LookupError(selector)
        return found[0]

    def execute_script(self, script, *args):
        self.executed.append((script, args))
        if "scrollHeight" in script and self.grows_on_scroll:
            # The new list extends itself as you scroll, which is what makes the
            # returned delta meaningful.
            self.cards.extend(self.grows_on_scroll)
            self.grows_on_scroll = []
        if "out.push({id: id" in script:
            return []
        if "querySelectorAll(selectors[i])" in script:
            return {}
        if "sameOrigin" in script:
            return []
        return []

    class _SwitchTo:
        def default_content(self):
            pass

    @property
    def switch_to(self):
        return FakeCardDriver._SwitchTo()


def test_cards_are_collected_in_document_order():
    ids = [f"41234567{index:02d}" for index in range(5)]
    driver = FakeCardDriver([FakeCard(attributes={"data-job-id": job_id}) for job_id in ids])
    collected = jobcard.collect_cards(driver, time=0)
    assert [jobcard.extract_job_id(driver, card) for card in collected] == ids


def test_scrolling_reports_how_many_new_jobs_arrived():
    '''The return value is what tells the caller whether the scroll was worth anything.'''
    driver = FakeCardDriver(
        [FakeCard(attributes={"data-job-id": "4123456789"})],
        grows_on_scroll=[FakeCard(attributes={"data-job-id": "4123456790"})],
    )
    assert jobcard.scroll_for_more(driver) == 1
    assert any("scrollHeight" in script for script, _ in driver.executed)


def test_scrolling_a_finished_list_reports_nothing_new():
    driver = FakeCardDriver([FakeCard(attributes={"data-job-id": "4123456789"})])
    assert jobcard.scroll_for_more(driver) == 0


# ---------------------------------------------------------------- registry


def test_every_selector_list_is_non_empty_and_prefers_identity_over_hashed_classes():
    '''
    A regression guard on the registry itself. An empty list means a lookup can
    never succeed, and letting a hashed class outrank an identity-based selector
    would undo the entire point of the file.
    '''
    lists = [value for value in vars(selectors).values() if isinstance(value, list) and value]
    assert lists, "expected the registry to expose selector lists"
    for name, value in vars(selectors).items():
        if isinstance(value, list):
            assert all(isinstance(selector, str) and selector for selector in value), f"{name} has a blank selector"

    hashed = ("jobs-easy-apply-modal", "jobs-apply-button", "jobs-box__html-content", "base-search-card__title")
    for candidate in (selectors.JOB_CARD, selectors.JOB_ID_ATTRIBUTES, selectors.EASY_APPLY_BUTTON):
        first = candidate[0]
        assert not any(name in first for name in hashed), f"{candidate} leads with a hashed class: {first}"
        assert any("data-" in selector or "aria-label" in selector or "componentkey" in selector for selector in candidate)


def test_no_playwright_only_pseudo_classes_leaked_into_the_registry():
    '''`:text-matches()` and friends are Playwright syntax and silently never match.'''
    banned = [":text-matches(", ":has-text(", ":visible", ">>"]
    for name, value in vars(selectors).items():
        if isinstance(value, list):
            for selector in value:
                if isinstance(selector, str):
                    assert not any(token in selector for token in banned), f"{name} uses Playwright-only syntax: {selector}"