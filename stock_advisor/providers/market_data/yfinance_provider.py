"""Market data provider backed by the yfinance library.

Known gaps in this provider (documented here rather than guessed around):

- `Fundamentals.non_permissible_income` has no corresponding field anywhere
  in yfinance (not in `.info`, not in the financial statements), so it is
  always `None` from this provider. Downstream halal-screening logic treats
  a `None` field as `insufficient_data` for whichever ratio depends on it.
- `Fundamentals.receivables` is likewise always `None`. yfinance exposes
  receivables line items (e.g. "Receivables", "AccountsReceivable") only via
  the balance-sheet statement endpoints, not via `.info`; this provider only
  reads `.info` and `.history(...)`, so the field is left `None` rather than
  adding a second yfinance call path outside this task's scope.
"""
import yfinance

from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    MarketDataProvider,
    PriceSeries,
)


class YFinanceProvider(MarketDataProvider):
    """Market data provider that reads from Yahoo Finance via yfinance."""

    def get_price_history(self, ticker: str, period: str = "1y") -> PriceSeries:
        """Fetch and parse the historical daily price series for a ticker."""
        history = yfinance.Ticker(ticker).history(period=period)
        dates = [timestamp.date() for timestamp in history.index]
        close = [float(value) for value in history["Close"]] if "Close" in history else []
        volume = [float(value) for value in history["Volume"]] if "Volume" in history else []
        return PriceSeries(dates=dates, close=close, volume=volume)

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Fetch fundamental financial figures for a ticker.

        Every field is read with `.get(key)` (never `[key]`) so a missing
        key becomes `None` rather than raising. See the module docstring for
        the two fields (`non_permissible_income`, `receivables`) that have no
        yfinance source at all and are therefore always `None`.
        """
        info = yfinance.Ticker(ticker).info
        return Fundamentals(
            total_debt=info.get("totalDebt"),
            total_cash=info.get("totalCash"),
            market_cap=info.get("marketCap"),
            total_revenue=info.get("totalRevenue"),
            non_permissible_income=None,
            receivables=None,
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Fetch descriptive profile information for a ticker.

        Every field is read with `.get(key)` (never `[key]`) so a missing
        key becomes `None` rather than raising.
        """
        info = yfinance.Ticker(ticker).info
        return CompanyProfile(
            sector=info.get("sector"),
            industry=info.get("industry"),
            business_summary=info.get("longBusinessSummary"),
        )
