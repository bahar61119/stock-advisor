# Stock Advisor — Phase 1 Design (Long-Term Advisory, Read-Only)

Working name: **stock-advisor**. Rename freely — nothing below depends on it.

## Intent and why

The user holds a Trading212 Stocks ISA and wants ongoing, hands-on-but-automated
help finding and evaluating long-term stock investments: growth, dividend,
value, and sector plays (they currently lean tech), held for 6–12 months or
1 year+. They want candidates to be screened for halal/Shariah compliance
(they have no personal expertise here and want to see the screen's work, not
just a verdict), and they want their existing ISA holdings reviewed the same
way. This should run both on-demand and automatically at least twice a day,
without ever placing a trade — all execution stays manual, by the user, in
the Trading212 app itself.

A second, fully separate project (not designed here) will later add
automated day-trading execution against a fixed fund, with a propose-then-
confirm workflow. That project does not exist yet and this one must not
assume it does.

The user also wants this built as a proper installable Claude Skill project
from the start — provider abstractions for broker and market-data sources,
clean packaging — because they intend to eventually open-source it so
others can install it on their own Claude (or other agent) setups. It will
stay private for an unspecified while first; today's build should make that
later step easy, not force it.

## Goals

- Scan broadly across the market (not just a fixed watchlist) for long-term
  candidates across growth, dividend, value, and sector-bet styles.
- Read the user's real Trading212 ISA holdings (read-only) and give a
  hold/trim/add-more comment on each position, using the same analysis
  as new candidates.
- Tag every candidate and holding with a time horizon: 6–12 months or
  1 year+.
- Apply a full halal/Shariah compliance screen to every candidate and
  holding: sector/business exclusions plus AAOIFI-style financial ratio
  checks, computed from scratch (no third-party halal-screening service).
  Show **both** compliant and non-compliant results, clearly labeled, with
  the underlying numbers — never silently filter non-compliant stocks out.
  Exclude pooled index funds/ETFs entirely (not just screen them).
- Combine two prediction/evaluation layers, not one:
  - Rules-based technical signals (moving averages, RSI, MACD, volume
    trend) — transparent, parameters not fit to data, so nothing here can
    silently overfit.
  - Claude's own qualitative reasoning over recent news/fundamentals/company
    context for shortlisted candidates — this is where genuine judgment and
    synthesis happens, not in a hand-fit statistical model.
- Run both on-demand (user asks, e.g. "check my ISA and suggest buys") and
  automatically at least twice a day going forward.
- Use the existing `trading212-labs/agent-skills` plugin as the Trading212
  connector rather than hand-rolling the raw API, calling only its
  read/portfolio endpoints — never its order-placement ones.
- Architect broker access and market-data access each behind a provider
  interface, config-selectable, with Trading212 and a free market-data
  source (default: yfinance) as the first implementations of each. Adding
  a second broker or data provider later should mean writing one new
  provider module, not touching the rest of the system.
  - Note: the qualitative/news layer is Claude doing live reasoning (via
    web search/fetch at run time), not a scripted "provider" — it isn't
    part of this interchangeable-provider abstraction.
- Package as a proper Claude Skill project (SKILL.md + scripts + config +
  README) that is realistically installable by someone else later, even
  though it stays private for now.
- Be honest in every output: this is a best-effort tool, not a source of
  guaranteed returns, and the halal screen is an automated heuristic, not
  a scholarly ruling. Say so in the generated reports, not just in docs.

## Non-goals

- No order placement, anywhere, in this phase — not even behind a flag.
  The Trading212 connector is used read-only only.
- No statistical/ML price-forecasting model. Explicitly rejected in favor
  of transparent technical rules + Claude's own reasoning (see prior
  conversation: fitting a model to limited historical price data is prone
  to overfitting and false confidence, which matters more here than any
  marginal accuracy gain).
- No continuous/real-time/intraday monitoring. Twice-daily cadence plus
  on-demand is the target, not a tick-by-tick system.
- No multi-tenant / multi-user product concerns (auth systems, billing,
  etc.) — it's a single user's private tool that happens to be built
  cleanly enough to hand to someone else later.
- No attempt to integrate Zoya, Musaffa, or any other halal-screening
  service. The screen is computed from raw financial data.
- No index funds or ETFs as candidates, ever, regardless of halal status.

## Anti-goals (would make this a failure even if "working")

- Silently dropping non-compliant candidates instead of showing them
  labeled — the user explicitly wants to see both.
- A halal screen (or report in general) that overstates its own
  authority — e.g. a plain "✅ Halal" badge with no numbers behind it.
- A technical or fundamentals module that produces a verdict without
  showing the inputs that produced it.
- Anything that places or modifies a real order, under any circumstance,
  in this phase.
- An architecture so tightly bound to Trading212 or to yfinance that
  adding a second provider means rewriting core logic.

## Constraints

- Trading212's public API is in beta; the `trading212-labs/agent-skills`
  plugin wraps it, but endpoints/behavior may shift. The broker-provider
  interface exists partly to contain that churn.
- Trading212 API values are reported in the account's primary currency
  only (no multi-currency support) — inherited limitation, not something
  to work around.
- Free market-data sources (default: yfinance) have inconsistent
  fundamentals coverage outside large/mid-cap US stocks. When data needed
  for the halal ratio screen is missing, the report must say
  "insufficient data," not guess or silently skip the ticker.
- No paid data or broker subscriptions are assumed up front.
- This stays a private, single-user project for now. Don't build
  infrastructure (e.g. per-user config, hosted anything) that only makes
  sense once it's actually distributed — but do keep the provider/config
  separation clean, since that's exactly what makes open-sourcing later
  straightforward instead of a rewrite.

## Decisions already made (not open to re-litigation by the builder)

- **Scope**: Phase 1 (this doc) is advisory-only, read-only against the
  broker. Phase 2 (automated day-trading execution) is a separate future
  project with its own design; nothing here should assume its existence
  or shared code beyond "both may one day use the same provider
  abstraction pattern."
- **Autonomy model**: n/a to this phase (no execution at all), but noted
  for continuity — Phase 2, whenever designed, starts from
  propose-then-confirm, not full autonomy.
- **Prediction approach**: hybrid of rules-based technical signals +
  Claude's own qualitative reasoning. Explicitly not a fitted statistical/
  ML model.
- **Broker connector**: use `trading212-labs/agent-skills`
  (https://github.com/trading212-labs/agent-skills), installed via its
  documented method, configured with `T212_API_KEY` /
  `T212_API_SECRET` / `T212_ENV`. Read endpoints only.
- **Universe & scan**: broad market scan (not a fixed personal watchlist),
  tech-weighted by the user's stated interest but not limited to tech,
  plus review of actual current ISA holdings.
- **Investment styles covered**: growth, dividend, value, sector bets —
  via individual stocks only (no index funds/ETFs for diversification).
- **Time horizons**: every candidate/holding tagged 6–12 months or
  1 year+.
- **Halal screen**: full AAOIFI-style screen (sector exclusions +
  financial ratios), computed in-house, applied to every candidate and
  holding. Both compliant and non-compliant results shown, each labeled
  and backed by the actual numbers. Index funds/ETFs excluded outright.
- **Delivery cadence**: on-demand plus automatic, at least twice daily.
- **Publication**: stays private for now. Architecture should make
  eventual open-sourcing easy, but nothing here is being published yet.
- **Halal verdict vs. hold/trim/add-more recommendation ("soft flag")**:
  the two are shown side by side, clearly labeled, with no verdict text
  that implies the other overrides it — but a holding or candidate that
  fails the halal screen must never be recommended as "add more." It can
  still be shown as "hold" (not forced toward "trim"/"exit") if that's
  what the technical/qualitative view supports; the user makes the
  compliance call themselves, informed by the numbers shown.
- **Sizing scope: directional only.** Recommendations are hold / trim /
  add-more / avoid, with no dollar or share amounts, no position-sizing,
  and no portfolio-concentration logic. This phase does not need the
  user's risk tolerance, concentration limits, or cash-deployment
  preferences defined. Quantified sizing is an explicit candidate for a
  later iteration once the directional advice has proven useful — not
  part of this build.
- **Unattended run mechanism**: the twice-daily automatic runs are
  implemented as a scheduled Claude Code agent routine (the `schedule`
  skill / cron-based cloud routine), which wakes a real Claude session
  with full tool access — including web search/fetch — and runs this
  skill exactly as an on-demand invocation would. This is not a bare
  script on a timer; it resolves the apparent tension between "proper
  Skill package" and "self-triggering automation" by having the
  *scheduler* invoke the skill as a session, rather than the skill
  invoking itself. API keys/credentials are available to that session the
  same way they are for an interactive one.
- **Qualitative-pass cost control**: the technical-signal and halal screen
  run cheaply across the full scan universe on every pass (no live web
  search involved). Claude's live qualitative reasoning (news/fundamentals
  synthesis) is then applied only to a bounded shortlist drawn from that
  pre-filter — default top ~15–20 candidates per run, configurable — to
  keep twice-daily unattended runs affordable and fast. The existing ISA
  holdings always get the qualitative pass regardless of shortlist size,
  since there are normally far fewer of them than the broad-scan
  universe.

## What's left to the builder (decide during planning/implementation)

- Exact repository layout within Claude Skill conventions (proposed:
  `stock-advisor/` as its own git repo under the workspace, with
  `SKILL.md`, `scripts/`, `providers/`, `config/`, `references/`,
  `README.md`).
- Exact integration mechanism with the `trading212-labs/agent-skills`
  plugin (e.g. invoked as its own skill/tool that Claude calls directly,
  vs. shelled out to from a Python script) — depends on how that plugin
  actually exposes itself once installed; verify at implementation time.
- Language choice for the original scripts: Python is the sensible default
  (market-data/finance tooling, halal ratio math) — the Trading212
  connector dependency can stay in whatever language it ships in
  (apparently Node-based) and is treated as an external dependency, not
  rewritten.
- Default market-data provider: yfinance (no API key required). Provider
  interface should make swapping this out (Alpha Vantage, Finnhub, etc.)
  a config change plus one new module.
- Exact technical indicator set and default parameters (e.g. which moving
  average windows, RSI/MACD defaults) — standard textbook defaults unless
  a reason emerges to deviate.
- Exact AAOIFI-style thresholds — commonly-used values (~33% debt/market
  cap, ~33% cash+interest-bearing securities/market cap, ~33%
  receivables+cash/market cap, <5% non-permissible income/revenue) unless
  research turns up a reason to differ; must be documented and
  config-adjustable, not hardcoded invisibly.
- Sector/business exclusion list specifics (conventional banking/
  insurance, alcohol, tobacco, gambling, adult entertainment, pork
  products, conventional weapons, interest-based lending, etc.) — a
  documented, editable list, not a black box.
- Source for the default broad-scan universe (e.g. a bundled static list
  of major index constituents such as S&P 500 / NASDAQ-100 / FTSE 100,
  intersected with what Trading212 actually offers) — needs a small
  implementation-time decision on where that list comes from and how it's
  refreshed.
- Report format and structure (Markdown report vs. Artifact dashboard vs.
  both), and whether the scheduled routine's output is pushed to the user
  (e.g. a notification) or simply left ready to view on demand.
- Exact schedule trigger times (e.g. aligned to US/UK market hours) —
  "at least twice a day" and "a scheduled Claude Code agent routine" are
  both fixed; the exact times are the builder's call.
- Credential storage convention (`.env`, gitignored) and any setup
  instructions needed in the README for a future installer to follow.
- Testing approach: there's no ground truth for "is this a good stock
  pick," so tests should target correctness of computation (ratio math,
  indicator math, provider interface contracts) rather than investment
  outcomes.
- License choice for eventual open-sourcing (not needed yet; MIT is a
  reasonable default to note for later, not something to add now).
