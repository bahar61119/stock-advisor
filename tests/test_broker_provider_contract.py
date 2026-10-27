import pytest
from stock_advisor.providers.broker.base import (
    AccountSummary,
    Instrument,
    Position,
)


@pytest.mark.parametrize("provider_factory", ["make_fake_broker_provider"])
def test_broker_provider_contract(provider_factory, request):
    """Test that a BrokerProvider implementation satisfies the contract."""
    # Get the actual fixture function from the request
    factory = request.getfixturevalue(provider_factory)
    provider = factory()

    # Test get_account_summary()
    summary = provider.get_account_summary()
    assert isinstance(summary, AccountSummary)

    # Test get_positions()
    positions = provider.get_positions()
    assert isinstance(positions, list)
    assert all(isinstance(p, Position) for p in positions)

    # Test get_instruments()
    instruments = provider.get_instruments()
    assert isinstance(instruments, list)
    assert all(isinstance(i, Instrument) for i in instruments)
