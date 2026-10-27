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
        """Issue a GET request against the Trading212 API and return parsed JSON."""
        response = requests.get(f"{self._base_url}{path}", headers=self._headers())
        response.raise_for_status()
        return response.json()

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
        """
        if self._cache_is_fresh():
            with open(self._instrument_cache_path, "r") as f:
                raw = json.load(f)
        else:
            raw = self._get("/api/v0/equity/metadata/instruments")
            self._write_cache(raw)
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

    def _cache_is_fresh(self) -> bool:
        """Return True if the cache file exists and is within the max age."""
        if not os.path.exists(self._instrument_cache_path):
            return False
        age = time.time() - os.path.getmtime(self._instrument_cache_path)
        return age < self._cache_max_age_seconds

    def _write_cache(self, raw) -> None:
        """Write the raw instruments payload to the cache file."""
        cache_dir = os.path.dirname(self._instrument_cache_path)
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)
        with open(self._instrument_cache_path, "w") as f:
            json.dump(raw, f)
