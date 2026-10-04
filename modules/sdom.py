'''
Traversal helpers for LinkedIn's Server-Driven UI (SDUI).

Why this module exists
----------------------
The rebuilt job search at `https://www.linkedin.com/jobs/search-results/` and its
Easy Apply modal are assembled at runtime out of components that carry hashed
class names and semantic `componentkey` attributes. Two pieces of that markup
also sit behind boundaries plain Selenium cannot see through:

  * **Shadow DOM** - nodes inside an *open* shadow root are invisible to
    `driver.find_element`, because the document's own query API never descends
    into a shadow tree.
  * **Same-origin iframes** - the Easy Apply form is rendered inside an iframe,
    so a lookup against the top document cannot reach a single form field.

That is the whole reason most third-party appliers stopped working against
LinkedIn, so this module exists to walk all three trees - top document, then
open shadow roots, then same-origin iframes - and return ordinary `WebElement`
objects rooted in whichever document actually contains the match.

The elements handed back are deliberately *real* `WebElement`s from the correct
document. `runAiBot.py` already chains its lookups off whatever element it is
given (`modal.find_element(...)` in `answer_questions()` and `upload_resume()`),
so returning genuine elements means those routines keep working against an
iframe-hosted modal without being rewritten.

Clicks need `deep_click`
------------------------
SDUI components bind pointer events, and Selenium's `.click()` synthesises a
mouse event that they routinely ignore. `deep_click()` dispatches the full
pointer + mouse lifecycle instead, which is what these handlers actually listen
for. It always restores the original scroll position afterwards.
'''

import time

from config.settings import smooth_scroll
from modules.helpers import print_lg, sleep
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.remote.webdriver import WebDriver


# LinkedIn nests its SDUI components a few levels deep at most. These bounds keep a
# pathological page from turning a single lookup into a very long crawl.
MAX_SHADOW_DEPTH = 3
MAX_FRAME_DEPTH = 3

# Attribute stamped on shadow hosts so Selenium can locate them again afterwards.
# JavaScript is the only thing that can *discover* shadow roots (it can read
# `el.shadowRoot` and walk into it freely), but it cannot hand a shadowed node
# back to Selenium as a `WebElement`. Tagging the host and then walking to it
# with `WebElement.shadow_root` is the bridge between the two.
HOST_ATTR = "data-sdom-host"


def _now() -> float:
    '''
    Seconds since the epoch.

    A named helper rather than a bare `time.time()`, because the lookup functions
    below take a `time` argument (matching the rest of the codebase) that shadows
    the module inside their own scope.
    '''
    return time.time()



# Finds every element with an open shadow root in the current document, including
# hosts nested inside other shadow trees, and reports each one's ancestry so the
# walker in Python can descend to it step by step.
_SHADOW_CENSUS_JS = """
var out = [];
var counter = 0;
(function rec(root, parents) {
    var all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        if (!el.shadowRoot) continue;
        counter += 1;
        var id = arguments[1] + counter;
        el.setAttribute(arguments[0], id);
        out.push({id: id, parents: parents.slice(), tag: String(el.tagName).toLowerCase()});
        rec(el.shadowRoot, parents.concat([id]));
    }
})(document, []);
return out;
"""

# How many times each candidate selector matches in the current document. Used by
# the capture tool to report which anchors actually exist on a given page.
_MATCH_CENSUS_JS = """
var selectors = arguments[0];
var out = {};
for (var i = 0; i < selectors.length; i++) {
    var count = -1;
    try { count = document.querySelectorAll(selectors[i]).length; } catch (e) { count = -1; }
    out[selectors[i]] = count;
}
return out;
"""

# Every iframe reachable from the current document, descending through shadow roots
# and recursing into same-origin children. `sameOrigin` is reported because a
# cross-origin frame cannot be switched into and must be skipped rather than
# raising.
_IFRAME_CENSUS_JS = """
var out = [];
(function rec(root) {
    var frames;
    try { frames = root.querySelectorAll('iframe'); } catch (e) { return; }
    for (var i = 0; i < frames.length; i++) {
        var frame = frames[i];
        var sameOrigin = false;
        try { sameOrigin = !!frame.contentDocument; } catch (e) { sameOrigin = false; }
        out.push({
            tag: String(frame.tagName).toLowerCase(),
            src: frame.getAttribute('src') || '',
            id: frame.id || '',
            name: frame.getAttribute('name') || '',
            title: frame.getAttribute('title') || '',
            sameOrigin: sameOrigin
        });
        if (sameOrigin) {
            try { rec(frame.contentDocument); } catch (e) {}
        }
    }
    var all;
    try { all = root.querySelectorAll('*'); } catch (e) { return; }
    for (var j = 0; j < all.length; j++) {
        if (all[j].shadowRoot) {
            try { rec(all[j].shadowRoot); } catch (e) {}
        }
    }
})(document);
return out;
"""


def _normalise(selectors) -> list[str]:
    '''Accepts a single selector or an ordered list and always returns a list.'''
    if isinstance(selectors, str):
        return [selectors]
    return [str(selector) for selector in selectors if selector]


def _matches_in(root, selector: str) -> list[WebElement]:
    '''Every match for `selector` in one document or shadow root, ignoring errors.'''
    try:
        return root.find_elements(By.CSS_SELECTOR, selector)
    except Exception:
        return []


def _shadow_census(driver: WebDriver, attr: str) -> list[dict]:
    '''Shadow hosts in the current document, each with the chain of parents needed to reach it.'''
    try:
        found = driver.execute_script(_SHADOW_CENSUS_JS, attr, attr)
    except Exception:
        return []
    return found or []


def _shadow_roots(driver: WebDriver, attr: str, max_depth: int = MAX_SHADOW_DEPTH) -> list:
    '''
    Open shadow roots in the current document, outermost first.

    Each host is reached by walking down through its parents' shadow roots, so
    hosts nested several levels deep still resolve.
    '''
    records = _shadow_census(driver, attr)
    by_id = {record["id"]: record for record in records}
    roots = []
    for record in records:
        if len(record["parents"]) >= max_depth:
            continue
        current = driver
        broken = False
        for parent_id in record["parents"]:
            parent_record = by_id.get(parent_id)
            if parent_record is None:
                broken = True
                break
            try:
                host = current.find_element(By.CSS_SELECTOR, f'[{attr}="{parent_id}"]')
                current = host.shadow_root
            except Exception:
                broken = True
                break
            if current is None:
                broken = True
                break
        if broken:
            continue
        try:
            host = current.find_element(By.CSS_SELECTOR, f'[{attr}="{record["id"]}"]')
            if host.shadow_root is not None:
                roots.append(host.shadow_root)
        except Exception:
            continue
    return roots


def _search_within_shadows(driver: WebDriver, attr: str, selector: str, all_elements: bool):
    '''
    Look for `selector` in the current document and in every open shadow root
    beneath it. Returns matching elements, or an empty list.
    '''
    found = _matches_in(driver, selector)
    if found and not all_elements:
        return found[:1]
    collected = list(found)
    if all_elements and collected:
        return collected
    for shadow in _shadow_roots(driver, attr):
        hits = _matches_in(shadow, selector)
        if hits:
            collected.extend(hits)
            if not all_elements:
                return collected[:1]
    return collected


def deep_find(
    driver: WebDriver,
    selectors,
    time: float = 5.0,
    root=None,
    frames: bool = True,
    shadows: bool = True,
    all_elements: bool = False,
    attr: str = HOST_ATTR,
):
    '''
    Finds elements by trying each selector in order, searching the current
    document, any open shadow roots, and (optionally) same-origin iframes.

    - `selectors`: one CSS selector or an ordered list of them. Order is
      significance: the first candidate that matches anywhere wins.
    - `time`: seconds to keep retrying before giving up, because SDUI often
      renders the thing you want a moment after the page settles.
    - `root`: search beneath this element instead of the whole document. Pass a
      `WebElement` (or a `ShadowRoot`) to scope a lookup to a modal.
    - `frames`: descend into same-origin iframes.
    - `shadows`: descend into open shadow roots.
    - `all_elements`: return every match instead of just the first.
    - `attr`: attribute used to mark shadow hosts, so concurrent callers can be
      given their own namespace.

    Returns a `WebElement`, a list of them when `all_elements` is set, or `False`.
    '''
    candidates = _normalise(selectors)
    if not candidates:
        return [] if all_elements else False

    base = driver if root is None else root
    deadline = (_now() + time) if (time and time > 0) else None

    while True:
        found = _find_once(driver, candidates, base, frames, shadows, all_elements, attr)
        if found:
            return found if all_elements else found[0]
        if deadline is None or _now() >= deadline:
            break
        sleep(0.25)

    return [] if all_elements else False


def deep_find_all(
    driver: WebDriver,
    selectors,
    time: float = 5.0,
    root=None,
    frames: bool = True,
    shadows: bool = True,
    attr: str = HOST_ATTR,
) -> list:
    '''`deep_find` for when every match matters. Always returns a list, never False.'''
    return deep_find(driver, selectors, time, root, frames, shadows, all_elements=True, attr=attr)


def _find_once(
    driver: WebDriver,
    candidates: list[str],
    base,
    frames: bool,
    shadows: bool,
    all_elements: bool,
    attr: str,
    frame_depth: int = 0,
) -> list:
    '''One pass of `deep_find` with no waiting. Always returns a list of matches.'''
    collected = []

    if base is driver:
        for selector in candidates:
            if shadows:
                found = _search_within_shadows(driver, attr, selector, all_elements)
            else:
                found = _matches_in(driver, selector)
                found = found[:1] if (found and not all_elements) else found
            if found:
                collected.extend(found)
                if not all_elements:
                    return collected[:1]
    else:
        for selector in candidates:
            found = _matches_in(base, selector)
            if found:
                collected.extend(found)
                if not all_elements:
                    return collected[:1]

    if not frames or frame_depth >= MAX_FRAME_DEPTH:
        return collected

    # Recurse into same-origin iframes. The frame list is gathered separately from
    # the selector walk because these iframes are often unnamed and identifiable
    # only by where they sit in the DOM.
    try:
        frames_info = driver.execute_script(_IFRAME_CENSUS_JS) or []
    except Exception:
        frames_info = []

    for info in frames_info:
        if not info.get("sameOrigin"):
            continue
        frame_element = _locate_frame(driver, attr, info)
        if frame_element is None:
            continue
        try:
            driver.switch_to.frame(frame_element)
        except Exception:
            # Selenium usually leaves the context alone when this fails, but a
            # half-applied switch would silently corrupt every later lookup in the
            # run, so the top document is restored either way.
            _restore_context(driver)
            continue
        try:
            found = _find_once(driver, candidates, driver, frames, shadows, all_elements, attr, frame_depth + 1)
            if found:
                collected.extend(found)
                if not all_elements:
                    return collected[:1]
        finally:
            # Always restore the context; leaking a frame switch corrupts every
            # later lookup in the run.
            _restore_context(driver)

    return collected


def _restore_context(driver: WebDriver) -> None:
    '''Return to the top document, ignoring any failure to do so.'''
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def _locate_frame(driver: WebDriver, attr: str, info: dict, max_depth: int = MAX_SHADOW_DEPTH):
    '''Re-find the iframe element matching a census entry, possibly inside a shadow root.'''
    frames = _search_within_shadows(driver, attr, "iframe", all_elements=True)
    for frame in frames:
        try:
            if info.get("id") and frame.get_attribute("id") != info["id"]:
                continue
            if info.get("name"):
                name = frame.get_attribute("name") or ""
                if name != info["name"]:
                    continue
            return frame
        except Exception:
            continue
    return frames[0] if frames else None


# Tags worth scanning when matching an element by its visible text. Buttons label
# themselves with a `<span>`, but the new UI often puts the text on the button or
# heading itself, so both are checked.
TEXT_TAGS = ("span", "button", "a", "h2", "h3", "div", "label")


def deep_find_by_text(
    driver: WebDriver,
    text: str,
    time: float = 5.0,
    root=None,
    tags=TEXT_TAGS,
    frames: bool = True,
    shadows: bool = True,
    exact: bool = True,
    attr: str = HOST_ATTR,
):
    '''
    Finds an element by its visible text, the way `wait_span_click()` does for the
    classic UI, but able to see inside shadow roots and iframes.

    Returns the element, or `False`. Never clicks anything - callers decide what
    to do with the match via `deep_click()`.
    '''
    wanted = (text or "").strip().lower()
    if not wanted:
        return False

    deadline = (_now() + time) if (time and time > 0) else None
    while True:
        found = _find_text_once(driver, wanted, root, tags, frames, shadows, exact, attr)
        if found:
            return found
        if deadline is None or _now() >= deadline:
            break
        sleep(0.25)
    return False


def _find_text_once(
    driver: WebDriver,
    wanted: str,
    root,
    tags,
    frames: bool,
    shadows: bool,
    exact: bool,
    attr: str,
    frame_depth: int = 0,
):
    '''One pass of `deep_find_by_text` with no waiting. Returns an element or False.'''
    elements = []
    for tag in tags:
        if root is not None and root is not driver:
            elements.extend(_matches_in(root, tag))
        elif shadows:
            elements.extend(_search_within_shadows(driver, attr, tag, all_elements=True))
        else:
            elements.extend(_matches_in(driver, tag))

    for element in elements:
        text = visible_text(driver, element).strip().lower()
        if not text:
            continue
        if (text == wanted) if exact else (wanted in text):
            return element

    if not frames or frame_depth >= MAX_FRAME_DEPTH:
        return False

    try:
        frames_info = driver.execute_script(_IFRAME_CENSUS_JS) or []
    except Exception:
        frames_info = []

    for info in frames_info:
        if not info.get("sameOrigin"):
            continue
        frame_element = _locate_frame(driver, attr, info)
        if frame_element is None:
            continue
        try:
            driver.switch_to.frame(frame_element)
        except Exception:
            _restore_context(driver)
            continue
        try:
            found = _find_text_once(driver, wanted, None, tags, True, shadows, exact, attr, frame_depth + 1)
            if found:
                return found
        finally:
            _restore_context(driver)

    return False


# Dispatching the whole lifecycle rather than calling `.click()`: SDUI handlers
# listen for `pointerdown`/`pointerup`, which a synthesised mouse click omits.
_CLICK_JS = """
var el = arguments[0];
if (!el) return 'missing';
el.scrollIntoView({block: 'center', behavior: arguments[1]});
var rect = el.getBoundingClientRect();
if (rect.width === 0 && rect.height === 0) return 'hidden';
var base = {
    bubbles: true, cancelable: true, composed: true, view: el.ownerDocument.defaultView,
    clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2,
    button: 0, buttons: 1
};
['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach(function(type) {
    var Ctor = type.indexOf('pointer') === 0 ? PointerEvent : MouseEvent;
    try { el.dispatchEvent(new Ctor(type, base)); }
    catch (e) { el.dispatchEvent(new MouseEvent(type, base)); }
});
return 'ok';
"""


def deep_click(driver: WebDriver, element: WebElement, scroll_back: bool = True) -> bool:
    '''
    Clicks an element the way the new UI expects.

    Dispatches the pointer and mouse event sequence SDUI handlers listen for, so
    unlike `WebElement.click()` the click is actually seen. Falls back to a normal
    Selenium click if scripting is refused.

    Returns True if a click was dispatched.
    '''
    if element is None or element is False:
        return False

    scroll_position = None
    if scroll_back:
        try:
            scroll_position = driver.execute_script("return window.scrollY;")
        except Exception:
            scroll_position = None

    try:
        driver.execute_script(_CLICK_JS, element, "smooth" if smooth_scroll else "instant")
        return True
    except Exception:
        pass

    # Scrolling is a convenience, not a prerequisite: a field that is already on
    # screen still deserves its click, so a refusal here must not skip the click.
    try:
        driver.execute_script('arguments[0].scrollIntoView({block: "center"});', element)
    except Exception:
        pass

    try:
        element.click()
        return True
    except Exception as e:
        print_lg(f"Couldn't click the element: {e}")

    if scroll_position is not None:
        try:
            driver.execute_script("window.scrollTo(0, arguments[0]);", scroll_position)
        except Exception:
            pass
    return False


def deep_type(driver: WebDriver, element: WebElement, value: str, clear: bool = True) -> bool:
    '''
    Types into a field that may live inside a shadow root or iframe.

    `send_keys` already works on such elements, but the field is first focused and
    scrolled into view by script because a detached or off-screen SDUI field will
    otherwise swallow the keystrokes silently.
    '''
    if element is None or element is False:
        return False
    try:
        driver.execute_script(
            """
            var el = arguments[0];
            if (!el) return;
            el.scrollIntoView({block: 'center'});
            if (el.focus) el.focus();
            """,
            element,
        )
        if clear:
            from selenium.webdriver.common.keys import Keys

            element.send_keys(Keys.CONTROL + "a")
        element.send_keys(value)
        return True
    except Exception as e:
        print_lg(f"Couldn't type into the field: {e}")
        return False


def visible_text(driver: WebDriver, element) -> str:
    '''`.text` for an element, with a textContent fallback for shadow-hosted nodes.'''
    try:
        text = element.text
        if text:
            return text
    except Exception:
        pass
    try:
        return driver.execute_script("return (arguments[0].textContent || '').trim();", element)
    except Exception:
        return ""


def shadow_report(driver: WebDriver) -> dict:
    '''
    Describes the shadow roots and same-origin iframes of the current page.

    Used by `tools/capture_dom.py` to explain *why* a selector did or did not match,
    which is the difference between guessing at the new UI and working with it.
    '''
    report = {"shadow_hosts": [], "iframes": [], "shadow_roots_reachable": 0}
    try:
        report["shadow_hosts"] = _shadow_census(driver, HOST_ATTR)
    except Exception:
        pass
    try:
        report["iframes"] = driver.execute_script(_IFRAME_CENSUS_JS) or []
    except Exception:
        pass
    try:
        report["shadow_roots_reachable"] = len(_shadow_roots(driver, HOST_ATTR))
    except Exception:
        pass
    return report


def selector_report(driver: WebDriver, selectors) -> dict:
    '''Match counts for each selector in the current document, plus the shadow census.'''
    candidates = _normalise(selectors)
    counts = {}
    try:
        counts = driver.execute_script(_MATCH_CENSUS_JS, candidates) or {}
    except Exception:
        counts = {selector: -1 for selector in candidates}
    report = shadow_report(driver)
    report["matches"] = counts
    return report