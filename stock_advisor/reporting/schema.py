"""Shared reporting schema for scan/review output.

`CandidateResult` is the per-ticker result shape produced by
`scripts/scan_market.py` (Task 8) and reused as-is by the portfolio review
script (Task 9) — defined once here so neither script redefines it.
"""
from dataclasses import dataclass

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
