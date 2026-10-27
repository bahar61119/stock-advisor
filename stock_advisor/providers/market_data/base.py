"""Base classes and data types for market data providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class PriceSeries:
    """Historical daily price series for a single ticker."""
    dates: list[date]
    close: list[float]
    volume: list[float]


@dataclass
class Fundamentals:
    """Fundamental financial figures for a single ticker.

    Every field is `None` when the provider cannot determine it — never a
    guessed or interpolated value. Downstream halal-screening logic treats a
    `None` field as `insufficient_data` for whichever ratio depends on it,
    rather than assuming compliance or non-compliance.
    """
    total_debt: float | None
    total_cash: float | None
    market_cap: float | None
    total_revenue: float | None
    non_permissible_income: float | None
    receivables: float | None


@dataclass
class CompanyProfile:
    """Descriptive profile information for a single ticker."""
    sector: str | None
    industry: str | None
    business_summary: str | None


class MarketDataProvider(ABC):
    """Abstract base class for market data providers."""

    @abstractmethod
    def get_price_history(self, ticker: str, period: str = "1y") -> PriceSeries:
        """Get the historical daily price series for a ticker."""
        pass

    @abstractmethod
    def get_fundamentals(self, ticker: str) -> Fundamentals:
        """Get fundamental financial figures for a ticker."""
        pass

    @abstractmethod
    def get_company_profile(self, ticker: str) -> CompanyProfile:
        """Get descriptive profile information for a ticker."""
        pass
