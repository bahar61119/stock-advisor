from datetime import date

import pandas as pd

from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider


class FakeYfTicker:
    """Stand-in for yfinance.Ticker that never touches the network.

    `info` is a property rather than a plain attribute so `info_access_count`
    can record every read -- that counter is what the memoization test
    asserts on. `balance_sheet`/`quarterly_balance_sheet` default to None
    (not an empty DataFrame) to mirror a yfinance version or ticker that
    exposes no balance sheet at all.
    """

    def __init__(
        self,
        info=None,
        history_df=None,
        balance_sheet=None,
        quarterly_balance_sheet=None,
    ):
        self._info = info if info is not None else {}
        self._history_df = history_df if history_df is not None else pd.DataFrame()
        self.balance_sheet = balance_sheet
        self.quarterly_balance_sheet = quarterly_balance_sheet
        self.history_calls = []
        self.info_access_count = 0

    @property
    def info(self):
        self.info_access_count += 1
        return self._info

    def history(self, period="1y"):
        self.history_calls.append(period)
        return self._history_df


def make_fake_yf_ticker(
    info=None, history_df=None, balance_sheet=None, quarterly_balance_sheet=None
):
    return FakeYfTicker(
        info=info,
        history_df=history_df,
        balance_sheet=balance_sheet,
        quarterly_balance_sheet=quarterly_balance_sheet,
    )


def balance_sheet_frame(rows):
    """Build a balance-sheet-shaped DataFrame: row labels are line items,
    columns are statement dates with the most recent FIRST (which is how
    yfinance orders them, and why the provider reads column 0).
    """
    index = list(rows.keys())
    recent = [values[0] for values in rows.values()]
    older = [values[1] for values in rows.values()]
    return pd.DataFrame(
        {
            pd.Timestamp("2024-09-30"): recent,
            pd.Timestamp("2023-09-30"): older,
        },
        index=index,
    )


def install_fake_ticker(monkeypatch, fake_ticker):
    """Patch yfinance.Ticker to hand back `fake_ticker`, counting calls."""
    calls = []

    def factory(ticker):
        calls.append(ticker)
        return fake_ticker

    monkeypatch.setattr("yfinance.Ticker", factory)
    return calls


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
    """`non_permissible_income` has no yfinance source at all (structural, not
    per-ticker) and is always None -- unlike `receivables`, which is now read
    from the balance sheet (see the receivables tests below).
    """
    fake_ticker = make_fake_yf_ticker(
        info={
            "totalDebt": 1_000_000,
            "totalCash": 500_000,
            "marketCap": 50_000_000,
            "totalRevenue": 10_000_000,
        },
        balance_sheet=balance_sheet_frame({"Receivables": [60_000.0, 55_000.0]}),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.non_permissible_income is None


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


# --- receivables, sourced from the balance sheet (Fix 1) ---


def test_receivables_read_from_annual_balance_sheet(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={"marketCap": 50_000_000},
        balance_sheet=balance_sheet_frame(
            {
                "Total Assets": [900_000.0, 850_000.0],
                "Receivables": [72_957.0, 66_243.0],
            }
        ),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.receivables == 72_957.0


def test_receivables_uses_most_recent_column(monkeypatch):
    """yfinance orders balance-sheet columns most-recent-first; reading the
    wrong end would silently screen against stale figures.
    """
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=balance_sheet_frame({"Receivables": [100.0, 999.0]}),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables == 100.0


def test_receivables_accepts_alternate_row_labels(monkeypatch):
    """Row labels vary by ticker and yfinance version, so the lookup has to
    be label-tolerant rather than keyed on one exact spelling.
    """
    for label in ("Net Receivables", "Accounts Receivable", "receivables", "NetReceivables"):
        fake_ticker = make_fake_yf_ticker(
            info={},
            balance_sheet=balance_sheet_frame({label: [1_234.0, 1_000.0]}),
        )
        monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
        fundamentals = YFinanceProvider().get_fundamentals("X")
        assert fundamentals.receivables == 1_234.0, label


def test_receivables_prefers_the_total_row_over_components(monkeypatch):
    """A real balance sheet carries "Receivables" (the total) alongside
    "Accounts Receivable" and "Other Receivables" -- picking a component
    would understate the ratio's numerator.
    """
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=balance_sheet_frame(
            {
                "Accounts Receivable": [39_777.0, 33_410.0],
                "Other Receivables": [33_180.0, 32_833.0],
                "Receivables": [72_957.0, 66_243.0],
            }
        ),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables == 72_957.0


def test_receivables_ignores_contra_and_unrelated_receivable_rows(monkeypatch):
    """"Receivables Adjustments Allowances" (a negative contra-account) and
    "Taxes Receivable" both contain the word, and neither is the figure the
    halal screen wants -- a blind substring match would pick one of them.
    """
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=balance_sheet_frame(
            {
                "Receivables Adjustments Allowances": [-798.0, -700.0],
                "Taxes Receivable": [864.0, 800.0],
            }
        ),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables is None


def test_receivables_falls_back_to_quarterly_balance_sheet(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=pd.DataFrame(),  # annual unavailable/empty
        quarterly_balance_sheet=balance_sheet_frame({"Receivables": [4_200.0, 4_000.0]}),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables == 4_200.0


def test_receivables_is_none_when_no_receivables_row_present(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=balance_sheet_frame(
            {"Total Assets": [900_000.0, 850_000.0], "Total Debt": [10.0, 9.0]}
        ),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables is None


def test_receivables_is_none_when_balance_sheet_absent_entirely(monkeypatch):
    """Graceful degradation: no balance sheet at all must still be None, not
    an exception -- the provider's documented contract.
    """
    fake_ticker = make_fake_yf_ticker(info={})
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables is None


def test_receivables_is_none_when_row_value_is_nan(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={},
        balance_sheet=balance_sheet_frame({"Receivables": [float("nan"), 1.0]}),
    )
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    assert YFinanceProvider().get_fundamentals("X").receivables is None


def test_receivables_survives_a_raising_balance_sheet_property(monkeypatch):
    """yfinance can raise from inside the balance_sheet property on a network
    or parse failure; that must degrade to None, not abort the ticker.
    """

    class ExplodingTicker:
        info = {"marketCap": 1.0}

        @property
        def balance_sheet(self):
            raise RuntimeError("yfinance backend blew up")

        @property
        def quarterly_balance_sheet(self):
            raise RuntimeError("yfinance backend blew up")

    monkeypatch.setattr("yfinance.Ticker", lambda t: ExplodingTicker())
    fundamentals = YFinanceProvider().get_fundamentals("X")
    assert fundamentals.receivables is None
    assert fundamentals.market_cap == 1.0


# --- .info memoization (Fix 4) ---


def test_info_fetched_once_across_fundamentals_and_profile(monkeypatch):
    """`.info` is the slowest, most rate-limit-sensitive call per ticker.
    Both get_fundamentals and get_company_profile need it, so it must be
    fetched once, not twice.
    """
    fake_ticker = make_fake_yf_ticker(
        info={"marketCap": 1.0, "sector": "Technology"},
        balance_sheet=balance_sheet_frame({"Receivables": [1.0, 1.0]}),
    )
    install_fake_ticker(monkeypatch, fake_ticker)
    provider = YFinanceProvider()
    provider.get_fundamentals("AAPL")
    provider.get_company_profile("AAPL")
    assert fake_ticker.info_access_count == 1


def test_ticker_object_constructed_once_per_ticker(monkeypatch):
    fake_ticker = make_fake_yf_ticker(
        info={"marketCap": 1.0},
        balance_sheet=balance_sheet_frame({"Receivables": [1.0, 1.0]}),
        history_df=sample_ohlcv_dataframe(),
    )
    calls = install_fake_ticker(monkeypatch, fake_ticker)
    provider = YFinanceProvider()
    provider.get_price_history("AAPL")
    provider.get_fundamentals("AAPL")
    provider.get_company_profile("AAPL")
    assert calls == ["AAPL"]


def test_distinct_tickers_are_cached_separately(monkeypatch):
    """Memoization must be keyed on the ticker -- a single shared entry would
    return one company's data for another's symbol.
    """
    tickers = {
        "AAPL": make_fake_yf_ticker(info={"sector": "Technology"}),
        "XOM": make_fake_yf_ticker(info={"sector": "Energy"}),
    }
    monkeypatch.setattr("yfinance.Ticker", lambda t: tickers[t])
    provider = YFinanceProvider()
    assert provider.get_company_profile("AAPL").sector == "Technology"
    assert provider.get_company_profile("XOM").sector == "Energy"
    assert provider.get_company_profile("AAPL").sector == "Technology"
    assert tickers["AAPL"].info_access_count == 1
    assert tickers["XOM"].info_access_count == 1
