'''
Tests for driving the new search UI.

These cover the decisions `modules/newui.py` makes, not the traversal in
`modules/sdom.py` (which has its own tests). The important ones are the safety
properties, because each of them exists because getting it wrong means submitting an
application to the wrong job:

- a click that lands on the wrong card must be detected, not absorbed
- a card whose id cannot be read must be refused, not applied to blindly
- the Easy Apply modal must never resolve to `<body>`, because answering questions
  against the page types into whatever happens to have focus
'''

import pytest

from modules import newui, selectors


# ---------------------------------------------------------------- harness


class FakeNode:
    '''An element with just enough surface for the lookups under test.'''

    def __init__(self, componentkey=None, text="", children=None, aria=None):
        self.componentkey = componentkey
        self.text = text
        self.children = children or []
        self.aria = aria or {}
        self.clicks = 0

    def get_dom_attribute(self, name):
        if name == "componentkey":
            return self.componentkey
        if name.startswith("aria-"):
            return self.aria.get(name)
        return None

    def find_elements(self, by, selector):
        return self.children if selector == "span" else []

    def click(self):
        self.clicks += 1
        return True


class FakeCard(FakeNode):
    '''A new-UI card: a role="button" div carrying the job id in its componentkey.'''

    def find_elements(self, by, selector):
        if selectors.JOB_CARD_COMPONENTKEY in selector:
            return [FakeNode(componentkey="job-card-component-ref-" + self.componentkey)]
        return []


class Recorder:
    '''Stands in for `sdom.deep_find` and `sdom.deep_click` with a selector map.'''

    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.clicked = []
        self.asked = []

    def find(self, driver, candidates, time=0, root=None, all_elements=False, **kwargs):
        candidates = [candidates] if isinstance(candidates, str) else list(candidates)
        self.asked.append(candidates[0] if candidates else None)
        for candidate in candidates:
            found = self.mapping.get(candidate)
            if found:
                return list(found) if all_elements else found[0]
        return [] if all_elements else False

    def click(self, driver, element, scroll_back=True):
        self.clicked.append(element)
        return True


def install(monkeypatch, mapping=None):
    recorder = Recorder(mapping)
    monkeypatch.setattr(newui, "deep_find", recorder.find)
    monkeypatch.setattr(newui, "deep_click", recorder.click)
    return recorder


# ---------------------------------------------------------------- selecting a card


def test_a_card_is_only_opened_when_its_own_details_pane_confirms(monkeypatch):
    '''
    The headline safety property. The pane repeats the job id in its componentkey, so
    a card can be matched against the pane it opened instead of trusting the click.
    '''
    recorder = install(
        monkeypatch,
        {
            selectors.JOB_CARD_CLICKABLE[0]: [FakeNode()],
            selectors.DETAILS_PANE[0]: [FakeNode(componentkey="JobDetails_AboutTheJob_4473342199")],
        },
    )
    assert newui.select_card(None, FakeCard("4473342199"), time=0) is True
    assert recorder.clicked


def test_a_click_that_opens_the_wrong_job_is_rejected(monkeypatch):
    '''
    Cards are recycled by the virtualised list, so a click can land on a neighbouring
    row. Accepting this would apply to the job that happens to be on screen.
    '''
    install(
        monkeypatch,
        {
            selectors.JOB_CARD_CLICKABLE[0]: [FakeNode()],
            selectors.DETAILS_PANE[0]: [FakeNode(componentkey="JobDetails_AboutTheJob_9999999999")],
        },
    )
    assert newui.select_card(None, FakeCard("4473342199"), time=0) is False


def test_a_pane_from_a_different_source_is_not_mistaken_for_a_match(monkeypatch):
    '''
    Several panes share the `JobDetails_` prefix and some carry no id at all. Only an
    exact id match counts, so a uuid componentkey cannot stand in for one.
    '''
    install(
        monkeypatch,
        {
            selectors.JOB_CARD_CLICKABLE[0]: [FakeNode()],
            selectors.DETAILS_PANE[0]: [
                FakeNode(componentkey="87799865-a64e-4c8c-9d87-a4dda5c5cf0a"),
                FakeNode(componentkey="JobMatchRef_9999999999"),
            ],
        },
    )
    assert newui.select_card(None, FakeCard("4473342199"), time=0) is False


def test_a_card_with_no_readable_id_is_refused_before_anything_is_clicked(monkeypatch):
    recorder = install(monkeypatch, {selectors.JOB_CARD_CLICKABLE[0]: [FakeNode()]})
    assert newui.select_card(None, FakeCard(None), time=0) is False
    assert recorder.clicked == []


def test_a_click_that_never_opens_a_pane_is_reported_as_a_failure(monkeypatch):
    install(monkeypatch, {selectors.JOB_CARD_CLICKABLE[0]: [FakeNode()]})
    assert newui.select_card(None, FakeCard("4473342199"), time=0) is False


# ---------------------------------------------------------------- focused job


def test_the_open_job_is_read_from_the_pane(monkeypatch):
    install(monkeypatch, {selectors.DETAILS_PANE[0]: [FakeNode(componentkey="JobDetails_AboutTheJob_4473342199")]})
    assert newui.focused_job_id(None) == "4473342199"


def test_nothing_open_means_no_job_id(monkeypatch):
    install(monkeypatch)
    assert newui.focused_job_id(None) is None


def test_a_pane_without_an_id_yields_none_rather_than_a_wrong_number(monkeypatch):
    install(monkeypatch, {selectors.DETAILS_PANE[0]: [FakeNode(componentkey="SearchResultsMainContent")]})
    assert newui.focused_job_id(None) is None


# ---------------------------------------------------------------- apply mode


@pytest.mark.parametrize(
    "present,expected",
    [
        ([selectors.EASY_APPLY_BUTTON[0]], newui.APPLY_EASY),
        ([selectors.IN_APP_APPLY_LINK[0]], newui.APPLY_EASY),
        ([selectors.EXTERNAL_APPLY_BUTTON[0]], newui.APPLY_EXTERNAL),
        (["button[aria-label*='Applied' i]"], newui.APPLY_ALREADY),
    ],
)
def test_apply_mode_reads_the_job(monkeypatch, present, expected):
    install(monkeypatch, {selector: [FakeNode()] for selector in present})
    assert newui.apply_mode(None) == expected


def test_a_job_with_nothing_to_click_is_not_treated_as_easy_apply(monkeypatch):
    '''The default matters: Easy Apply must never be assumed, or the bot will try to
    answer a form on a job that only takes off-site applications.'''
    install(monkeypatch)
    assert newui.apply_mode(None) == newui.APPLY_NONE


def test_a_verified_easy_apply_button_outranks_an_external_link(monkeypatch):
    '''Both can be present on the same job, and the in-app one is what we can drive.'''
    install(
        monkeypatch,
        {
            selectors.EASY_APPLY_BUTTON[0]: [FakeNode()],
            selectors.EXTERNAL_APPLY_BUTTON[0]: [FakeNode()],
        },
    )
    assert newui.apply_mode(None) == newui.APPLY_EASY


# ---------------------------------------------------------------- the modal


def test_the_modal_is_never_resolved_to_the_body():
    '''
    `<body>` is in the registry for the capture tool, which must always have something
    to write. For the bot it is a trap: answering questions rooted at the page types
    into whatever has focus.
    '''
    assert "body" in selectors.EASY_APPLY_MODAL
    assert "body" not in newui.MODAL_CANDIDATES


def test_opening_easy_apply_reports_failure_when_no_modal_appears(monkeypatch):
    install(monkeypatch, {selectors.EASY_APPLY_BUTTON[0]: [FakeNode()]})
    assert newui.open_easy_apply(None, time=0) is False


def test_opening_easy_apply_reports_failure_when_there_is_no_button(monkeypatch):
    install(monkeypatch)
    assert newui.open_easy_apply(None, time=0) is False


def test_opening_easy_apply_returns_the_modal_it_found(monkeypatch):
    modal = FakeNode(componentkey="EasyApplyModal")
    install(monkeypatch, {selectors.EASY_APPLY_BUTTON[0]: [FakeNode()], newui.MODAL_CANDIDATES[0]: [modal]})
    assert newui.open_easy_apply(None, time=0) is modal


# ---------------------------------------------------------------- posting date


def test_a_posted_line_is_read_out_of_the_description(monkeypatch):
    pane = FakeNode(children=[FakeNode(text="Posted 3 days ago"), FakeNode(text="Be one of the first")])
    install(monkeypatch, {selectors.JOB_DESCRIPTION[0]: [pane]})
    assert newui.read_posted_date(None) == "Posted 3 days ago"


def test_text_that_is_not_a_posting_age_is_ignored(monkeypatch):
    '''This string is written to the applied-jobs CSV as the listing date, so a
    description sentence must never be captured as one.'''
    pane = FakeNode(children=[FakeNode(text="Posted"), FakeNode(text="Great company to work for")])
    install(monkeypatch, {selectors.JOB_DESCRIPTION[0]: [pane]})
    assert newui.read_posted_date(None) == "Unknown"


def test_no_description_means_an_unknown_date(monkeypatch):
    install(monkeypatch)
    assert newui.read_posted_date(None) == "Unknown"


# ---------------------------------------------------------------- details


def test_details_are_read_from_the_verified_componentkeys(monkeypatch):
    description = FakeNode(text="Build and ship models.")
    about = FakeNode(text="We are a big energy company.")
    people = FakeNode(text="Ravi is the hiring manager.")
    install(
        monkeypatch,
        {
            selectors.DETAILS_PANE[0]: [FakeNode(componentkey="JobDetails_AboutTheJob_4473342199")],
            selectors.JOB_DESCRIPTION[0]: [description],
            selectors.JOB_ABOUT_COMPANY[0]: [about],
            selectors.JOB_PEOPLE_SLOT[0]: [people],
        },
    )
    details = newui.read_details(None)
    assert details["job_id"] == "4473342199"
    assert details["description"] == "Build and ship models."
    assert details["about_company"] == "We are a big energy company."
    assert details["people"] == "Ravi is the hiring manager."


def test_details_omit_the_title_and_company_rather_than_guessing(monkeypatch):
    '''
    The capture found no reliable hook for either, so they are read from the card by
    the caller. Reporting a guess here would silently corrupt the CSV's company column.
    '''
    install(monkeypatch, {selectors.DETAILS_PANE[0]: [FakeNode(componentkey="JobDetails_AboutTheJob_4473342199")]})
    details = newui.read_details(None)
    assert "title" not in details
    assert "company" not in details
    assert details["description"] == ""


# ---------------------------------------------------------------- pagination


def page_button(number, current=False):
    return FakeNode(aria={"aria-label": f"Page {number}", "aria-current": "true" if current else "false"})


def test_the_current_page_is_read_from_the_flagged_button(monkeypatch):
    install(monkeypatch, {selectors.PAGINATION_CURRENT[0]: [page_button(2, current=True)]})
    assert newui.current_page(None) == 2


def test_the_page_is_still_found_when_the_dedicated_selector_does_not_match(monkeypatch):
    install(monkeypatch, {selectors.PAGINATION_PAGE[0]: [page_button(3, current=True), page_button(1)]})
    assert newui.current_page(None) == 3


def test_a_control_with_no_current_page_reads_as_none(monkeypatch):
    '''Nothing flagged as current means no page is guessed, so the caller stops.'''
    install(
        monkeypatch,
        {
            selectors.PAGINATION_CURRENT[0]: [],
            selectors.PAGINATION_PAGE[0]: [page_button(1), page_button(2)],
        },
    )
    assert newui.current_page(None) is None


def test_no_pagination_at_all_reads_as_none(monkeypatch):
    install(monkeypatch)
    assert newui.current_page(None) is None


def test_the_end_of_the_results_is_a_normal_stop_not_a_failure(monkeypatch):
    '''One page of results is the common case, so this must return False quietly.'''
    install(monkeypatch, {selectors.PAGINATION_CURRENT[0]: [page_button(1, current=True)]})
    assert newui.go_to_next_page(None, page=1) is False


def test_a_page_turn_is_confirmed_rather_than_assumed(monkeypatch):
    install(
        monkeypatch,
        {
            "button[aria-label='Page 2']": [page_button(2)],
            selectors.PAGINATION_CURRENT[0]: [page_button(2, current=True)],
        },
    )
    assert newui.go_to_next_page(None, page=1) is True


def test_a_page_turn_that_does_not_happen_is_reported(monkeypatch):
    '''
    The control still reads page 1 after clicking, so the turn did not take. Returning
    True here would make the caller apply to the same jobs a second time.
    '''
    install(
        monkeypatch,
        {
            "button[aria-label='Page 2']": [page_button(2)],
            selectors.PAGINATION_CURRENT[0]: [page_button(1, current=True)],
        },
    )
    assert newui.go_to_next_page(None, page=1) is False