"""Configuration loading and validation for stock-advisor."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import yaml


# Valid provider names
VALID_BROKERS = {"trading212"}
VALID_MARKET_DATA_PROVIDERS = {"yfinance"}

# Required configuration keys
REQUIRED_KEYS = {
    "broker_provider",
    "market_data_provider",
    "shortlist_size",
    "universe_sources",
    "instrument_cache_path",
    "instrument_cache_max_age_seconds",
    "halal_thresholds",
}

# Required halal_thresholds sub-keys
REQUIRED_HALAL_KEYS = {
    "debt_to_market_cap",
    "cash_and_interest_to_market_cap",
    "receivables_and_cash_to_market_cap",
    "non_permissible_income_ratio",
}


@dataclass(frozen=True)
class HalalThresholds:
    """Shariah compliance ratio thresholds."""

    debt_to_market_cap: float
    cash_and_interest_to_market_cap: float
    receivables_and_cash_to_market_cap: float
    non_permissible_income_ratio: float


@dataclass(frozen=True)
class AppConfig:
    """Application configuration."""

    broker_provider: str
    market_data_provider: str
    shortlist_size: int
    halal_thresholds: HalalThresholds
    universe_sources: list[str]
    instrument_cache_path: str
    instrument_cache_max_age_seconds: int


def load_config(path: Optional[str] = None) -> AppConfig:
    """
    Load and validate application configuration from a YAML file.

    Args:
        path: Path to the config file. If None, uses default 'config/config.yaml'.

    Returns:
        AppConfig: Validated configuration object.

    Raises:
        ValueError: If broker/market-data provider is invalid or required keys are missing.
    """
    if path is None:
        path = "config/config.yaml"

    config_path = Path(path)
    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raise ValueError(f"Configuration file {path} is empty")

    # Validate all required keys are present
    missing_keys = REQUIRED_KEYS - set(raw_config.keys())
    if missing_keys:
        raise ValueError(f"Missing required configuration keys: {missing_keys}")

    # Validate broker_provider
    broker = raw_config["broker_provider"]
    if broker not in VALID_BROKERS:
        raise ValueError(f"Unknown broker_provider: {broker}. Valid options: {VALID_BROKERS}")

    # Validate market_data_provider
    market_data = raw_config["market_data_provider"]
    if market_data not in VALID_MARKET_DATA_PROVIDERS:
        raise ValueError(
            f"Unknown market_data_provider: {market_data}. Valid options: {VALID_MARKET_DATA_PROVIDERS}"
        )

    # Validate halal_thresholds
    halal_raw = raw_config["halal_thresholds"]
    if not isinstance(halal_raw, dict):
        raise ValueError("halal_thresholds must be a dictionary")

    missing_halal_keys = REQUIRED_HALAL_KEYS - set(halal_raw.keys())
    if missing_halal_keys:
        raise ValueError(f"Missing required halal_thresholds keys: {missing_halal_keys}")

    halal_thresholds = HalalThresholds(
        debt_to_market_cap=halal_raw["debt_to_market_cap"],
        cash_and_interest_to_market_cap=halal_raw["cash_and_interest_to_market_cap"],
        receivables_and_cash_to_market_cap=halal_raw["receivables_and_cash_to_market_cap"],
        non_permissible_income_ratio=halal_raw["non_permissible_income_ratio"],
    )

    return AppConfig(
        broker_provider=broker,
        market_data_provider=market_data,
        shortlist_size=raw_config["shortlist_size"],
        halal_thresholds=halal_thresholds,
        universe_sources=raw_config["universe_sources"],
        instrument_cache_path=raw_config["instrument_cache_path"],
        instrument_cache_max_age_seconds=raw_config["instrument_cache_max_age_seconds"],
    )
