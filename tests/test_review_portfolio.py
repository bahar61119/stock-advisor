"""Tests for the portfolio-review pipeline: `run_portfolio_review` matches
each held `Position` to its broker `Instrument` (by Trading212 ticker, e.g.
"AAPL_US_EQ" -- NOT the plain-ticker-to-short_name match Task 7 uses), looks
up the matched `short_name` in the market-data provider, and screens it the
same way `scan_market.py` does -- reusing Task 8's `compute_allowed_recommendations`
rather than reimplementing the add_more exclusion rule.
"""
from datetime import date, timedelta

from scripts.review_portfolio import HoldingResult, run_portfolio_review
from stock_advisor.config import AppConfig, HalalThresholds
from stock_advisor.providers.broker.base import AccountSummary, Instrument, Position
from stock_advisor.providers.broker.fake import FakeBrokerProvider
from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    PriceSeries,
)
from stock_advisor.providers.market_data.fake import FakeMarketDataProvider

DEFAULT_THRESHOLDS = HalalThresholds(
    debt_to_market_cap=0.33,
    cash_and_interest_to_market_cap=0.33,
    receivables_and_cash_to_market_cap=0.33,
    non_permissible_income_ratio=0.05,
)


def make_test_config(shortlist_size: int = 20) -> AppConfig:
    """Build an AppConfig for tests without reading config/config.yaml."""
    return AppConfig(
        broker_provider="trading212",
        market_data_provider="yfinance",
        shortlist_size=shortlist_size,
        halal_thresholds=DEFAULT_THRESHOLDS,
        universe_sources=["sp500"],
        instrument_cache_path=".cache/t212_instruments.json",
        instrument_cache_max_age_seconds=3600,
    )


def make_account_summary() -> AccountSummary:
    return AccountSummary(
        currency="GBP",
        total_value=25000.0,
        cash_available=5000.0,
        cash_reserved=500.0,
        cash_in_pies=1000.0,
        investments_current_value=20000.0,
        investments_total_cost=18000.0,
        realized_pl=1500.0,
        unrealized_pl=2000.0,
    )


def make_position(ticker: str = "AAPL_US_EQ") -> Position:
    return Position(
        ticker=ticker,
        name="Apple Inc",
        isin="US0378331005",
        currency="USD",
        quantity=10.0,
        quantity_available=10.0,
        current_price=185.5,
        average_price_paid=150.0,
        wallet_currency="GBP",
        wallet_current_value=1500.0,
        wallet_total_cost=1200.0,
        wallet_unrealized_pl=300.0,
    )


def aapl_instrument() -> Instrument:
    return Instrument(
        ticker="AAPL_US_EQ",
        name="Apple Inc",
        short_name="AAPL",
        isin="US0378331005",
        currency_code="USD",
        type="STOCK",
    )


def bullish_price_series() -> PriceSeries:
    """A price series compute_technical_signal classifies 'bullish' -- see
    test_scan_market.py's identically-named helper for the detailed rationale.
    """
    n = 250
    closes = [100 * (1.004**i) for i in range(n)]
    volumes = [1000.0] * (n - 20) + [3000.0] * 20
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    return PriceSeries(dates=dates, close=closes, volume=volumes)


def clean_profile() -> CompanyProfile:
    return CompanyProfile(
        sector="Technology",
        industry="Software—Application",
        business_summary="Develops productivity software.",
    )


def compliant_fundamentals() -> Fundamentals:
    return Fundamentals(
        total_debt=1,
        total_cash=1,
        market_cap=100,
        total_revenue=100,
        non_permissible_income=0,
        receivables=1,
    )


def non_compliant_fundamentals() -> Fundamentals:
    """Fails exactly debt_to_market_cap (50/100 = 0.5 >= 0.33)."""
    return Fundamentals(
        total_debt=50,
        total_cash=1,
        market_cap=100,
        total_revenue=100,
        non_permissible_income=1,
        receivables=1,
    )


# --- Brief's required tests ---


def test_held_non_compliant_position_excludes_add_more():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position()],
        instruments=[aapl_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data)
    holding = output.holdings[0]
    assert holding.candidate is not None
    assert holding.candidate.halal.status == "non_compliant"
    assert "add_more" not in holding.candidate.allowed_recommendations


def test_unmatched_holding_still_appears_with_candidate_none():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="ZZZZ_XX_EQ")],
        instruments=[],
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {})
    )
    assert len(output.holdings) == 1
    assert output.holdings[0].candidate is None


def test_account_summary_passed_through_unchanged():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(), positions=[], instruments=[]
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {})
    )
    assert output.account_summary == make_account_summary()


# --- Additional coverage beyond the brief's listed tests ---


def test_matched_holding_has_market_data_but_no_entry_still_candidate_none():
    """Instrument matches by ticker, but the market-data provider has no
    entry for the matched short_name -- candidate must be None, not raised.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position()],
        instruments=[aapl_instrument()],
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {})
    )
    assert len(output.holdings) == 1
    assert output.holdings[0].position.ticker == "AAPL_US_EQ"
    assert output.holdings[0].candidate is None


def test_matched_holding_produces_candidate_using_short_name_as_ticker():
    """The candidate's ticker is the plain short_name used to query
    market data, not the Trading212-format position/instrument ticker.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position()],
        instruments=[aapl_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data)
    holding = output.holdings[0]
    assert holding.candidate is not None
    assert holding.candidate.ticker == "AAPL"
    assert holding.candidate.broker_ticker == "AAPL_US_EQ"
    assert holding.candidate.halal.status == "compliant"
    assert "add_more" in holding.candidate.allowed_recommendations


def test_multiple_holdings_mixed_matched_and_unmatched():
    """A portfolio with one matched+screened holding and one unmatched
    holding -- both must appear, exactly one with candidate is not None.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="AAPL_US_EQ"), make_position(ticker="ZZZZ_XX_EQ")],
        instruments=[aapl_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data)
    assert len(output.holdings) == 2
    by_ticker = {h.position.ticker: h for h in output.holdings}
    assert by_ticker["AAPL_US_EQ"].candidate is not None
    assert by_ticker["ZZZZ_XX_EQ"].candidate is None


def test_holding_result_is_dataclass_with_position_and_candidate_fields():
    holding = HoldingResult(position=make_position(), candidate=None)
    assert holding.position.ticker == "AAPL_US_EQ"
    assert holding.candidate is None
