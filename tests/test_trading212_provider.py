import base64
import os
import time

from stock_advisor.providers.broker.trading212 import Trading212BrokerProvider


def test_auth_header_from_plain_pair(monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "key123")
    monkeypatch.setenv("T212_API_SECRET", "secret456")
    provider = Trading212BrokerProvider(env="demo")
    assert provider._auth_header() == "Basic " + base64.b64encode(b"key123:secret456").decode()


def test_auth_header_prefers_stocks_isa_pair_when_present(monkeypatch):
    monkeypatch.setenv("T212_API_KEY_STOCKS_ISA", "isakey")
    monkeypatch.setenv("T212_API_SECRET_STOCKS_ISA", "isasecret")
    provider = Trading212BrokerProvider(env="live")
    assert provider._auth_header() == "Basic " + base64.b64encode(b"isakey:isasecret").decode()


def test_auth_header_raises_when_no_credentials(monkeypatch):
    monkeypatch.delenv("T212_API_KEY_STOCKS_ISA", raising=False)
    monkeypatch.delenv("T212_API_SECRET_STOCKS_ISA", raising=False)
    monkeypatch.delenv("T212_API_KEY", raising=False)
    monkeypatch.delenv("T212_API_SECRET", raising=False)
    provider = Trading212BrokerProvider(env="demo")
    try:
        provider._auth_header()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "T212_API_KEY" in str(exc)


def test_get_account_summary_maps_fields(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        json={"currency": "GBP", "totalValue": 15250.75,
              "cash": {"availableToTrade": 2500.5, "reservedForOrders": 150.0, "inPies": 500.0},
              "investments": {"currentValue": 12100.25, "totalCost": 10500.0,
                               "realizedProfitLoss": 850.5, "unrealizedProfitLoss": 1600.25}},
    )
    summary = Trading212BrokerProvider(env="demo").get_account_summary()
    assert summary.currency == "GBP"
    assert summary.total_value == 15250.75
    assert summary.cash_available == 2500.5
    assert summary.cash_reserved == 150.0
    assert summary.cash_in_pies == 500.0
    assert summary.investments_current_value == 12100.25
    assert summary.investments_total_cost == 10500.0
    assert summary.realized_pl == 850.5
    assert summary.unrealized_pl == 1600.25


def test_get_account_summary_sends_basic_auth_header(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "key123")
    monkeypatch.setenv("T212_API_SECRET", "secret456")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        json={"currency": "GBP", "totalValue": 1.0,
              "cash": {"availableToTrade": 0.0, "reservedForOrders": 0.0, "inPies": 0.0},
              "investments": {"currentValue": 0.0, "totalCost": 0.0,
                               "realizedProfitLoss": 0.0, "unrealizedProfitLoss": 0.0}},
    )
    Trading212BrokerProvider(env="demo").get_account_summary()
    expected = "Basic " + base64.b64encode(b"key123:secret456").decode()
    assert requests_mock.last_request.headers["Authorization"] == expected


def test_get_positions_maps_fields(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/positions",
        json=[{"instrument": {"ticker": "AAPL_US_EQ", "name": "Apple Inc",
                               "isin": "US0378331005", "currency": "USD"},
               "quantity": 15.5, "quantityAvailableForTrading": 12.5,
               "currentPrice": 185.5, "averagePricePaid": 170.25,
               "walletImpact": {"currency": "GBP", "totalCost": 2089.45,
                                 "currentValue": 2275.1, "unrealizedProfitLoss": 185.65}}],
    )
    positions = Trading212BrokerProvider(env="demo").get_positions()
    assert positions[0].ticker == "AAPL_US_EQ"
    assert positions[0].name == "Apple Inc"
    assert positions[0].isin == "US0378331005"
    assert positions[0].currency == "USD"
    assert positions[0].quantity == 15.5
    assert positions[0].quantity_available == 12.5
    assert positions[0].current_price == 185.5
    assert positions[0].average_price_paid == 170.25
    assert positions[0].wallet_currency == "GBP"
    assert positions[0].wallet_total_cost == 2089.45
    assert positions[0].wallet_current_value == 2275.1
    assert positions[0].wallet_unrealized_pl == 185.65


def test_get_instruments_uses_cache_when_fresh(tmp_path, requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text('[{"ticker": "AAPL_US_EQ", "name": "Apple Inc", "shortName": "AAPL", "isin": "US0378331005", "currencyCode": "USD", "type": "STOCK"}]')
    provider = Trading212BrokerProvider(env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600)
    instruments = provider.get_instruments()
    assert instruments[0].short_name == "AAPL"
    assert instruments[0].ticker == "AAPL_US_EQ"
    assert instruments[0].name == "Apple Inc"
    assert instruments[0].isin == "US0378331005"
    assert instruments[0].currency_code == "USD"
    assert instruments[0].type == "STOCK"
    assert requests_mock.call_count == 0  # cache hit, no HTTP call


def test_get_instruments_refetches_when_cache_stale(tmp_path, requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text("[]")
    old_time = time.time() - 7200
    os.utime(cache_file, (old_time, old_time))
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[{"ticker": "MSFT_US_EQ", "name": "Microsoft", "shortName": "MSFT", "isin": "US5949181045", "currencyCode": "USD", "type": "STOCK"}],
    )
    provider = Trading212BrokerProvider(env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600)
    instruments = provider.get_instruments()
    assert instruments[0].short_name == "MSFT"
    assert requests_mock.call_count == 1


def test_get_instruments_refetches_when_cache_missing(tmp_path, requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    cache_file = tmp_path / "instruments.json"
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[{"ticker": "MSFT_US_EQ", "name": "Microsoft", "shortName": "MSFT", "isin": "US5949181045", "currencyCode": "USD", "type": "STOCK"}],
    )
    provider = Trading212BrokerProvider(env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600)
    instruments = provider.get_instruments()
    assert instruments[0].short_name == "MSFT"
    assert cache_file.exists()
    assert requests_mock.call_count == 1


def test_get_requests_pass_a_timeout(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        json={"currency": "GBP", "totalValue": 1.0,
              "cash": {"availableToTrade": 0.0, "reservedForOrders": 0.0, "inPies": 0.0},
              "investments": {"currentValue": 0.0, "totalCost": 0.0,
                               "realizedProfitLoss": 0.0, "unrealizedProfitLoss": 0.0}},
    )
    Trading212BrokerProvider(env="demo").get_account_summary()
    assert requests_mock.last_request.timeout is not None


def test_base_url_uses_env_parameter(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://live.trading212.com/api/v0/equity/account/summary",
        json={"currency": "GBP", "totalValue": 1.0,
              "cash": {"availableToTrade": 0.0, "reservedForOrders": 0.0, "inPies": 0.0},
              "investments": {"currentValue": 0.0, "totalCost": 0.0,
                               "realizedProfitLoss": 0.0, "unrealizedProfitLoss": 0.0}},
    )
    Trading212BrokerProvider(env="live").get_account_summary()
    assert requests_mock.called
