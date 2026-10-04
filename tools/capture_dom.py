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

from modules.sdom import deep_click, deep_find, selector_report, shadow_report  # noqa: E402
from modules.selectors import EASY_APPLY_BUTTON, JOB_CARD  # noqa: E402
from modules.helpers import print_lg  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402


DEFAULT_URL = "https://www.linkedin.com/jobs/search-results/"

# A deliberately wide net. This is a discovery tool, so it probes everything
# plausible rather than trusting one list of known-good selectors - the point is
# to find out what this account is actually served.
#
# The anchors marked "verified" were counted in a real capture of this account and
# are listed first, so a later capture that stops matching one of them is an
# immediate, obvious signal that LinkedIn changed something.
PROBE_SELECTORS = [
    # --- verified on a logged-in capture ---
    "div[data-view-name='job-search-job-card']",
    "div[componentkey^='job-card-component-ref-']",
    "button[data-view-name='job-apply-button']",
    "button[data-view-name='continue-unify']",
    "[data-testid='lazy-column']",
    "[data-component-type='LazyColumn']",
    "[data-testid='pagination-controls-list']",
    "button[aria-label^='Page ']",
    "[data-view-name='job-search-facet-dropdown']",
    "[data-view-name='job-search-facet-pill']",
    "[data-view-name='search-filter-top-bar-select']",
    "[data-view-name='job-search-location-picker']",
    "[data-view-name='dismiss-job']",
    "[componentkey='SearchResults_AllFiltersButton']",
    "[componentkey='semanticSearchBox']",
    "[componentkey^='JobDetails_']",
    "[componentkey^='JobDetails_AboutTheJob']",
    "[componentkey^='JobDetails_AboutTheCompany']",
    "[componentkey^='JobDetailsPeopleWhoCanHelpSlot']",
    "[data-sdui-screen^='com.linkedin.sdui.flagshipnav.jobs.']",

    # --- plausible, not yet confirmed ---
    "li[data-job-id]",
    "li[data-entity-urn]",
    "div[data-job-id]",
    "li[data-occludable-job-id]",
    "div.jobs-search-results__list-item",
    "div.scaffold-layout__list-item",
    "a[data-tracking-control-name*='public_jobs_jserp-result']",
    "a[href*='/jobs/view/']",
    "div.jobs-search-results-list",
    "[data-test='results-list']",
    "ol.jobs-search-results__list",
    "#jobs-search-results-main",
    "main",

    # --- filters ---
    "div[aria-label^='Filter by']",
    "button[aria-label^='Filter by']",
    "input[placeholder='Add a location']",
    "input[placeholder='Add a company']",
    "div[role='option']",

    # --- apply controls ---
    "a[href*='openSDUIApplyFlow=true']",
    "a[data-tracking-control-name*='apply-link-offsite']",
    "button[data-tracking-control-name*='apply']",

    # --- job details ---
    "div.jobs-box__html-content",
    "div.jobs-description__text",
    "div[data-test='job-description']",

    # --- easy apply modal: unverified, the previous capture never had one open ---
    "div.jobs-easy-apply-modal",
    "div.jobs-easy-apply-modal__content",
    "[data-test='easy-apply-modal']",
    "[componentkey*='EasyApply']",
    "[role='dialog']",
    "form",
    "div[data-test-form-element]",
    "div[data-test-single-line-text-form-component]",
    "div[data-test-text-entity-list-form-component]",
    "div[data-test-checkbox-form-component]",
    "div[data-test-combobox-form-component]",
    "input[type='file']",
    "input[data-id]",
    "select[data-id]",
    "textarea[data-id]",
    "fieldset.artdeco-radio-group",
]

# Every form control worth naming, so the Easy Apply form can be mapped field by
# field without guessing from a wall of HTML.
FIELD_SELECTOR = (
    'input, select, textarea, button, [role="combobox"], [role="switch"], '
    '[role="checkbox"], [contenteditable="true"], label'
)

# Confirms the Easy Apply modal is genuinely on screen. Deliberately strict: an
# earlier version of this tool carried on capturing when the modal had not actually
# opened, which silently produced a dump of the job page and left the whole apply
# flow undocumented. Better to write a file that says so than one that lies.
MODAL_STRICT_PROBES = [
    "div[data-test-form-element]",
    "div[data-test-single-line-text-form-component]",
    "div[data-test-text-entity-list-form-component]",
    "div[data-test-checkbox-form-component]",
    "div[data-test-combobox-form-component]",
    "input[type='file']",
    "div.jobs-easy-apply-modal",
    "[data-test='easy-apply-modal']",
    "[componentkey*='EasyApply']",
    "[role='dialog'] form",
    "[role='dialog'] [role='combobox']",
    "[aria-label*='years of experience' i]",
    "[aria-label*='phone number' i]",
]

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
        // The nearest ancestors carrying an identifying hook, so a field can be
        // traced back to the component that owns it.
        var hooks = [];
        var walker = el.parentElement;
        for (var depth = 0; walker && depth < 6; depth++) {
            var ck = walker.getAttribute('componentkey');
            var dt = walker.getAttribute('data-test') || walker.getAttribute('data-id');
            var dv = walker.getAttribute('data-view-name');
            if (ck || dt || dv) {
                hooks.push(walker.tagName.toLowerCase()
                    + (ck ? '[componentkey=' + ck + ']' : '')
                    + (dt ? '[data-test=' + dt + ']' : '')
                    + (dv ? '[data-view-name=' + dv + ']' : ''));
            }
            walker = walker.parentElement;
        }
        var inShadow = false;
        try { inShadow = typeof el.getRootNode === 'function' && el.getRootNode() !== document; } catch (e) {}
        out.push({
            tag: String(el.tagName).toLowerCase(),
            type: attr('type'),
            id: attr('id') || '',
            name: attr('name') || '',
            componentkey: attr('componentkey') || '',
            aria_label: attr('aria-label') || '',
            placeholder: attr('placeholder') || '',
            test_id: attr('data-id') || attr('data-test') || '',
            data_view_name: attr('data-view-name') || '',
            required: attr('required') !== null || attr('aria-required') === 'true',
            in_shadow_root: inShadow,
            ancestor_hooks: hooks,
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

    cards = deep_find(driver, JOB_CARD, time=4, all_elements=True) or []
    if not cards:
        print_lg("No job cards matched. The results list may not be loaded, or this account may not have AI search.")
        return

    print_lg(f"Found {len(cards)} card(s); writing the first {card_limit}.")
    ids = []
    for index, card in enumerate(cards[:card_limit], start=1):
        html = _outer_html(driver, card)
        _write(os.path.join(out_dir, "cards", f"card_{index:03d}.html"), html)
        try:
            holders = card.find_elements(By.CSS_SELECTOR, "[componentkey^='job-card-component-ref-']")
            for holder in holders:
                key = holder.get_dom_attribute("componentkey") or ""
                if key not in ids:
                    ids.append(key)
        except Exception:
            pass

    if ids:
        print_lg(f"Job ids from componentkeys: {', '.join(ids[:8])}{' ...' if len(ids) > 8 else ''}")

    panel = deep_find(
        driver,
        ["[data-testid='lazy-column']", "div.jobs-search-results-list", "main", "body"],
        time=3,
    )
    if panel:
        name = "results_panel.html" if panel.tag_name.lower() != "body" else "full_page.html"
        _write(os.path.join(out_dir, name), _outer_html(driver, panel))


def modal_probe_hit(driver) -> str | None:
    '''The first strict modal probe that matches, or None if the modal is not open.'''
    try:
        counts = driver.execute_script(
            """
            var selectors = arguments[0];
            var out = {};
            for (var i = 0; i < selectors.length; i++) {
                var n = 0;
                try { n = document.querySelectorAll(selectors[i]).length; } catch (e) { n = 0; }
                out[selectors[i]] = n;
            }
            return out;
            """,
            MODAL_STRICT_PROBES,
        ) or {}
    except Exception:
        return None
    for selector, count in counts.items():
        if count and count > 0:
            return selector
    return None


def open_apply_modal(driver) -> str | None:
    '''
    Tries to open the Easy Apply modal, escalating through click strategies.

    A plain Selenium click is tried first because it produces a trusted event, which
    is what LinkedIn's handlers generally want; the scripted pointer dispatch in
    `deep_click` is the fallback for when something overlays the button. Returns the
    probe that confirms the modal, or None.
    '''
    button = deep_find(driver, EASY_APPLY_BUTTON, time=5)
    if not button:
        print_lg("No Easy Apply button found by any known selector.")
        return None

    strategies = (
        ("scrolled Selenium click", lambda: _native_click(driver, button)),
        ("scripted pointer dispatch", lambda: deep_click(driver, button)),
        ("element.click() in script", lambda: driver.execute_script("arguments[0].click();", button)),
    )

    for label, action in strategies:
        try:
            action()
        except Exception as e:
            print_lg(f"  {label} raised: {e}")
            continue
        time.sleep(3)
        hit = modal_probe_hit(driver)
        if hit:
            print_lg(f"Easy Apply modal opened via {label} (matched '{hit}').")
            return hit
        print_lg(f"  {label} did not open the modal.")

    return None


def _native_click(driver, element) -> None:
    '''Scroll into view, then a real Selenium click.'''
    try:
        driver.execute_script('arguments[0].scrollIntoView({block: "center"});', element)
    except Exception:
        pass
    element.click()


def capture_apply_modal(driver, out_dir: str) -> None:
    '''Opens the Easy Apply modal if it can, then dumps the modal and every field in it.'''
    print_lg("Looking for an Easy Apply button...")

    opened = open_apply_modal(driver)

    if not opened:
        print_lg("")
        print_lg("Could not open the Easy Apply modal automatically.")
        print_lg("This is expected sometimes - the button may be covered, or the page may")
        print_lg("need a moment. Please open it by hand.")
        _wait_for_user("Open the Easy Apply modal on the focused job (if it is not already"
                       "\nopen), step to the second page of the form if it has more than one,"
                       "\nthen come back here.")

    confirmed = modal_probe_hit(driver)
    if confirmed:
        print_lg(f"Modal confirmed on screen via '{confirmed}'.")
    else:
        print_lg("")
        print_lg("!! NO MODAL DETECTED. Writing the page as-is.")
        print_lg("!! The apply form will NOT be documented by this capture.")
        print_lg("!! Check that the modal really is open, then re-run with --modal-only.")

    time.sleep(1)
    report = selector_report(driver, PROBE_SELECTORS)
    _write_json(os.path.join(out_dir, "structure_modal.json"), report)

    fields = _collect_fields(driver)
    _write_json(os.path.join(out_dir, "fields.json"), fields)
    print_lg(f"Found {len(fields)} form controls across the modal and its iframes.")
    identified = sum(1 for field in fields if field.get("componentkey") or field.get("test_id"))
    print_lg(f"  {identified} of them carry a componentkey or data-test hook.")
    print_lg(f"  {sum(1 for field in fields if field['in_shadow_root'])} are inside a shadow root.")

    modal = deep_find(
        driver,
        [
            "div.jobs-easy-apply-modal",
            "[data-test='easy-apply-modal']",
            "[componentkey*='EasyApply']",
            "[role='dialog']",
            "div[data-test-form-element]",
            "body",
        ],
        time=3,
    )
    if modal:
        name = "modal.html" if modal.tag_name.lower() != "body" else "modal_full_page.html"
        _write(os.path.join(out_dir, name), _outer_html(driver, modal))
        print_lg(f"Wrote {name} (<{modal.tag_name}>).")

    _write_json(
        os.path.join(out_dir, "modal_confirmed.json"),
        {
            "opened_automatically": bool(opened),
            "confirming_probe": confirmed,
            "field_count": len(fields),
            "url": driver.current_url,
            "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


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
    parser.add_argument(
        "--modal-only",
        action="store_true",
        help="Skip the results page and go straight for the Easy Apply modal. Use this to"
        " re-capture the form without redoing the search.",
    )
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

        if not arguments.modal_only:
            driver.get(arguments.url)
            time.sleep(4)

            _wait_for_user(
                "Set up the search you want to run (keywords, location, filters - whatever you"
                "\nwould normally search for), let the results finish loading, then come back here."
            )

            capture_results_page(driver, out_dir, arguments.cards)
        else:
            print_lg("Modal-only run: skipping the results page capture.")
            driver.get(arguments.url)
            time.sleep(4)
            _wait_for_user(
                "Set up your search, then click on ONE job so its details pane opens."
                "\nThe Easy Apply button only exists on a selected job, not on the list."
            )

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