import pytest

from ghostdesk.filings.verify import extract_claims, matches, unsupported_claims, verify_answer

REV = 260_174_000_000  # Apple fiscal 2019 revenue


@pytest.mark.parametrize("answer", [
    "Total revenue was $260.2 billion.",
    "Apple reported net sales of $260,174 million [0000320193-19-000119:item_8:3].",
    "Revenue: 260,174,000,000 USD",
    "260174000000",
    "$260 billion",
])
def test_correct_forms_match(answer):
    assert verify_answer(answer, REV, "revenue")["status"] == "correct"


@pytest.mark.parametrize("answer", ["Total revenue was $265.6 billion.", "$0.3 trillion", "$26.0 billion"])
def test_wrong_or_vague_figures_do_not_match(answer):
    assert verify_answer(answer, REV, "revenue")["status"] == "wrong"


def test_years_dates_percentages_and_citations_are_not_claims():
    text = "For the fiscal year ended September 28, 2019 (Form 10-K, FY2019), margin rose 12.5% [0000320193-19-000119:item_7:6]."
    assert extract_claims(text) == []


def test_refusal_and_no_number():
    assert verify_answer("The excerpts do not contain this figure.", REV)["status"] == "refused"
    assert verify_answer("Revenue grew strongly.", REV)["status"] == "no_number"


def test_eps_needs_two_decimals_and_exact_cents():
    assert verify_answer("Diluted EPS was $11.89.", 11.89, "eps_diluted")["status"] == "correct"
    assert verify_answer("Diluted EPS was $11.9.", 11.89, "eps_diluted")["status"] == "wrong"
    assert verify_answer("Diluted EPS was $11.88.", 11.89, "eps_diluted")["status"] == "wrong"


def test_losses_compare_on_magnitude():
    assert verify_answer("a net loss of $(2,722) million", -2_722_000_000, "net_income")["status"] == "correct"


def test_half_unit_tolerance_follows_printed_precision():
    (c,) = extract_claims("$260.17 billion")
    assert matches(c, REV) and not matches(c, 260_180_000_000)


def test_unsupported_claims_lists_figures_not_in_the_facts():
    answer = "Revenue was $260.2 billion and net income was $99.9 billion."
    assert unsupported_claims(answer, [REV, 55_256_000_000]) == ["$99.9 billion"]
