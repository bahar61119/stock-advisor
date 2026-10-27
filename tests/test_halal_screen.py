"""Tests for the in-house AAOIFI-style halal screening module."""
from stock_advisor.analysis.halal_screen import load_exclusions, screen
from stock_advisor.config import HalalThresholds
from stock_advisor.providers.market_data.base import CompanyProfile, Fundamentals

DEFAULT_THRESHOLDS = HalalThresholds(
    debt_to_market_cap=0.33,
    cash_and_interest_to_market_cap=0.33,
    receivables_and_cash_to_market_cap=0.33,
    non_permissible_income_ratio=0.05,
)

EXCLUSIONS = load_exclusions()


def clean_profile() -> CompanyProfile:
    """A profile that should never trip the sector exclusion list."""
    return CompanyProfile(
        sector="Technology",
        industry="Software—Application",
        business_summary="Develops productivity software.",
    )


def make_fundamentals(
    total_debt=None,
    market_cap=None,
    total_cash=None,
    total_revenue=None,
    non_permissible_income=None,
    receivables=None,
) -> Fundamentals:
    return Fundamentals(
        total_debt=total_debt,
        total_cash=total_cash,
        market_cap=market_cap,
        total_revenue=total_revenue,
        non_permissible_income=non_permissible_income,
        receivables=receivables,
    )


def full_fundamentals(all_low: bool = False) -> Fundamentals:
    """A fundamentals set with every field populated.

    With all_low=True every ratio sits well under DEFAULT_THRESHOLDS so the
    company passes every financial check.
    """
    if all_low:
        return make_fundamentals(
            total_debt=1,
            market_cap=100,
            total_cash=1,
            total_revenue=100,
            non_permissible_income=0,
            receivables=1,
        )
    return make_fundamentals(
        total_debt=10,
        market_cap=100,
        total_cash=10,
        total_revenue=100,
        non_permissible_income=1,
        receivables=10,
    )


def test_sector_exclusion_matches_case_insensitive():
    profile = CompanyProfile(
        sector="Financial Services", industry="Banks—Diversified", business_summary=None
    )
    verdict = screen(profile, full_fundamentals(), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert "sector" in verdict.failed_checks[0]


def test_ratio_just_under_threshold_passes():
    fundamentals = make_fundamentals(
        total_debt=32,
        market_cap=100,
        total_cash=0,
        total_revenue=100,
        non_permissible_income=0,
        receivables=0,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"


def test_ratio_at_threshold_fails():
    fundamentals = make_fundamentals(
        total_debt=33,
        market_cap=100,
        total_cash=0,
        total_revenue=100,
        non_permissible_income=0,
        receivables=0,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert "debt_to_market_cap" in verdict.failed_checks


def test_missing_single_field_is_insufficient_data_not_pass_or_fail():
    fundamentals = make_fundamentals(
        total_debt=5,
        market_cap=100,
        total_cash=None,
        total_revenue=100,
        non_permissible_income=0,
        receivables=0,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "insufficient_data"
    assert "cash_and_interest_to_market_cap" in verdict.missing_fields


def test_all_pass_is_compliant():
    verdict = screen(clean_profile(), full_fundamentals(all_low=True), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"
    assert verdict.failed_checks == []


# --- Additional coverage beyond the brief's listed tests ---


def test_missing_field_present_but_zero_is_not_treated_as_missing():
    """A ratio input of 0 (falsy) must still be computed, not flagged missing."""
    fundamentals = make_fundamentals(
        total_debt=0,
        market_cap=100,
        total_cash=0,
        total_revenue=100,
        non_permissible_income=0,
        receivables=0,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.missing_fields == []
    assert verdict.ratios.debt_to_market_cap == 0.0
    assert verdict.status == "compliant"


def test_missing_market_cap_marks_all_market_cap_ratios_missing():
    fundamentals = make_fundamentals(
        total_debt=5,
        market_cap=None,
        total_cash=5,
        total_revenue=100,
        non_permissible_income=0,
        receivables=5,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "insufficient_data"
    assert set(verdict.missing_fields) == {
        "debt_to_market_cap",
        "cash_and_interest_to_market_cap",
        "receivables_and_cash_to_market_cap",
    }
    assert verdict.ratios.debt_to_market_cap is None
    assert verdict.ratios.non_permissible_income_ratio == 0.0


def test_multiple_failed_ratios_all_listed():
    fundamentals = make_fundamentals(
        total_debt=50,
        market_cap=100,
        total_cash=50,
        total_revenue=100,
        non_permissible_income=10,
        receivables=0,
    )
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert "debt_to_market_cap" in verdict.failed_checks
    assert "cash_and_interest_to_market_cap" in verdict.failed_checks
    assert "receivables_and_cash_to_market_cap" in verdict.failed_checks
    assert "non_permissible_income_ratio" in verdict.failed_checks


def test_sector_exclusion_checked_before_ratios_even_if_fundamentals_missing():
    """Sector exclusion short-circuits regardless of whether fundamentals are usable."""
    profile = CompanyProfile(sector="Gambling", industry=None, business_summary=None)
    fundamentals = make_fundamentals()  # everything None
    verdict = screen(profile, fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert verdict.missing_fields == []


def test_business_summary_can_trigger_exclusion():
    profile = CompanyProfile(
        sector="Consumer Defensive",
        industry="Beverages—Brewers",
        business_summary="Brews and distributes alcoholic beverages worldwide.",
    )
    verdict = screen(profile, full_fundamentals(all_low=True), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"


def test_load_exclusions_returns_nonempty_list_of_strings():
    exclusions = load_exclusions()
    assert len(exclusions) > 0
    assert all(isinstance(keyword, str) for keyword in exclusions)


def test_business_summary_bankruptcy_does_not_trigger_bank_exclusion():
    """'bankruptcy' must not collide with bank-related exclusion keywords."""
    profile = CompanyProfile(
        sector="Technology",
        industry="Software—Application",
        business_summary="The company emerged from bankruptcy in 2015 and has operated profitably since.",
    )
    verdict = screen(profile, full_fundamentals(all_low=True), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"


def test_business_summary_blending_does_not_trigger_lending_exclusion():
    """'blending' must not collide with the 'interest-based lending' exclusion keyword."""
    profile = CompanyProfile(
        sector="Consumer Defensive",
        industry="Packaged Foods",
        business_summary="A tea blending company that sources direct trade leaves.",
    )
    verdict = screen(profile, full_fundamentals(all_low=True), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"
