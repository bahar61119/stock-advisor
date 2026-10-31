"""Trading212 broker provider: real HTTP client against the Trading212 REST API.

Only the three read-only endpoints documented for this project are called:
  GET /api/v0/equity/account/summary
  GET /api/v0/equity/positions
  GET /api/v0/equity/metadata/instruments

No order-placement endpoint is ever called from here, by design.
"""
import base64
import json
import os
import time

import requests

from stock_advisor.providers.broker.base import (
    AccountSummary,
    BrokerProvider,
    Instrument,
    Position,
)

DEFAULT_INSTRUMENT_CACHE_PATH = ".cache/t212_instruments.json"
DEFAULT_CACHE_MAX_AGE_SECONDS = 3600
REQUEST_TIMEOUT_SECONDS = 10

# Likely cause per HTTP status, phrased for the person running the tool
# rather than for a log aggregator. The first-run failure mode for this tool
# is almost always a bad or missing API key, and a bare requests.HTTPError
# ("401 Client Error: Unauthorized for url: ...") does not say which
# environment variables to go and check.
_STATUS_CAUSES = {
    401: (
        "credentials rejected, check T212_API_KEY/T212_API_SECRET or "
        "T212_API_KEY_STOCKS_ISA/T212_API_SECRET_STOCKS_ISA"
    ),
    403: (
        "credentials accepted but not permitted for this endpoint -- check "
        "the API key's scopes in Trading212 Settings -> API"
    ),
    429: (
        "rate limited by Trading212 (the instruments endpoint allows one "
        "request per 50 seconds); retry later"
    ),
}


class Trading212Error(RuntimeError):
    """A Trading212 API call failed in a way worth explaining.

    Carries the HTTP status code (when there was one) alongside a
    human-readable likely cause, so a misconfigured key surfaces as an
    actionable message instead of a raw `requests.HTTPError` traceback. The
    originating exception is kept as `__cause__` via `raise ... from`, so
    nothing is lost for debugging.
    """

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class Trading212BrokerProvider(BrokerProvider):
    """Broker provider backed by the real Trading212 REST API."""

    def __init__(
        self,
        env: str = "live",
        instrument_cache_path: str = DEFAULT_INSTRUMENT_CACHE_PATH,
        cache_max_age_seconds: int = DEFAULT_CACHE_MAX_AGE_SECONDS,
    ):
        """Initialize the provider for a given Trading212 environment.

        Args:
            env: "demo" or "live" — selects the Trading212 host.
            instrument_cache_path: where the instruments metadata cache is read/written.
            cache_max_age_seconds: how long a cached instruments file is considered fresh.
        """
        self._base_url = f"https://{env}.trading212.com"
        self._instrument_cache_path = instrument_cache_path
        self._cache_max_age_seconds = cache_max_age_seconds

    def _auth_header(self) -> str:
        """Build the HTTP Basic auth header value from environment variables.

        Prefers T212_API_KEY_STOCKS_ISA/T212_API_SECRET_STOCKS_ISA when both are
        set; otherwise falls back to T212_API_KEY/T212_API_SECRET. Raises
        RuntimeError naming the missing variables if neither pair is complete.
        """
        isa_key = os.environ.get("T212_API_KEY_STOCKS_ISA")
        isa_secret = os.environ.get("T212_API_SECRET_STOCKS_ISA")
        if isa_key and isa_secret:
            key, secret = isa_key, isa_secret
        else:
            key = os.environ.get("T212_API_KEY")
            secret = os.environ.get("T212_API_SECRET")
            if not key or not secret:
                raise RuntimeError(
                    "Trading212 credentials not found. Set either "
                    "T212_API_KEY_STOCKS_ISA and T212_API_SECRET_STOCKS_ISA, "
                    "or T212_API_KEY and T212_API_SECRET."
                )
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        return f"Basic {token}"

    def _headers(self) -> dict:
        """Build the request headers, including the Authorization header."""
        return {"Authorization": self._auth_header()}

    def _get(self, path: str):
        """Issue a GET request against the Trading212 API and return parsed JSON.

        A timeout is applied so a slow or hanging Trading212 endpoint cannot
        block this call (and whatever pipeline is waiting on it) forever.

        Every failure mode is translated into `Trading212Error` with a likely
        cause: an error status (401/403/429 named specifically, anything else
        generically), a transport failure, or a response body that isn't
        JSON. Letting `raise_for_status()`'s bare `HTTPError` propagate made
        401, 429 and 500 indistinguishable to the person reading the
        traceback, which matters most for the one failure that is almost
        always the cause on a first run: a bad API key.
        """
        url = f"{self._base_url}{path}"
        try:
            response = requests.get(
                url,
                headers=self._headers(),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise Trading212Error(
                f"Trading212 request to {path} failed before a response "
                f"arrived (network error or timeout): {exc}"
            ) from exc

        status = response.status_code
        if not response.ok:
            cause = _STATUS_CAUSES.get(
                status,
                "unexpected response from Trading212; its API is in beta and "
                "may have changed",
            )
            raise Trading212Error(
                f"Trading212 returned HTTP {status} for {path} -- {cause}.",
                status_code=status,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise Trading212Error(
                f"Trading212 returned a non-JSON body for {path} (HTTP "
                f"{status}); its API is in beta and may have changed.",
                status_code=status,
            ) from exc

    def get_account_summary(self) -> AccountSummary:
        """Fetch and map the account summary from Trading212."""
        data = self._get("/api/v0/equity/account/summary")
        cash = data["cash"]
        investments = data["investments"]
        return AccountSummary(
            currency=data["currency"],
            total_value=data["totalValue"],
            cash_available=cash["availableToTrade"],
            cash_reserved=cash["reservedForOrders"],
            cash_in_pies=cash["inPies"],
            investments_current_value=investments["currentValue"],
            investments_total_cost=investments["totalCost"],
            realized_pl=investments["realizedProfitLoss"],
            unrealized_pl=investments["unrealizedProfitLoss"],
        )

    def get_positions(self) -> list[Position]:
        """Fetch and map the current positions from Trading212."""
        data = self._get("/api/v0/equity/positions")
        positions = []
        for item in data:
            instrument = item["instrument"]
            wallet = item["walletImpact"]
            positions.append(
                Position(
                    ticker=instrument["ticker"],
                    name=instrument["name"],
                    isin=instrument["isin"],
                    currency=instrument["currency"],
                    quantity=item["quantity"],
                    quantity_available=item["quantityAvailableForTrading"],
                    current_price=item["currentPrice"],
                    average_price_paid=item["averagePricePaid"],
                    wallet_currency=wallet["currency"],
                    wallet_current_value=wallet["currentValue"],
                    wallet_total_cost=wallet["totalCost"],
                    wallet_unrealized_pl=wallet["unrealizedProfitLoss"],
                )
            )
        return positions

    def get_instruments(self) -> list[Instrument]:
        """Fetch the instrument metadata list, using a local JSON cache.

        The instruments endpoint is rate-limited (1 request per 50 seconds)
        and returns a large (~5MB) payload, so this reads a cached copy when
        it exists and is fresher than cache_max_age_seconds; otherwise it
        calls the API and overwrites the cache file.

        An unreadable or corrupted cache file is treated as a cache miss and
        re-fetched (overwriting it), rather than crashing with a raw
        `JSONDecodeError` or `KeyError`. A cache is an optimization; a
        truncated one -- which is exactly what a run interrupted mid-write
        leaves behind -- should cost a request, not the whole run.
        """
        raw = self._read_cache()
        if raw is None:
            raw = self._get("/api/v0/equity/metadata/instruments")
            self._write_cache(raw)
        return self._parse_instruments(raw)

    @staticmethod
    def _parse_instruments(raw) -> list[Instrument]:
        """Map the raw instruments payload to `Instrument` objects.

        Raises `Trading212Error` rather than a bare `KeyError`/`TypeError` if
        the payload doesn't have the documented shape -- that is a changed
        beta API, and saying so is more use than the name of one key.
        """
        try:
            return [
                Instrument(
                    ticker=item["ticker"],
                    name=item["name"],
                    short_name=item["shortName"],
                    isin=item["isin"],
                    currency_code=item["currencyCode"],
                    type=item["type"],
                )
                for item in raw
            ]
        except (KeyError, TypeError) as exc:
            raise Trading212Error(
                "Trading212 instruments payload was not in the expected "
                f"shape ({exc!r}); its API is in beta and may have changed."
            ) from exc

    def _read_cache(self):
        """Return the cached instruments payload, or `None` for a cache miss.

        A miss is: no file, a stale file, an unreadable file, a file that
        isn't valid JSON, or a file whose contents aren't instrument-shaped.
        Every one of those falls through to a re-fetch.
        """
        if not self._cache_is_fresh():
            return None
        try:
            with open(self._instrument_cache_path, "r") as f:
                raw = json.load(f)
            # Validate before trusting it, so a partially-written cache is a
            # miss rather than a crash deeper in the pipeline.
            self._parse_instruments(raw)
            return raw
        except (OSError, ValueError, Trading212Error):
            return None

    def _cache_is_fresh(self) -> bool:
        """Return True if the cache file exists and is within the max age."""
        if not os.path.exists(self._instrument_cache_path):
            return False
        age = time.time() - os.path.getmtime(self._instrument_cache_path)
        return age < self._cache_max_age_seconds

    def _write_cache(self, raw) -> None:
        """Write the raw instruments payload to the cache file.

        A write failure (unwritable directory, full disk, the cache path
        occupied by a directory) is swallowed: the payload has already been
        fetched and the caller can be served from it, so failing to *save*
        it should cost the next run a request, not abort this one. Same
        reasoning as treating an unreadable cache as a miss.
        """
        try:
            cache_dir = os.path.dirname(self._instrument_cache_path)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
            with open(self._instrument_cache_path, "w") as f:
                json.dump(raw, f)
        except OSError:
            return
