"""Market-scan CLI: screens the configured universe for broker-tradable,
technically bullish, halal-compliant candidates.

Pipeline (`run_scan`):
1. Match the scan universe against the broker's tradable instruments
   (`match_broker_tradable`) -- this is what drops ETFs and anything the
   broker doesn't actually offer; only matched stock tickers proceed.
   Universe tickers with no tradable instrument are reported in
   `ScanOutput.unmatched` / `unmatched_count` rather than discarded, so
   coverage loss is visible in the output.
2. For each matched ticker, fetch price history, fundamentals, and company
   profile from the market-data provider. A ticker the provider has no data
   for is skipped and listed in `no_market_data_tickers` -- the
   universe/broker metadata and the market-data provider's coverage are
   independent and can disagree. A ticker whose fetch *raises* is skipped
   and listed in `failed_tickers`.
3. Compute a `TechnicalSignal` (Task 5) and a `HalalVerdict` (Task 6) for
   each, and derive `allowed_recommendations` from the halal verdict --
   `add_more` is withheld for anything other than exactly "compliant".
4. Rank into a shortlist: bullish verdicts first, then alphabetically by
   ticker, truncated to `config.shortlist_size`.

`main()` builds the providers the config selects (via
`stock_advisor.providers.factory`), loads the universe and exclusions, and
prints `json.dumps(dataclasses.asdict(scan_output))` to stdout -- no other
I/O.
"""
import dataclasses
import json
import os

from stock_advisor.analysis.halal_screen import load_exclusions, screen
from stock_advisor.analysis.technical import compute_technical_signal
from stock_advisor.analysis.universe import load_universe, match_broker_tradable
from stock_advisor.config import AppConfig, load_config
from stock_advisor.providers.broker.base import Instrument
from stock_advisor.providers.factory import build_broker, build_market_data
from stock_advisor.providers.market_data.base import MarketDataProvider
from stock_advisor.reporting.schema import (
    CandidateResult,
    ScanOutput,
    compute_allowed_recommendations,
)

__all__ = ["ScanOutput", "run_scan", "main"]


def run_scan(
    config: AppConfig,
    market_data: MarketDataProvider,
    universe: list[str],
    instruments: list[Instrument],
    exclusions: list[str],
) -> ScanOutput:
    """Run the full scan pipeline against an already-loaded universe,
    instrument list, and exclusion keyword list -- genuinely no I/O beyond
    the injected `market_data` provider.

    A per-ticker market-data failure never aborts the scan. The real
    provider can raise for any of ~600 tickers in a run (rate limiting, a
    connection or timeout error, a malformed response), and an unattended
    twice-daily run that dies on ticker 300 produces a traceback and no
    report at all -- strictly worse than a report missing one ticker. So
    every provider call is isolated per ticker with a broad `except
    Exception`: the point is to contain a third-party backend's unpredictable
    failure modes, not to enumerate them. The affected ticker is recorded in
    `failed_tickers` so the loss is reported rather than silently absorbed.
    """
    match_result = match_broker_tradable(universe, instruments)

    all_results: list[CandidateResult] = []
    failed_tickers: list[str] = []
    no_market_data_tickers: list[str] = []

    for ticker, broker_ticker in match_result.matched:
        try:
            price_history = market_data.get_price_history(ticker)
            fundamentals = market_data.get_fundamentals(ticker)
            profile = market_data.get_company_profile(ticker)
        except KeyError:
            # No market-data entry for this (broker-tradable) ticker --
            # a coverage gap, not a fault. Skip it rather than fail the scan.
            no_market_data_tickers.append(ticker)
            continue
        except Exception:
            # Any other provider failure: rate limit, connection/timeout,
            # JSON decode error, or anything else the backend throws.
            failed_tickers.append(ticker)
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

    return ScanOutput(
        all_results=all_results,
        shortlist=shortlist,
        unmatched_count=len(match_result.unmatched),
        unmatched=list(match_result.unmatched),
        failed_tickers=failed_tickers,
        no_market_data_tickers=no_market_data_tickers,
    )


def main() -> None:
    """Build the configured providers, run the scan, and print the result as
    JSON to stdout.
    """
    config = load_config()
    market_data = build_market_data(config)
    broker = build_broker(config, env=os.environ.get("T212_ENV", "live"))

    universe = load_universe(config.universe_sources)
    instruments = broker.get_instruments()
    exclusions = load_exclusions()

    scan_output = run_scan(config, market_data, universe, instruments, exclusions)
    print(json.dumps(dataclasses.asdict(scan_output)))


if __name__ == "__main__":
    main()
