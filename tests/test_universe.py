"""Tests for the scan universe builder: loading bundled ticker lists and
matching them against broker-tradable instruments.
"""
import json

from stock_advisor.analysis.universe import load_universe, match_broker_tradable
from stock_advisor.providers.broker.base import Instrument


def write_universe_file(path, tickers):
    path.write_text(json.dumps(tickers))


def test_load_universe_dedupes_across_sources(tmp_path):
    write_universe_file(tmp_path / "a.json", ["AAPL", "MSFT"])
    write_universe_file(tmp_path / "b.json", ["MSFT", "GOOGL"])
    tickers = load_universe(["a", "b"], data_dir=str(tmp_path))
    assert tickers == ["AAPL", "MSFT", "GOOGL"]


def test_load_universe_single_source(tmp_path):
    write_universe_file(tmp_path / "a.json", ["AAPL", "MSFT"])
    tickers = load_universe(["a"], data_dir=str(tmp_path))
    assert tickers == ["AAPL", "MSFT"]


def test_load_universe_preserves_first_appearance_order(tmp_path):
    write_universe_file(tmp_path / "a.json", ["MSFT", "AAPL"])
    write_universe_file(tmp_path / "b.json", ["AAPL", "GOOGL", "MSFT"])
    tickers = load_universe(["a", "b"], data_dir=str(tmp_path))
    assert tickers == ["MSFT", "AAPL", "GOOGL"]


def test_match_broker_tradable_matches_case_insensitive():
    instruments = [
        Instrument(
            ticker="AAPL_US_EQ",
            name="Apple Inc",
            short_name="AAPL",
            isin="US0378331005",
            currency_code="USD",
            type="STOCK",
        )
    ]
    result = match_broker_tradable(["aapl"], instruments)
    assert result.matched == [("aapl", "AAPL_US_EQ")]
    assert result.unmatched == []


def test_match_broker_tradable_excludes_etfs():
    instruments = [
        Instrument(
            ticker="SPY_US_EQ",
            name="SPDR S&P 500 ETF",
            short_name="SPY",
            isin="US78462F1030",
            currency_code="USD",
            type="ETF",
        )
    ]
    result = match_broker_tradable(["SPY"], instruments)
    assert result.matched == []
    assert result.unmatched == ["SPY"]


def test_match_broker_tradable_reports_unmatched_without_failing():
    result = match_broker_tradable(["NOTREAL"], [])
    assert result.unmatched == ["NOTREAL"]


def test_match_broker_tradable_preserves_universe_order():
    instruments = [
        Instrument(
            ticker="MSFT_US_EQ",
            name="Microsoft Corp",
            short_name="MSFT",
            isin="US5949181045",
            currency_code="USD",
            type="STOCK",
        ),
        Instrument(
            ticker="AAPL_US_EQ",
            name="Apple Inc",
            short_name="AAPL",
            isin="US0378331005",
            currency_code="USD",
            type="STOCK",
        ),
    ]
    result = match_broker_tradable(["AAPL", "NOTREAL", "MSFT"], instruments)
    assert result.matched == [("AAPL", "AAPL_US_EQ"), ("MSFT", "MSFT_US_EQ")]
    assert result.unmatched == ["NOTREAL"]
