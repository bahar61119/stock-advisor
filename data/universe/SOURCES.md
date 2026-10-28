# Universe data sources

These three files are flat JSON arrays of plain ticker strings, hand-refreshed
from a public reference at implementation time. **No code in this phase
fetches them live** — refreshing them (e.g. when index composition changes)
is a manual, periodic task: re-pull the source page, re-extract the ticker
column, and overwrite the file.

Retrieved: **2026-10-28**.

## `sp500.json` — S&P 500

- Source: Wikipedia, ["List of S&P 500 companies"](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies), the "Symbol" column of the constituents table.
- 503 entries (503 listings for 500 index members — a handful of companies
  have two share classes each listed separately in the index: Alphabet
  (`GOOGL`/`GOOG`), Fox Corporation (`FOXA`/`FOX`), and News Corp
  (`NWSA`/`NWS`)).
- Ticker convention: plain US exchange ticker as quoted by Wikipedia/S&P,
  e.g. `AAPL`, `MSFT`. Two tickers carry a share-class suffix with a **dot**
  rather than a hyphen, as Wikipedia renders them: `BRK.B` (Berkshire
  Hathaway Class B), `BF.B` (Brown-Forman Class B). Some data providers
  (notably Yahoo Finance / yfinance) use a hyphen instead (`BRK-B`, `BF-B`) —
  callers matching this universe against such a provider's symbols will need
  to translate `.` to `-` for those two tickers specifically.

## `nasdaq100.json` — Nasdaq-100

- Source: Wikipedia, ["List of NASDAQ-100 companies"](https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies)
  (the main ["Nasdaq-100"](https://en.wikipedia.org/wiki/Nasdaq-100) article
  no longer embeds the constituent table itself — it links out to this
  dedicated list page, which is where the "Ticker" column was pulled from).
- 101 entries (101 listings for 100 index members — Alphabet's dual share
  classes, GOOGL and GOOG, both sit in the index as of this retrieval).
- Ticker convention: plain Nasdaq ticker, e.g. `AAPL`, `MSFT`, `GOOGL`.

## `ftse100.json` — FTSE 100

- Source: Wikipedia, ["FTSE 100 Index"](https://en.wikipedia.org/wiki/FTSE_100_Index),
  the "Ticker" column of the constituents table.
- 100 entries.
- Ticker convention: bare London Stock Exchange EPIC code with **no `.L`
  suffix** (e.g. `HSBA`, `BARC`, `AAL`), matching how these are quoted on
  Wikipedia and in UK financial media generally. Data providers that
  disambiguate by exchange (e.g. Yahoo Finance / yfinance) typically expect
  the `.L` suffix appended (`HSBA.L`, `BARC.L`) — callers feeding this
  universe into such a provider will need to append it.

## Refresh procedure (manual)

1. Re-fetch the relevant Wikipedia page above.
2. Re-extract the ticker/symbol column (a one-off `pandas.read_html(...)` on
   the saved page, picking out the constituents table, is enough — no need
   to script this permanently).
3. Overwrite the corresponding JSON file with the new flat ticker array.
4. Update the retrieval date and entry counts in this file.
