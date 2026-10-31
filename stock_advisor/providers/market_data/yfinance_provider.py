"""Market data provider backed by the yfinance library.

Known gaps in this provider (documented here rather than guessed around):

- `Fundamentals.non_permissible_income` has no corresponding field anywhere
  in yfinance (not in `.info`, not in the financial statements), so it is
  always `None` from this provider. This is a structural gap in free data,
  not a per-ticker one — see the module docstring of
  `stock_advisor.analysis.halal_screen` for how the screen handles it (it
  does *not* treat it as per-ticker missing data, because that would make
  every verdict `insufficient_data` forever).
- `Fundamentals.receivables` is read from the balance-sheet statement
  (`.balance_sheet`, falling back to `.quarterly_balance_sheet`), since
  yfinance exposes receivables only there and not in `.info`. Row labels
  vary by ticker and yfinance version, so `_extract_receivables` matches
  them defensively; a ticker whose balance sheet has no usable receivables
  row still yields `None` rather than raising.

Caching: each provider instance memoizes both the `yfinance.Ticker` object
and its `.info` dict per ticker. `.info` is the slowest and most
rate-limit-sensitive call per ticker and *both* `get_fundamentals` and
`get_company_profile` need it, so without this a single scan fetched it
twice for every one of ~600 tickers. The `.info` dict is cached here rather
than leaning on `yfinance.Ticker`'s own internal memoization, which is an
implementation detail that has varied across versions. These caches are
per-instance and never invalidated, which suits the single-pass scan/review
lifecycle these scripts have; they are not a long-lived process-wide cache.
"""
import yfinance

from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    MarketDataProvider,
    PriceSeries,
)

# Balance-sheet row labels that represent a usable receivables figure, in
# priority order (most preferred first). Compared against the normalized
# (lowercased, non-alphanumerics stripped) row label, so "Net Receivables",
# "net receivables" and "NetReceivables" all match the same entry.
RECEIVABLES_ROW_LABELS = (
    "receivables",
    "netreceivables",
    "totalreceivables",
    "receivablesnet",
    "accountsreceivable",
    "netaccountsreceivable",
    "grossaccountsreceivable",
)

# Substrings that disqualify a row from the loose fallback match below. Real
# balance sheets carry rows like "Receivables Adjustments Allowances" (a
# negative contra-account), "Taxes Receivable" and "Other Receivables" — none
# of which is the receivables total the halal screen wants.
RECEIVABLES_ROW_EXCLUSIONS = (
    "adjustment",
    "allowance",
    "tax",
    "other",
    "payable",
    "duefrom",
    "loan",
)


def _normalize_row_label(label: object) -> str:
    """Lowercase a balance-sheet row label and strip everything that isn't
    alphanumeric, so label casing/spacing differences between tickers and
    yfinance versions don't change whether a row is found.
    """
    return "".join(char for char in str(label).lower() if char.isalnum())


def _most_recent_value(frame, label) -> float | None:
    """Read the most recent (first) column of `frame.loc[label]` as a float,
    or `None` if the row is empty or the value isn't a finite number.
    """
    try:
        value = frame.loc[label].iloc[0]
    except Exception:
        return None
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric != numeric:  # NaN
        return None
    return numeric


def _extract_receivables(frame) -> float | None:
    """Pull a receivables figure out of a yfinance balance-sheet DataFrame.

    Tries `RECEIVABLES_ROW_LABELS` in priority order against normalized row
    labels, then falls back to any row mentioning "receivable" that isn't
    disqualified by `RECEIVABLES_ROW_EXCLUSIONS`. Returns `None` for a frame
    that is empty, missing, or has no usable row — never raises, so a ticker
    with an odd or absent balance sheet degrades gracefully.
    """
    if frame is None:
        return None
    try:
        if getattr(frame, "empty", True):
            return None
        index = list(frame.index)
    except Exception:
        return None

    normalized = {_normalize_row_label(label): label for label in index}

    for wanted in RECEIVABLES_ROW_LABELS:
        label = normalized.get(wanted)
        if label is not None:
            value = _most_recent_value(frame, label)
            if value is not None:
                return value

    for norm, label in normalized.items():
        if "receivable" not in norm:
            continue
        if any(excluded in norm for excluded in RECEIVABLES_ROW_EXCLUSIONS):
            continue
        value = _most_recent_value(frame, label)
        if value is not None:
            return value

    return None


class YFinanceProvider(MarketDataProvider):
    """Market data provider that reads from Yahoo Finance via yfinance."""

    def __init__(self) -> None:
        """Create a provider with empty per-instance `Ticker` and `.info` caches."""
        self._tickers: dict[str, object] = {}
        self._infos: dict[str, dict] = {}

    def _ticker(self, ticker: str):
        """Return the memoized `yfinance.Ticker` for `ticker`, constructing
        it on first use, so one ticker means one object across all three
        provider methods.
        """
        if ticker not in self._tickers:
            self._tickers[ticker] = yfinance.Ticker(ticker)
        return self._tickers[ticker]

    def _info(self, ticker: str) -> dict:
        """Return the memoized `.info` dict for `ticker`.

        Cached here rather than relying on `yfinance.Ticker`'s own internal
        `.info` memoization, which is an implementation detail that has
        varied across yfinance versions. Caching in the provider makes the
        "one `.info` fetch per ticker" guarantee ours to keep.
        """
        if ticker not in self._infos:
            self._infos[ticker] = self._ticker(ticker).info
        return self._infos[ticker]

    def get_price_history(self, ticker: str, period: str = "1y") -> PriceSeries:
        """Fetch and parse the historical daily price series for a ticker."""
        history = self._ticker(ticker).history(period=period)
        dates = [timestamp.date() for timestamp in history.index]
        close = [float(value) for value in history["Close"]] if "Close" in history else []
        volume = [float(value) for value in history["Volume"]] if "Volume" in history else []
        return PriceSeries(dates=dates, close=close, volume=volume)

    def _receivables(self, ticker: str) -> float | None:
        """Read the most recent receivables figure from the balance sheet.

        Prefers the annual statement and falls back to the quarterly one when
        the annual is empty or unavailable. Any failure (no such attribute, a
        network/parse error inside yfinance, an unexpected frame shape)
        degrades to `None` — the provider's contract is that an undeterminable
        field is `None`, never an exception.
        """
        yf_ticker = self._ticker(ticker)
        for attribute in ("balance_sheet", "quarterly_balance_sheet"):
            try:
                frame = getattr(yf_ticker, attribute, None)
            except Exception:
                continue
            value = _extract_receivables(frame)
            if value is not None:
                return value
        return None

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Fetch fundamental financial figures for a ticker.

        `.info`-sourced fields are read with `.get(key)` (never `[key]`) so a
        missing key becomes `None` rather than raising. `receivables` comes
        from the balance sheet instead (see `_receivables`).
        `non_permissible_income` has no yfinance source at all and is always
        `None` — see the module docstring.
        """
        info = self._info(ticker)
        return Fundamentals(
            total_debt=info.get("totalDebt"),
            total_cash=info.get("totalCash"),
            market_cap=info.get("marketCap"),
            total_revenue=info.get("totalRevenue"),
            non_permissible_income=None,
            receivables=self._receivables(ticker),
        )

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Fetch descriptive profile information for a ticker.

        Every field is read with `.get(key)` (never `[key]`) so a missing
        key becomes `None` rather than raising.
        """
        info = self._info(ticker)
        return CompanyProfile(
            sector=info.get("sector"),
            industry=info.get("industry"),
            business_summary=info.get("longBusinessSummary"),
        )
