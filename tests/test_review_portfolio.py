"""Tests for the portfolio-review pipeline: `run_portfolio_review` matches
each held `Position` to its broker `Instrument` (by Trading212 ticker, e.g.
"AAPL_US_EQ" -- NOT the plain-ticker-to-short_name match Task 7 uses), looks
up the matched `short_name` in the market-data provider, and screens it the
same way `scan_market.py` does -- reusing Task 8's `compute_allowed_recommendations`
rather than reimplementing the add_more exclusion rule.
"""
from datetime import date, timedelta

from scripts.review_portfolio import HoldingResult, run_portfolio_review
from stock_advisor.analysis.halal_screen import load_exclusions
from stock_advisor.config import AppConfig, HalalThresholds
from stock_advisor.providers.broker.base import AccountSummary, Instrument, Position
from stock_advisor.providers.broker.fake import FakeBrokerProvider
from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    PriceSeries,
)
from stock_advisor.providers.market_data.fake import FakeMarketDataProvider

EXCLUSIONS = load_exclusions()

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
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
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
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
    )
    assert len(output.holdings) == 1
    assert output.holdings[0].candidate is None


def test_account_summary_passed_through_unchanged():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(), positions=[], instruments=[]
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
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
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
    )
    assert len(output.holdings) == 1
    assert output.holdings[0].position.ticker == "AAPL_US_EQ"
    assert output.holdings[0].candidate is None


def test_matched_holding_produces_candidate_using_short_name_as_ticker():
    """The candidate's ticker is the market-data symbol used to query
    market data, not the Trading212-format position/instrument ticker.
    For a plain US instrument like AAPL, that symbol equals the bare
    short_name unchanged -- see test_held_lse_stock_is_queried_with_the_
    suffixed_market_data_symbol for a case where translation changes it.
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
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
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
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert len(output.holdings) == 2
    by_ticker = {h.position.ticker: h for h in output.holdings}
    assert by_ticker["AAPL_US_EQ"].candidate is not None
    assert by_ticker["ZZZZ_XX_EQ"].candidate is None


def test_holding_result_is_dataclass_with_position_and_candidate_fields():
    holding = HoldingResult(position=make_position(), candidate=None)
    assert holding.position.ticker == "AAPL_US_EQ"
    assert holding.candidate is None


# --- Why a holding has no candidate (Fixes 3 and 7) ---

from stock_advisor.reporting.schema import (  # noqa: E402
    REASON_MARKET_DATA_ERROR,
    REASON_NO_MARKET_DATA,
    REASON_POOLED_FUND,
    REASON_UNMATCHED_INSTRUMENT,
)


class RaisingMarketDataProvider(FakeMarketDataProvider):
    """Raises a generic exception (not KeyError) for chosen tickers -- what
    the real YFinanceProvider does on a rate limit, connection error, or
    malformed response, and what the old `except KeyError` did not catch.
    """

    def __init__(self, failing: set[str], **kwargs):
        super().__init__(**kwargs)
        self._failing = failing

    def get_price_history(self, ticker: str, period: str = "1y") -> PriceSeries:
        if ticker in self._failing:
            raise RuntimeError(f"simulated provider backend failure for {ticker}")
        return super().get_price_history(ticker)


def etf_instrument(ticker: str = "VUSA_EQ", short_name: str = "VUSA") -> Instrument:
    return Instrument(
        ticker=ticker,
        name="Vanguard S&P 500 UCITS ETF",
        short_name=short_name,
        isin="IE00B3XXRP09",
        currency_code="GBX",
        type="ETF",
    )


def test_screened_holding_has_no_reason():
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
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert output.holdings[0].candidate is not None
    assert output.holdings[0].reason is None


def test_unmatched_holding_reports_the_unmatched_reason():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="ZZZZ_XX_EQ")],
        instruments=[],
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
    )
    assert output.holdings[0].candidate is None
    assert output.holdings[0].reason == REASON_UNMATCHED_INSTRUMENT


def test_matched_holding_with_no_market_data_entry_reports_coverage_gap():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position()],
        instruments=[aapl_instrument()],
    )
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
    )
    assert output.holdings[0].candidate is None
    assert output.holdings[0].reason == REASON_NO_MARKET_DATA


def test_fetch_failure_is_distinguishable_from_a_coverage_gap():
    """The Fix-3 requirement: a consumer must be able to tell "we couldn't
    look" from "there's nothing to see" -- and neither may crash the run.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position()],
        instruments=[aapl_instrument()],
    )
    market_data = RaisingMarketDataProvider(
        failing={"AAPL"},
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert len(output.holdings) == 1
    assert output.holdings[0].candidate is None
    assert output.holdings[0].reason == REASON_MARKET_DATA_ERROR
    assert output.holdings[0].reason != REASON_NO_MARKET_DATA


def test_one_failing_holding_does_not_lose_the_others():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position("AAPL_US_EQ"), make_position("MSFT_US_EQ")],
        instruments=[
            aapl_instrument(),
            Instrument(
                ticker="MSFT_US_EQ",
                name="Microsoft Corp",
                short_name="MSFT",
                isin="US5949181045",
                currency_code="USD",
                type="STOCK",
            ),
        ],
    )
    market_data = RaisingMarketDataProvider(
        failing={"AAPL"},
        prices={"MSFT": bullish_price_series(), "AAPL": bullish_price_series()},
        fundamentals={"MSFT": compliant_fundamentals(), "AAPL": compliant_fundamentals()},
        profiles={"MSFT": clean_profile(), "AAPL": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    by_ticker = {h.position.ticker: h for h in output.holdings}
    assert by_ticker["AAPL_US_EQ"].reason == REASON_MARKET_DATA_ERROR
    assert by_ticker["MSFT_US_EQ"].candidate is not None


def test_held_etf_is_not_screened_and_says_why():
    """Fix 7: the spec excludes pooled funds from candidacy "regardless of
    halal status". A held ETF was being screened and scored exactly like an
    individual stock.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="VUSA_EQ")],
        instruments=[etf_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"VUSA": bullish_price_series()},
        fundamentals={"VUSA": compliant_fundamentals()},
        profiles={"VUSA": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert len(output.holdings) == 1
    assert output.holdings[0].position.ticker == "VUSA_EQ"
    assert output.holdings[0].candidate is None
    assert output.holdings[0].reason == REASON_POOLED_FUND


def test_held_etf_still_appears_alongside_screened_stocks():
    """Excluded from candidacy, never dropped from the report."""
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position("AAPL_US_EQ"), make_position("VUSA_EQ")],
        instruments=[aapl_instrument(), etf_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series(), "VUSA": bullish_price_series()},
        fundamentals={"AAPL": compliant_fundamentals(), "VUSA": compliant_fundamentals()},
        profiles={"AAPL": clean_profile(), "VUSA": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert len(output.holdings) == 2
    by_ticker = {h.position.ticker: h for h in output.holdings}
    assert by_ticker["AAPL_US_EQ"].candidate is not None
    assert by_ticker["VUSA_EQ"].candidate is None
    assert by_ticker["VUSA_EQ"].reason == REASON_POOLED_FUND


def test_non_stock_instrument_types_other_than_etf_are_also_excluded():
    """The rule is an allow-list on "STOCK", not a deny-list on "ETF", so an
    unfamiliar pooled type can't slip through.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="FUND_EQ")],
        instruments=[etf_instrument(ticker="FUND_EQ", short_name="FUND")],
    )
    broker._instruments[0].type = "ETC"
    output = run_portfolio_review(
        make_test_config(), broker, FakeMarketDataProvider({}, {}, {}), EXCLUSIONS
    )
    assert output.holdings[0].reason == REASON_POOLED_FUND


def test_review_does_no_file_io_of_its_own():
    """run_portfolio_review's docstring claims no I/O beyond the injected
    providers; it used to call load_exclusions() anyway. A sentinel
    exclusion list proves it screens with what it was handed.
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
    output = run_portfolio_review(
        make_test_config(), broker, market_data, ["productivity software"]
    )
    assert output.holdings[0].candidate.halal.status == "non_compliant"


def test_holding_result_reason_defaults_to_none():
    holding = HoldingResult(position=make_position(), candidate=None)
    assert holding.reason is None


# --- Holdings-ticker fix: translate short_name before querying market data ---
#
# _build_candidate used to pass instrument.short_name straight to the
# market-data provider with no translation. For a held LSE stock whose bare
# short_name collides with a US ticker (e.g. "BA" is both BAE Systems' EPIC
# and Boeing's NYSE ticker), that silently queried the wrong company. The
# fake provider below is seeded ONLY under the ".L"-suffixed key, so getting
# a real candidate back (not REASON_NO_MARKET_DATA) is only possible if the
# correct, translated symbol was used to query it.


def bae_systems_instrument() -> Instrument:
    return Instrument(
        ticker="BAl_EQ",
        name="BAE Systems plc",
        short_name="BA",
        isin="GB0002634946",
        currency_code="GBX",
        type="STOCK",
    )


def test_held_lse_stock_is_queried_with_the_suffixed_market_data_symbol():
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="BAl_EQ")],
        instruments=[bae_systems_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"BA.L": bullish_price_series()},
        fundamentals={"BA.L": compliant_fundamentals()},
        profiles={"BA.L": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    holding = output.holdings[0]
    assert holding.candidate is not None
    assert holding.reason is None
    assert holding.candidate.ticker == "BA.L"
    assert holding.candidate.broker_ticker == "BAl_EQ"


def test_held_lse_stock_bare_short_name_is_not_queried_directly():
    """The regression check: if the bare short_name ("BA") were still used
    directly, the lookup would miss the suffixed-only fake provider and
    report a coverage gap instead of a real candidate.
    """
    broker = FakeBrokerProvider(
        accounts=make_account_summary(),
        positions=[make_position(ticker="BAl_EQ")],
        instruments=[bae_systems_instrument()],
    )
    market_data = FakeMarketDataProvider(
        prices={"BA.L": bullish_price_series()},
        fundamentals={"BA.L": compliant_fundamentals()},
        profiles={"BA.L": clean_profile()},
    )
    output = run_portfolio_review(make_test_config(), broker, market_data, EXCLUSIONS)
    assert output.holdings[0].reason != REASON_NO_MARKET_DATA
