'''
Tests for the Server-Driven UI traversal helpers.

No real browser here on purpose: the shadow-root and iframe *walk* is the part
that can silently do the wrong thing, so it is exercised against fake drivers that
describe a page's structure. What each test pins down is that
`deep_find()` still returns an element from the right "document" and in the right
order of preference - because `runAiBot.py` chains its own lookups off whatever
element it is handed.
'''

import re

import pytest

from modules import sdom
from selenium.webdriver.common.by import By


HOST_SELECTOR = re.compile(r'^\[data-sdom-host="([^"]+)"\]$')


class FakeElement:
    '''Stands in for a WebElement: answers locators from a per-selector map.'''

    def __init__(self, tag_name="div", matches=None, shadow_root=None, attributes=None, text=""):
        self.tag_name = tag_name
        self.text = text
        self.shadow_root = shadow_root
        self._matches = matches or {}
        self._attributes = attributes or {}

    def find_elements(self, by, selector):
        if by == By.CSS_SELECTOR:
            return list(self._matches.get(selector, []))
        return []

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            raise LookupError(selector)
        return found[0]

    def get_attribute(self, name):
        return self._attributes.get(name)

    def click(self):
        raise AssertionError("tests must not rely on a native click")


class FakeDriver:
    '''
    A driver whose pages are described declaratively:

      * `elements`     - selector -> elements in the top document
      * `frames`       - iframes reachable from the top document
      * `frame_docs`   - frame id -> selector -> elements inside that frame
      * `shadow_hosts` - open shadow roots, each with the parent chain to reach it
      * `shadow_roots`- host id -> the shadow root hanging off that host

    Shadow hosts are synthesised on demand, so a test only has to describe the
    *contents* of each shadow root.
    '''

    def __init__(self, elements=None, frames=None, frame_docs=None, shadow_hosts=None, match_counts=None, shadow_roots=None):
        self.elements = elements or {}
        self.frames = frames or []
        self.frame_docs = frame_docs or {}
        self.shadow_hosts = shadow_hosts or []
        self.match_counts = match_counts or {}
        self.shadow_roots = shadow_roots or {}
        self.frame_stack = []
        self.executed = []

    @property
    def _context(self):
        '''The document currently in scope: the top one, or the innermost frame.'''
        if not self.frame_stack:
            return self.elements
        return self.frame_docs.get(self.frame_stack[-1], {})

    def _synthesised_host(self, host_id):
        return FakeElement(
            "li",
            shadow_root=self.shadow_roots.get(host_id),
            attributes={sdom.HOST_ATTR: host_id, "id": host_id},
        )

    def find_elements(self, by, selector):
        if by != By.CSS_SELECTOR:
            return []
        host = HOST_SELECTOR.match(selector)
        if host and host.group(1) in self.shadow_roots:
            return [self._synthesised_host(host.group(1))]
        return list(self._context.get(selector, []))

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            raise LookupError(selector)
        return found[0]

    def _enter_frame(self, element):
        self.frame_stack.append(element.get_attribute("id") or "")

    def _leave_frame(self):
        if self.frame_stack:
            self.frame_stack.pop()

    class _SwitchTo:
        def __init__(self, driver):
            self.driver = driver

        def frame(self, element):
            self.driver._enter_frame(element)

        def default_content(self):
            self.driver._leave_frame()

    @property
    def switch_to(self):
        return FakeDriver._SwitchTo(self)

    def execute_script(self, script, *args):
        self.executed.append((script, args))
        if "out.push({id: id" in script:
            return self.shadow_hosts
        if "querySelectorAll(selectors[i])" in script:
            return dict(self.match_counts)
        if "sameOrigin" in script:
            return self.frames
        if "textContent" in script:
            return getattr(args[0], "text_content", "") if args else ""
        return []


def frame_element(frame_id="apply"):
    return FakeElement("iframe", attributes={"id": frame_id, "name": "", "src": ""})


def frame_info(frame_id="apply", src="about:blank", same_origin=True):
    return {"tag": "iframe", "id": frame_id, "name": "", "src": src, "sameOrigin": same_origin}


# ---------------------------------------------------------------- normalisation


def test_single_selector_is_wrapped_in_a_list():
    assert sdom._normalise("div.card") == ["div.card"]


def test_blank_selectors_are_dropped():
    assert sdom._normalise(["a", "", None, "b"]) == ["a", "b"]


def test_empty_selectors_never_reach_the_crawler():
    assert sdom.deep_find(FakeDriver(), [], time=0) is False
    assert sdom.deep_find(FakeDriver(), [], time=0, all_elements=True) == []


# ---------------------------------------------------------------- plain document


def test_finds_a_match_in_the_ordinary_document():
    card = FakeElement("li")
    assert sdom.deep_find(FakeDriver(elements={"li.card": [card]}), "li.card", time=0) is card


def test_missing_selector_returns_false_not_an_exception():
    assert sdom.deep_find(FakeDriver(), "li.nope", time=0) is False


def test_candidates_are_tried_in_order_of_preference():
    first = FakeElement("li")
    chosen = FakeElement("section")
    driver = FakeDriver(elements={"li.card": [first], "section.details": [chosen]})
    assert sdom.deep_find(driver, ["li.card", "section.details"], time=0) is first
    assert sdom.deep_find(driver, ["section.details", "li.card"], time=0) is chosen


def test_all_elements_returns_every_candidate_match():
    first, second = FakeElement("li"), FakeElement("li")
    driver = FakeDriver(elements={"li.card": [first, second]})
    assert sdom.deep_find(driver, "li.card", time=0, all_elements=True) == [first, second]


def test_scoping_to_a_root_ignores_the_wider_document():
    inside = FakeElement("span")
    outside = FakeElement("p", matches={"p.inside": [inside]})
    driver = FakeDriver(elements={"p.outside": [outside], "p.inside": [FakeElement("p")]})
    assert sdom.deep_find(driver, "p.inside", time=0, root=outside) is inside


# ---------------------------------------------------------------- shadow roots


def test_finds_a_match_hidden_inside_a_shadow_root():
    hidden = FakeElement("button")
    driver = FakeDriver(
        shadow_hosts=[{"id": "sdom1", "parents": [], "tag": "li"}],
        shadow_roots={"sdom1": FakeElement("#shadow", {"button.easy-apply": [hidden]})},
    )
    assert sdom._matches_in(driver, "button.easy-apply") == []
    assert sdom.deep_find(driver, "button.easy-apply", time=0) is hidden


def test_shadow_walk_is_skipped_when_shadows_are_disabled():
    driver = FakeDriver(
        shadow_hosts=[{"id": "sdom1", "parents": [], "tag": "li"}],
        shadow_roots={"sdom1": FakeElement("#shadow", {"button.easy-apply": [FakeElement("button")]})},
    )
    assert sdom.deep_find(driver, "button.easy-apply", time=0, shadows=False) is False


def test_a_nested_shadow_host_is_reached_through_its_parent():
    '''
    SDUI nests components, so a host inside another host must still resolve. The
    walker has to descend parent by parent rather than looking the nested host up in
    the top document, where it does not exist.
    '''
    target = FakeElement("input")
    inner_shadow = FakeElement("#inner", {"input[name='name']": [target]})
    inner_host = FakeElement("form", shadow_root=inner_shadow, attributes={"id": "sdom2"})
    driver = FakeDriver(
        shadow_hosts=[
            {"id": "sdom1", "parents": [], "tag": "div"},
            {"id": "sdom2", "parents": ["sdom1"], "tag": "form"},
        ],
        shadow_roots={
            "sdom1": FakeElement("#outer", {'[data-sdom-host="sdom2"]': [inner_host]}),
            "sdom2": inner_shadow,
        },
    )
    assert inner_shadow in sdom._shadow_roots(driver, sdom.HOST_ATTR)
    assert sdom.deep_find(driver, "input[name='name']", time=0) is target


def test_a_shadow_host_that_cannot_be_reached_is_skipped_not_fatal():
    driver = FakeDriver(
        elements={"[data-sdom-host='gone']": []},
        shadow_hosts=[{"id": "gone", "parents": [], "tag": "div"}],
        shadow_roots={},
    )
    assert sdom._shadow_roots(driver, sdom.HOST_ATTR) == []


def test_shadow_census_is_namespaced_per_caller():
    '''Two lookups in flight at once must not overwrite each other's host tags.'''
    driver = FakeDriver(shadow_hosts=[])
    sdom._shadow_census(driver, "data-a")
    sdom._shadow_census(driver, "data-b")
    assert [args[0] for script, args in driver.executed if args] == ["data-a", "data-b"]


def test_a_failing_shadow_census_degrades_to_the_plain_document():
    class Broken(FakeDriver):
        def execute_script(self, script, *args):
            raise RuntimeError("shadow roots unavailable")

    card = FakeElement("li")
    assert sdom.deep_find(Broken(elements={"li.card": [card]}), "li.card", time=0) is card


# ---------------------------------------------------------------- iframes


def test_finds_a_match_inside_a_same_origin_iframe():
    '''The Easy Apply form lives in an iframe; reaching it is the whole point.'''
    field = FakeElement("input")
    driver = FakeDriver(
        elements={"iframe": [frame_element("apply")]},
        frames=[frame_info("apply")],
        frame_docs={"apply": {"input": [field]}},
    )
    assert sdom.deep_find(driver, "input", time=0) is field
    assert driver.frame_stack == []


def test_the_context_is_restored_even_when_the_frame_lookup_fails():
    '''
    A leaked frame switch silently corrupts every later lookup in a run, so the top
    document has to be restored whether the search succeeded, failed, or found
    nothing.
    '''
    class Hostile(FakeDriver):
        def _enter_frame(self, element):
            self.frame_stack.append(element.get_attribute("id") or "")
            raise RuntimeError("detached frame")

    driver = Hostile(elements={"iframe": [frame_element("apply")]}, frames=[frame_info("apply")])
    sdom.deep_find(driver, "input", time=0)
    assert driver.frame_stack == []


def test_cross_origin_frames_are_not_entered():
    driver = FakeDriver(
        elements={"iframe": [frame_element("ads")]},
        frames=[frame_info("ads", src="https://ads.example", same_origin=False)],
    )
    sdom.deep_find(driver, "input", time=0)
    assert driver.frame_stack == []


def test_frame_recursion_stops_at_the_depth_limit():
    driver = FakeDriver(elements={"iframe": [frame_element()]}, frames=[frame_info("")])
    assert sdom.deep_find(driver, "never-there", time=0, shadows=False) is False
    assert driver.frame_stack == []


def test_an_unidentifiable_frame_still_gets_a_chance():
    '''Unnamed frames are common; they must not be skipped just for lacking an id.'''
    field = FakeElement("input")
    driver = FakeDriver(
        elements={"iframe": [FakeElement("iframe", attributes={"id": "", "name": ""})]},
        frames=[frame_info("", src="about:blank")],
        frame_docs={"": {"input": [field]}},
    )
    assert sdom.deep_find(driver, "input", time=0) is field


# ---------------------------------------------------------------- text matching


def test_finds_an_element_by_its_visible_text():
    button = FakeElement("button", text="Submit application")
    driver = FakeDriver(elements={"button": [button]})
    assert sdom.deep_find_by_text(driver, "Submit application", time=0) is button


def test_text_matching_is_case_insensitive_and_trims():
    button = FakeElement("span", text="  Next  ")
    driver = FakeDriver(elements={"span": [button]})
    assert sdom.deep_find_by_text(driver, "next", time=0) is button


def test_partial_text_matching_is_opt_in():
    other = FakeElement("span", text="Next step of the wizard")
    driver = FakeDriver(elements={"span": [other]})
    assert sdom.deep_find_by_text(driver, "Next", time=0, exact=True) is False
    assert sdom.deep_find_by_text(driver, "Next", time=0, exact=False) is other


def test_text_matching_reaches_into_shadow_roots():
    hidden = FakeElement("span", text="Submit application")
    driver = FakeDriver(
        shadow_hosts=[{"id": "sdom1", "parents": [], "tag": "div"}],
        shadow_roots={"sdom1": FakeElement("#shadow", {"span": [hidden]})},
    )
    assert sdom.deep_find_by_text(driver, "Submit application", time=0) is hidden


def test_text_matching_reaches_into_iframes():
    button = FakeElement("span", text="Submit application")
    driver = FakeDriver(
        elements={"iframe": [frame_element("apply")]},
        frames=[frame_info("apply")],
        frame_docs={"apply": {"span": [button]}},
    )
    assert sdom.deep_find_by_text(driver, "Submit application", time=0) is button
    assert driver.frame_stack == []


def test_blank_text_never_reaches_the_crawler():
    assert sdom.deep_find_by_text(FakeDriver(), "   ", time=0) is False


def test_text_matching_does_not_click_what_it_finds():
    '''`deep_find_by_text` is a lookup; clicking is `deep_click`'s job.'''
    class Exploding(FakeElement):
        def click(self):
            raise AssertionError("must not click")

    driver = FakeDriver(elements={"span": [Exploding("span", text="Next")]})
    assert sdom.deep_find_by_text(driver, "Next", time=0) is not False


# ---------------------------------------------------------------- clicking


def test_deep_click_dispatches_the_pointer_lifecycle_sdui_needs():
    driver = FakeDriver()
    target = FakeElement("button")
    assert sdom.deep_click(driver, target) is True
    script, args = driver.executed[-1]
    assert "pointerdown" in script and "pointerup" in script
    assert args[0] is target


def test_deep_click_falls_back_to_a_normal_click_when_scripting_is_refused():
    class Refuses(FakeDriver):
        def execute_script(self, script, *args):
            raise RuntimeError("blocked by CSP")

    clicked = {}

    class Clickable(FakeElement):
        def click(self):
            clicked["yes"] = True

    assert sdom.deep_click(Refuses(), Clickable("button")) is True
    assert clicked == {"yes": True}


@pytest.mark.parametrize("element", [None, False])
def test_deep_click_ignores_a_missing_element(element):
    assert sdom.deep_click(FakeDriver(), element) is False


def test_deep_click_reports_failure_instead_of_raising():
    '''
    When the dispatched event is ignored *and* the element has detached, this has
    to come back as a plain `False` so the caller can skip the job - not as an
    exception that aborts the whole run.
    '''
    class Refuses(FakeDriver):
        def execute_script(self, script, *args):
            raise RuntimeError("blocked by CSP")

    class Broken(FakeElement):
        def click(self):
            raise RuntimeError("element detached")

    assert sdom.deep_click(Refuses(), Broken("button")) is False


# ---------------------------------------------------------------- typing


def test_deep_type_focuses_before_typing():
    driver = FakeDriver()
    typed = []

    class Field(FakeElement):
        def send_keys(self, value):
            typed.append(value)

    assert sdom.deep_type(driver, Field("input"), "hello") is True
    assert "hello" in typed


def test_deep_type_reports_failure_instead_of_raising():
    class Broken(FakeElement):
        def send_keys(self, value):
            raise RuntimeError("not focusable")

    assert sdom.deep_type(FakeDriver(), Broken("input"), "hello") is False


@pytest.mark.parametrize("element", [None, False])
def test_deep_type_ignores_a_missing_element(element):
    assert sdom.deep_type(FakeDriver(), element, "hello") is False


# ---------------------------------------------------------------- reporting


def test_selector_report_carries_counts_shadows_and_iframes():
    driver = FakeDriver(
        match_counts={"li.card": 12, "div.missing": 0},
        shadow_hosts=[{"id": "sdom1", "parents": [], "tag": "li"}],
        shadow_roots={"sdom1": FakeElement("#shadow")},
        frames=[frame_info("apply")],
    )
    report = sdom.selector_report(driver, ["li.card", "div.missing"])
    assert report["matches"] == {"li.card": 12, "div.missing": 0}
    assert report["shadow_roots_reachable"] == 1
    assert report["iframes"][0]["id"] == "apply"


def test_visible_text_falls_back_to_text_content_when_dot_text_is_empty():
    '''Shadow-hosted nodes often report no `.text`, so textContent is the fallback.'''
    driver = FakeDriver()
    assert sdom.visible_text(driver, FakeElement("span")) == ""
    assert sdom.visible_text(driver, FakeElement("span", text="Hello")) == "Hello"

    class ShadowOnly(FakeElement):
        text_content = "From textContent"

    assert sdom.visible_text(driver, ShadowOnly("span")) == "From textContent"