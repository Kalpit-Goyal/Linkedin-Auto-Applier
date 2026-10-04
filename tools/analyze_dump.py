'''
One-off analysis of a capture in tools/_dom_dump.

Answers the questions the selector registry cannot answer on its own: what actually
wraps a job in the results list, and whether the Easy Apply form was captured at
all. Kept in the repo because the next capture will need the same questions asked
of it.
'''

import json
import os
import sys
from collections import Counter

from bs4 import BeautifulSoup


DUMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_dom_dump")


def soup_of(name):
    path = os.path.join(DUMP, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return BeautifulSoup(handle.read(), "lxml")


def describe(node, depth=0, limit=4):
    if node is None or depth > limit:
        return
    attrs = node.attrs or {}
    bits = [node.name]
    for key in ("class", "role", "aria-label", "componentkey", "data-view-name", "data-id",
                "data-tracking-control-name", "data-entity-urn", "data-job-id", "type", "href"):
        value = attrs.get(key)
        if not value:
            continue
        if isinstance(value, list):
            value = " ".join(value)
        bits.append(f'{key}="{str(value)[:70]}"')
    print("   " + "  " * depth + " ".join(bits)[:190])
    for child in node.children:
        if getattr(child, "name", None) == "a" and "/jobs/view/" in (child.get("href") or ""):
            print("   " + "  " * (depth + 1) + ">>> " + child.get_text(strip=True)[:60])
            return


def main():
    print("=" * 78)
    print("WHAT WRAPS A /jobs/view/ LINK")
    print("=" * 78)
    for filename in ("results_panel.html", "modal_full_page.html"):
        soup = soup_of(filename)
        if soup is None:
            print(f"{filename}: missing")
            continue
        links = soup.select("a[href*='/jobs/view/']")
        print(f"\n{filename}: {len(links)} job link(s)")
        for link in links[:2]:
            print("  ancestor chain, outermost first:")
            chain = []
            node = link
            while node is not None and getattr(node, "name", None) not in ("[document]", "html"):
                chain.append(node)
                node = node.parent
            for ancestor in reversed(chain[-9:]):
                describe(ancestor, 0)

    print()
    print("=" * 78)
    print("TAG/CLASS HISTOGRAM OF THE RESULTS LIST")
    print("=" * 78)
    soup = soup_of("results_panel.html")
    if soup is not None:
        classes = Counter()
        for node in soup.find_all(True):
            for cls in node.get("class") or []:
                classes[cls] += 1
        print("most common classes:")
        for cls, count in classes.most_common(30):
            print(f"   {count:>4}  {cls}")

        print()
        print("elements carrying any data-* attribute:")
        seen = {}
        for node in soup.find_all(True):
            for key, value in node.attrs.items():
                if key.startswith("data-") and isinstance(value, str):
                    seen.setdefault(key, Counter())[value[:40]] += 1
        for key, values in sorted(seen.items()):
            print(f"   data-{key[5:]}  ({sum(values.values())} uses)")
            for value, count in values.most_common(8):
                print(f"        {count:>3}  {value}")

    print()
    print("=" * 78)
    print("IS AN EASY APPLY FORM PRESENT?")
    print("=" * 78)
    soup = soup_of("modal_full_page.html")
    if soup is not None:
        for probe in ("form", "div[data-test-form-element]", "input[type='file']",
                      "div.jobs-easy-apply-modal", "[role='dialog']", "[data-test='easy-apply-modal']",
                      "button[aria-label*='Easy Apply']"):
            print(f"   {len(soup.select(probe)):>4}  {probe}")

        print()
        print("aria-labels mentioning apply:")
        for node in soup.find_all(attrs={"aria-label": True}):
            label = node["aria-label"]
            if "apply" in label.lower():
                print(f"   <{node.name}> aria-label={label[:80]!r}")

        print()
        print("buttons whose text mentions applying:")
        for node in soup.find_all("button"):
            text = node.get_text(" ", strip=True)
            if any(word in text.lower() for word in ("apply", "submit", "next", "continue", "review")):
                print(f"   {text[:70]!r}  attrs={ {k: v for k, v in (node.attrs or {}).items() if k in ('class', 'aria-label', 'componentkey', 'data-view-name')} }")

    print()
    print("=" * 78)
    print("FILTER CONTROLS")
    print("=" * 78)
    soup = soup_of("results_panel.html")
    if soup is not None:
        for node in soup.select("div[aria-label^='Filter by']")[:12]:
            print(f"   {node.get('aria-label')!r}")
        print()
        print("data-view-name values present:")
        names = Counter(n.get("data-view-name") for n in soup.find_all(attrs={"data-view-name": True}))
        for name, count in names.most_common(20):
            print(f"   {count:>4}  {name}")


if __name__ == "__main__":
    sys.exit(main())