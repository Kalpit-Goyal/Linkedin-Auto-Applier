'''
Capture the real DOM of the new LinkedIn job search and its Easy Apply modal.

Why this exists
---------------
LinkedIn's search is now a Server-Driven UI whose markup is assembled at runtime,
and it is still rolling out gradually, so the selectors published by other people
may simply not describe what *your* account is served. Writing the applier against
those would mean guessing.

So: run this once, while sitting on the search you care about, and it writes a
folder full of the actual markup. Every selector added afterwards is written
against what is really there instead of what ought to be.

What it writes
--------------
    tools/_dom_dump/
        meta.json                 URL, title, timestamp, viewport
        structure.json            Shadow hosts, same-origin iframes, and a match
                                  count for every probe selector
        results_panel.html        The results list container
        cards/card_NNN.html       The first few job cards, verbatim
        fields.json               Every form control in the Easy Apply modal, with
                                  the id / name / aria-label / componentkey that
                                  identifies it
        modal.html                The Easy Apply modal itself

Usage
-----
    python tools/capture_dom.py
    python tools/capture_dom.py --url "https://www.linkedin.com/jobs/search-results/"

The script reuses the bot's own Chrome profile, so if you are already logged in
you will not be asked to log in again.
'''

import argparse
import json
import os
import sys
import time


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.sdom import HOST_ATTR, deep_click, deep_find, selector_report, shadow_report  # noqa: E402
from modules.helpers import print_lg  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402


DEFAULT_URL = "https://www.linkedin.com/jobs/search-results/"

# A deliberately wide net. This is a discovery tool, so it probes everything
# plausible rather than trusting one list of known-good selectors - the point is
# to find out what this account is actually served.
PROBE_SELECTORS = [
    # Job cards
    "li[data-occludable-job-id]",
    "li[data-job-id]",
    "li[data-entity-urn]",
    "div[data-job-id]",
    "div[data-entity-urn]",
    "div.job-card-container",
    "div.jobs-search-results__list-item",
    "li.jobs-search-results__list-item",
    "div.scaffold-layout__list-item",
    "a[data-tracking-control-name*='public_jobs_jserp-result']",
    "a[href*='/jobs/view/']",
    # Results containers
    "#jobs-search-results-main",
    "div.jobs-search-results-list",
    "div.jobs-search-results",
    "[data-test='results-list']",
    "section[data-test='search-results']",
    "ol.jobs-search-results__list",
    "ul.jobs-search-results__list",
    "main",
    # Filters
    "[data-view-name='search-filter-top-bar-select']",
    "div[aria-label^='Filter by']",
    "button[aria-label^='Filter by']",
    "input[placeholder='Add a location']",
    "input[placeholder='Add a company']",
    "div[role='option']",
    "a[role='button']:not([aria-label])",
    # Apply controls
    "button.jobs-apply-button",
    "button[aria-label*='Easy Apply']",
    "a[href*='openSDUIApplyFlow=true']",
    "a[data-tracking-control-name*='public_jobs_apply-link-offsite']",
    "button[data-tracking-control-name*='apply']",
    # Job details
    "div.jobs-box__html-content",
    "div.jobs-description__text",
    "[componentkey^='JobDetails_AboutTheJob']",
    "[componentkey^='JobDetails_AboutTheCompany']",
    "[componentkey^='JobDetails_Header']",
    "[componentkey^='JobDetailsPeopleWhoCanHelpSlot']",
    "[componentkey*='Apply']",
    "[componentkey*='apply']",
    # Easy Apply modal
    "div.jobs-easy-apply-modal",
    "div.jobs-easy-apply-modal__content",
    "[data-test='easy-apply-modal']",
    "[componentkey*='EasyApply']",
    "[componentkey*='Modal']",
    "form",
    "div[data-test-form-element]",
    "div[data-test-single-line-text-form-component]",
    "div[data-test-text-entity-list-form-component]",
    # Old-style form-field hooks, kept because LinkedIn often reuses them
    "input[data-id]",
    "select[data-id]",
    "textarea[data-id]",
    "input[type='file']",
    "fieldset.artdeco-radio-group",
]

# Every form control worth naming, so the Easy Apply form can be mapped field by
# field without guessing from a wall of HTML.
FIELD_SELECTOR = (
    'input, select, textarea, button, [role="combobox"], [role="switch"], '
    '[role="checkbox"], [contenteditable="true"], label'
)

_FIELD_CENSUS_JS = """
var selector = arguments[0];
var out = [];
(function rec(root) {
    var nodes;
    try { nodes = root.querySelectorAll(selector); } catch (e) { return; }
    for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        function attr(name) {
            try { return el.getAttribute(name); } catch (e) { return null; }
        }
        out.push({
            tag: String(el.tagName).toLowerCase(),
            type: attr('type'),
            id: attr('id') || '',
            name: attr('name') || '',
            componentkey: attr('componentkey') || '',
            aria_label: attr('aria-label') || '',
            placeholder: attr('placeholder') || '',
            test_id: attr('data-id') || attr('data-test') || '',
            required: attr('required') !== null,
            in_shadow_root: !!el.getRootNode || (el.getRootNode && el.getRootNode() !== document),
            text: ((el.textContent || '').replace(/\\s+/g, ' ').trim()).slice(0, 120)
        });
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

_OUTER_HTML_JS = "return arguments[0].outerHTML;"

# Refuse to write something unusable: the full page of a search results list runs
# to several megabytes, and the interesting part is always a subtree.
MAX_HTML_BYTES = 4 * 1024 * 1024


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if content is None:
        content = ""
    if len(content.encode("utf-8", "ignore")) > MAX_HTML_BYTES:
        content = content[:MAX_HTML_BYTES] + "\n\n<!-- TRUNCATED BY capture_dom.py -->"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _write_json(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def _outer_html(driver, element) -> str:
    try:
        return driver.execute_script(_OUTER_HTML_JS, element) or ""
    except Exception as e:
        print_lg(f"Couldn't read the markup for an element: {e}")
        return ""


def _wait_for_user(message: str) -> None:
    print("\n" + "=" * 72)
    print(message)
    print("=" * 72)
    try:
        input("Press Enter here when you're ready...")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")


def _logged_in(driver) -> bool:
    current = (driver.current_url or "").lower()
    return "/login" not in current and "/checkpoint" not in current and "/authwall" not in current


def capture_results_page(driver, out_dir: str, card_limit: int = 5) -> None:
    '''Dumps the results list, a few job cards, and everything structural about the page.'''
    print_lg("Reading the results page...")

    report = selector_report(driver, PROBE_SELECTORS)
    _write_json(os.path.join(out_dir, "structure.json"), report)

    matched = {selector: count for selector, count in report.get("matches", {}).items() if count and count > 0}
    print_lg(f"{len(matched)} of {len(PROBE_SELECTORS)} probe selectors matched.")
    for selector, count in sorted(matched.items(), key=lambda pair: -pair[1]):
        print(f"   {count:>4}  {selector}")

    if report.get("shadow_roots_reachable"):
        print_lg(f"Shadow roots found: {len(report['shadow_hosts'])} hosts, {report['shadow_roots_reachable']} reachable.")
    else:
        print_lg("No shadow roots on this page.")

    same_origin = [frame for frame in report.get("iframes", []) if frame.get("sameOrigin")]
    if same_origin:
        print_lg(f"Same-origin iframes: {len(same_origin)}")
        for frame in same_origin:
            print(f"   {frame.get('tag', '')}{frame.get('id') or frame.get('name') or '(unnamed)'} src={frame.get('src', '')[:80]}")

    _write_json(
        os.path.join(out_dir, "meta.json"),
        {
            "url": driver.current_url,
            "title": driver.title,
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "window_size": driver.get_window_size(),
            "matched_selectors": matched,
        },
    )

    cards = deep_find(driver, PROBE_SELECTORS[:14], time=4, all_elements=True) or []
    if not cards:
        print_lg("No job cards matched. The results list may not be loaded, or this account may not have AI search.")
        return

    print_lg(f"Found {len(cards)} card candidates; writing the first {card_limit}.")
    for index, card in enumerate(cards[:card_limit], start=1):
        _write(os.path.join(out_dir, "cards", f"card_{index:03d}.html"), _outer_html(driver, card))

    panel = deep_find(
        driver,
        ["#jobs-search-results-main", "[data-test='results-list']", "div.jobs-search-results-list", "main", "body"],
        time=3,
    )
    if panel:
        name = "results_panel.html" if panel.tag_name.lower() != "body" else "full_page.html"
        _write(os.path.join(out_dir, name), _outer_html(driver, panel))


def capture_apply_modal(driver, out_dir: str) -> None:
    '''Clicks Easy Apply on the first card, then dumps the modal and every field in it.'''
    print_lg("Looking for an Easy Apply button...")

    apply_button = deep_find(
        driver,
        [
            "button[aria-label*='Easy Apply']",
            "a[href*='openSDUIApplyFlow=true']",
            "button.jobs-apply-button",
            "button[data-tracking-control-name*='apply']",
            "button[data-tracking-control-name*='apply-offsite']",
        ],
        time=5,
    )

    if apply_button:
        deep_click(driver, apply_button)
        time.sleep(3)
    else:
        print_lg("No Easy Apply button found by any known selector. Open one by hand, then continue.")

    _wait_for_user(
        "Open the Easy Apply modal on the first job (if it is not already open),"
        "\nand get it fully rendered, then come back here."
    )

    time.sleep(1)
    report = selector_report(driver, PROBE_SELECTORS)
    _write_json(os.path.join(out_dir, "structure_modal.json"), report)

    fields = _collect_fields(driver)
    _write_json(os.path.join(out_dir, "fields.json"), fields)
    print_lg(f"Found {len(fields)} form controls across the modal and its iframes.")

    modal = deep_find(
        driver,
        [
            "div.jobs-easy-apply-modal",
            "[data-test='easy-apply-modal']",
            "[componentkey*='EasyApply']",
            "[componentkey*='Modal']",
            "div[data-test-form-element]",
            "body",
        ],
        time=3,
    )
    if modal:
        name = "modal.html" if modal.tag_name.lower() != "body" else "modal_full_page.html"
        _write(os.path.join(out_dir, name), _outer_html(driver, modal))

    for frame in report.get("iframes", []):
        if frame.get("sameOrigin"):
            print(f"   iframe src={frame.get('src', '')[:90]}")


def _collect_fields(driver) -> list:
    '''Every form control in the page and in each same-origin iframe it can reach.'''
    collected = []
    try:
        for field in driver.execute_script(_FIELD_CENSUS_JS, FIELD_SELECTOR) or []:
            field["document"] = "top"
            collected.append(field)
    except Exception as e:
        print_lg(f"Couldn't read the top document's fields: {e}")

    try:
        frames = shadow_report(driver).get("iframes", [])
    except Exception:
        frames = []

    for index, info in enumerate(frames):
        if not info.get("sameOrigin"):
            continue
        try:
            frame_element = driver.find_element(By.CSS_SELECTOR, "iframe")
            driver.switch_to.frame(frame_element)
        except Exception:
            continue
        try:
            for field in driver.execute_script(_FIELD_CENSUS_JS, FIELD_SELECTOR) or []:
                field["document"] = f"iframe[{index}] src={info.get('src', '')[:80]}"
                collected.append(field)
        except Exception:
            pass
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the new LinkedIn job search DOM.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Search URL to open first.")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "tools", "_dom_dump"), help="Output folder.")
    parser.add_argument("--cards", type=int, default=5, help="How many job cards to write.")
    parser.add_argument("--skip-modal", action="store_true", help="Only capture the results page.")
    arguments = parser.parse_args()

    out_dir = os.path.abspath(arguments.out)
    os.makedirs(out_dir, exist_ok=True)

    # Importing this starts Chrome on the bot's own profile, which is where the
    # saved LinkedIn login lives.
    from modules.open_chrome import driver

    try:
        if not _logged_in(driver):
            print_lg("Not signed in. Log in inside the browser that just opened, then continue.")
            _wait_for_user("Log in to LinkedIn in the browser window, then come back here.")

        driver.get(arguments.url)
        time.sleep(4)

        _wait_for_user(
            "Set up the search you want to run (keywords, location, filters - whatever you"
            "\nwould normally search for), let the results finish loading, then come back here."
        )

        capture_results_page(driver, out_dir, arguments.cards)

        if not arguments.skip_modal:
            capture_apply_modal(driver, out_dir)

        print("\n" + "=" * 72)
        print(f"Done. Everything written to:\n{out_dir}")
        print("=" * 72)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()