---
name: stock-advisor
description: "Review a Trading212 Stocks ISA and/or scan the market for new long-term stock candidates (growth, dividend, value, sector bets), screened for Shariah/halal compliance and tagged with a technical signal and a time horizon, then published to a persistent interactive dashboard (one stable link, updated in place every run) with Claude's own qualitative research layered on top. Use when the user asks things like \"check my ISA\", \"review my portfolio\", \"suggest stocks\", \"find me stock ideas\", or \"scan the market for candidates\", and on scheduled twice-daily runs set up via the `schedule` skill. Read-only, advisory-only: this skill never places, modifies, or cancels a Trading212 order, under any framing, in any phase of this project."
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

Note the invocation: **`python -m scripts.scan_market`**, not `python scripts/scan_market.py`. The scripts import `stock_advisor` as a package with no `pip install` step, and `-m` is what puts the repo root on `sys.path` so that import resolves; running the file directly fails with `ModuleNotFoundError: No module named 'stock_advisor'`. Both scripts take no CLI flags or arguments — they read `config/config.yaml` (resolved relative to the package, not the working directory), the `T212_API_KEY`/`T212_API_SECRET` (or `T212_API_KEY_STOCKS_ISA`/`T212_API_SECRET_STOCKS_ISA`) environment variables, and `T212_ENV` (`demo`/`live`, defaulting to `live`), and print one JSON object to stdout. Read and parse that JSON (from the file or directly from the command's stdout — redirecting to a temp file is just a convenience, not a requirement).

**`scan_market` output shape** (`ScanOutput`):
- `all_results`: every broker-tradable, market-data-covered ticker in the scan universe, each a `CandidateResult`.
- `shortlist`: the top `shortlist_size` (default 20, set in `config/config.yaml`) of those, bullish-technical-first then alphabetical. **Use `shortlist` for the report and for the qualitative-research pass in Step 2** — this bound exists to keep an unattended twice-daily run fast and cheap; don't widen it to `all_results` without being asked.
- `unmatched_count` / `unmatched`: universe tickers the broker doesn't offer as a tradable stock.
- `no_market_data_tickers`: tickers the market-data provider has no entry for.
- `failed_tickers`: tickers whose market-data fetch **raised** — in production usually rate limiting, a connection/timeout error, or a malformed provider response.

These last three are coverage-loss reporting, and they change what you should say about the run. A handful of `unmatched` entries is normal (index membership drifts; not every listing is ISA-available). But **a large `failed_tickers` list means the scan was throttled or the network was flaky, so the shortlist was drawn from a partial universe** — say so plainly in the report rather than presenting the shortlist as if it ranked the whole scan. Don't list every failed ticker individually; a count and a one-line caveat is enough. Note also that these exist precisely so a partial run still *produces* a report: a single provider exception no longer aborts the whole scan.

**`review_portfolio` output shape** (`PortfolioReviewOutput`):
- `account_summary`: pass-through broker account data — not used in the report body (see "No sizing," below).
- `holdings`: one entry per currently-held position. Each has `position` (broker data), `candidate` (a `CandidateResult`, or `null`), and `reason` (`null` when `candidate` is present, otherwise *why* it isn't). **A `null` candidate must still produce a holdings-report row** — ticker and name from `position`, with technical and halal fields explicitly marked unavailable, never a dropped row.

  `reason` has four possible values, and they want **different wording** in the report — do not collapse them into one "data unavailable" message:
  - `"unmatched_instrument"` — no tradable broker instrument matched this position's ticker, so there was no plain ticker to look it up by.
  - `"no_market_data"` — the market-data provider has no entry for it. A genuine coverage gap.
  - `"market_data_error"` — the fetch *failed* (rate limit, connection error, malformed response). This is "we couldn't look", **not** "there's nothing to see" — a transient fault, worth saying is worth re-checking, and explicitly not a verdict about the holding.
  - `"pooled_fund_excluded"` — the holding is an ETF or other pooled fund. The spec excludes pooled funds from candidacy outright, *regardless of halal status*, so it is deliberately not screened or scored. Report it as held, state that it's a pooled fund excluded from candidacy by design, and give it **no** technical verdict, no halal verdict, and no recommendation. This is not a data problem and must not be described as one.

**Every `CandidateResult`** (shared shape, both scripts) has:
- `ticker`, `broker_ticker`
- `technical`: `sma_50`, `sma_200`, `rsi_14`, `macd_line`, `macd_signal_line`, `volume_trend`, `verdict` (`bullish`/`neutral`/`bearish`) — any field can be `null` on insufficient price history.
- `halal`: `status` (`compliant` / `non_compliant` / `insufficient_data`), `failed_checks`, `missing_fields`, `ratios` (the four AAOIFI-style ratios, each `null` if not computable), and `caveats`. **This is the actual screen output, not a label someone attached after the fact — always show the ratios, not just the status.**

  **`caveats` must be rendered for every entry that has a halal verdict, on every status — compliant included.** It is a list of plain sentences; show them verbatim (once per entry, or once per report section if you'd otherwise repeat the identical text for every entry — but never omitted entirely). It always contains at least the note that the non-permissible-income ratio was not checked, because no reliable free data source exists for it. That is a permanent, structural gap, not a per-ticker one, which is why `status` is computed from the sector screen plus the other three ratios instead of being forced to `insufficient_data` forever.

  Two consequences to get right:
  - A `compliant` verdict here means **"passed the sector screen and the three computable ratios"**, not "AAOIFI compliant". Don't write it up as a clean halal pass; write it up as what it is, with the caveat attached.
  - `missing_fields` may therefore be non-empty on a `compliant` result (typically listing exactly `non_permissible_income_ratio`). **Do not infer the status from `missing_fields`** — read `status`.
- `allowed_recommendations`: the list of recommendation words this entry is permitted to receive. **Treat this as an allow-list you read, never one you reconstruct from the halal status yourself.** It is `["hold", "trim", "add_more", "avoid"]` when `halal.status == "compliant"`, and `["hold", "trim", "avoid"]` (no `add_more`) for every other status, including `insufficient_data` and any status you don't recognize. Your final recommendation for that entry must be a member of this list — if your judgment says "this looks ready to add to," but `add_more` isn't allowed, the most you can say is `hold`.

**If a script fails outright**, a Trading212 credential or connectivity problem now surfaces as a `Trading212Error` naming the likely cause (e.g. HTTP 401 → "credentials rejected, check T212_API_KEY/..."). Relay that cause to the user rather than pasting the traceback — on a first run it is nearly always a missing or wrong API key. Note that a broker failure means neither script can run at all, whereas a *market-data* failure only costs individual tickers (see `failed_tickers` above).

**Known limitation worth keeping in mind while reading a report:** the real market-data provider (`YFinanceProvider`) doesn't raise a catchable error for a ticker it can't actually resolve — unlike the test `FakeMarketDataProvider`, a bad or unmapped ticker can come back from yfinance with hollow/empty fields instead of an exception. If a `CandidateResult` shows unusually sparse data (most technical fields `null`, halal `insufficient_data` with everything missing) for a ticker you'd expect good coverage for, treat that as possibly a data-fetch problem rather than a real "insufficient data" situation, and say so plainly rather than treating it as a normal case.

## Step 2: Research and tag — every holding, every shortlisted candidate

For every entry in `review_portfolio`'s `holdings` with a non-null `candidate`, and every entry in `scan_market`'s `shortlist` (not `all_results` — see Step 1's cost-control note):

1. Use web search/fetch to pull recent news, fundamentals context, and company situation for the ticker (earnings, guidance, sector dynamics, anything materially recent).
2. Write a short (2–4 sentence) qualitative rationale grounded in that research plus the technical/halal numbers already computed — this is where your own judgment and synthesis happens; the scripts only hand you transparent, rules-based inputs.
3. Tag an **investment style**: `growth`, `dividend`, `value`, or `sector-bet`.
4. Tag a **time horizon**: `6–12 months` or `1 year+`.
5. Pick a **recommendation** from that entry's `allowed_recommendations` — informed by the technical verdict and your qualitative read, constrained by the halal soft-flag rule already baked into that list (see Step 1).

A holding whose `candidate` is `null` gets no research pass — there's nothing to research against. State plainly in the report that technical/halal data is unavailable for it.

## Step 3: Assemble the report content

Whether it ends up on the dashboard (Step 4, the normal path) or in a plain Markdown reply (the fallback), the same content rules apply:

1. **Disclaimer, always** — verbatim or near-verbatim: "This report is produced by a best-effort automated tool. It is not financial advice and there is no guarantee of any investment return, past, present, or future. The halal/Shariah compliance screen is an automated heuristic — sector keyword matching plus AAOIFI-style financial ratio thresholds computed from available data — and is **not a scholarly ruling**. It is provided so you can see the underlying numbers and apply your own or a qualified scholar's judgment, not as a substitute for one." (The dashboard template already renders this; a Markdown fallback must include it itself.)

2. **Your ISA Holdings** — one entry per item in `review_portfolio`'s `holdings`, in the order returned. For each: ticker and company name (from `position`; see "No sizing" below for what *not* to include), then halal verdict status plus every ratio (not just the verdict), technical signal values and verdict, investment style and time horizon tags, qualitative rationale, and a recommendation chosen from `allowed_recommendations` — or, if `candidate` is `null`, the `reason`-specific wording from Step 1 instead of any of that.

3. **New Candidates** — built from `scan_market`'s `shortlist`, split into exactly two groups, **both always present even if one is empty**: **Halal-Compliant** (`halal.status == "compliant"`) and **Non-Compliant / Flagged** (`non_compliant` or `insufficient_data`). Never blend them into one unlabeled bucket, and never drop entries just because they're not buy-worthy — showing both groups, clearly labeled, is the whole point of the screen. Each candidate gets the same fields as a holding (minus anything sizing-related).

4. **No sizing, anywhere.** Never include a dollar amount, share count, position size, account value, cash balance, or P&L figure — not for holdings, not for candidates, not in any summary, and not in the qualitative rationale either (e.g. "missed consensus on revenue and EPS," not the actual dollar figures). `account_summary` and each `position`'s `quantity`/`current_price`/`average_price_paid`/`wallet_*` fields exist for your own context while assembling the report but must never appear in the report text itself. Recommendations are exactly one of `hold`, `trim`, `add_more`, `avoid` — directional only. Relative percentages ("35% revenue growth") are fine as research context; they're not sizing figures.

5. **Never silently drop a result.** Every holding and every shortlisted candidate appears somewhere, clearly labeled. Tickers in `all_results` that didn't make the `shortlist` don't need individual mention (cost control, Step 1) — the report is about the shortlist and the holdings, not the full scan.

## Step 4: Publish the dashboard

The report's home is a single, persistent Artifact — the user explicitly wants one stable link that updates in place on every run (on-demand or scheduled), not a fresh link each time, since they intend to treat it like a small web app.

1. **Read `stock_advisor/reporting/dashboard_template.html`** as your starting point — it already has the full page (styles, layout, the "ask about this report" panel wired to the Artifact `sample` capability) and a `const REPORT_DATA = {...}` object near the top of its `<script>` block populated with clearly-marked example data.

2. **Replace that one object wholesale** with the real data from this run: `isExample: false`, `generatedAt` as the current timestamp.

   **Field mapping — the pipeline's field names are not the dashboard's.** The JSON from Step 1 is Python snake_case; the dashboard reads camelCase, and a few names changed outright. A straight pass-through produces a page where every value quietly reads "not available" instead of erroring — map every field explicitly, exactly as below, don't guess at the rest:

   | Dashboard field | Comes from |
   |---|---|
   | `coverage.universeSize` | `len(scan_market's all_results)` |
   | `coverage.shortlisted` | `len(scan_market's shortlist)` |
   | `coverage.unmatched` | `scan_market's unmatched_count` |
   | `coverage.noMarketData` | `len(scan_market's no_market_data_tickers)` |
   | `coverage.failed` | `len(scan_market's failed_tickers)` |
   | `thresholds.{debt,cash,receivables,income}` | `config/config.yaml`'s `halal_thresholds.{debt_to_market_cap, cash_and_interest_to_market_cap, receivables_and_cash_to_market_cap, non_permissible_income_ratio}` — static, set once, not per-entry |
   | per-entry `technical.{sma50,sma200,rsi14,macdLine,macdSignal,volumeTrend,verdict}` | `TechnicalSignal.{sma_50,sma_200,rsi_14,macd_line,macd_signal_line,volume_trend,verdict}` |
   | per-entry `halal.status` / `halal.failedChecks` / `halal.caveats` | `HalalVerdict.status` / `.failed_checks` / `.caveats` |
   | per-entry `halal.ratios.{debt,cash,receivables,income}` | `HalalRatios.{debt_to_market_cap, cash_and_interest_to_market_cap, receivables_and_cash_to_market_cap, non_permissible_income_ratio}` |
   | per-entry `allowed` | `allowed_recommendations` (don't drop this — a missing `allowed` array is the one thing that can blank the whole page, not just this entry) |
   | per-entry `style` | Step 2's tag, exactly one of `growth` / `dividend` / `value` / `sector-bet` |
   | per-entry `horizon` | Step 2's tag, as exactly one of these two tokens: `6-12mo` for "6–12 months", `1yr+` for "1 year+" — not the human-readable phrase |
   | per-entry `rationale` / `recommendation` | Step 2's own output |

   `holdings` comes from `review_portfolio`'s `holdings`; each `reason`-only entry (no `candidate`) is `{ ticker: position.ticker, brokerTicker: position.ticker, name: position.name, reason: <the HoldingResult.reason string, unchanged> }` — no `technical`/`halal`/`recommendation`/`allowed` fields at all when `candidate` is `null`. `candidatesCompliant` / `candidatesFlagged` are the two halal-split groups from `scan_market`'s `shortlist` (Step 3's rule 3), each entry built from the mapping table above. Don't touch the file's CSS, JS logic, or structure outside the data object — it's already built and reviewed; your job each run is the data, not the page.

3. **Check `stock_advisor.reporting.dashboard_state.read_dashboard_url()`** (run `python -c "from stock_advisor.reporting.dashboard_state import read_dashboard_url; print(read_dashboard_url())"` or equivalent):
   - A URL already recorded → **read that artifact first** (the publish tool refuses a publish to a URL this conversation hasn't read or published — every scheduled run is a fresh conversation, so this step is not optional just because you already know the URL), then publish the edited file to that `url`, which updates it in place. Omit `capabilities` so the existing `sample` grant carries forward unchanged (per the Artifact tool: omitting the field on a redeploy keeps what the page already has — passing `{}` would clear it, and restating `{"sample": {}}` would also work but isn't needed). Likewise omit `favicon`/`icon` so they're kept.
   - `None` (first run ever) → publish fresh with no `url`, `title: "Halal Screen"`, a one-sentence `description`, `favicon: "📊"`, `icon: "chart"`, and `capabilities: {"sample": {}}` (required on this first publish — a capability has to be declared before it can be omitted-to-keep on a later one). Then call `write_dashboard_url()` with the URL this publish call returns, so every later run updates this same artifact instead of repeating this branch.

4. **Reply in chat with a short summary, not the full report** — a few lines covering headline counts (holdings reviewed, candidates compliant/flagged, any coverage caveats from Step 1) and the dashboard's link. The dashboard is where the detail lives; don't duplicate it all in the chat reply.

**Fallback:** if the Artifact tool genuinely isn't available in whatever context is running this skill, fall back to a plain Markdown reply following Step 3's content rules directly in chat, and say that's what you're doing and why.

## Delivery

Both on-demand ("check my ISA and suggest buys") and scheduled runs follow exactly the steps above — a scheduled run is a normal session woken by the `schedule` skill's cron routine with the same tool access (including web search/fetch and the Artifact tool), not a bare script on a timer. Set up the schedule yourself with the `schedule` skill if the user asks for the twice-daily routine; exact times are the user's call (see README.md). Either way, the dashboard link stays the same run to run — that's the point of Step 4's URL persistence.
