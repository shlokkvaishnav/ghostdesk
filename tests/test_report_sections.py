"""Item sections: table of contents, page headers, item numbers, cross-references."""
from ghostdesk.filings.report_sections import split_sections
from ghostdesk.text_signal.report_features import prose

HTML = """<html><body>
<p>TABLE OF CONTENTS</p><p>Item 1A. Risk Factors</p><p>Item 7. Management Discussion</p>
<div>Item 1A. Risk Factors</div>
<p>We face competition. Our results depend on demand for our products and on supply chain stability.</p>
<div>Item 7. Management Discussion and Analysis</div>
<p>Revenue grew in 2023.</p>
<p>Operating margin improved.</p>
</body></html>"""


def test_section_split_skips_the_table_of_contents():
    secs = split_sections(prose(HTML))
    assert "competition" in secs["item_1a"] and "Revenue grew" in secs["item_7"]
    assert len(secs["item_1a"]) > len("Item 1A. Risk Factors") + 20


def test_running_page_headers_do_not_cut_a_section_short():
    page = "x " * 300
    text = (f"Item 7. Management's Discussion\n{page}\n\nItem 7\n{page}\n\nItem 7\n{page}\n\n"
            f"Item 8. Financial Statements\nstatements\n")
    secs = split_sections(text)
    assert len(secs["item_7"].split()) > 900 and "Item 8" not in secs["item_7"]


def test_item_numbers_10_to_15_are_not_read_as_item_1():
    text = ("Item 1. Business\nb\n\nItem 1A. Risk\nr\n\nItem 10. Directors\nd\n\nItem 15. Exhibits\ne\n\n"
            "Item 7A. Market risk\nm\n")
    assert set(split_sections(text)) == {"item_1", "item_1a", "item_10", "item_15", "item_7a"}


def test_cross_reference_is_not_a_heading():
    body = "risk " * 300
    text = (f"Item 1A.\nRisk Factors\n{body}\nItem 7, \u201cManagement\u2019s Discussion and Analysis\u201d of this "
            f"Form 10-K, describes the results of operations, liquidity and capital resources, and the critical accounting "
            f"estimates in detail, and refers to further notes.\n{body}\nItem 1B.\nNone.\n")
    assert len(split_sections(text, max_heading=160)["item_1a"].split()) > 600
    assert len(split_sections(text)["item_1a"].split()) < 400  # without the limit the cross-reference cuts it
