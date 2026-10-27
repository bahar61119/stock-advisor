"""Fake broker provider for testing."""
from stock_advisor.providers.broker.base import (
    AccountSummary,
    BrokerProvider,
    Instrument,
    Position,
)


class FakeBrokerProvider(BrokerProvider):
    """A fake broker provider that returns canned data."""

    def __init__(
        self,
        account_summary: AccountSummary,
        positions: list[Position],
        instruments: list[Instrument],
    ):
        """Initialize with canned data."""
        self._account_summary = account_summary
        self._positions = positions
        self._instruments = instruments

    def get_account_summary(self) -> AccountSummary:
        """Return the canned account summary."""
        return self._account_summary

    def get_positions(self) -> list[Position]:
        """Return the canned positions list."""
        return self._positions

    def get_instruments(self) -> list[Instrument]:
        """Return the canned instruments list."""
        return self._instruments
