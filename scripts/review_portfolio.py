"""Portfolio-review CLI: screens every currently-held position the same way
`scripts/scan_market.py` screens the market universe, so a holding's halal
compliance and technical signal can be checked without re-deriving the rules.

Pipeline (`run_portfolio_review`):
1. Fetch the account summary and current positions from the broker, and pass
   the account summary straight through unchanged.
2. For each `Position`, find the `Instrument` whose `ticker` field exactly
   equals `position.ticker` (both are Trading212-format identifiers, e.g.
   "AAPL_US_EQ") -- a direct ticker-to-ticker match, distinct from Task 7's
   `match_broker_tradable`, which matches a plain universe ticker against
   `instrument.short_name`.
3. If a matching `Instrument` is found, use its `short_name` as the plain
   ticker to query the market-data provider for price history, fundamentals,
   and company profile. Compute a `TechnicalSignal` (Task 5) and a
   `HalalVerdict` (Task 6), and derive `allowed_recommendations` via Task 8's
   `compute_allowed_recommendations` (reused, not reimplemented).
4. If no `Instrument` matches the position's ticker, or the matched
   `short_name` has no entry in the market-data provider, the holding still
   appears in the output with `candidate = None` -- never silently dropped,
   never an exception.

`main()` wires the real providers (`YFinanceProvider`, `Trading212BrokerProvider`)
from `load_config()` and prints `json.dumps(dataclasses.asdict(review_output))`
to stdout -- no other I/O.
"""
import dataclasses
import json

from stock_advisor.analysis.halal_screen import load_exclusions, screen
from stock_advisor.analysis.technical import compute_technical_signal
from stock_advisor.config import AppConfig, load_config
from stock_advisor.providers.broker.base import (
    AccountSummary,
    BrokerProvider,
    Instrument,
    Position,
)
from stock_advisor.providers.broker.trading212 import Trading212BrokerProvider
from stock_advisor.providers.market_data.base import MarketDataProvider
from stock_advisor.providers.market_data.yfinance_provider import YFinanceProvider
from stock_advisor.reporting.schema import CandidateResult, compute_allowed_recommendations


@dataclasses.dataclass
class HoldingResult:
    """A single held position plus its screened candidate -- `candidate` is
    `None` when the position's ticker could not be matched to an `Instrument`
    or the matched `short_name` has no market-data entry.
    """

    position: Position
    candidate: CandidateResult | None


@dataclasses.dataclass
class PortfolioReviewOutput:
    """Full portfolio-review output: the account summary passed through
    unchanged, plus a screened result for every held position.
    """

    account_summary: AccountSummary
    holdings: list[HoldingResult]


def _find_instrument_by_ticker(ticker: str, instruments: list[Instrument]) -> Instrument | None:
    """Find the `Instrument` whose `ticker` field exactly equals `ticker`.

    Both `Position.ticker` and `Instrument.ticker` are Trading212-format
    identifiers (e.g. "AAPL_US_EQ") -- this is a direct ticker-to-ticker
    match, distinct from Task 7's `match_broker_tradable`, which matches a
    plain universe ticker against `instrument.short_name`.
    """
    for instrument in instruments:
        if instrument.ticker == ticker:
            return instrument
    return None


def _build_candidate(
    short_name: str,
    broker_ticker: str,
    market_data: MarketDataProvider,
    config: AppConfig,
    exclusions: list[str],
) -> CandidateResult | None:
    """Screen a single matched holding, returning `None` (rather than
    raising) when the market-data provider has no entry for `short_name`.
    """
    try:
        price_history = market_data.get_price_history(short_name)
        fundamentals = market_data.get_fundamentals(short_name)
        profile = market_data.get_company_profile(short_name)
    except KeyError:
        return None

    technical = compute_technical_signal(price_history)
    halal = screen(profile, fundamentals, config.halal_thresholds, exclusions)
    allowed_recommendations = compute_allowed_recommendations(halal.status)

    return CandidateResult(
        ticker=short_name,
        broker_ticker=broker_ticker,
        technical=technical,
        halal=halal,
        allowed_recommendations=allowed_recommendations,
    )


def run_portfolio_review(
    config: AppConfig,
    broker: BrokerProvider,
    market_data: MarketDataProvider,
) -> PortfolioReviewOutput:
    """Run the full portfolio-review pipeline (no I/O beyond the injected
    `broker` and `market_data` providers).
    """
    account_summary = broker.get_account_summary()
    positions = broker.get_positions()
    instruments = broker.get_instruments()
    exclusions = load_exclusions()

    holdings: list[HoldingResult] = []
    for position in positions:
        instrument = _find_instrument_by_ticker(position.ticker, instruments)
        candidate = None
        if instrument is not None:
            candidate = _build_candidate(
                instrument.short_name,
                instrument.ticker,
                market_data,
                config,
                exclusions,
            )
        holdings.append(HoldingResult(position=position, candidate=candidate))

    return PortfolioReviewOutput(account_summary=account_summary, holdings=holdings)


def main() -> None:
    """Wire the real providers from config, run the portfolio review, and
    print the result as JSON to stdout.
    """
    config = load_config()
    market_data = YFinanceProvider()
    broker = Trading212BrokerProvider(
        instrument_cache_path=config.instrument_cache_path,
        cache_max_age_seconds=config.instrument_cache_max_age_seconds,
    )

    review_output = run_portfolio_review(config, broker, market_data)
    print(json.dumps(dataclasses.asdict(review_output)))


if __name__ == "__main__":
    main()
