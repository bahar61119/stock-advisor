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


# --- Domain errors instead of raw HTTP/parse exceptions (Fix 8) ---

import json  # noqa: E402

import pytest  # noqa: E402
import requests  # noqa: E402

from stock_advisor.providers.broker.trading212 import Trading212Error  # noqa: E402


def creds(monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")


def test_401_raises_domain_error_naming_the_credential_variables(requests_mock, monkeypatch):
    """The first-run failure mode is almost always a bad key, and a bare
    requests.HTTPError doesn't say which variables to check.
    """
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        status_code=401,
        json={"error": "unauthorized"},
    )
    with pytest.raises(Trading212Error) as excinfo:
        Trading212BrokerProvider(env="demo").get_account_summary()
    message = str(excinfo.value)
    assert excinfo.value.status_code == 401
    assert "credentials rejected" in message
    assert "T212_API_KEY" in message
    assert "T212_API_KEY_STOCKS_ISA" in message


def test_401_domain_error_is_not_a_bare_http_error(requests_mock, monkeypatch):
    """requests.HTTPError must no longer reach the caller -- that is what
    made 401, 429 and 5xx indistinguishable.
    """
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/positions",
        status_code=401,
        json={},
    )
    with pytest.raises(Trading212Error) as excinfo:
        Trading212BrokerProvider(env="demo").get_positions()
    assert not isinstance(excinfo.value, requests.HTTPError)


def test_429_raises_domain_error_mentioning_rate_limiting(requests_mock, monkeypatch, tmp_path):
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        status_code=429,
        json={},
    )
    provider = Trading212BrokerProvider(
        env="demo", instrument_cache_path=str(tmp_path / "missing.json")
    )
    with pytest.raises(Trading212Error, match="rate limited"):
        provider.get_instruments()


def test_other_status_codes_get_a_generic_but_identifiable_message(requests_mock, monkeypatch):
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        status_code=503,
        json={},
    )
    with pytest.raises(Trading212Error) as excinfo:
        Trading212BrokerProvider(env="demo").get_account_summary()
    assert excinfo.value.status_code == 503
    assert "HTTP 503" in str(excinfo.value)


def test_non_json_response_body_raises_domain_error(requests_mock, monkeypatch):
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        status_code=200,
        text="<html>maintenance</html>",
    )
    with pytest.raises(Trading212Error, match="non-JSON body"):
        Trading212BrokerProvider(env="demo").get_account_summary()


def test_transport_failure_raises_domain_error(requests_mock, monkeypatch):
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        exc=requests.ConnectTimeout("connection timed out"),
    )
    with pytest.raises(Trading212Error, match="before a response"):
        Trading212BrokerProvider(env="demo").get_account_summary()


# --- A corrupted instrument cache is a cache miss, not a crash ---


FRESH_INSTRUMENT = {
    "ticker": "MSFT_US_EQ",
    "name": "Microsoft",
    "shortName": "MSFT",
    "isin": "US5949181045",
    "currencyCode": "USD",
    "type": "STOCK",
}


@pytest.mark.parametrize(
    "corrupt_contents",
    [
        '[{"ticker": "AAPL_US_EQ", "name": "App',  # truncated mid-write
        "not json at all",
        "",
        '[{"ticker": "AAPL_US_EQ"}]',  # valid JSON, missing required keys
        '{"instruments": []}',  # valid JSON, wrong shape entirely
    ],
    ids=["truncated", "garbage", "empty", "missing-keys", "wrong-shape"],
)
def test_corrupted_cache_is_treated_as_a_miss_and_refetched(
    corrupt_contents, tmp_path, requests_mock, monkeypatch
):
    """A truncated cache is exactly what an interrupted run leaves behind.
    A cache is an optimization; a bad one should cost a request, not the run.
    """
    creds(monkeypatch)
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text(corrupt_contents)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[FRESH_INSTRUMENT],
    )
    provider = Trading212BrokerProvider(
        env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600
    )
    instruments = provider.get_instruments()
    assert [i.short_name for i in instruments] == ["MSFT"]
    assert requests_mock.call_count == 1


def test_corrupted_cache_is_overwritten_with_the_refetched_payload(
    tmp_path, requests_mock, monkeypatch
):
    """The repair has to stick, or every subsequent run pays for it again."""
    creds(monkeypatch)
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text("{{{ truncated")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[FRESH_INSTRUMENT],
    )
    provider = Trading212BrokerProvider(
        env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600
    )
    provider.get_instruments()
    assert json.loads(cache_file.read_text()) == [FRESH_INSTRUMENT]


def test_unreadable_cache_path_is_treated_as_a_miss(tmp_path, requests_mock, monkeypatch):
    """A directory where a cache file should be: an OSError on read, which
    must fall through to the fetch path -- and the subsequent failed *write*
    must not abort the run either.
    """
    creds(monkeypatch)
    cache_path = tmp_path / "instruments.json"
    cache_path.mkdir()
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[FRESH_INSTRUMENT],
    )
    provider = Trading212BrokerProvider(
        env="demo", instrument_cache_path=str(cache_path), cache_max_age_seconds=3600
    )
    assert provider.get_instruments()[0].short_name == "MSFT"


def test_malformed_api_payload_raises_domain_error_not_key_error(
    requests_mock, monkeypatch, tmp_path
):
    creds(monkeypatch)
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[{"ticker": "AAPL_US_EQ"}],
    )
    provider = Trading212BrokerProvider(
        env="demo", instrument_cache_path=str(tmp_path / "missing.json")
    )
    with pytest.raises(Trading212Error, match="not in the expected"):
        provider.get_instruments()
