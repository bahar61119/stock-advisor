import pytest
from stock_advisor.providers.market_data.base import (
    CompanyProfile,
    Fundamentals,
    PriceSeries,
)


@pytest.mark.parametrize("provider_factory", ["make_fake_market_data_provider"])
def test_market_data_provider_contract(provider_factory, request):
    """Test that a MarketDataProvider implementation satisfies the contract."""
    # Get the actual fixture function from the request
    factory = request.getfixturevalue(provider_factory)
    provider = factory()

    assert isinstance(provider.get_price_history("AAPL"), PriceSeries)
    assert isinstance(provider.get_fundamentals("AAPL"), Fundamentals)
    assert isinstance(provider.get_company_profile("AAPL"), CompanyProfile)
