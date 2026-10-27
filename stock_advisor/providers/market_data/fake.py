"""Fake market data provider for testing."""
from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    MarketDataProvider,
    PriceSeries,
)


class FakeMarketDataProvider(MarketDataProvider):
    """A fake market data provider that returns canned data by ticker."""

    def __init__(
        self,
        prices: dict[str, PriceSeries],
        fundamentals: dict[str, Fundamentals],
        profiles: dict[str, CompanyProfile],
    ):
        """Initialize with canned data keyed by ticker."""
        self._prices = prices
        self._fundamentals = fundamentals
        self._profiles = profiles

    def get_price_history(self, ticker: str, period: str = "1y") -> PriceSeries:
        """Return the canned price series for the ticker."""
        return self._prices[ticker]

    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Return the canned fundamentals for the ticker."""
        return self._fundamentals[ticker]

    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Return the canned company profile for the ticker."""
        return self._profiles[ticker]
