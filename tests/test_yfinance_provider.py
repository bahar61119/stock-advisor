from datetime import date

import pandas as pd

from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider


class FakeYfTicker:
    """Stand-in for yfinance.Ticker that never touches the network."""

    def __init__(self, info=None, history_df=None):
        self.info = info if info is not None else {}
        self._history_df = history_df if history_df is not None else pd.DataFrame()
        self.history_calls = []

    def history(self, period="1y"):
        self.history_calls.append(period)
        return self._history_df


def make_fake_yf_ticker(info=None, history_df=None):
    return FakeYfTicker(info=info, history_df=history_df)


def sample_ohlcv_dataframe():
    index = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "Open": [184.0, 185.0, 186.5],
            "High": [186.0, 187.0, 188.0],
            "Low": [183.5, 184.5, 185.5],
            "Close": [185.5, 186.25, 187.75],
            "Volume": [50_000_000, 48_000_000, 52_000_000],
        },
        index=index,
    )


def test_get_fundamentals_handles_missing_fields(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={"totalDebt": 1_000_000, "marketCap": 50_000_000}
    )
    # no "totalRevenue" / "totalCash" keys present
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.total_debt == 1_000_000
    assert fundamentals.market_cap == 50_000_000
    assert fundamentals.total_cash is None
    assert fundamentals.total_revenue is None


def test_get_fundamentals_non_permissible_income_always_none(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={
            "totalDebt": 1_000_000,
            "totalCash": 500_000,
            "marketCap": 50_000_000,
            "totalRevenue": 10_000_000,
        }
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.non_permissible_income is None
    assert fundamentals.receivables is None


def test_get_fundamentals_all_present(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={
            "totalDebt": 1_000_000,
            "totalCash": 500_000,
            "marketCap": 50_000_000,
            "totalRevenue": 10_000_000,
        }
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.total_debt == 1_000_000
    assert fundamentals.total_cash == 500_000
    assert fundamentals.market_cap == 50_000_000
    assert fundamentals.total_revenue == 10_000_000


def test_get_company_profile_handles_missing_fields(monkeypatch):
    fake_ticker = make_fake_yf_ticker(info={"sector": "Technology"})
    # no "industry" / "longBusinessSummary" keys present
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    profile = YFinanceProvider().get_company_profile("AAPL")
    assert profile.sector == "Technology"
    assert profile.industry is None
    assert profile.business_summary is None


def test_get_company_profile_all_present(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "longBusinessSummary": "Makes phones.",
        }
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    profile = YFinanceProvider().get_company_profile("AAPL")
    assert profile.sector == "Technology"
    assert profile.industry == "Consumer Electronics"
    assert profile.business_summary == "Makes phones."


def test_get_price_history_parses_history(monkeypatch):
    df = sample_ohlcv_dataframe()
    fake_ticker = make_fake_yf_ticker(history_df=df)
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    series = YFinanceProvider().get_price_history("AAPL", period="1y")
    assert len(series.close) == len(df)
    assert series.dates == [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)]
    assert series.close == [185.5, 186.25, 187.75]
    assert series.volume == [50_000_000.0, 48_000_000.0, 52_000_000.0]


def test_get_price_history_passes_period_through(monkeypatch):
    fake_ticker = make_fake_yf_ticker(history_df=sample_ohlcv_dataframe())
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    YFinanceProvider().get_price_history("AAPL", period="6mo")
    assert fake_ticker.history_calls == ["6mo"]


def test_get_price_history_empty_history_returns_empty_series(monkeypatch):
    fake_ticker = make_fake_yf_ticker(history_df=pd.DataFrame())
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    series = YFinanceProvider().get_price_history("UNKNOWN")
    assert series.dates == []
    assert series.close == []
    assert series.volume == []
