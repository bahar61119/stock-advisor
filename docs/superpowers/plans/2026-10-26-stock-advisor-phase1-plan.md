# Stock Advisor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, installable Claude Skill (`stock-advisor`) that, on demand or on a twice-daily schedule, reads the user's real Trading212 Stocks ISA holdings and broadly scans the market for new candidates, scoring both with transparent technical signals and an in-house halal/Shariah screen, then has Claude layer its own qualitative research on top to produce a report — with no order placement anywhere in this phase.

**Architecture:** A small Python package (`stock_advisor/`) provides two pluggable provider interfaces — `BrokerProvider` (Trading212 first, calling its REST API directly per the conventions documented by the `trading212-labs/agent-skills` instruction-skill) and `MarketDataProvider` (yfinance first) — plus pure-computation modules for technical signals and the halal screen. Two CLI scripts (`scan_market.py`, `review_portfolio.py`) orchestrate these into structured JSON. `SKILL.md` is the Claude-facing layer: it runs those scripts, does the live qualitative research (web search/fetch) the scripts can't do, and assembles the final Markdown report under the rules fixed by the spec (soft-flag halal interaction, directional-only recommendations, both compliant and non-compliant results shown).

**Tech Stack:** Python 3.11+, `requests` (Trading212 HTTP calls), `yfinance` (market data), `pyyaml` (config), `pytest` + `requests-mock` (tests). No Node dependency is needed in our own code — the `trading212-labs/agent-skills` plugin is an instruction-only skill (no library to call), so its conventions are followed directly in `trading212.py` rather than wrapped.

**Spec:** `docs/superpowers/specs/2026-10-26-stock-advisor-design.md`

## Global Constraints

- Python 3.11+.
- No code path may call a Trading212 order-placement endpoint (`/equity/orders/*`) — this phase is read-only against the broker. Only `/equity/account/summary`, `/equity/positions`, and `/equity/metadata/instruments` may be called.
- Index funds and ETFs are never included as candidates, regardless of halal status (spec: Non-goals).
- A candidate or holding whose halal screen status is `non_compliant` or `insufficient_data` must never have `"add_more"` in its allowed recommendations (spec: "soft flag" decision).
- Non-compliant and insufficient-data results are always included in output, clearly labeled with the underlying numbers — never silently dropped (spec: Anti-goals).
- No recommendation includes a dollar amount, share count, or position-sizing figure (spec: "Sizing scope: directional only" decision). Allowed recommendation values are exactly: `hold`, `trim`, `add_more`, `avoid`.
- AAOIFI-style thresholds (spec, "What's left to the builder," adopted as-is): debt-to-market-cap < 0.33; cash + interest-bearing securities to market-cap < 0.33; receivables + cash to market-cap < 0.33; non-permissible income / total revenue < 0.05.
- Technical indicator defaults (this plan's call, documented here so every task uses the same numbers): SMA windows 50 and 200 days; RSI window 14 days; MACD fast/slow/signal = 12/26/9; volume trend compares the most recent 20-trading-day average volume to the preceding 20-trading-day average volume.
- Every provider implementation satisfies its ABC in full — no partial implementations.
- Credentials (`T212_API_KEY*`, `T212_API_SECRET*`) are only ever read from environment variables, never written to logs, config files, or test fixtures.

## Review Focus

- A halal-non-compliant stock with a strong bullish technical signal, currently held in the ISA — must never surface `add_more` in its allowed recommendations, under any combination of inputs. (Task 9)
- A ticker with some but not all fundamentals fields available (e.g. debt known, revenue breakdown missing) — the halal screen must report `insufficient_data` naming the specific missing ratio(s), not silently treat the unknown ratio as passing or fail the whole screen on a guess. (Task 6)
- An ETF or index fund appearing anywhere in a bundled universe list or in Trading212's instrument metadata — must be filtered out of scan results entirely, not merely flagged. (Task 7)
- A currently-held position whose ticker cannot be matched to any market-data/universe entry (mapping failure) — must still appear in the portfolio report using the broker's own data, with technical/halal fields marked unavailable, not dropped from the report. (Task 9)
- The same ticker appearing in more than one bundled universe source list (e.g. both an S&P 500 and a NASDAQ-100 list) — must be deduplicated before analysis, not scored or reported twice. (Task 7)

---

## File Structure

```
stock-advisor/
├── SKILL.md
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config/
│   ├── config.yaml
│   └── halal_exclusions.yaml
├── data/
│   └── universe/
│       ├── sp500.json
│       ├── nasdaq100.json
│       └── ftse100.json
├── stock_advisor/
│   ├── __init__.py
│   ├── config.py
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── broker/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── fake.py
│   │   │   └── trading212.py
│   │   └── market_data/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── fake.py
│   │       └── yfinance_provider.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── technical.py
│   │   ├── halal_screen.py
│   │   └── universe.py
│   └── reporting/
│       ├── __init__.py
│       └── schema.py
├── scripts/
│   ├── scan_market.py
│   └── review_portfolio.py
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_broker_provider_contract.py
│   ├── test_trading212_provider.py
│   ├── test_market_data_provider_contract.py
│   ├── test_yfinance_provider.py
│   ├── test_technical.py
│   ├── test_halal_screen.py
│   ├── test_universe.py
│   ├── test_scan_market.py
│   └── test_review_portfolio.py
└── docs/superpowers/{specs,plans}/
```

---

### Task 1: Project scaffolding and config system

**Files:**
- Create: `requirements.txt`, `.gitignore`, `.env.example`, `config/config.yaml`
- Create: `stock_advisor/__init__.py`, `stock_advisor/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `load_config(path: str | None = None) -> AppConfig`, where `AppConfig` is a frozen dataclass with fields: `broker_provider: str`, `market_data_provider: str`, `shortlist_size: int`, `halal_thresholds: HalalThresholds` (`debt_to_market_cap: float`, `cash_and_interest_to_market_cap: float`, `receivables_and_cash_to_market_cap: float`, `non_permissible_income_ratio: float`), `universe_sources: list[str]`, `instrument_cache_path: str`, `instrument_cache_max_age_seconds: int`. Raises `ValueError` on an unknown `broker_provider`/`market_data_provider` name or a missing required key.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_config_defaults(tmp_path):
    cfg = load_config("config/config.yaml")
    assert cfg.broker_provider == "trading212"
    assert cfg.market_data_provider == "yfinance"
    assert cfg.shortlist_size == 20
    assert cfg.halal_thresholds.debt_to_market_cap == 0.33
    assert cfg.halal_thresholds.non_permissible_income_ratio == 0.05

def test_load_config_rejects_unknown_broker(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("broker_provider: not_a_real_broker\nmarket_data_provider: yfinance\n")
    with pytest.raises(ValueError):
        load_config(str(bad))

def test_load_config_rejects_missing_key(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("broker_provider: trading212\n")
    with pytest.raises(ValueError):
        load_config(str(bad))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`load_config` not defined / `config/config.yaml` not present)

- [ ] **Step 3: Write `config/config.yaml` with the real defaults**

Exact values: `broker_provider: trading212`, `market_data_provider: yfinance`, `shortlist_size: 20`, `universe_sources: [sp500, nasdaq100, ftse100]`, `instrument_cache_path: .cache/t212_instruments.json`, `instrument_cache_max_age_seconds: 3600`, and a `halal_thresholds` block with the four values from Global Constraints.

- [ ] **Step 4: Implement `load_config` and the dataclasses in `stock_advisor/config.py`**

Valid broker names: `{"trading212"}`. Valid market-data names: `{"yfinance"}` (single-entry sets now, so adding a provider later is extending this set plus one new module, per spec).

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Write `requirements.txt`, `.env.example`, and extend the existing `.gitignore`**

`requirements.txt`: `requests`, `pyyaml`, `yfinance`, `pandas`, `numpy`, and dev extras `pytest`, `requests-mock`. The repo root already has a `.gitignore` (containing `.worktrees/`) — append to it rather than overwrite: add `.env`, `.cache/`, `__pycache__/`, `*.pyc`. `.env.example` documents `T212_API_KEY`, `T212_API_SECRET`, `T212_ENV` (and the `_STOCKS_ISA` suffixed alternative) with placeholder values and comments, matching the trading212-api skill's convention.

- [ ] **Step 7: Commit**

The git repo and this task's working branch already exist — do not run `git init`.

```bash
git add -A
git commit -m "chore: scaffold project and config system"
```

---

### Task 2: Broker provider interface and fake implementation

**Files:**
- Create: `stock_advisor/providers/broker/base.py`
- Create: `stock_advisor/providers/broker/fake.py`
- Test: `tests/test_broker_provider_contract.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: ABC `BrokerProvider` with methods `get_account_summary() -> AccountSummary` and `get_positions() -> list[Position]` and `get_instruments() -> list[Instrument]`. Dataclasses: `AccountSummary(currency: str, total_value: float, cash_available: float, cash_reserved: float, cash_in_pies: float, investments_current_value: float, investments_total_cost: float, realized_pl: float, unrealized_pl: float)`; `Position(ticker: str, name: str, isin: str, currency: str, quantity: float, quantity_available: float, current_price: float, average_price_paid: float, wallet_currency: str, wallet_current_value: float, wallet_total_cost: float, wallet_unrealized_pl: float)`; `Instrument(ticker: str, name: str, short_name: str, isin: str, currency_code: str, type: str)`. `FakeBrokerProvider(accounts: AccountSummary, positions: list[Position], instruments: list[Instrument])` returns exactly what it was constructed with — used by later tasks' tests and by `review_portfolio.py` runs without real credentials.

- [ ] **Step 1: Write the failing contract test**

```python
@pytest.mark.parametrize("provider_factory", [make_fake_broker_provider])
def test_broker_provider_contract(provider_factory):
    provider = provider_factory()
    summary = provider.get_account_summary()
    assert isinstance(summary, AccountSummary)
    positions = provider.get_positions()
    assert all(isinstance(p, Position) for p in positions)
    instruments = provider.get_instruments()
    assert all(isinstance(i, Instrument) for i in instruments)
```

(`make_fake_broker_provider` is a `tests/conftest.py` fixture factory building a `FakeBrokerProvider` with one canned position, one canned instrument, and a canned summary.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_broker_provider_contract.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `base.py` and `fake.py`**

`FakeBrokerProvider` stores its constructor arguments and returns them unmodified from each method — no logic beyond that.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_broker_provider_contract.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stock_advisor/providers/broker tests/test_broker_provider_contract.py tests/conftest.py
git commit -m "feat: add BrokerProvider interface and fake implementation"
```

---

### Task 3: Trading212 broker provider

**Files:**
- Create: `stock_advisor/providers/broker/trading212.py`
- Test: `tests/test_trading212_provider.py`

**Interfaces:**
- Consumes: `BrokerProvider`, `AccountSummary`, `Position`, `Instrument` from Task 2.
- Produces: `Trading212BrokerProvider(env: str = "live")` implementing `BrokerProvider` by calling `https://{env}.trading212.com/api/v0/equity/account/summary`, `.../equity/positions`, and `.../equity/metadata/instruments` with `requests`, using HTTP Basic auth built from environment variables.

- [ ] **Step 1: Write the failing tests**

```python
def test_auth_header_from_plain_pair(monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "key123")
    monkeypatch.setenv("T212_API_SECRET", "secret456")
    provider = Trading212BrokerProvider(env="demo")
    assert provider._auth_header() == "Basic " + base64.b64encode(b"key123:secret456").decode()

def test_auth_header_prefers_stocks_isa_pair_when_present(monkeypatch):
    monkeypatch.setenv("T212_API_KEY_STOCKS_ISA", "isakey")
    monkeypatch.setenv("T212_API_SECRET_STOCKS_ISA", "isasecret")
    provider = Trading212BrokerProvider(env="live")
    assert provider._auth_header() == "Basic " + base64.b64encode(b"isakey:isasecret").decode()

def test_get_account_summary_maps_fields(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/account/summary",
        json={"currency": "GBP", "totalValue": 15250.75,
              "cash": {"availableToTrade": 2500.5, "reservedForOrders": 150.0, "inPies": 500.0},
              "investments": {"currentValue": 12100.25, "totalCost": 10500.0,
                               "realizedProfitLoss": 850.5, "unrealizedProfitLoss": 1600.25}},
    )
    summary = Trading212BrokerProvider(env="demo").get_account_summary()
    assert summary.currency == "GBP"
    assert summary.cash_available == 2500.5
    assert summary.unrealized_pl == 1600.25

def test_get_positions_maps_fields(requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/positions",
        json=[{"instrument": {"ticker": "AAPL_US_EQ", "name": "Apple Inc",
                               "isin": "US0378331005", "currency": "USD"},
               "quantity": 15.5, "quantityAvailableForTrading": 12.5,
               "currentPrice": 185.5, "averagePricePaid": 170.25,
               "walletImpact": {"currency": "GBP", "totalCost": 2089.45,
                                 "currentValue": 2275.1, "unrealizedProfitLoss": 185.65}}],
    )
    positions = Trading212BrokerProvider(env="demo").get_positions()
    assert positions[0].ticker == "AAPL_US_EQ"
    assert positions[0].wallet_unrealized_pl == 185.65

def test_get_instruments_uses_cache_when_fresh(tmp_path, requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text('[{"ticker": "AAPL_US_EQ", "name": "Apple Inc", "shortName": "AAPL", "isin": "US0378331005", "currencyCode": "USD", "type": "STOCK"}]')
    provider = Trading212BrokerProvider(env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600)
    instruments = provider.get_instruments()
    assert instruments[0].short_name == "AAPL"
    assert requests_mock.call_count == 0  # cache hit, no HTTP call

def test_get_instruments_refetches_when_cache_stale(tmp_path, requests_mock, monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "k")
    monkeypatch.setenv("T212_API_SECRET", "s")
    cache_file = tmp_path / "instruments.json"
    cache_file.write_text("[]")
    old_time = time.time() - 7200
    os.utime(cache_file, (old_time, old_time))
    requests_mock.get(
        "https://demo.trading212.com/api/v0/equity/metadata/instruments",
        json=[{"ticker": "MSFT_US_EQ", "name": "Microsoft", "shortName": "MSFT", "isin": "US5949181045", "currencyCode": "USD", "type": "STOCK"}],
    )
    provider = Trading212BrokerProvider(env="demo", instrument_cache_path=str(cache_file), cache_max_age_seconds=3600)
    instruments = provider.get_instruments()
    assert instruments[0].short_name == "MSFT"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_trading212_provider.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `Trading212BrokerProvider` in `stock_advisor/providers/broker/trading212.py`**

Auth resolution order (matches the trading212-api skill's documented precedence): if `T212_API_KEY_STOCKS_ISA`/`T212_API_SECRET_STOCKS_ISA` are both set, use that pair; else if `T212_API_KEY`/`T212_API_SECRET` are both set, use that pair; else raise `RuntimeError` naming the missing env vars. Base URL is `https://{env}.trading212.com`. `get_instruments()` reads the JSON cache file if it exists and its mtime is newer than `cache_max_age_seconds` ago; otherwise it calls the API and overwrites the cache file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_trading212_provider.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stock_advisor/providers/broker/trading212.py tests/test_trading212_provider.py
git commit -m "feat: implement Trading212 broker provider"
```

---

### Task 4: Market data provider interface and yfinance implementation

**Files:**
- Create: `stock_advisor/providers/market_data/base.py`
- Create: `stock_advisor/providers/market_data/fake.py`
- Create: `stock_advisor/providers/market_data/yfinance_provider.py`
- Test: `tests/test_market_data_provider_contract.py`, `tests/test_yfinance_provider.py`

**Interfaces:**
- Produces: ABC `MarketDataProvider` with `get_price_history(ticker: str, period: str = "1y") -> PriceSeries`, `get_fundamentals(ticker: str) -> Fundamentals`, `get_company_profile(ticker: str) -> CompanyProfile`. `PriceSeries(dates: list[date], close: list[float], volume: list[float])`. `Fundamentals(total_debt: float | None, total_cash: float | None, market_cap: float | None, total_revenue: float | None, non_permissible_income: float | None, receivables: float | None)` — every field `None` when the provider cannot determine it, never a guessed value. `CompanyProfile(sector: str | None, industry: str | None, business_summary: str | None)`. `FakeMarketDataProvider(prices: dict[str, PriceSeries], fundamentals: dict[str, Fundamentals], profiles: dict[str, CompanyProfile])` returns canned data by ticker.

- [ ] **Step 1: Write the failing contract test**

```python
@pytest.mark.parametrize("provider_factory", [make_fake_market_data_provider])
def test_market_data_provider_contract(provider_factory):
    provider = provider_factory()
    assert isinstance(provider.get_price_history("AAPL"), PriceSeries)
    assert isinstance(provider.get_fundamentals("AAPL"), Fundamentals)
    assert isinstance(provider.get_company_profile("AAPL"), CompanyProfile)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_market_data_provider_contract.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `base.py` and `fake.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_market_data_provider_contract.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing yfinance tests (monkeypatching `yfinance.Ticker`)**

```python
def test_get_fundamentals_handles_missing_fields(monkeypatch):
    fake_ticker = make_fake_yf_ticker(info={"totalDebt": 1_000_000, "marketCap": 50_000_000})
    # no "totalRevenue" / "totalCash" keys present
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    fundamentals = YFinanceProvider().get_fundamentals("AAPL")
    assert fundamentals.total_debt == 1_000_000
    assert fundamentals.market_cap == 50_000_000
    assert fundamentals.total_cash is None
    assert fundamentals.total_revenue is None

def test_get_price_history_parses_history(monkeypatch):
    fake_ticker = make_fake_yf_ticker(history_df=sample_ohlcv_dataframe())
    monkeypatch.setattr("yfinance.Ticker", lambda t: fake_ticker)
    series = YFinanceProvider().get_price_history("AAPL", period="1y")
    assert len(series.close) == len(sample_ohlcv_dataframe())
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/test_yfinance_provider.py -v`
Expected: FAIL

- [ ] **Step 7: Implement `YFinanceProvider` in `yfinance_provider.py`**

Reads `yfinance.Ticker(ticker).info` for fundamentals/profile fields (`totalDebt`, `totalCash`, `marketCap`, `totalRevenue`, `sector`, `industry`, `longBusinessSummary`) and `.history(period=period)` for price series, using `.get(key)` (never `[key]`) so a missing field becomes `None` rather than raising. `non_permissible_income` has no direct yfinance field — leave it `None` always in this provider (documented in a docstring as a known gap: the halal screen must treat it as `insufficient_data` for that one ratio when using this provider, which Task 6's logic already does for any `None` field).

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_yfinance_provider.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add stock_advisor/providers/market_data tests/test_market_data_provider_contract.py tests/test_yfinance_provider.py
git commit -m "feat: add MarketDataProvider interface, fake, and yfinance implementation"
```

---

### Task 5: Technical signal module

**Files:**
- Create: `stock_advisor/analysis/technical.py`
- Test: `tests/test_technical.py`

**Interfaces:**
- Consumes: `PriceSeries` from Task 4.
- Produces: `TechnicalSignal(sma_50: float | None, sma_200: float | None, rsi_14: float | None, macd_line: float | None, macd_signal_line: float | None, volume_trend: Literal["rising","flat","falling"] | None, verdict: Literal["bullish","neutral","bearish"])` and `compute_technical_signal(series: PriceSeries) -> TechnicalSignal`. Any component is `None` when `series` has fewer data points than that component's window (e.g. fewer than 200 closes means `sma_200` is `None`); `verdict` falls back to `"neutral"` when fewer than two of the four inputs it needs are available.

- [ ] **Step 1: Write the failing tests**

```python
def test_sma_matches_hand_computed_average():
    series = make_price_series(closes=[10, 20, 30, 40, 50])
    assert compute_sma(series.close, window=5) == 30.0

def test_rsi_all_gains_is_100():
    series = make_price_series(closes=list(range(1, 20)))  # strictly rising
    assert compute_rsi(series.close, window=14) == pytest.approx(100.0)

def test_macd_known_values():
    # Linear price series + small fast/slow/signal windows (not the 50/200/12-26-9
    # production defaults — this test is of the generic compute_macd function,
    # same as test_sma_matches_hand_computed_average uses window=5, not 50/200).
    # Hand-verified: with closes rising by 1 each step, EMA(fast=2) - EMA(slow=4)
    # stabilizes at exactly 1.0 from the first point both EMAs are defined, and
    # the signal line (an EMA of a constant 1.0 series) is also exactly 1.0.
    series = make_price_series(closes=[10, 11, 12, 13, 14, 15, 16])
    line, signal = compute_macd(series.close, fast=2, slow=4, signal=2)
    assert line == pytest.approx(1.0, abs=0.001)
    assert signal == pytest.approx(1.0, abs=0.001)

def test_volume_trend_rising_when_recent_higher():
    volumes = [100] * 20 + [300] * 20
    assert compute_volume_trend(volumes, window=20) == "rising"

def test_composite_verdict_bullish_when_three_signals_align():
    signal = TechnicalSignal(sma_50=110, sma_200=100, rsi_14=55,
                              macd_line=1.0, macd_signal_line=0.5,
                              volume_trend="rising", verdict=None)
    assert classify_verdict(signal) == "bullish"

def test_composite_verdict_neutral_when_mixed():
    signal = TechnicalSignal(sma_50=100, sma_200=110, rsi_14=55,
                              macd_line=1.0, macd_signal_line=0.5,
                              volume_trend="flat", verdict=None)
    assert classify_verdict(signal) == "neutral"

def test_sma_200_none_with_insufficient_history():
    series = make_price_series(closes=[1.0] * 50)
    result = compute_technical_signal(series)
    assert result.sma_200 is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_technical.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `technical.py`**

`compute_macd`'s EMA seeding (fixes the `test_macd_known_values` result, which depends on this): the first EMA value for each span is the simple average of that span's first `window` prices (not the first price alone); every subsequent value is the standard recursive EMA update `price * k + prev_ema * (1-k)` with `k = 2/(window+1)`. The signal line is the same EMA recursion applied to the series of MACD-line values, seeded the same way once `signal` MACD-line values exist.

`classify_verdict` approach (fixed by this plan, since the signature doesn't determine it): count bullish points — `sma_50 > sma_200`, `macd_line > macd_signal_line`, `30 < rsi_14 < 70`, `volume_trend == "rising"` — and bearish points — the mirror conditions (`sma_50 < sma_200`, `macd_line < macd_signal_line`, `rsi_14 >= 70 or rsi_14 <= 30`, `volume_trend == "falling"`), each skipped if its inputs are `None`. Verdict is `"bullish"` if bullish points `>= 3`, `"bearish"` if bearish points `>= 3`, else `"neutral"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_technical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stock_advisor/analysis/technical.py tests/test_technical.py
git commit -m "feat: add rules-based technical signal module"
```

---

### Task 6: Halal screen module

**Files:**
- Create: `stock_advisor/analysis/halal_screen.py`
- Create: `config/halal_exclusions.yaml`
- Test: `tests/test_halal_screen.py`

**Interfaces:**
- Consumes: `Fundamentals`, `CompanyProfile` from Task 4; `HalalThresholds` from Task 1.
- Produces: `HalalRatios(debt_to_market_cap: float | None, cash_and_interest_to_market_cap: float | None, receivables_and_cash_to_market_cap: float | None, non_permissible_income_ratio: float | None)`; `HalalVerdict(status: Literal["compliant","non_compliant","insufficient_data"], failed_checks: list[str], missing_fields: list[str], ratios: HalalRatios)`; `screen(profile: CompanyProfile, fundamentals: Fundamentals, thresholds: HalalThresholds, exclusions: list[str]) -> HalalVerdict`.

- [ ] **Step 1: Write the failing tests**

```python
def test_sector_exclusion_matches_case_insensitive():
    profile = CompanyProfile(sector="Financial Services", industry="Banks—Diversified", business_summary=None)
    verdict = screen(profile, full_fundamentals(), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert "sector" in verdict.failed_checks[0]

def test_ratio_just_under_threshold_passes():
    fundamentals = make_fundamentals(total_debt=32, market_cap=100, total_cash=0, total_revenue=100, non_permissible_income=0, receivables=0)
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"

def test_ratio_at_threshold_fails():
    fundamentals = make_fundamentals(total_debt=33, market_cap=100, total_cash=0, total_revenue=100, non_permissible_income=0, receivables=0)
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "non_compliant"
    assert "debt_to_market_cap" in verdict.failed_checks

def test_missing_single_field_is_insufficient_data_not_pass_or_fail():
    fundamentals = make_fundamentals(total_debt=5, market_cap=100, total_cash=None, total_revenue=100, non_permissible_income=0, receivables=0)
    verdict = screen(clean_profile(), fundamentals, DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "insufficient_data"
    assert "cash_and_interest_to_market_cap" in verdict.missing_fields

def test_all_pass_is_compliant():
    verdict = screen(clean_profile(), full_fundamentals(all_low=True), DEFAULT_THRESHOLDS, EXCLUSIONS)
    assert verdict.status == "compliant"
    assert verdict.failed_checks == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_halal_screen.py -v`
Expected: FAIL

- [ ] **Step 3: Write `config/halal_exclusions.yaml`**

A documented, flat list of sector/industry/business-summary keywords, case-insensitive substring matched: conventional banking, conventional insurance, interest-based lending, alcohol, tobacco, gambling, casinos, adult entertainment, pork products, conventional weapons/arms manufacturing. One entry per line, with a comment above the file explaining it is editable and not exhaustive.

- [ ] **Step 4: Implement `halal_screen.py`**

`screen()` checks sector exclusion first (against `profile.sector`, `profile.industry`, `profile.business_summary`, case-insensitive substring match on any exclusion keyword) → `non_compliant` immediately if matched, with `failed_checks=["sector: <matched keyword>"]`. Otherwise computes each of the four ratios only when its required `Fundamentals` fields are not `None`; any ratio whose inputs are missing is omitted from `ratios` (left `None`) and its name added to `missing_fields`. If `missing_fields` is non-empty, `status = "insufficient_data"`. Else if any computed ratio is `>=` its threshold, `status = "non_compliant"` with each failing ratio's name in `failed_checks`. Else `status = "compliant"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_halal_screen.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add stock_advisor/analysis/halal_screen.py config/halal_exclusions.yaml tests/test_halal_screen.py
git commit -m "feat: add in-house AAOIFI-style halal screen"
```

---

### Task 7: Scan universe builder

**Files:**
- Create: `stock_advisor/analysis/universe.py`
- Create: `data/universe/sp500.json`, `data/universe/nasdaq100.json`, `data/universe/ftse100.json`
- Test: `tests/test_universe.py`

**Interfaces:**
- Consumes: `Instrument` from Task 2.
- Produces: `load_universe(sources: list[str], data_dir: str = "data/universe") -> list[str]` (deduplicated plain tickers, order-preserving by first appearance); `match_broker_tradable(universe: list[str], instruments: list[Instrument]) -> UniverseMatchResult` where `UniverseMatchResult(matched: list[tuple[str, str]], unmatched: list[str])` — `matched` pairs are `(universe_ticker, broker_ticker)`, matched by case-insensitive equality between the universe ticker and `Instrument.short_name`; instruments whose `type` is not `"STOCK"` (e.g. `"ETF"`) are never included in `matched`, even if a universe ticker happens to equal their short name.

- [ ] **Step 1: Write the failing tests**

```python
def test_load_universe_dedupes_across_sources(tmp_path):
    write_universe_file(tmp_path / "a.json", ["AAPL", "MSFT"])
    write_universe_file(tmp_path / "b.json", ["MSFT", "GOOGL"])
    tickers = load_universe(["a", "b"], data_dir=str(tmp_path))
    assert tickers == ["AAPL", "MSFT", "GOOGL"]

def test_match_broker_tradable_matches_case_insensitive():
    instruments = [Instrument(ticker="AAPL_US_EQ", name="Apple Inc", short_name="AAPL", isin="US0378331005", currency_code="USD", type="STOCK")]
    result = match_broker_tradable(["aapl"], instruments)
    assert result.matched == [("aapl", "AAPL_US_EQ")]
    assert result.unmatched == []

def test_match_broker_tradable_excludes_etfs():
    instruments = [Instrument(ticker="SPY_US_EQ", name="SPDR S&P 500 ETF", short_name="SPY", isin="US78462F1030", currency_code="USD", type="ETF")]
    result = match_broker_tradable(["SPY"], instruments)
    assert result.matched == []
    assert result.unmatched == ["SPY"]

def test_match_broker_tradable_reports_unmatched_without_failing():
    result = match_broker_tradable(["NOTREAL"], [])
    assert result.unmatched == ["NOTREAL"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_universe.py -v`
Expected: FAIL

- [ ] **Step 3: Build the bundled universe data files**

Populate `data/universe/sp500.json`, `nasdaq100.json`, `ftse100.json`, each a flat JSON array of plain ticker strings (e.g. `["AAPL", "MSFT", ...]`), sourced once from a stable public reference (e.g. Wikipedia's "List of S&P 500 companies" / "Nasdaq-100" / "FTSE 100 Index" pages) at implementation time. Document the source and retrieval date in a comment file `data/universe/SOURCES.md` alongside them, since these lists go stale and will need periodic manual refresh — no code in this phase fetches them live.

- [ ] **Step 4: Implement `universe.py`**

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_universe.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add stock_advisor/analysis/universe.py data/universe tests/test_universe.py
git commit -m "feat: add scan universe loader and broker-tradable matching"
```

---

### Task 8: `scripts/scan_market.py`

**Files:**
- Create: `scripts/scan_market.py`
- Create: `stock_advisor/reporting/schema.py`
- Test: `tests/test_scan_market.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `MarketDataProvider`/`FakeMarketDataProvider` (Task 4), `compute_technical_signal` (Task 5), `screen` (Task 6), `load_universe`/`match_broker_tradable` (Task 7).
- Produces: `CandidateResult(ticker: str, broker_ticker: str | None, technical: TechnicalSignal, halal: HalalVerdict, allowed_recommendations: list[str])` in `stock_advisor/reporting/schema.py` (shared with Task 9); `run_scan(config: AppConfig, market_data: MarketDataProvider, universe: list[str], instruments: list[Instrument]) -> ScanOutput` where `ScanOutput(all_results: list[CandidateResult], shortlist: list[CandidateResult])`; a `main()` that wires real providers from config and prints `json.dumps(dataclasses.asdict(scan_output))` to stdout.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_scan_includes_non_compliant_results_in_all_results():
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()])
    assert any(r.ticker == "AAPL" and r.halal.status == "non_compliant" for r in output.all_results)

def test_run_scan_shortlist_capped_at_configured_size():
    config = test_config(shortlist_size=2)
    market_data = make_fake_market_data_for(["A", "B", "C", "D"])
    output = run_scan(config, market_data, universe=["A", "B", "C", "D"], instruments=make_instruments(["A", "B", "C", "D"]))
    assert len(output.shortlist) == 2

def test_run_scan_excludes_etfs_from_universe():
    output = run_scan(test_config(), FakeMarketDataProvider({}, {}, {}), universe=["SPY"], instruments=[etf_instrument("SPY")])
    assert output.all_results == []

def test_allowed_recommendations_excludes_add_more_when_non_compliant():
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_scan(test_config(), market_data, universe=["AAPL"], instruments=[aapl_instrument()])
    result = output.all_results[0]
    assert "add_more" not in result.allowed_recommendations
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scan_market.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `schema.py` and `run_scan` in `scan_market.py`**

`allowed_recommendations`: `["hold", "trim", "add_more", "avoid"]` when `halal.status == "compliant"`; `["hold", "trim", "avoid"]` (no `add_more`) when `status` is `"non_compliant"` or `"insufficient_data"` (Global Constraints: treat unknown halal status conservatively, same as non-compliant, for this field only). `all_results` is built by filtering the matched (non-ETF) universe to those with a market-data entry, running technical + halal on each; `shortlist` is `all_results` sorted by `verdict == "bullish"` first then by name, truncated to `config.shortlist_size`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scan_market.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/scan_market.py stock_advisor/reporting/schema.py tests/test_scan_market.py
git commit -m "feat: add scan_market CLI script"
```

---

### Task 9: `scripts/review_portfolio.py`

**Files:**
- Create: `scripts/review_portfolio.py`
- Test: `tests/test_review_portfolio.py`

**Interfaces:**
- Consumes: `load_config` (Task 1), `BrokerProvider`/`FakeBrokerProvider` (Task 2), `MarketDataProvider` (Task 4), `compute_technical_signal` (Task 5), `screen` (Task 6), `CandidateResult`/`allowed_recommendations` logic (Task 8, reused not reimplemented).
- Produces: `HoldingResult(position: Position, candidate: CandidateResult | None)` (`candidate` is `None` when the holding's ticker cannot be matched to market data); `run_portfolio_review(config: AppConfig, broker: BrokerProvider, market_data: MarketDataProvider) -> PortfolioReviewOutput` where `PortfolioReviewOutput(account_summary: AccountSummary, holdings: list[HoldingResult])`; a `main()` wiring real providers and printing JSON to stdout.

- [ ] **Step 1: Write the failing tests**

```python
def test_held_non_compliant_position_excludes_add_more():
    broker = FakeBrokerProvider(accounts=test_account_summary(), positions=[aapl_position()], instruments=[aapl_instrument()])
    market_data = FakeMarketDataProvider(
        prices={"AAPL": bullish_price_series()},
        fundamentals={"AAPL": non_compliant_fundamentals()},
        profiles={"AAPL": clean_profile()},
    )
    output = run_portfolio_review(test_config(), broker, market_data)
    holding = output.holdings[0]
    assert holding.candidate.halal.status == "non_compliant"
    assert "add_more" not in holding.candidate.allowed_recommendations

def test_unmatched_holding_still_appears_with_candidate_none():
    broker = FakeBrokerProvider(accounts=test_account_summary(), positions=[position_with_ticker("ZZZZ_XX_EQ")], instruments=[])
    output = run_portfolio_review(test_config(), broker, FakeMarketDataProvider({}, {}, {}))
    assert len(output.holdings) == 1
    assert output.holdings[0].candidate is None

def test_account_summary_passed_through_unchanged():
    broker = FakeBrokerProvider(accounts=test_account_summary(), positions=[], instruments=[])
    output = run_portfolio_review(test_config(), broker, FakeMarketDataProvider({}, {}, {}))
    assert output.account_summary == test_account_summary()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_review_portfolio.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `review_portfolio.py`**

For each `Position`, find the `Instrument` whose `ticker` field exactly equals the position's `ticker` (both are Trading212-format identifiers, e.g. `AAPL_US_EQ` — this is a direct ticker-to-ticker match, distinct from Task 7's plain-ticker-to-`short_name` match). If found, use that instrument's `short_name` as the plain ticker for the market-data lookup. If no `Instrument` matches, or the matched `short_name` has no entry in the market-data provider, set `candidate = None` rather than raising or skipping the holding. Reuse Task 8's `allowed_recommendations` function (import it; do not reimplement the rule) when `candidate` is built.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_review_portfolio.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/review_portfolio.py tests/test_review_portfolio.py
git commit -m "feat: add review_portfolio CLI script"
```

---

### Task 10: SKILL.md, README, and end-to-end dry run

**Files:**
- Create: `SKILL.md`
- Create: `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–9 (invoked as subprocesses/CLI calls from the skill instructions, per their `main()` entry points).
- Produces: nothing new in code — this task's deliverable is the orchestration document itself and a manually-verified dry run.

- [ ] **Step 1: Write `SKILL.md`**

Frontmatter: `name: stock-advisor`, a `description` covering trigger phrases ("check my ISA", "suggest stocks", "review my portfolio", "find me stock ideas", scheduled-run invocation). Body instructs Claude to: (1) run `python scripts/review_portfolio.py` and `python scripts/scan_market.py`, read their JSON; (2) for every holding and every shortlisted candidate, research recent news/fundamentals context via web search/fetch and write a short rationale, tagging investment style (growth/dividend/value/sector-bet) and time horizon (6–12 months / 1 year+); (3) assemble the final Markdown report with required sections — "Your ISA Holdings" and "New Candidates" (split into "Halal-Compliant" and "Non-Compliant / Flagged" subsections) — each entry showing the technical values, the halal ratios (not just the verdict), the recommendation (restricted to that entry's `allowed_recommendations`), and the qualitative rationale; (4) include, verbatim near the top of every report, a disclaimer that this is a best-effort tool with no guaranteed returns and the halal screen is an automated heuristic, not a scholarly ruling; (5) never include a dollar amount, share count, or portfolio-sizing figure anywhere in the report (Global Constraints). State explicitly that this skill never calls a Trading212 order-placement endpoint.

- [ ] **Step 2: Write `README.md`**

Covers: what this project is and is not (read-only, Phase 1 only); install steps (`python -m venv`, `pip install -r requirements.txt`); generating a Trading212 Stocks ISA API key (Settings → API in the app) and populating `.env` from `.env.example`; running on demand; setting up the twice-daily scheduled routine (references the `schedule` skill, exact times left to the user); a short "how to add another broker or market-data provider" section pointing at `providers/broker/base.py` and `providers/market_data/base.py`.

- [ ] **Step 3: Manual dry run with fake providers**

Temporarily point `config/config.yaml` at no real credentials; run `python scripts/scan_market.py` and `python scripts/review_portfolio.py` against the `Fake*Provider`s with a small hand-built fixture universe (reuse test fixtures or a small ad hoc script) to confirm both scripts produce valid JSON end to end. Then, following `SKILL.md`'s own instructions, manually produce one sample Markdown report from that fixture JSON and check it against the Review Focus list and Global Constraints (no `add_more` on the non-compliant fixture, no sizing figures, disclaimer present, non-compliant results shown not hidden).

- [ ] **Step 4: Run the full test suite**

Run: `pytest -v`
Expected: PASS (every test from Tasks 1–9, no regressions)

- [ ] **Step 5: Commit**

```bash
git add SKILL.md README.md
git commit -m "docs: add SKILL.md orchestration and README"
```

---

## Self-Review Notes

- **Spec coverage:** broad scan (Tasks 7–8), ISA holdings review (Task 9), time-horizon tagging and qualitative reasoning (Task 10, since both require Claude's live judgment, not a script), halal screen with both compliant/non-compliant shown (Task 6, 8, 9), hybrid technical+qualitative evaluation (Tasks 5 + 10), provider abstraction for broker and market data (Tasks 2–4), Trading212 connector via its documented REST conventions (Task 3), on-demand + twice-daily delivery (Task 10's `SKILL.md`, cadence itself is a scheduling setup step outside this plan's code), soft-flag and directional-only-sizing rules (Task 8's `allowed_recommendations`, enforced again in Task 9, and restated in Task 10's report rules), honest disclaimers (Task 10). No index funds/ETFs (Task 7's type filter). All covered.
- **Type consistency:** `CandidateResult` and `allowed_recommendations` are defined once in Task 8 and imported (not redefined) by Task 9; `Position`/`Instrument`/`AccountSummary` defined once in Task 2 and reused throughout; `Fundamentals`/`CompanyProfile`/`PriceSeries` defined once in Task 4.
- **Review Focus:** all five items map to a specific task's tests, as listed above.
