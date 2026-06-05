"""NSE live analysis client for top gainers and losers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import requests

NSE_HOME_URL = "https://www.nseindia.com"
NSE_VARIATIONS_URL = "https://www.nseindia.com/api/live-analysis-variations"
NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
NSE_INDICES_REFERER = "https://www.nseindia.com/market-data/live-market-indices"

NIFTY_INDEX_NAME = "NIFTY 50"
VIX_INDEX_NAME = "INDIA VIX"

MoverDirection = Literal["gainers", "loosers"]
FOSEC_SEGMENT = "FOSec"


@dataclass(frozen=True)
class NSEMover:
    symbol: str
    ltp: float
    per_change: float
    prev_price: float
    turnover: float
    trade_quantity: int
    rank: int


class NSEClient:
    """Fetch NSE top gainers/losers filtered to the F&O securities segment."""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.nseindia.com/market-data/live-market-indices",
            }
        )

    def _ensure_session(self) -> None:
        self._session.get(NSE_HOME_URL, timeout=self.timeout)

    def fetch_fosec_movers(self, direction: MoverDirection) -> list[NSEMover]:
        """Return F&O securities sorted by NSE for the requested direction."""

        self._ensure_session()
        response = self._session.get(
            NSE_VARIATIONS_URL,
            params={"index": direction},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()

        segment = payload.get(FOSEC_SEGMENT)
        if not segment or "data" not in segment:
            raise ValueError(f"NSE response missing '{FOSEC_SEGMENT}' segment")

        movers: list[NSEMover] = []
        for index, row in enumerate(segment["data"], start=1):
            movers.append(
                NSEMover(
                    symbol=str(row["symbol"]).upper(),
                    ltp=float(row["ltp"]),
                    per_change=float(row.get("perChange", row.get("net_price", 0))),
                    prev_price=float(row["prev_price"]),
                    turnover=float(row.get("turnover", 0)),
                    trade_quantity=int(row.get("trade_quantity", 0)),
                    rank=index,
                )
            )
        return movers

    def get_top_mover(self, direction: MoverDirection, rank: int = 1) -> NSEMover:
        movers = self.fetch_fosec_movers(direction)
        if rank < 1 or rank > len(movers):
            raise IndexError(
                f"Rank {rank} out of range for {direction}; "
                f"NSE returned {len(movers)} F&O securities"
            )
        return movers[rank - 1]

    def _fetch_all_indices(self) -> list[dict]:
        self._session.headers["Referer"] = NSE_INDICES_REFERER
        self._ensure_session()
        response = self._session.get(NSE_ALL_INDICES_URL, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list):
            raise ValueError("NSE allIndices response missing data list")
        return data

    def get_index_quote(self, index_name: str) -> dict:
        """Return live/index quote fields for a named NSE index."""

        for row in self._fetch_all_indices():
            if str(row.get("index", "")).upper() == index_name.upper():
                last = float(row["last"])
                prev = float(row["previousClose"])
                pct = row.get("percentChange")
                if pct is None and prev:
                    pct = round(((last - prev) / prev) * 100, 2)
                return {
                    "index": row["index"],
                    "last": last,
                    "previous_close": prev,
                    "percent_change": float(pct),
                    "open": float(row.get("open") or 0),
                    "high": float(row.get("high") or 0),
                    "low": float(row.get("low") or 0),
                    "indicative_close": float(row.get("indicativeClose") or 0),
                }
        raise ValueError(f"Index '{index_name}' not found in NSE allIndices")

    def get_nifty_quote(self) -> dict:
        return self.get_index_quote(NIFTY_INDEX_NAME)

    def get_india_vix(self) -> float:
        return self.get_index_quote(VIX_INDEX_NAME)["last"]

    def get_nifty_preopen_change_pct(self) -> float:
        """Pre-open indicative move vs previous close (use around 09:08–09:13 IST)."""

        quote = self.get_nifty_quote()
        prev = quote["previous_close"]
        if prev <= 0:
            raise ValueError("Invalid Nifty previous close from NSE")
        indicative = quote["indicative_close"] or quote["last"]
        return round(((indicative - prev) / prev) * 100, 2)
