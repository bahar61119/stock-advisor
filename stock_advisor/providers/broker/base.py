"""Base classes and data types for broker providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AccountSummary:
    """Summary of a brokerage account."""
    currency: str
    total_value: float
    cash_available: float
    cash_reserved: float
    cash_in_pies: float
    investments_current_value: float
    investments_total_cost: float
    realized_pl: float
    unrealized_pl: float


@dataclass
class Position:
    """A position held in a brokerage account."""
    ticker: str
    name: str
    isin: str
    currency: str
    quantity: float
    quantity_available: float
    current_price: float
    average_price_paid: float
    wallet_currency: str
    wallet_current_value: float
    wallet_total_cost: float
    wallet_unrealized_pl: float


@dataclass
class Instrument:
    """An investable instrument (stock, ETF, etc.)."""
    ticker: str
    name: str
    short_name: str
    isin: str
    currency_code: str
    type: str


class BrokerProvider(ABC):
    """Abstract base class for broker data providers."""

    @abstractmethod
    def get_account_summary(self) -> AccountSummary:
        """Get the account summary."""
        pass

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get the list of current positions."""
        pass

    @abstractmethod
    def get_instruments(self) -> list[Instrument]:
        """Get the list of available instruments."""
        pass
