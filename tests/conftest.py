import pytest
from stock_advisor.providers.broker.base import (
    AccountSummary,
    Instrument,
    Position,
)
from stock_advisor.providers.broker.fake import FakeBrokerProvider


@pytest.fixture
def make_fake_broker_provider():
    """Factory fixture that creates a FakeBrokerProvider with canned test data."""
    def _factory():
        summary = AccountSummary(
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

        positions = [
            Position(
                ticker="ASML",
                name="ASML Holding NV",
                isin="NL0010273215",
                currency="EUR",
                quantity=10.5,
                quantity_available=10.5,
                current_price=450.25,
                average_price_paid=420.0,
                wallet_currency="GBP",
                wallet_current_value=4725.26,
                wallet_total_cost=4410.0,
                wallet_unrealized_pl=315.26,
            )
        ]

        instruments = [
            Instrument(
                ticker="ASML",
                name="ASML Holding NV",
                short_name="ASML",
                isin="NL0010273215",
                currency_code="EUR",
                type="stock",
            )
        ]

        return FakeBrokerProvider(
            account_summary=summary,
            positions=positions,
            instruments=instruments,
        )

    return _factory
