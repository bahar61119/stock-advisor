"""Tests for provider selection (Fix 6) and the T212_ENV wiring (Fix 5).

`config.broker_provider` / `config.market_data_provider` were validated at
load time but never read -- both scripts hardcoded their providers, so the
config keys did nothing. And `T212_ENV` was documented in `.env.example` and
README.md but never read either, so the documented demo/live safety switch
silently did nothing and the provider always hit the live account.

These tests check the wiring, not the network: no request is ever issued.
"""
import pytest

from stock_advisor.config import AppConfig, HalalThresholds
from stock_advisor.providers.broker.trading212 import Trading212BrokerProvider
from stock_advisor.providers.factory import build_broker, build_market_data
from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider

DEFAULT_THRESHOLDS = HalalThresholds(
    debt_to_market_cap=0.33,
    cash_and_interest_to_market_cap=0.33,
    receivables_and_cash_to_market_cap=0.33,
    non_permissible_income_ratio=0.05,
)


def make_config(broker="trading212", market_data="yfinance") -> AppConfig:
    return AppConfig(
        broker_provider=broker,
        market_data_provider=market_data,
        shortlist_size=20,
        halal_thresholds=DEFAULT_THRESHOLDS,
        universe_sources=["sp500"],
        instrument_cache_path=".cache/t212_instruments.json",
        instrument_cache_max_age_seconds=3600,
    )


# --- Fix 6: the config actually selects the provider ---


def test_build_broker_returns_the_configured_broker():
    broker = build_broker(make_config())
    assert isinstance(broker, Trading212BrokerProvider)


def test_build_market_data_returns_the_configured_provider():
    assert isinstance(build_market_data(make_config()), YFinanceProvider)


def test_build_broker_passes_cache_settings_from_config():
    config = make_config()
    config = AppConfig(
        broker_provider=config.broker_provider,
        market_data_provider=config.market_data_provider,
        shortlist_size=config.shortlist_size,
        halal_thresholds=config.halal_thresholds,
        universe_sources=config.universe_sources,
        instrument_cache_path="/tmp/custom_cache.json",
        instrument_cache_max_age_seconds=99,
    )
    broker = build_broker(config)
    assert broker._instrument_cache_path == "/tmp/custom_cache.json"
    assert broker._cache_max_age_seconds == 99


def test_build_broker_rejects_an_unknown_name_clearly():
    """load_config already rejects these, but an AppConfig can be built
    directly -- and a factory that quietly fell back to a default provider
    would be a worse failure than one that names what it was asked for.
    """
    with pytest.raises(ValueError, match="Unknown broker_provider: not_a_broker"):
        build_broker(make_config(broker="not_a_broker"))


def test_build_market_data_rejects_an_unknown_name_clearly():
    with pytest.raises(ValueError, match="Unknown market_data_provider: nope"):
        build_market_data(make_config(market_data="nope"))


# --- Fix 5: T212_ENV selects the Trading212 environment ---


def test_env_argument_selects_the_demo_host():
    assert build_broker(make_config(), env="demo")._base_url == "https://demo.trading212.com"


def test_env_argument_selects_the_live_host():
    assert build_broker(make_config(), env="live")._base_url == "https://live.trading212.com"


def test_build_broker_defaults_to_live_when_no_env_given():
    assert build_broker(make_config())._base_url == "https://live.trading212.com"


@pytest.mark.parametrize("script_module", ["scripts.scan_market", "scripts.review_portfolio"])
@pytest.mark.parametrize("env_value,expected_host", [("demo", "demo"), ("live", "live")])
def test_main_reads_t212_env_and_targets_that_environment(
    monkeypatch, script_module, env_value, expected_host, tmp_path
):
    """The actual bug: `main()` never read T212_ENV, so T212_ENV=demo still
    hit the live account. Run `main()` with every outbound call stubbed and
    assert the broker it built points at the requested host.
    """
    import importlib

    module = importlib.import_module(script_module)
    monkeypatch.setenv("T212_ENV", env_value)

    built = {}
    real_build_broker = module.build_broker

    def spy_build_broker(config, env="live"):
        broker = real_build_broker(config, env=env)
        built["broker"] = broker
        broker.get_instruments = lambda: []
        broker.get_account_summary = lambda: None
        broker.get_positions = lambda: []
        return broker

    monkeypatch.setattr(module, "build_broker", spy_build_broker)
    monkeypatch.setattr(module, "build_market_data", lambda config: None)
    if hasattr(module, "load_universe"):
        monkeypatch.setattr(module, "load_universe", lambda sources: [])
    monkeypatch.setattr(module, "load_exclusions", lambda: [])

    module.main()

    assert built["broker"]._base_url == f"https://{expected_host}.trading212.com"


@pytest.mark.parametrize("script_module", ["scripts.scan_market", "scripts.review_portfolio"])
def test_main_defaults_to_live_when_t212_env_is_unset(monkeypatch, script_module):
    import importlib

    module = importlib.import_module(script_module)
    monkeypatch.delenv("T212_ENV", raising=False)

    built = {}
    real_build_broker = module.build_broker

    def spy_build_broker(config, env="live"):
        broker = real_build_broker(config, env=env)
        built["env"] = env
        broker.get_instruments = lambda: []
        broker.get_account_summary = lambda: None
        broker.get_positions = lambda: []
        return broker

    monkeypatch.setattr(module, "build_broker", spy_build_broker)
    monkeypatch.setattr(module, "build_market_data", lambda config: None)
    if hasattr(module, "load_universe"):
        monkeypatch.setattr(module, "load_universe", lambda sources: [])
    monkeypatch.setattr(module, "load_exclusions", lambda: [])

    module.main()

    assert built["env"] == "live"


@pytest.mark.parametrize("script_module", ["scripts.scan_market", "scripts.review_portfolio"])
def test_main_builds_providers_through_the_factories(monkeypatch, script_module):
    """Both scripts must go through the factories rather than naming a
    concrete provider class -- that indirection is the whole of Fix 6.
    """
    import importlib

    module = importlib.import_module(script_module)
    calls = []

    def fake_build_broker(config, env="live"):
        calls.append(("broker", config.broker_provider))

        class Stub:
            get_instruments = staticmethod(lambda: [])
            get_account_summary = staticmethod(lambda: None)
            get_positions = staticmethod(lambda: [])

        return Stub()

    def fake_build_market_data(config):
        calls.append(("market_data", config.market_data_provider))
        return None

    monkeypatch.setattr(module, "build_broker", fake_build_broker)
    monkeypatch.setattr(module, "build_market_data", fake_build_market_data)
    if hasattr(module, "load_universe"):
        monkeypatch.setattr(module, "load_universe", lambda sources: [])
    monkeypatch.setattr(module, "load_exclusions", lambda: [])

    module.main()

    assert ("broker", "trading212") in calls
    assert ("market_data", "yfinance") in calls
