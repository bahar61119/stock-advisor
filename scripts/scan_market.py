"""Market-scan CLI: screens the configured universe for broker-tradable,
technically bullish, halal-compliant candidates.

Pipeline (`run_scan`):
1. Match the scan universe against the broker's tradable instruments
   (`match_broker_tradable`) -- this is what drops ETFs and anything the
   broker doesn't actually offer; only matched stock tickers proceed.
2. For each matched ticker, fetch price history, fundamentals, and company
   profile from the market-data provider. A ticker the provider has no data
   for is skipped (not raised) -- the universe/broker metadata and the
   market-data provider's coverage are independent and can disagree.
3. Compute a `TechnicalSignal` (Task 5) and a `HalalVerdict` (Task 6) for
   each, and derive `allowed_recommendations` from the halal verdict --
   `add_more` is withheld for anything other than exactly "compliant".
4. Rank into a shortlist: bullish verdicts first, then alphabetically by
   ticker, truncated to `config.shortlist_size`.

`main()` wires the real providers (`YFinanceProvider`, `Trading212BrokerProvider`)
from `load_config()` and prints `json.dumps(dataclasses.asdict(scan_output))`
to stdout -- no other I/O.
"""
import dataclasses
import json

from stock_advisor.analysis.halal_screen import load_exclusions, screen
from stock_advisor.analysis.technical import compute_technical_signal
from stock_advisor.analysis.universe import load_universe, match_broker_tradable
from stock_advisor.config import AppConfig, load_config
from stock_advisor.providers.broker.base import Instrument
from stock_advisor.providers.broker.trading212 import Trading212BrokerProvider
from stock_advisor.providers.market_data.base import MarketDataProvider
from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider
from stock_advisor.reporting.schema import CandidateResult, compute_allowed_recommendations


@dataclasses.dataclass
class ScanOutput:
    """Full scan output: every screened candidate plus the ranked shortlist."""

    all_results: list[CandidateResult]
    shortlist: list[CandidateResult]


def run_scan(
    config: AppConfig,
    market_data: MarketDataProvider,
    universe: list[str],
    instruments: list[Instrument],
) -> ScanOutput:
    """Run the full scan pipeline against an already-loaded universe and
    instrument list (no I/O beyond the injected `market_data` provider).
    """
    match_result = match_broker_tradable(universe, instruments)
    exclusions = load_exclusions()

    all_results: list[CandidateResult] = []
    for ticker, broker_ticker in match_result.matched:
        try:
            price_history = market_data.get_price_history(ticker)
            fundamentals = market_data.get_fundamentals(ticker)
            profile = market_data.get_company_profile(ticker)
        except KeyError:
            # No market-data entry for this (broker-tradable) ticker --
            # skip it rather than fail the whole scan.
            continue

        technical = compute_technical_signal(price_history)
        halal = screen(profile, fundamentals, config.halal_thresholds, exclusions)
        allowed_recommendations = compute_allowed_recommendations(halal.status)

        all_results.append(
            CandidateResult(
                ticker=ticker,
                broker_ticker=broker_ticker,
                technical=technical,
                halal=halal,
                allowed_recommendations=allowed_recommendations,
            )
        )

    shortlist = sorted(
        all_results,
        key=lambda result: (result.technical.verdict != "bullish", result.ticker),
    )[: config.shortlist_size]

    return ScanOutput(all_results=all_results, shortlist=shortlist)


def main() -> None:
    """Wire the real providers from config, run the scan, and print the
    result as JSON to stdout.
    """
    config = load_config()
    market_data = YFinanceProvider()
    broker = Trading212BrokerProvider(
        instrument_cache_path=config.instrument_cache_path,
        cache_max_age_seconds=config.instrument_cache_max_age_seconds,
    )

    universe = load_universe(config.universe_sources)
    instruments = broker.get_instruments()

    scan_output = run_scan(config, market_data, universe, instruments)
    print(json.dumps(dataclasses.asdict(scan_output)))


if __name__ == "__main__":
    main()
