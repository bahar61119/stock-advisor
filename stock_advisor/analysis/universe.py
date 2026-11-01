"""Scan universe builder: load bundled index-constituent ticker lists and
match them against the instruments a broker actually lets us trade.

Two independent pieces of pure logic, no I/O beyond reading the bundled JSON
files in `data/universe/`:

1. `load_universe` unions one or more flat JSON ticker-list files into a
   single deduplicated, order-preserving list.
2. `match_broker_tradable` takes that universe and a broker's `Instrument`
   list and reports which universe tickers the broker can actually trade.

The bundled ticker files are stored in the market-data provider's symbol
format (yfinance: `HSBA.L`, `BRK-B`), not as bare index symbols — see
`data/universe/SOURCES.md`. That is load-bearing for `load_universe`'s dedup
as well as for the provider: five symbols (`ADM`, `BA`, `BBY`, `PRU`,
`TSCO`) are both a US ticker and a *different* company's London EPIC, so
with bare strings the union silently collapsed each pair into one entry and
dropped the London company. Suffixed, they are distinct strings and both
survive.
"""
import json
from dataclasses import dataclass
from pathlib import Path

from stock_advisor.providers.broker.base import Instrument

DEFAULT_DATA_DIR = str(Path(__file__).resolve().parent.parent.parent / "data" / "universe")

# The bundled universe files are stored in the symbol format the configured
# market-data provider (yfinance) needs: an explicit `.L` suffix for London
# listings, and a hyphen for US share-class suffixes (`BRK-B`). See
# data/universe/SOURCES.md.
#
# The broker, however, keys instruments on a bare `shortName` whose exact
# spelling for a London listing is not something this codebase can verify
# without live API credentials (it may be "HSBA", "HSBA.L", or similar). So
# `match_broker_tradable` tries the universe ticker as-is first and then the
# de-suffixed form, with a currency guard described below.
LSE_SUFFIX = ".L"

# Currency codes Trading212 uses for London listings (GBX is pence-quoted).
# Compared case-insensitively.
LSE_CURRENCY_CODES = frozenset({"GBX", "GBP"})


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


def _is_lse_currency(currency_code: str) -> bool:
    """Whether a broker instrument's currency marks it as a London listing."""
    return currency_code.upper() in LSE_CURRENCY_CODES


def to_market_data_symbol(instrument: Instrument) -> str:
    """Translate a broker Instrument's bare short_name into the symbol
    format the market-data provider (yfinance) expects — the reverse of
    _lookup_keys's forward translation, using the same currency-guard
    reasoning match_broker_tradable relies on.

    A London listing (GBX/GBP currency) gets an explicit .L suffix
    (idempotent if already present), with any internal share-class dot
    converted to a hyphen first (so "BT.A" + GBX -> "BT-A.L", matching the
    bundled universe file's own convention for BT Group). A non-London
    short_name's internal dot (a share-class separator, e.g. "BRK.B") is
    converted to yfinance's hyphenated form ("BRK-B").

    This is what prevents a bare short_name like "BA" (BAE Systems, GBX)
    from being queried as the unrelated US-listed Boeing: appending .L
    guarantees a symbol that can only resolve to the London listing (or to
    nothing at all, which surfaces visibly as a market-data gap) -- never
    silently to a different real company's data, by the same reasoning
    match_broker_tradable already uses for the opposite direction.
    """
    short_name = instrument.short_name
    if not _is_lse_currency(instrument.currency_code):
        return short_name.replace(".", "-")
    if short_name.upper().endswith(LSE_SUFFIX):
        return short_name
    return short_name.replace(".", "-") + LSE_SUFFIX


def _lookup_keys(ticker: str) -> list[tuple[str, bool]]:
    """Broker `short_name` spellings to try for one universe ticker, in
    priority order, each paired with whether the matched instrument must be a
    London listing.

    The universe ticker's suffix declares its exchange, and that is what
    prevents the cross-listing collisions this translation exists to avoid:
    `ADM`, `BA`, `BBY`, `PRU` and `TSCO` are all *both* a US ticker and a
    different company's London EPIC. So:

    - A `.L` ticker (`BA.L`, BAE Systems) is tried verbatim, then as the bare
      EPIC (`BA`) but **only** against a GBX/GBP instrument — so it can never
      match US-listed Boeing.
    - A bare ticker (`BA`, Boeing) is tried verbatim but **only** against a
      non-GBX/GBP instrument — so it can never match BAE Systems either, even
      if the broker happens to list BAE first.
    - `BT-A.L` additionally tries the dot form of the EPIC (`BT.A`), since
      the hyphen there is a yfinance spelling, not the LSE's.
    - A hyphenated US ticker (`BRK-B`) additionally tries the dot form
      (`BRK.B`), which is how most other sources render a share class.
    """
    if ticker.upper().endswith(LSE_SUFFIX):
        base = ticker[: -len(LSE_SUFFIX)]
        keys = [(ticker.lower(), True), (base.lower(), True)]
        if "-" in base:
            keys.append((base.replace("-", ".").lower(), True))
        return keys

    keys = [(ticker.lower(), False)]
    if "-" in ticker:
        keys.append((ticker.replace("-", ".").lower(), False))
    return keys


def match_broker_tradable(
    universe: list[str], instruments: list[Instrument]
) -> UniverseMatchResult:
    """Match a scan universe against the broker's tradable instruments.

    A universe ticker matches an instrument when the instrument's
    `short_name` equals one of the ticker's `_lookup_keys` spellings
    case-insensitively AND the instrument is on the exchange the ticker's
    suffix implies (see `_lookup_keys`) — but only for instruments whose
    `type` is exactly `"STOCK"`; any other type (e.g. `"ETF"`) is never a
    match candidate, even if its `short_name` happens to equal a universe
    ticker. At most one match is reported per universe ticker (the first
    stock instrument found under the highest-priority spelling that matches);
    universe order is preserved in both `matched` and `unmatched`.
    """
    stocks_by_short_name: dict[str, list[Instrument]] = {}
    for instrument in instruments:
        if instrument.type != "STOCK":
            continue
        stocks_by_short_name.setdefault(instrument.short_name.lower(), []).append(
            instrument
        )

    matched: list[tuple[str, str]] = []
    unmatched: list[str] = []
    for ticker in universe:
        broker_ticker: str | None = None
        for key, want_lse in _lookup_keys(ticker):
            for instrument in stocks_by_short_name.get(key, ()):
                if _is_lse_currency(instrument.currency_code) == want_lse:
                    broker_ticker = instrument.ticker
                    break
            if broker_ticker is not None:
                break
        if broker_ticker is not None:
            matched.append((ticker, broker_ticker))
        else:
            unmatched.append(ticker)

    return UniverseMatchResult(matched=matched, unmatched=unmatched)
