"""Scan universe builder: load bundled index-constituent ticker lists and
match them against the instruments a broker actually lets us trade.

Two independent pieces of pure logic, no I/O beyond reading the bundled JSON
files in `data/universe/`:

1. `load_universe` unions one or more flat JSON ticker-list files into a
   single deduplicated, order-preserving list.
2. `match_broker_tradable` takes that universe and a broker's `Instrument`
   list and reports which universe tickers the broker can actually trade.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from stock_advisor.providers.broker.base import Instrument

DEFAULT_DATA_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "universe")


@dataclass
class UniverseMatchResult:
    """Outcome of matching a scan universe against broker instruments.

    `matched` pairs are `(universe_ticker, broker_ticker)` — the universe
    ticker as given, alongside the broker's own `Instrument.ticker` for the
    instrument it matched. `unmatched` lists universe tickers (in their
    original order) for which no tradable broker instrument was found.
    """

    matched: list[tuple[str, str]]
    unmatched: list[str]


def load_universe(sources: list[str], data_dir: str = DEFAULT_DATA_DIR) -> list[str]:
    """Load and union one or more bundled universe files.

    Each source name maps to `<data_dir>/<source>.json`, a flat JSON array
    of plain ticker strings. Returns tickers deduplicated across all sources
    combined, order-preserving by first appearance (scanning sources in the
    order given, and within a file in file order).
    """
    seen: set[str] = set()
    tickers: list[str] = []
    for source in sources:
        path = Path(data_dir) / f"{source}.json"
        with open(path, "r") as f:
            raw = json.load(f)
        for ticker in raw:
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
    return tickers


def match_broker_tradable(
    universe: list[str], instruments: list[Instrument]
) -> UniverseMatchResult:
    """Match a scan universe against the broker's tradable instruments.

    A universe ticker matches an instrument when they are equal
    case-insensitively to the instrument's `short_name` — but only for
    instruments whose `type` is exactly `"STOCK"`; any other type (e.g.
    `"ETF"`) is never a match candidate, even if its `short_name` happens to
    equal a universe ticker. At most one match is reported per universe
    ticker (the first stock instrument found with that short name); universe
    order is preserved in both `matched` and `unmatched`.
    """
    stock_by_short_name: dict[str, str] = {}
    for instrument in instruments:
        if instrument.type != "STOCK":
            continue
        key = instrument.short_name.lower()
        if key not in stock_by_short_name:
            stock_by_short_name[key] = instrument.ticker

    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for ticker in universe:
        broker_ticker = stock_by_short_name.get(ticker.lower())
        if broker_ticker is not None:
            matched.append((ticker, broker_ticker))
        else:
            unmatched.append(ticker)

    return UniverseMatchResult(matched=matched, unmatched=unmatched)
