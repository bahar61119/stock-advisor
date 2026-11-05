# stock-advisor

A private Claude Skill that reviews a Trading212 Stocks ISA and scans the
market for long-term stock candidates (growth, dividend, value, sector
bets), screening every result for halal/Shariah compliance and tagging it
with a transparent technical signal and a time horizon. Claude layers its
own qualitative research (news, fundamentals, company context) on top of
the rules-based numbers before publishing it all to a single, persistent
interactive dashboard — one stable link that updates in place every run,
with its own "ask about this report" panel.

## What this is — and is not

- **Phase 1 only: advisory, read-only.** This project reads your Trading212
  account (balances, positions, tradable instruments) and the market. It
  never places, modifies, or cancels an order. All execution stays manual,
  by you, in the Trading212 app.
- **Not financial advice.** It is a best-effort tool with no guaranteed
  returns — every generated report says so.
- **Not a Shariah ruling.** The halal screen is an automated heuristic
  (sector-keyword exclusions plus AAOIFI-style financial ratio thresholds
  computed from available data), not a scholarly determination. Both
  compliant and non-compliant/flagged results are always shown, with the
  numbers behind them — never silently filtered out.
- **No position sizing.** Recommendations are directional only: `hold`,
  `trim`, `add_more`, `avoid`. No dollar amounts, share counts, or
  portfolio-sizing figures appear anywhere in a report.
- A second, separate project may later add automated trade execution. That
  project does not exist yet, and nothing here assumes it does.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` is the runtime set. To run the tests as well, install the
dev set instead (it includes the runtime one):

```bash
pip install -r requirements-dev.txt
```

## Trading212 API credentials

1. In the Trading212 app: **Settings → API** (beta feature — enable it if
   you don't see it yet).
2. Generate an API key for your Stocks ISA account. Trading212 issues a
   key + secret pair.
3. Copy `.env.example` to `.env` and fill in the values:

   ```bash
   cp .env.example .env
   ```

   `.env` holds `T212_API_KEY` / `T212_API_SECRET` (or the
   `T212_API_KEY_STOCKS_ISA` / `T212_API_SECRET_STOCKS_ISA` variants, which
   take priority if both are set — see
   `stock_advisor/providers/broker/trading212.py`) and `T212_ENV`
   (`demo` or `live`). `.env` is gitignored; never commit it.

   `T212_ENV` selects which Trading212 host the scripts talk to and
   **defaults to `live` when unset** — set it to `demo` explicitly if that's
   what you want. (Note that everything here is read-only either way; no
   order endpoint is ever called.)

4. Export those variables into the shell/session that will actually run
   the scripts (source `.env` yourself, or let your Claude session's
   environment do it) — `load_config()` and the Trading212 provider read
   them from `os.environ`, not from the `.env` file directly.

Trading212's API is in beta and reports values in your account's primary
currency only (no multi-currency support) — an inherited limitation, not
something this project works around.

## Running on demand

Ask Claude something like *"check my ISA and suggest buys"*, *"scan the
market for stock ideas"*, or *"review my portfolio"* — this triggers the
`stock-advisor` skill (see `SKILL.md`), which runs both pipeline scripts
and assembles the report. You generally won't invoke the scripts directly
yourself; but if you want to see the raw JSON a pipeline produces:

```bash
python -m scripts.scan_market
python -m scripts.review_portfolio
```

Run these **from the repository root**, with the virtualenv active and the
Trading212 environment variables exported — `python -m scripts.scan_market`
(not `python scripts/scan_market.py`; the `-m` form is what puts the repo
root on `sys.path` so `import stock_advisor` resolves). Neither script
takes command-line flags; they read `config/config.yaml` and the
environment, and print one JSON document to stdout.

## The dashboard

Every run — on-demand or scheduled — publishes to the **same** Artifact
link, updated in place, rather than creating a new one each time. The
template lives at `stock_advisor/reporting/dashboard_template.html`; its
URL (once it exists) is recorded locally at `.state/dashboard_url.txt` via
`stock_advisor/reporting/dashboard_state.py` so the next run knows to
update that artifact instead of publishing a separate one. The template
and the state-reading code are committed like everything else; only the
recorded URL itself isn't — `.state/` is gitignored, since that URL is
specific to your own published copy, not something to check into source
control.

The dashboard itself has an "ask about this report" panel (an Artifact
`sample`-capability chat box) that answers questions grounded in that
run's data — "why is X flagged," "compare these two," that kind of thing.
It can't trigger a new scan or touch your real account; that still goes
through Claude in a normal conversation, since only that has the
credentials and tool access the dashboard's browser-side panel doesn't.

## Scheduling the twice-daily run

The spec calls for at least two automatic runs a day, implemented as a
scheduled Claude Code agent routine rather than a bare cron script, so the
scheduled session gets full tool access (including web search/fetch) and
runs the skill exactly as an on-demand invocation would. Set this up with
the `schedule` skill (`/schedule` or ask Claude to "schedule my stock
advisor to run twice a day") — the exact times are up to you; morning and
evening around market hours is a reasonable starting point.

## Adding another broker or market-data provider

Both integrations sit behind an abstract interface, so adding a new one is
one new module, not a rewrite:

- **Broker:** implement `BrokerProvider` from
  `stock_advisor/providers/broker/base.py` (`get_account_summary`,
  `get_positions`, `get_instruments`). `trading212.py` is the reference
  implementation; `fake.py` is the test double.
- **Market data:** implement `MarketDataProvider` from
  `stock_advisor/providers/market_data/base.py` (`get_price_history`,
  `get_fundamentals`, `get_company_profile`). `yfinance_provider.py` is the
  reference implementation; `fake.py` is the test double.

Wire the new provider name into `VALID_BROKERS` /
`VALID_MARKET_DATA_PROVIDERS` in `stock_advisor/config.py`, add one dispatch
line to `build_broker` / `build_market_data` in
`stock_advisor/providers/factory.py`, and select it via `broker_provider` /
`market_data_provider` in `config/config.yaml`. Both scripts build their
providers through those factories, so nothing else in the pipeline
(technical signals, halal screen, universe matching, reporting schema, the
scripts themselves) needs to change.

Note that `data/universe/*.json` ships in the **default market-data
provider's symbol format** (yfinance: `HSBA.L`, `BRK-B`) — see
`data/universe/SOURCES.md`. A provider with a different symbol convention
needs those files translated, or a translation step in the new provider.

## Known limitations

**The halal screen checks three of four ratios, not four.** The
non-permissible-income ratio (interest and other impermissible income over
revenue) has no reliable free data source — no free provider publishes that
figure, since it is a Shariah-specific aggregation. Rather than let that
permanent gap force every single ticker to "insufficient data" forever
(which would make the report's Halal-Compliant section permanently empty),
the screen computes its verdict from the sector exclusions plus the three
ratios it *can* compute, and attaches an explicit caveat to **every**
verdict saying the fourth was not checked. A "compliant" verdict from this
tool therefore means "passed the sector screen and the three computable
ratios", not "AAOIFI compliant". See
`stock_advisor/analysis/halal_screen.py`'s module docstring and
`config/halal_exclusions.yaml`.

**yfinance fails silently on an unresolvable ticker.** It doesn't raise a
catchable error for a ticker it can't resolve — unlike the
`FakeMarketDataProvider` used in tests, an unmapped or invalid ticker can
come back with hollow/empty fields rather than an exception. If a report
shows a ticker with unusually sparse technical/fundamentals data, that can
be a data-fetch problem rather than genuinely "insufficient data" — worth a
second look rather than taking it at face value. (This is why
`data/universe/*.json` ships in yfinance's exact symbol format and why every
symbol in it was verified to resolve.)

**Coverage loss is reported, not hidden.** A ticker can drop out of a scan
three ways, and the scan output names each one: `unmatched` (the broker
doesn't offer it as a tradable stock), `no_market_data_tickers` (the
provider has no entry for it), and `failed_tickers` (its fetch raised —
typically rate limiting). A large `failed_tickers` list means the run was
throttled and is worth re-running, not that those companies have no data.

## Running the tests

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v
```

Tests run entirely against `FakeBrokerProvider` / `FakeMarketDataProvider`
— no network access or real credentials required.
