# stock-advisor

A private Claude Skill that reviews a Trading212 Stocks ISA and scans the
market for long-term stock candidates (growth, dividend, value, sector
bets), screening every result for halal/Shariah compliance and tagging it
with a transparent technical signal and a time horizon. Claude layers its
own qualitative research (news, fundamentals, company context) on top of
the rules-based numbers before writing a Markdown report.

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
`VALID_MARKET_DATA_PROVIDERS` in `stock_advisor/config.py`, select it via
`broker_provider` / `market_data_provider` in `config/config.yaml`, and
instantiate it in `scripts/scan_market.py` / `scripts/review_portfolio.py`'s
`main()`. Nothing else in the pipeline (technical signals, halal screen,
universe matching, reporting schema) needs to change.

## Known limitation

`YFinanceProvider` doesn't raise a catchable error for a ticker it can't
actually resolve — unlike the `FakeMarketDataProvider` used in tests, an
unmapped or invalid ticker can come back from yfinance with hollow/empty
fields rather than an exception. If a report shows a ticker with unusually
sparse technical/fundamentals data, that can be a data-fetch problem rather
than genuinely "insufficient data" — worth a second look rather than taking
it at face value.

## Running the tests

```bash
source .venv/bin/activate
pytest -v
```

Tests run entirely against `FakeBrokerProvider` / `FakeMarketDataProvider`
— no network access or real credentials required.
