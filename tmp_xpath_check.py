from lxml import html
doc = html.parse(r"tools\_dom_dump\modal_full_page.html")
XP = ".//div[@data-test-form-element or starts-with(@componentkey, 'easyApplyFieldFocus_') or (label[@for] and .//select and not(div[label])) or (count(.//input[@type='radio']) >= 2 and not(div[count(.//input[@type='radio']) >= 2])) or (label[@for] and .//input and not(div[label[@for] and .//input]))]"
for root in doc.xpath("//dialog[@data-testid='dialog']") or doc.xpath("//body"):
    found = root.xpath(XP)
    print("matches:", len(found))
    for f in found:
        txt = " | ".join(t.strip() for t in f.text_content().split("\n") if t.strip())[:90]
        print(" -", f.tag, f.get("componentkey"), "::", txt)
    print("controls in dialog:", len(root.xpath(".//input | .//select | .//textarea")))
