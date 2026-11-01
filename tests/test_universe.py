"""Tests for the scan universe builder: loading bundled ticker lists and
matching them against broker-tradable instruments.
"""
import json

from stock_advisor.analysis.universe import (
    load_universe,
    match_broker_tradable,
    to_market_data_symbol,
)
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


# --- Bundled symbol format and the cross-listing collision (Fix 2) ---
#
# The bundled files ship in the market-data provider's symbol format. Five
# symbols are both a US ticker and a *different* company's London EPIC, and
# with bare strings load_universe's dedup silently collapsed each pair,
# dropping the London company entirely.

COLLIDING_SYMBOLS = ["ADM", "BA", "BBY", "PRU", "TSCO"]


def bundled(source):
    return load_universe([source])


def test_bundled_ftse_tickers_all_carry_the_lse_suffix():
    tickers = bundled("ftse100")
    assert tickers, "ftse100.json should not be empty"
    assert all(t.endswith(".L") for t in tickers), [t for t in tickers if not t.endswith(".L")]


def test_bundled_us_tickers_use_hyphen_share_classes_not_dots():
    """yfinance renders a share class with a hyphen (BRK-B); a dot (BRK.B)
    resolves to an empty result rather than an error, which is exactly the
    silent failure this format change prevents.
    """
    us = bundled("sp500") + bundled("nasdaq100")
    assert "BRK-B" in us
    assert "BF-B" in us
    assert not [t for t in us if "." in t]


def test_bundled_us_tickers_carry_no_exchange_suffix():
    us = bundled("sp500") + bundled("nasdaq100")
    assert not [t for t in us if t.endswith(".L")]


def test_bundled_ftse_dotted_epic_uses_yfinance_hyphen_form():
    """BT Group's LSE EPIC is BT.A; yfinance spells it BT-A.L."""
    tickers = bundled("ftse100")
    assert "BT-A.L" in tickers
    assert "BT.A.L" not in tickers
    assert "BT.A" not in tickers


def test_dedup_keeps_both_us_and_london_versions_of_colliding_symbols():
    """The regression this format change fixes: a combined load must contain
    the US ticker AND the London one for each colliding symbol, as distinct
    entries -- previously the London company vanished.
    """
    combined = load_universe(["sp500", "nasdaq100", "ftse100"])
    for symbol in COLLIDING_SYMBOLS:
        assert symbol in combined, f"US {symbol} missing"
        assert f"{symbol}.L" in combined, f"London {symbol}.L missing"


def test_combined_universe_size_is_the_sum_of_distinct_entries():
    """No cross-file collisions remain: the union is exactly as large as the
    three files' distinct entries, so nothing is being silently absorbed.
    """
    sources = ["sp500", "nasdaq100", "ftse100"]
    combined = load_universe(sources)
    per_file = [bundled(source) for source in sources]
    assert len(combined) == len(set().union(*(set(f) for f in per_file)))
    # The only intra-US overlap is Nasdaq-100 names also in the S&P 500.
    assert len(combined) == len(set(per_file[0]) | set(per_file[1])) + len(per_file[2])


# --- Exchange-aware broker matching (Fix 2) ---


def lse_stock(short_name, ticker=None):
    return Instrument(
        ticker=ticker or f"{short_name}l_EQ",
        name=f"{short_name} plc",
        short_name=short_name,
        isin="GB0000000000",
        currency_code="GBX",
        type="STOCK",
    )


def us_stock(short_name, ticker=None):
    return Instrument(
        ticker=ticker or f"{short_name}_US_EQ",
        name=f"{short_name} Inc",
        short_name=short_name,
        isin="US0000000000",
        currency_code="USD",
        type="STOCK",
    )


def test_suffixed_lse_ticker_matches_a_bare_london_short_name():
    """The broker keys instruments on a bare shortName, so a `.L` universe
    ticker has to fall back to the de-suffixed spelling to match at all.
    """
    result = match_broker_tradable(["HSBA.L"], [lse_stock("HSBA")])
    assert result.matched == [("HSBA.L", "HSBAl_EQ")]
    assert result.unmatched == []


def test_suffixed_lse_ticker_also_matches_a_suffixed_short_name():
    """Whether Trading212 spells it "HSBA" or "HSBA.L" is not something this
    codebase can verify without live credentials, so both are accepted.
    """
    result = match_broker_tradable(["HSBA.L"], [lse_stock("HSBA.L")])
    assert result.matched == [("HSBA.L", "HSBA.Ll_EQ")]


def test_london_ticker_never_matches_the_same_named_us_company():
    """BA.L is BAE Systems; BA is Boeing. The currency guard is what keeps
    the de-suffixed fallback from matching the wrong company.
    """
    result = match_broker_tradable(["BA.L"], [us_stock("BA")])
    assert result.matched == []
    assert result.unmatched == ["BA.L"]


def test_us_ticker_never_matches_the_same_named_london_company():
    """The reverse direction, which matters because the broker may list the
    London instrument first -- a plain short-name index would return it.
    """
    result = match_broker_tradable(["BA"], [lse_stock("BA")])
    assert result.matched == []
    assert result.unmatched == ["BA"]


def test_colliding_symbols_each_match_their_own_exchange():
    """Both spellings present at once: each must find its own company."""
    instruments = [lse_stock("BA"), us_stock("BA")]
    result = match_broker_tradable(["BA", "BA.L"], instruments)
    assert result.matched == [("BA", "BA_US_EQ"), ("BA.L", "BAl_EQ")]


def test_lse_instrument_quoted_in_gbp_also_matches():
    instrument = lse_stock("SHEL")
    instrument.currency_code = "GBP"
    result = match_broker_tradable(["SHEL.L"], [instrument])
    assert result.matched == [("SHEL.L", "SHELl_EQ")]


def test_dotted_lse_epic_matches_the_brokers_dot_spelling():
    """BT-A.L is the yfinance spelling; the LSE EPIC itself is BT.A."""
    result = match_broker_tradable(["BT-A.L"], [lse_stock("BT.A")])
    assert result.matched == [("BT-A.L", "BT.Al_EQ")]


def test_hyphenated_us_share_class_matches_the_brokers_dot_spelling():
    """The universe carries yfinance's BRK-B; a broker spelling it BRK.B
    must still match.
    """
    result = match_broker_tradable(["BRK-B"], [us_stock("BRK.B")])
    assert result.matched == [("BRK-B", "BRK.B_US_EQ")]


def test_hyphenated_us_share_class_matches_its_own_spelling_first():
    result = match_broker_tradable(["BRK-B"], [us_stock("BRK-B"), us_stock("BRK.B")])
    assert result.matched == [("BRK-B", "BRK-B_US_EQ")]


def test_etf_exclusion_still_applies_to_suffixed_tickers():
    etf = lse_stock("ISF")
    etf.type = "ETF"
    result = match_broker_tradable(["ISF.L"], [etf])
    assert result.matched == []
    assert result.unmatched == ["ISF.L"]


# --- to_market_data_symbol: the reverse translation (holdings-ticker fix) ---
#
# review_portfolio.py's _build_candidate queries the market-data provider
# with a broker Instrument's bare short_name and no translation. For a held
# LSE stock that silently queries the wrong company (e.g. "BA" resolves to
# Boeing, not BAE Systems). to_market_data_symbol fixes that by reusing the
# same currency-guard reasoning match_broker_tradable already applies in the
# opposite direction.


def test_to_market_data_symbol_leaves_a_plain_us_ticker_unchanged():
    instrument = us_stock("AAPL")
    assert to_market_data_symbol(instrument) == "AAPL"


def test_to_market_data_symbol_converts_a_dotted_us_share_class_to_hyphen():
    instrument = us_stock("BRK.B")
    assert to_market_data_symbol(instrument) == "BRK-B"


def test_to_market_data_symbol_appends_l_suffix_for_a_plain_lse_ticker():
    instrument = lse_stock("BA")
    assert to_market_data_symbol(instrument) == "BA.L"


def test_to_market_data_symbol_converts_dot_and_appends_l_for_lse_share_class():
    """BT Group's LSE EPIC is BT.A; yfinance wants BT-A.L -- the hyphen
    conversion must happen before the .L suffix is appended, not after.
    """
    instrument = lse_stock("BT.A")
    result = to_market_data_symbol(instrument)
    assert result == "BT-A.L"
    assert result != "BT.A.L"
    assert result != "BT-A.l.L"


def test_to_market_data_symbol_is_idempotent_when_already_suffixed():
    instrument = lse_stock("BA.L")
    assert to_market_data_symbol(instrument) == "BA.L"


def test_to_market_data_symbol_currency_check_is_case_insensitive():
    """Consistent with _is_lse_currency's own case-insensitive comparison."""
    instrument = lse_stock("BA")
    instrument.currency_code = "gbx"
    assert to_market_data_symbol(instrument) == "BA.L"

    instrument_gbp = lse_stock("SHEL")
    instrument_gbp.currency_code = "Gbp"
    assert to_market_data_symbol(instrument_gbp) == "SHEL.L"
