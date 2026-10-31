"""Shared reporting schema for scan/review output.

`CandidateResult` is the per-ticker result shape produced by
`scripts/scan_market.py` (Task 8) and reused as-is by the portfolio review
script (Task 9) — defined once here so neither script redefines it.
`ScanOutput` is the scan script's whole output document, and the
`REASON_*` constants are the shared vocabulary both scripts use to say why
a ticker has no screened candidate.
"""
from dataclasses import dataclass, field

from stock_advisor.analysis.halal_screen import HalalVerdict
from stock_advisor.analysis.technical import TechnicalSignal

# The full set of recommendation actions available to a compliant candidate.
ALL_RECOMMENDATIONS = ["hold", "trim", "add_more", "avoid"]

# Global Constraint: a candidate that is not affirmatively "compliant" must
# never be allowed "add_more" — this is the restrictive set used for
# non_compliant, insufficient_data, and (conservatively) any other status.
RECOMMENDATIONS_WITHOUT_ADD_MORE = ["hold", "trim", "avoid"]


@dataclass
class CandidateResult:
    """Result of screening a single ticker: its technical signal, halal
    verdict, and the recommendation actions the halal verdict allows.
    """

    ticker: str
    broker_ticker: str | None
    technical: TechnicalSignal
    halal: HalalVerdict
    allowed_recommendations: list[str]


@dataclass
class ScanOutput:
    """Full scan output: every screened candidate, the ranked shortlist, and
    the coverage losses that produced the difference between them.

    The three list fields after `shortlist` exist so coverage loss is
    *visible* instead of silent. A scan of ~600 tickers that quietly returns
    40 results is indistinguishable from a healthy one unless the dropouts
    are reported, and each of these three is a materially different failure
    worth telling apart:

    - `unmatched` / `unmatched_count`: universe tickers the broker does not
      offer as a tradable stock. Expected in small numbers (index membership
      drifts, some listings aren't available in an ISA); a large count means
      the universe's symbol format no longer lines up with the broker's.
    - `failed_tickers`: tickers whose market-data fetch raised. In
      production this is rate limiting, a connection/timeout error, or a
      JSON decode failure from the provider's backend — transient and worth
      retrying, not a property of the ticker.
    - `no_market_data_tickers`: tickers the provider has no entry for at
      all. A genuine coverage gap, not a transient fault.
    """

    all_results: list[CandidateResult]
    shortlist: list[CandidateResult]
    unmatched_count: int = 0
    unmatched: list[str] = field(default_factory=list)
    failed_tickers: list[str] = field(default_factory=list)
    no_market_data_tickers: list[str] = field(default_factory=list)


# Why a holding has no screened `candidate`. Each is a distinct situation a
# report must describe differently, so they are named constants rather than
# ad-hoc strings invented at each call site.
#
# `None` (no reason) means the candidate was screened successfully.
REASON_UNMATCHED_INSTRUMENT = "unmatched_instrument"
REASON_NO_MARKET_DATA = "no_market_data"
REASON_MARKET_DATA_ERROR = "market_data_error"
REASON_POOLED_FUND = "pooled_fund_excluded"

# Human-readable gloss for each reason, so a consumer renders the same
# explanation every time rather than paraphrasing the constant.
HOLDING_REASON_DESCRIPTIONS = {
    REASON_UNMATCHED_INSTRUMENT: (
        "No tradable broker instrument matched this position's ticker, so no "
        "plain ticker was available to query market data with."
    ),
    REASON_NO_MARKET_DATA: (
        "The market-data provider has no entry for this ticker."
    ),
    REASON_MARKET_DATA_ERROR: (
        "Fetching market data for this ticker failed (e.g. rate limit, "
        "connection error, or malformed provider response). This is a "
        "transient fetch failure, not a verdict about the holding."
    ),
    REASON_POOLED_FUND: (
        "This holding is a pooled fund (ETF or similar), not an individual "
        "stock. Pooled funds are excluded from candidacy outright, "
        "regardless of halal status, so no technical signal or halal screen "
        "is computed for it."
    ),
}


def compute_allowed_recommendations(halal_status: str) -> list[str]:
    """Determine which recommendation actions a halal verdict status allows.

    `add_more` is included only when `halal_status == "compliant"` exactly.
    Every other status — including `"non_compliant"`, `"insufficient_data"`,
    and any status not explicitly known — is treated conservatively the same
    as non-compliant for this field only: `add_more` is withheld. This is
    deliberately an allow-list (compare-to-"compliant"), not a deny-list
    (compare-to-the-two-bad-statuses), so an unrecognized future status falls
    on the conservative side by construction rather than by enumeration.
    """
    if halal_status == "compliant":
        return list(ALL_RECOMMENDATIONS)
    return list(RECOMMENDATIONS_WITHOUT_ADD_MORE)
