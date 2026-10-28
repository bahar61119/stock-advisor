"""Tests for the market-scan pipeline: `run_scan` ties together universe
matching, technical signal computation, and the halal screen into a ranked
shortlist of `CandidateResult`s.
"""
from datetime import date, timedelta

from scripts.scan_market import run_scan
from stock_advisor.config import AppConfig, HalalThresholds
from stock_advisor.providers.broker.base import Instrument
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


def bullish_price_series() -> PriceSeries:
    """A price series that compute_technical_signal classifies 'bullish':
    accelerating (compounding) growth gives sma_50 > sma_200 and
    macd_line > macd_signal_line, and a volume step-up gives a 'rising'
    volume trend -- 3 of 4 bullish points, which is enough regardless of
    RSI (a near-monotonic series pins RSI near 100, outside the neutral
    30-70 band, but classify_verdict only requires >=3 bullish points).
    Hand-verified via compute_technical_signal during development.
    """
    n = 250
    closes = [100 * (1.004**i) for i in range(n)]
    volumes = [1000.0] * (n - 20) + [3000.0] * 20
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    return PriceSeries(dates=dates, close=closes, volume=volumes)


def flat_short_price_series() -> PriceSeries:
    """A too-short price series: every indicator is None (insufficient
    history), so classify_verdict falls back to 'neutral' (0 bullish, 0
    bearish points). Used wherever a test needs a candidate that is
    definitely not 'bullish'.
    """
    closes = [100.0, 101.0, 102.0]
    volumes = [1000.0, 1000.0, 1000.0]
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(len(closes))]
    return PriceSeries(dates=dates, close=closes, volume=volumes)


def clean_profile() -> CompanyProfile:
    """A profile that never trips the sector exclusion list."""
    return CompanyProfile(
        sector="Technology",
        industry="Software—Application",
        business_summary="Develops productivity software.",
    )


def compliant_fundamentals() -> Fundamentals:
    """Fundamentals where every ratio sits well under DEFAULT_THRESHOLDS."""
    return Fundamentals(
        total_debt=1,
        total_cash=1,
        market_cap=100,
        total_revenue=100,
        non_permissible_income=0,
        receivables=1,
    )


def non_compliant_fundamentals() -> Fundamentals:
    """Fundamentals that fail exactly the debt_to_market_cap ratio
    (50/100 = 0.5 >= 0.33) while every other ratio passes -- a clean
    non_compliant case (not insufficient_data, not sector-excluded).
    """
    return Fundamentals(
        total_debt=50,
        total_cash=1,
        market_cap=100,
        total_revenue=100,
        non_permissible_income=1,
        receivables=1,
    )


def insufficient_data_fundamentals() -> Fundamentals:
    """Fundamentals missing a required field, forcing status='insufficient_data'."""
    return Fundamentals(
        total_debt=1,
        total_cash=None,
        market_cap=100,
        total_revenue=100,
        non_permissible_income=0,
        receivables=1,
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


def etf_instrument(ticker: str) -> Instrument:
    return Instrument(
        ticker=f"{ticker}_US_EQ",
        name=f"{ticker} ETF",
        short_name=ticker,
        isin="US0000000000",
        currency_code="USD",
        type="ETF",
    )


def stock_instrument(ticker: str) -> Instrument:
    return Instrument(
        ticker=f"{ticker}_US_EQ",
        name=f"{ticker} Inc",
        short_name=ticker,
        isin="US0000000000",
        currency_code="USD",
        type="STOCK",
    )


def make_instruments(tickers: list[str]) -> list[Instrument]:
    return [stock_instrument(ticker) for ticker in tickers]


def make_fake_market_data_for(tickers: list[str]) -> FakeMarketDataProvider:
    """A FakeMarketDataProvider where every ticker is bullish and halal-compliant."""
    prices = {ticker: bullish_price_series() for ticker in tickers}
    fundamentals = {ticker: compliant_fundamentals() for ticker in tickers}
    profiles = {ticker: clean_profile() for ticker in tickers}
    return FakeMarketDataProvider(prices=prices, fundamentals=fundamentals, profiles=profiles)


# --- Brief's required tests ---


def test_run_scan_includes_non_compliant_results_in_all_results():
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(
        make_test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()]
    )
    assert any(r.ticker == "AAPL" and r.halal.status == "non_compliant" for r in output.all_results)


def test_run_scan_shortlist_capped_at_configured_size():
    config = make_test_config(shortlist_size=2)
    market_data = make_fake_market_data_for(["A", "B", "C", "D"])
    output = run_scan(
        config,
        market_data,
        universe=["A", "B", "C", "D"],
        instruments=make_instruments(["A", "B", "C", "D"]),
    )
    assert len(output.shortlist) == 2


def test_run_scan_excludes_etfs_from_universe():
    output = run_scan(
        make_test_config(), FakeMarketDataProvider({}, {}, {}), universe=["SPY"], instruments=[etf_instrument("SPY")]
    )
    assert output.all_results == []


def test_allowed_recommendations_excludes_add_more_when_non_compliant():
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(
        make_test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()]
    )
    result = output.all_results[0]
    assert "add_more" not in result.allowed_recommendations


# --- Additional coverage beyond the brief's listed tests ---


def test_allowed_recommendations_includes_add_more_when_compliant():
    """Bidirectional check alongside the non_compliant test above: proves the
    exclusion rule is conditional on status, not a bug that always strips
    add_more regardless of verdict.
    """
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(
        make_test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()]
    )
    result = output.all_results[0]
    assert result.halal.status == "compliant"
    assert "add_more" in result.allowed_recommendations


def test_allowed_recommendations_excludes_add_more_when_insufficient_data():
    """insufficient_data must be treated as conservatively as non_compliant
    for this field -- a status the brief calls out explicitly.
    """
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": insufficient_data_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(
        make_test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()]
    )
    result = output.all_results[0]
    assert result.halal.status == "insufficient_data"
    assert "add_more" not in result.allowed_recommendations


def test_run_scan_skips_tickers_without_market_data_entry():
    """A matched, tradable ticker that the market-data provider has no entry
    for is skipped rather than raised -- the brief's "filtering the matched
    universe to those with a market-data entry" clause.
    """
    market_data = FakeMarketDataProvider(prices={}, fundamentals={}, profiles={})
    output = run_scan(
        make_test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()]
    )
    assert output.all_results == []
    assert output.shortlist == []


def test_run_scan_shortlist_orders_bullish_before_others():
    """Shortlist ordering: bullish verdicts first, then by ticker name --
    not merely universe/match order preserved.
    """
    market_data = FakeMarketDataProvider(
        prices={"A": flat_short_price_series(), "B": bullish_price_series()},
        fundamentals={
            "A": compliant_fundamentals(),
            "B": compliant_fundamentals(),
        },
        profiles={"A": clean_profile(), "B": clean_profile()},
    )
    # Universe lists the non-bullish ticker ("A") first, alphabetically ahead
    # of "B" too -- so only a real bullish-first sort puts B ahead of A.
    output = run_scan(
        make_test_config(shortlist_size=2),
        market_data,
        universe=["A", "B"],
        instruments=make_instruments(["A", "B"]),
    )
    assert [r.ticker for r in output.shortlist] == ["B", "A"]
    assert output.shortlist[0].technical.verdict == "bullish"


def test_run_scan_broker_ticker_is_the_instrument_ticker():
    output = run_scan(
        make_test_config(),
        FakeMarketDataProvider(
            prices={"AAPL": bullish_price_series()},
            fundamentals={"AAPL": compliant_fundamentals()},
            profiles={"AAPL": clean_profile()},
        ),
        universe=["AAPL"],
        instruments=[aapl_instrument()],
    )
    assert output.all_results[0].broker_ticker == "AAPL_US_EQ"


# --- Direct unit tests on the schema helper (isolated from run_scan) ---


def test_compute_allowed_recommendations_compliant_includes_add_more():
    from stock_advisor.reporting.schema import compute_allowed_recommendations

    assert "add_more" in compute_allowed_recommendations("compliant")


def test_compute_allowed_recommendations_non_compliant_excludes_add_more():
    from stock_advisor.reporting.schema import compute_allowed_recommendations

    assert "add_more" not in compute_allowed_recommendations("non_compliant")


def test_compute_allowed_recommendations_insufficient_data_excludes_add_more():
    from stock_advisor.reporting.schema import compute_allowed_recommendations

    assert "add_more" not in compute_allowed_recommendations("insufficient_data")


def test_compute_allowed_recommendations_unknown_status_excludes_add_more():
    """An unrecognized status must fall on the conservative (no add_more)
    side -- this is what proves the rule is an allow-list on "compliant",
    not a deny-list enumerating only the two known bad statuses.
    """
    from stock_advisor.reporting.schema import compute_allowed_recommendations

    assert "add_more" not in compute_allowed_recommendations("some_future_status")
