import pytest
from pathlib import Path
from stock_advisor.config import load_config


def test_load_config_defaults(tmp_path):
    cfg = load_config("config/config.yaml")
    assert cfg.broker_provider == "trading212"
    assert cfg.market_data_provider == "yfinance"
    assert cfg.shortlist_size == 20
    assert cfg.halal_thresholds.debt_to_market_cap == 0.33
    assert cfg.halal_thresholds.non_permissible_income_ratio == 0.05


def test_load_config_rejects_unknown_broker(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("broker_provider: not_a_real_broker\nmarket_data_provider: yfinance\n")
    with pytest.raises(ValueError):
        load_config(str(bad))


def test_load_config_rejects_missing_key(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("broker_provider: trading212\n")
    with pytest.raises(ValueError):
        load_config(str(bad))
