"""Construct the provider implementations the config selects.

`config.broker_provider` and `config.market_data_provider` were validated at
load time against `VALID_BROKERS` / `VALID_MARKET_DATA_PROVIDERS` but nothing
read them — both scripts hardcoded `Trading212BrokerProvider` and
`YFinanceProvider`, which made the config keys decorative and defeated the
spec's own goal that "adding a second provider later should mean writing one
new provider module, not touching the rest of the system."

These two functions are that one place. Adding a provider means writing the
module, adding its name to the config's valid set, and adding one line to the
dispatch dict here — no script changes.

The dispatch still raises on an unknown name even though `load_config`
rejects those already: a caller can build an `AppConfig` directly (the tests
do), and a factory that silently fell back to a default provider would be a
worse failure than one that says what it was asked for.
"""
from stock_advisor.config import AppConfig
from stock_advisor.providers.broker.base import BrokerProvider
from stock_advisor.providers.broker.trading212 import Trading212BrokerProvider
from stock_advisor.providers.market_data.base import MarketDataProvider
from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider


def build_broker(config: AppConfig, env: str = "live") -> BrokerProvider:
    """Construct the broker provider named by `config.broker_provider`.

    `env` ("demo" or "live") comes from the caller rather than the config
    file because it is a credential-environment switch read from `T212_ENV`,
    not a committed setting -- the same variable that selects which account's
    keys are in play. It is accepted (and ignored) uniformly so a future
    broker that has no environments doesn't change the call site.
    """
    name = config.broker_provider
    if name == "trading212":
        return Trading212BrokerProvider(
            env=env,
            instrument_cache_path=config.instrument_cache_path,
            cache_max_age_seconds=config.instrument_cache_max_age_seconds,
        )
    raise ValueError(f"Unknown broker_provider: {name}")


def build_market_data(config: AppConfig) -> MarketDataProvider:
    """Construct the market-data provider named by
    `config.market_data_provider`.
    """
    name = config.market_data_provider
    if name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"Unknown market_data_provider: {name}")
