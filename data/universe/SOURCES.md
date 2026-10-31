# Universe data sources

These three files are flat JSON arrays of ticker strings, hand-refreshed from
a public reference at implementation time. **No code in this phase fetches
them live** — refreshing them (e.g. when index composition changes) is a
manual, periodic task: re-pull the source page, re-extract the ticker column,
**translate it to the symbol convention below**, and overwrite the file.

Retrieved: **2026-10-28**. Symbol convention applied: **2026-10-31**.

## Symbol convention: these files ship in yfinance format

The tickers stored here are **not** the bare index symbols the source pages
quote. They are already in the symbol format the configured market-data
provider (yfinance, per `market_data_provider` in `config/config.yaml`)
actually needs, because nothing in the pipeline translates them:

- **FTSE 100 tickers carry the `.L` exchange suffix** — `HSBA.L`, `BA.L`,
  `BARC.L`. Yahoo Finance disambiguates by exchange and a bare EPIC either
  resolves to a different company or to nothing at all.
- **London EPICs with an embedded dot use a hyphen** — BT Group's EPIC is
  `BT.A`, and yfinance spells it `BT-A.L`.
- **US dual-class tickers use a hyphen, not a dot** — `BRK-B` and `BF-B`,
  not `BRK.B` / `BF.B`.

### Why this is stored rather than translated at call time

Two reasons, both about silent failure:

1. **yfinance does not error on an unresolvable symbol.** `Ticker("BRK.B")`
   returns an `.info` dict with no `marketCap`, and `Ticker("HSBA")` resolves
   to an unrelated listing. Either way the scan produces a plausible-looking
   result for the wrong (or no) company instead of raising.
2. **`load_universe`'s dedup needs the symbols to be distinct.** Five
   symbols are *both* a US ticker and a different company's London EPIC:
   `ADM` (Archer-Daniels-Midland / Admiral Group), `BA` (Boeing / BAE
   Systems), `BBY` (Best Buy / Bytes Technology), `PRU` (Prudential
   Financial / Prudential plc) and `TSCO` (Tractor Supply / Tesco). As bare
   strings, the union of the three files collapsed each pair into one entry
   and the London company disappeared from the scan entirely, with nothing
   reporting the loss. Suffixed, they are distinct strings and both survive.

### Verification

Every symbol in all three files was checked against live yfinance on
2026-10-31 (`yfinance.download(...)` over each file's full list, confirming
a non-empty price series): 518 distinct US symbols and 100 FTSE symbols, all
resolving. Spot-checked individually via `.info`, including the awkward
ones: `BRK-B`, `BF-B`, `BT-A.L`, `BA.L`, `NG.L`, `UU.L`, `SN.L`, `RR.L`,
`AV.L`, `III.L`, `HSBA.L`, `SPX.L`, `ITH.L`, `MTLN.L`. For contrast,
`BRK.B` returned an empty `.info` rather than an error — the silent failure
mode this convention avoids.

### Broker-side matching

The broker (Trading212) keys instruments on a bare `shortName`, which is a
*different* convention again. `match_broker_tradable` in
`stock_advisor/analysis/universe.py` translates between the two: it tries
the stored symbol verbatim, then the de-suffixed form, and uses the
instrument's currency code to ensure a `.L` ticker can only match a London
listing (and a bare ticker can only match a non-London one) — which is what
stops `BA.L` matching Boeing. See that module for the details.

## `sp500.json` — S&P 500

- Source: Wikipedia, ["List of S&P 500 companies"](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies), the "Symbol" column of the constituents table.
- 503 entries (503 listings for 500 index members — a handful of companies
  have two share classes each listed separately in the index: Alphabet
  (`GOOGL`/`GOOG`), Fox Corporation (`FOXA`/`FOX`), and News Corp
  (`NWSA`/`NWS`)).
- Ticker convention **as stored**: plain US exchange ticker, e.g. `AAPL`,
  `MSFT`. The two share-class tickers Wikipedia renders with a dot have been
  **translated to yfinance's hyphen form**: `BRK.B` → `BRK-B` (Berkshire
  Hathaway Class B) and `BF.B` → `BF-B` (Brown-Forman Class B). No other
  entry needed changing. On refresh, re-apply `.` → `-` to the Symbol
  column.

## `nasdaq100.json` — Nasdaq-100

- Source: Wikipedia, ["List of NASDAQ-100 companies"](https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies)
  (the main ["Nasdaq-100"](https://en.wikipedia.org/wiki/Nasdaq-100) article
  no longer embeds the constituent table itself — it links out to this
  dedicated list page, which is where the "Ticker" column was pulled from).
- 101 entries (101 listings for 100 index members — Alphabet's dual share
  classes, GOOGL and GOOG, both sit in the index as of this retrieval).
- Ticker convention **as stored**: plain Nasdaq ticker, e.g. `AAPL`, `MSFT`,
  `GOOGL`. No entry in this list carries a share-class dot, so the `.` → `-`
  translation was a no-op here — still apply it on refresh, since index
  membership changes.

## `ftse100.json` — FTSE 100

- Source: Wikipedia, ["FTSE 100 Index"](https://en.wikipedia.org/wiki/FTSE_100_Index),
  the "Ticker" column of the constituents table.
- 100 entries.
- Ticker convention **as stored**: London Stock Exchange EPIC **with the
  `.L` suffix appended** — `HSBA.L`, `BARC.L`, `AAL.L` — not the bare EPIC
  Wikipedia and UK financial media quote. The one EPIC containing a dot,
  `BT.A`, is stored as `BT-A.L` (yfinance's spelling), not `BT.A.L`. On
  refresh, append `.L` to every extracted EPIC and replace any embedded `.`
  with `-` first.

## Refresh procedure (manual)

1. Re-fetch the relevant Wikipedia page above.
2. Re-extract the ticker/symbol column (a one-off `pandas.read_html(...)` on
   the saved page, picking out the constituents table, is enough — no need
   to script this permanently).
3. **Apply the symbol convention above** before writing: `.` → `-` for US
   lists; for the FTSE list, `.` → `-` then append `.L`.
4. Overwrite the corresponding JSON file with the new flat ticker array.
5. Verify the new symbols resolve, e.g.

   ```python
   import json, yfinance
   syms = json.load(open("data/universe/ftse100.json"))
   close = yfinance.download(syms, period="5d", progress=False)["Close"]
   print([s for s in syms if s not in close.columns or close[s].dropna().empty])
   ```

   An empty list means every symbol resolved. A non-empty one usually means
   a constituent changed name/EPIC, not that the convention is wrong.
6. Update the retrieval date and entry counts in this file.
