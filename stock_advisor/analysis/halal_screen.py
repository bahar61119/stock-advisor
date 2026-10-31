"""In-house AAOIFI-style halal (Shariah-compliance) screening module.

Pure computation over data already fetched by the market-data provider layer
(`Fundamentals`, `CompanyProfile`) plus configured thresholds
(`HalalThresholds`). The only I/O here is reading the exclusions YAML file.

## The non-permissible-income ratio is permanently unavailable, by design

AAOIFI-style screens include a fourth ratio — non-permissible (e.g. interest)
income over total revenue, conventionally capped around 5%. There is **no
reliable free data source for it**. It is not a per-ticker coverage gap that
better symbols or a retry would close: no free provider (yfinance included)
publishes a "non-permissible income" line at all, because it is a
Shariah-specific aggregation of interest income and other impermissible
revenue streams that general financial-data vendors do not compute.

Treating that permanent gap the same way a per-ticker gap is treated would
make `status = "insufficient_data"` the only reachable outcome for every
company forever, which in turn would make `add_more` unreachable and the
report's "Halal-Compliant" section permanently empty — the screen would look
like it was working while actually screening nothing.

So `screen()` deliberately splits the two cases:

- **The three market-cap ratios** (debt, cash+interest-bearing securities,
  receivables+cash) are genuinely per-ticker. A missing input for any of them
  still lands in `missing_fields` and still forces `insufficient_data` — a
  verdict cannot be computed with a hole in those inputs.
- **`non_permissible_income_ratio`** is reported honestly (left `None` in
  `ratios`, and named in `missing_fields` when its inputs are absent) but
  **never affects `status`**. Instead, every verdict this module returns —
  compliant, non-compliant, and insufficient-data alike, unconditionally —
  carries `HalalVerdict.caveats` containing `NON_PERMISSIBLE_INCOME_CAVEAT`,
  so a consumer cannot render a "compliant" verdict without also rendering
  the statement that one of the four ratios was not checked.

The honest claim this module can therefore make is "passes the three
computable AAOIFI-style ratios and the sector screen", not "AAOIFI
compliant". The caveat field is how that distinction reaches the user.
"""
from dataclasses import dataclass, field
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

# Attached to EVERY verdict this module returns, unconditionally. See the
# module docstring for why this ratio is permanently unavailable rather than
# per-ticker missing.
NON_PERMISSIBLE_INCOME_CAVEAT = (
    "Non-permissible income (e.g. interest income) was not checked — no "
    "reliable free data source exists for this ratio. Verify independently "
    "if this matters to you."
)

# The ratios whose absence genuinely forces `insufficient_data`. Deliberately
# excludes `non_permissible_income_ratio`: see the module docstring.
STATUS_BLOCKING_RATIOS = (
    "debt_to_market_cap",
    "cash_and_interest_to_market_cap",
    "receivables_and_cash_to_market_cap",
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
    """Outcome of screening a single company for Shariah compliance.

    `caveats` is a first-class field, not a derived view of `missing_fields`:
    it always contains at least `NON_PERMISSIBLE_INCOME_CAVEAT`, on every
    status, so no consumer can render a verdict without the limits of the
    screen that produced it. It is a plain list of human-readable sentences
    meant to be shown verbatim.

    Note that `missing_fields` no longer implies `status ==
    "insufficient_data"`: `non_permissible_income_ratio` appears there when
    its inputs are absent but never blocks a verdict. Only the ratios in
    `STATUS_BLOCKING_RATIOS` do. See the module docstring.
    """

    status: Literal["compliant", "non_compliant", "insufficient_data"]
    failed_checks: list[str]
    missing_fields: list[str]
    ratios: HalalRatios
    caveats: list[str] = field(default_factory=lambda: [NON_PERMISSIBLE_INCOME_CAVEAT])


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
       `Fundamentals` fields are present and its denominator is non-zero. A
       ratio that cannot be computed is left `None` in `ratios` and its name
       is added to `missing_fields`. (A zero denominator is treated the same
       as a missing one: a ratio against zero market cap or zero revenue has
       no meaning, so it is reported as uncomputable rather than raising
       `ZeroDivisionError` or silently producing an infinity.)
    3. If any of `STATUS_BLOCKING_RATIOS` could not be computed, `status =
       "insufficient_data"` — a verdict can't be computed with a hole in
       those inputs. `non_permissible_income_ratio` is deliberately NOT
       status-blocking; see the module docstring.
    4. Otherwise, any computed ratio `>=` its threshold makes the company
       `non_compliant`, with every failing ratio's name in `failed_checks`.
       An uncomputed `non_permissible_income_ratio` simply contributes no
       pass and no fail.
    5. Otherwise, `compliant`.

    Every returned verdict carries `caveats` containing
    `NON_PERMISSIBLE_INCOME_CAVEAT`, on every path above.
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
            caveats=[NON_PERMISSIBLE_INCOME_CAVEAT],
        )

    missing_fields: list[str] = []

    def _ratio(name: str, numerators: list[float | None], denominator: float | None):
        """Compute `sum(numerators) / denominator`, or `None` when any
        numerator is missing or the denominator is missing/zero — recording
        `name` in `missing_fields` in that case.
        """
        if any(value is None for value in numerators) or not denominator:
            missing_fields.append(name)
            return None
        return sum(numerators) / denominator

    market_cap = fundamentals.market_cap

    debt_to_market_cap = _ratio(
        "debt_to_market_cap", [fundamentals.total_debt], market_cap
    )
    cash_and_interest_to_market_cap = _ratio(
        "cash_and_interest_to_market_cap", [fundamentals.total_cash], market_cap
    )
    receivables_and_cash_to_market_cap = _ratio(
        "receivables_and_cash_to_market_cap",
        [fundamentals.receivables, fundamentals.total_cash],
        market_cap,
    )
    non_permissible_income_ratio = _ratio(
        "non_permissible_income_ratio",
        [fundamentals.non_permissible_income],
        fundamentals.total_revenue,
    )

    ratios = HalalRatios(
        debt_to_market_cap=debt_to_market_cap,
        cash_and_interest_to_market_cap=cash_and_interest_to_market_cap,
        receivables_and_cash_to_market_cap=receivables_and_cash_to_market_cap,
        non_permissible_income_ratio=non_permissible_income_ratio,
    )

    blocking_missing = [name for name in missing_fields if name in STATUS_BLOCKING_RATIOS]
    if blocking_missing:
        return HalalVerdict(
            status="insufficient_data",
            failed_checks=[],
            missing_fields=missing_fields,
            ratios=ratios,
            caveats=[NON_PERMISSIBLE_INCOME_CAVEAT],
        )

    failed_checks: list[str] = []
    if debt_to_market_cap >= thresholds.debt_to_market_cap:
        failed_checks.append("debt_to_market_cap")
    if cash_and_interest_to_market_cap >= thresholds.cash_and_interest_to_market_cap:
        failed_checks.append("cash_and_interest_to_market_cap")
    if receivables_and_cash_to_market_cap >= thresholds.receivables_and_cash_to_market_cap:
        failed_checks.append("receivables_and_cash_to_market_cap")
    # Only checkable when the ratio was actually computed; an unavailable
    # non-permissible-income ratio neither passes nor fails (the caveat is
    # what carries that fact to the reader).
    if (
        non_permissible_income_ratio is not None
        and non_permissible_income_ratio >= thresholds.non_permissible_income_ratio
    ):
        failed_checks.append("non_permissible_income_ratio")

    status: Literal["compliant", "non_compliant"] = (
        "non_compliant" if failed_checks else "compliant"
    )

    return HalalVerdict(
        status=status,
        failed_checks=failed_checks,
        missing_fields=missing_fields,
        ratios=ratios,
        caveats=[NON_PERMISSIBLE_INCOME_CAVEAT],
    )
