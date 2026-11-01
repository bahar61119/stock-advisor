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
3. If the matched `Instrument.type` is not exactly `"STOCK"`, the holding is
   a pooled fund (ETF or similar). The spec excludes pooled funds from
   candidacy outright, "regardless of halal status", so no technical signal
   or halal screen is computed for it -- it gets `candidate = None` and
   `reason = REASON_POOLED_FUND`.
4. Otherwise translate the instrument into the market-data provider's symbol
   format via `stock_advisor.analysis.universe.to_market_data_symbol` --
   the same currency-guard reasoning Task 7's `match_broker_tradable` uses
   in the opposite direction, so a held LSE stock's bare `short_name` (e.g.
   "BA" for BAE Systems) is queried as "BA.L" rather than colliding with an
   unrelated US ticker (plain "BA" is Boeing). Use that translated symbol to
   query the market-data provider for price history, fundamentals, and
   company profile. Compute a `TechnicalSignal` (Task 5) and a
   `HalalVerdict` (Task 6), and derive `allowed_recommendations` via Task
   8's `compute_allowed_recommendations` (reused, not reimplemented).
5. A holding always appears in the output -- never silently dropped, never an
   exception. When it has no `candidate`, `HoldingResult.reason` says which
   of the four situations applies (see `HoldingResult`).

`main()` builds the providers the config selects (via
`stock_advisor.providers.factory`), loads the exclusions, and prints
`json.dumps(dataclasses.asdict(review_output))` to stdout -- no other I/O.
"""
import dataclasses
import json
import os

from stock_advisor.analysis.halal_screen import load_exclusions, screen
from stock_advisor.analysis.technical import compute_technical_signal
from stock_advisor.analysis.universe import to_market_data_symbol
from stock_advisor.config import AppConfig, load_config
from stock_advisor.providers.broker.base import (
    AccountSummary,
    BrokerProvider,
    Instrument,
    Position,
)
from stock_advisor.providers.factory import build_broker, build_market_data
from stock_advisor.providers.market_data.base import MarketDataProvider
from stock_advisor.reporting.schema import (
    REASON_MARKET_DATA_ERROR,
    REASON_NO_MARKET_DATA,
    REASON_POOLED_FUND,
    REASON_UNMATCHED_INSTRUMENT,
    CandidateResult,
    compute_allowed_recommendations,
)


@dataclasses.dataclass
class HoldingResult:
    """A single held position plus its screened candidate.

    `candidate` is `None` whenever the holding could not be screened, and
    `reason` then says why -- one of the `REASON_*` constants in
    `stock_advisor.reporting.schema`:

    - `REASON_UNMATCHED_INSTRUMENT`: no broker instrument matched the
      position's ticker, so there was no plain ticker to query with.
    - `REASON_NO_MARKET_DATA`: the provider has no entry for that ticker (a
      coverage gap).
    - `REASON_MARKET_DATA_ERROR`: the fetch raised (rate limit, connection
      error, malformed response). Transient, and deliberately distinguishable
      from a real coverage gap -- "we couldn't look" and "there's nothing to
      see" warrant different wording in a report.
    - `REASON_POOLED_FUND`: the holding is an ETF or other pooled fund,
      excluded from candidacy by the spec rather than by any data problem.

    `reason` is `None` exactly when `candidate` is not `None`.
    """

    position: Position
    candidate: CandidateResult | None
    reason: str | None = None


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
    market_symbol: str,
    broker_ticker: str,
    market_data: MarketDataProvider,
    config: AppConfig,
    exclusions: list[str],
) -> tuple[CandidateResult | None, str | None]:
    """Screen a single matched holding.

    `market_symbol` must already be translated into the market-data
    provider's symbol format (see `to_market_data_symbol`) -- this function
    does no translation of its own, it just queries with whatever symbol it
    is given.

    Returns `(candidate, None)` on success, or `(None, reason)` when the
    market-data provider has no entry for `market_symbol` or its fetch
    raised. Never propagates the provider's exception: one unlucky holding
    must not cost the user the entire portfolio review, so the three
    provider calls are isolated with a broad `except Exception` (the point
    is containing a third-party backend's unpredictable failures, not
    enumerating them).

    `CandidateResult.ticker` is set to `market_symbol` -- the symbol that
    was actually queried -- rather than the broker's bare `short_name`, so
    the report shows what was screened (consistent with `scan_market.py`,
    where `CandidateResult.ticker` is likewise the symbol queried, and
    `broker_ticker` separately carries the broker's own identifier for
    anyone matching the report back to their account).
    """
    try:
        price_history = market_data.get_price_history(market_symbol)
        fundamentals = market_data.get_fundamentals(market_symbol)
        profile = market_data.get_company_profile(market_symbol)
    except KeyError:
        return None, REASON_NO_MARKET_DATA
    except Exception:
        return None, REASON_MARKET_DATA_ERROR

    technical = compute_technical_signal(price_history)
    halal = screen(profile, fundamentals, config.halal_thresholds, exclusions)
    allowed_recommendations = compute_allowed_recommendations(halal.status)

    return (
        CandidateResult(
            ticker=market_symbol,
            broker_ticker=broker_ticker,
            technical=technical,
            halal=halal,
            allowed_recommendations=allowed_recommendations,
        ),
        None,
    )


def run_portfolio_review(
    config: AppConfig,
    broker: BrokerProvider,
    market_data: MarketDataProvider,
    exclusions: list[str],
) -> PortfolioReviewOutput:
    """Run the full portfolio-review pipeline against an already-loaded
    exclusion keyword list -- genuinely no I/O beyond the injected `broker`
    and `market_data` providers.
    """
    account_summary = broker.get_account_summary()
    positions = broker.get_positions()
    instruments = broker.get_instruments()

    holdings: list[HoldingResult] = []
    for position in positions:
        instrument = _find_instrument_by_ticker(position.ticker, instruments)
        if instrument is None:
            candidate, reason = None, REASON_UNMATCHED_INSTRUMENT
        elif instrument.type != "STOCK":
            # Pooled funds are excluded from candidacy outright, per the
            # spec -- the same rule `match_broker_tradable` applies to the
            # scan universe, applied here to what is actually held.
            candidate, reason = None, REASON_POOLED_FUND
        else:
            candidate, reason = _build_candidate(
                to_market_data_symbol(instrument),
                instrument.ticker,
                market_data,
                config,
                exclusions,
            )
        holdings.append(
            HoldingResult(position=position, candidate=candidate, reason=reason)
        )

    return PortfolioReviewOutput(account_summary=account_summary, holdings=holdings)


def main() -> None:
    """Build the configured providers, run the portfolio review, and print
    the result as JSON to stdout.
    """
    config = load_config()
    market_data = build_market_data(config)
    broker = build_broker(config, env=os.environ.get("T212_ENV", "live"))
    exclusions = load_exclusions()

    review_output = run_portfolio_review(config, broker, market_data, exclusions)
    print(json.dumps(dataclasses.asdict(review_output)))


if __name__ == "__main__":
    main()
