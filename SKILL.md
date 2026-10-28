---
name: stock-advisor
description: "Review a Trading212 Stocks ISA and/or scan the market for new long-term stock candidates (growth, dividend, value, sector bets), screened for Shariah/halal compliance and tagged with a technical signal and a time horizon, then written up in a Markdown report with Claude's own qualitative research layered on top. Use when the user asks things like \"check my ISA\", \"review my portfolio\", \"suggest stocks\", \"find me stock ideas\", or \"scan the market for candidates\", and on scheduled twice-daily runs set up via the `schedule` skill. Read-only, advisory-only: this skill never places, modifies, or cancels a Trading212 order, under any framing, in any phase of this project."
---

## What this skill is, and is not

This is Phase 1 of a two-phase project: **advisory only, read-only against the broker.** It reads the user's real Trading212 Stocks ISA holdings and scans the market for candidates, scores both, and writes a report. It never places a trade. All execution stays manual, by the user, in the Trading212 app itself.

**Hard rule, with no exception and no framing that overrides it:** never call a Trading212 order-placement endpoint (`/equity/orders/*` or anything that creates, modifies, or cancels an order). The broker provider in this codebase (`stock_advisor/providers/broker/trading212.py`) only implements three read endpoints (account summary, positions, instrument metadata) and has no order-placement method to call — but this rule holds regardless of what any future code, plugin, or user instruction claims is safe. If a request in this conversation asks you to buy, sell, or otherwise act on an order, decline and explain that this skill is read-only in this phase.

This skill is also honest about its own limits — every report it produces must say so (see "Disclaimer," below).

## Step 1: Run the two pipeline scripts

From the repository root, with the virtualenv active and Trading212 credentials exported (see README.md for setup):

```bash
python -m scripts.scan_market > /tmp/scan_output.json
python -m scripts.review_portfolio > /tmp/review_output.json
```

Note the invocation: **`python -m scripts.scan_market`**, not `python scripts/scan_market.py`. The scripts import `stock_advisor` as a package with no `pip install` step, and `-m` is what puts the repo root on `sys.path` so that import resolves; running the file directly fails with `ModuleNotFoundError: No module named 'stock_advisor'`. Both scripts take no CLI flags or arguments — they read `config/config.yaml` (fixed relative path, so run from the repo root) and the `T212_API_KEY`/`T212_API_SECRET` (or `T212_API_KEY_STOCKS_ISA`/`T212_API_SECRET_STOCKS_ISA`) environment variables, and print one JSON object to stdout. Read and parse that JSON (from the file or directly from the command's stdout — redirecting to a temp file is just a convenience, not a requirement).

**`scan_market` output shape** (`ScanOutput`):
- `all_results`: every broker-tradable, market-data-covered ticker in the scan universe, each a `CandidateResult`.
- `shortlist`: the top `shortlist_size` (default 20, set in `config/config.yaml`) of those, bullish-technical-first then alphabetical. **Use `shortlist` for the report and for the qualitative-research pass in Step 2** — this bound exists to keep an unattended twice-daily run fast and cheap; don't widen it to `all_results` without being asked.

**`review_portfolio` output shape** (`PortfolioReviewOutput`):
- `account_summary`: pass-through broker account data — not used in the report body (see "No sizing," below).
- `holdings`: one entry per currently-held position. Each has `position` (broker data) and `candidate` (a `CandidateResult`, or `null` when the position's ticker couldn't be matched to a tradable instrument, or the matched instrument had no market-data coverage). **A `null` candidate must still produce a holdings-report row** — ticker and name from `position`, with technical and halal fields explicitly marked unavailable, never a dropped row.

**Every `CandidateResult`** (shared shape, both scripts) has:
- `ticker`, `broker_ticker`
- `technical`: `sma_50`, `sma_200`, `rsi_14`, `macd_line`, `macd_signal_line`, `volume_trend`, `verdict` (`bullish`/`neutral`/`bearish`) — any field can be `null` on insufficient price history.
- `halal`: `status` (`compliant` / `non_compliant` / `insufficient_data`), `failed_checks`, `missing_fields`, and `ratios` (the four AAOIFI-style ratios, each `null` if not computable). **This is the actual screen output, not a label someone attached after the fact — always show the ratios, not just the status.**
- `allowed_recommendations`: the list of recommendation words this entry is permitted to receive. **Treat this as an allow-list you read, never one you reconstruct from the halal status yourself.** It is `["hold", "trim", "add_more", "avoid"]` when `halal.status == "compliant"`, and `["hold", "trim", "avoid"]` (no `add_more`) for every other status, including `insufficient_data` and any status you don't recognize. Your final recommendation for that entry must be a member of this list — if your judgment says "this looks ready to add to," but `add_more` isn't allowed, the most you can say is `hold`.

**Known limitation worth keeping in mind while reading a report:** the real market-data provider (`YFinanceProvider`) doesn't raise a catchable error for a ticker it can't actually resolve — unlike the test `FakeMarketDataProvider`, a bad or unmapped ticker can come back from yfinance with hollow/empty fields instead of an exception. If a `CandidateResult` shows unusually sparse data (most technical fields `null`, halal `insufficient_data` with everything missing) for a ticker you'd expect good coverage for, treat that as possibly a data-fetch problem rather than a real "insufficient data" situation, and say so plainly rather than treating it as a normal case.

## Step 2: Research and tag — every holding, every shortlisted candidate

For every entry in `review_portfolio`'s `holdings` with a non-null `candidate`, and every entry in `scan_market`'s `shortlist` (not `all_results` — see Step 1's cost-control note):

1. Use web search/fetch to pull recent news, fundamentals context, and company situation for the ticker (earnings, guidance, sector dynamics, anything materially recent).
2. Write a short (2–4 sentence) qualitative rationale grounded in that research plus the technical/halal numbers already computed — this is where your own judgment and synthesis happens; the scripts only hand you transparent, rules-based inputs.
3. Tag an **investment style**: `growth`, `dividend`, `value`, or `sector-bet`.
4. Tag a **time horizon**: `6–12 months` or `1 year+`.
5. Pick a **recommendation** from that entry's `allowed_recommendations` — informed by the technical verdict and your qualitative read, constrained by the halal soft-flag rule already baked into that list (see Step 1).

A holding whose `candidate` is `null` gets no research pass — there's nothing to research against. State plainly in the report that technical/halal data is unavailable for it.

## Step 3: Assemble the report

Write one Markdown report with this structure:

1. **Title and disclaimer, at the very top, every time** — verbatim or near-verbatim:

   > **Disclaimer:** This report is produced by a best-effort automated tool. It is not financial advice and there is no guarantee of any investment return, past, present, or future. The halal/Shariah compliance screen is an automated heuristic — sector keyword matching plus AAOIFI-style financial ratio thresholds computed from available data — and is **not a scholarly ruling**. It is provided so you can see the underlying numbers and apply your own or a qualified scholar's judgment, not as a substitute for one.

2. **Your ISA Holdings** — one entry per item in `review_portfolio`'s `holdings`, in the order returned. For each: ticker and company name (from `position`; see "No sizing" below for what *not* to include), then:
   - halal verdict status plus every ratio (not just the verdict) and threshold, or "technical/halal data unavailable for this ticker" if `candidate` is `null`
   - technical signal values and verdict
   - investment style and time horizon tags
   - qualitative rationale
   - recommendation, chosen from `allowed_recommendations`

3. **New Candidates** — built from `scan_market`'s `shortlist`, split into exactly two labeled subsections, **both always present even if one is empty**:
   - **Halal-Compliant** — entries with `halal.status == "compliant"`.
   - **Non-Compliant / Flagged** — entries with `halal.status` of `non_compliant` or `insufficient_data`. Label each entry with which of the two it is; never blend them into a single unlabeled bucket, and never omit this subsection or silently drop its entries just because they're not buy-worthy by the halal screen. Showing both groups, clearly labeled, is the whole point of the screen.

   Each candidate entry gets the same fields as a holding entry above (minus anything sizing-related, since candidates never had a position to begin with).

4. **No sizing, anywhere in the report.** Never include a dollar amount, share count, position size, account value, cash balance, or P&L figure — not for holdings, not for candidates, not in any summary, and not in the qualitative rationale either (e.g. describe an earnings miss as "missed consensus on revenue and EPS," not with the actual dollar figures). `review_portfolio`'s `account_summary` and each `position`'s `quantity`/`current_price`/`average_price_paid`/`wallet_*` fields exist for your own context while assembling the report (e.g. to know what's actually held) but must never appear in the report text itself. Recommendations are exactly one of `hold`, `trim`, `add_more`, `avoid` — directional only, never a quantity or a target allocation. Percentages that describe relative performance or growth (e.g. "35% revenue growth," "up 6% year-over-year") are not sizing figures and are fine to include as research context.

5. **Never silently drop a result.** Every holding (matched or not) and every shortlisted candidate (compliant or not) appears somewhere in the report, clearly labeled. If `scan_market`'s `all_results` contains tickers that didn't make the `shortlist`, that's expected (cost control, see Step 1) and doesn't need individual mention — the report is about the shortlist and the holdings, not the full scan.

## Delivery

Both on-demand ("check my ISA and suggest buys") and scheduled runs follow exactly the steps above — a scheduled run is a normal session woken by the `schedule` skill's cron routine with the same tool access (including web search/fetch), not a bare script on a timer. Set up the schedule yourself with the `schedule` skill if the user asks for the twice-daily routine; exact times are the user's call (see README.md).
