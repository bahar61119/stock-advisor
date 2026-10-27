"""In-house AAOIFI-style halal (Shariah-compliance) screening module.

Pure computation over data already fetched by the market-data provider layer
(`Fundamentals`, `CompanyProfile`) plus configured thresholds
(`HalalThresholds`). The only I/O here is reading the exclusions YAML file.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from stock_advisor.config import HalalThresholds
from stock_advisor.providers.market_data.base import CompanyProfile, Fundamentals

# config/halal_exclusions.yaml, resolved relative to this file so it works
# regardless of the caller's current working directory.
DEFAULT_EXCLUSIONS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "halal_exclusions.yaml"
)


@dataclass
class HalalRatios:
    """Computed Shariah-compliance ratios.

    A field is `None` when one or more of its required `Fundamentals` inputs
    were `None` — the ratio was never computed, not computed-and-rounded-to-zero.
    """

    debt_to_market_cap: float | None
    cash_and_interest_to_market_cap: float | None
    receivables_and_cash_to_market_cap: float | None
    non_permissible_income_ratio: float | None


@dataclass
class HalalVerdict:
    """Outcome of screening a single company for Shariah compliance."""

    status: Literal["compliant", "non_compliant", "insufficient_data"]
    failed_checks: list[str]
    missing_fields: list[str]
    ratios: HalalRatios


def load_exclusions(path: str | Path | None = None) -> list[str]:
    """Load the flat list of sector/industry/business-summary exclusion keywords.

    Defaults to `config/halal_exclusions.yaml`. Returns an empty list if the
    file is empty.
    """
    if path is None:
        path = DEFAULT_EXCLUSIONS_PATH
    with open(path, "r") as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return []
    return list(raw)


def _matched_exclusion(profile: CompanyProfile, exclusions: list[str]) -> str | None:
    """Return the first exclusion keyword found as a case-insensitive substring
    of `profile.sector`, `profile.industry`, or `profile.business_summary`.

    Returns `None` if no keyword matches (or none of the three fields are set).
    """
    haystacks = [profile.sector, profile.industry, profile.business_summary]
    lowered_haystacks = [h.lower() for h in haystacks if h is not None]
    for keyword in exclusions:
        keyword_lower = keyword.lower()
        for haystack in lowered_haystacks:
            if keyword_lower in haystack:
                return keyword
    return None


def screen(
    profile: CompanyProfile,
    fundamentals: Fundamentals,
    thresholds: HalalThresholds,
    exclusions: list[str],
) -> HalalVerdict:
    """Screen a single company for AAOIFI-style Shariah compliance.

    1. Sector/industry/business-summary exclusion check first. A match is an
       immediate `non_compliant`, with `failed_checks = ["sector: <keyword>"]`
       — financial ratios are not computed in this case.
    2. Otherwise, compute each of the four ratios only when its required
       `Fundamentals` fields are not `None`. A ratio with a missing input is
       left `None` in `ratios` and its name is added to `missing_fields`.
    3. If any `missing_fields` were recorded, `status = "insufficient_data"`
       (this takes priority over the pass/fail check below, since a verdict
       can't be computed with a hole in its inputs).
    4. Otherwise, any ratio `>=` its threshold makes the company
       `non_compliant`, with every failing ratio's name in `failed_checks`.
    5. Otherwise, `compliant`.
    """
    matched_keyword = _matched_exclusion(profile, exclusions)
    if matched_keyword is not None:
        return HalalVerdict(
            status="non_compliant",
            failed_checks=[f"sector: {matched_keyword}"],
            missing_fields=[],
            ratios=HalalRatios(
                debt_to_market_cap=None,
                cash_and_interest_to_market_cap=None,
                receivables_and_cash_to_market_cap=None,
                non_permissible_income_ratio=None,
            ),
        )

    missing_fields: list[str] = []

    debt_to_market_cap: float | None = None
    if fundamentals.total_debt is not None and fundamentals.market_cap is not None:
        debt_to_market_cap = fundamentals.total_debt / fundamentals.market_cap
    else:
        missing_fields.append("debt_to_market_cap")

    cash_and_interest_to_market_cap: float | None = None
    if fundamentals.total_cash is not None and fundamentals.market_cap is not None:
        cash_and_interest_to_market_cap = fundamentals.total_cash / fundamentals.market_cap
    else:
        missing_fields.append("cash_and_interest_to_market_cap")

    receivables_and_cash_to_market_cap: float | None = None
    if (
        fundamentals.receivables is not None
        and fundamentals.total_cash is not None
        and fundamentals.market_cap is not None
    ):
        receivables_and_cash_to_market_cap = (
            fundamentals.receivables + fundamentals.total_cash
        ) / fundamentals.market_cap
    else:
        missing_fields.append("receivables_and_cash_to_market_cap")

    non_permissible_income_ratio: float | None = None
    if (
        fundamentals.non_permissible_income is not None
        and fundamentals.total_revenue is not None
    ):
        non_permissible_income_ratio = (
            fundamentals.non_permissible_income / fundamentals.total_revenue
        )
    else:
        missing_fields.append("non_permissible_income_ratio")

    ratios = HalalRatios(
        debt_to_market_cap=debt_to_market_cap,
        cash_and_interest_to_market_cap=cash_and_interest_to_market_cap,
        receivables_and_cash_to_market_cap=receivables_and_cash_to_market_cap,
        non_permissible_income_ratio=non_permissible_income_ratio,
    )

    if missing_fields:
        return HalalVerdict(
            status="insufficient_data",
            failed_checks=[],
            missing_fields=missing_fields,
            ratios=ratios,
        )

    failed_checks: list[str] = []
    if debt_to_market_cap >= thresholds.debt_to_market_cap:
        failed_checks.append("debt_to_market_cap")
    if cash_and_interest_to_market_cap >= thresholds.cash_and_interest_to_market_cap:
        failed_checks.append("cash_and_interest_to_market_cap")
    if receivables_and_cash_to_market_cap >= thresholds.receivables_and_cash_to_market_cap:
        failed_checks.append("receivables_and_cash_to_market_cap")
    if non_permissible_income_ratio >= thresholds.non_permissible_income_ratio:
        failed_checks.append("non_permissible_income_ratio")

    status: Literal["compliant", "non_compliant"] = (
        "non_compliant" if failed_checks else "compliant"
    )

    return HalalVerdict(
        status=status,
        failed_checks=failed_checks,
        missing_fields=missing_fields,
        ratios=ratios,
    )
