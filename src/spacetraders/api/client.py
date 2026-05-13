from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx
import structlog
from aiolimiter import AsyncLimiter

from spacetraders.api.models import (
    Agent,
    Contract,
    Extraction,
    Market,
    MarketTransaction,
    RegisterResponse,
    ServerStatus,
    Ship,
    ShipNav,
    Shipyard,
    Survey,
    System,
    Waypoint,
)

log = structlog.get_logger()

_RATE_LIMITER = AsyncLimiter(2, 1)


class SpaceTradersError(Exception):
    def __init__(self, status: int, code: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class SpaceTradersClient:
    """Async HTTP client. One instance per process. Rate limited to 2 req/s sustained."""

    def __init__(self, token: str, base_url: str = "https://api.spacetraders.io/v2") -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SpaceTradersClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = path if path.startswith("http") else path
        max_retries = 3
        for attempt in range(max_retries + 1):
            await _RATE_LIMITER.acquire()
            t0 = time.monotonic()
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.RequestError as exc:
                log.error("request_error", method=method, path=path, error=str(exc))
                if attempt < max_retries:
                    await asyncio.sleep(2**attempt + random.random())
                    continue
                raise

            latency = time.monotonic() - t0
            remaining = resp.headers.get("x-ratelimit-remaining", "?")
            log.debug(
                "api_request",
                method=method,
                path=path,
                status=resp.status_code,
                latency_ms=round(latency * 1000),
                ratelimit_remaining=remaining,
            )

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("retry-after", "1"))
                log.warning("rate_limited", retry_after=retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                if attempt < max_retries:
                    delay = (2**attempt) + random.random()
                    log.warning("server_error", status=resp.status_code, retry_in=delay)
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()

            if not resp.content:
                return {}

            data = resp.json()

            if resp.status_code >= 400:
                err = data.get("error", {})
                raise SpaceTradersError(
                    resp.status_code, err.get("code", 0), err.get("message", str(data))
                )

            return data

        raise RuntimeError("Exceeded max retries")

    # ---- typed API methods -----------------------------------------------

    async def get_status(self) -> ServerStatus:
        data = await self._request("GET", "/")
        return ServerStatus.model_validate(data)

    async def register(self, symbol: str, faction: str) -> RegisterResponse:
        data = await self._request(
            "POST",
            "/register",
            json={"symbol": symbol, "faction": faction},
        )
        return RegisterResponse.model_validate(data["data"])

    async def get_agent(self) -> Agent:
        data = await self._request("GET", "/my/agent")
        return Agent.model_validate(data["data"])

    async def list_ships(self, limit: int = 20, page: int = 1) -> list[Ship]:
        data = await self._request("GET", "/my/ships", params={"limit": limit, "page": page})
        return [Ship.model_validate(s) for s in data["data"]]

    async def get_ship(self, symbol: str) -> Ship:
        data = await self._request("GET", f"/my/ships/{symbol}")
        return Ship.model_validate(data["data"])

    async def orbit(self, ship: str) -> ShipNav:
        data = await self._request("POST", f"/my/ships/{ship}/orbit")
        return ShipNav.model_validate(data["data"]["nav"])

    async def dock(self, ship: str) -> ShipNav:
        data = await self._request("POST", f"/my/ships/{ship}/dock")
        return ShipNav.model_validate(data["data"]["nav"])

    async def navigate(self, ship: str, waypoint: str) -> ShipNav:
        data = await self._request(
            "POST", f"/my/ships/{ship}/navigate", json={"waypointSymbol": waypoint}
        )
        return ShipNav.model_validate(data["data"]["nav"])

    async def set_flight_mode(self, ship: str, mode: str) -> ShipNav:
        data = await self._request("PATCH", f"/my/ships/{ship}/nav", json={"flightMode": mode})
        return ShipNav.model_validate(data["data"])

    async def extract(self, ship: str, survey: dict[str, Any] | None = None) -> Extraction:
        body: dict[str, Any] = {}
        if survey:
            body["survey"] = survey
        data = await self._request("POST", f"/my/ships/{ship}/extract", json=body)
        return Extraction.model_validate(data["data"]["extraction"])

    async def extract_with_survey(self, ship: str, survey: Survey) -> Extraction:
        body = {
            "survey": {
                "signature": survey.signature,
                "symbol": survey.symbol,
                "deposits": survey.deposits,
                "expiration": survey.expiration.isoformat(),
                "size": survey.size,
            }
        }
        data = await self._request("POST", f"/my/ships/{ship}/extract/survey", json=body)
        return Extraction.model_validate(data["data"]["extraction"])

    async def survey(self, ship: str) -> list[Survey]:
        data = await self._request("POST", f"/my/ships/{ship}/survey")
        return [Survey.model_validate(s) for s in data["data"]["surveys"]]

    async def purchase_cargo(self, ship: str, symbol: str, units: int) -> MarketTransaction:
        data = await self._request(
            "POST",
            f"/my/ships/{ship}/purchase",
            json={"symbol": symbol, "units": units},
        )
        return MarketTransaction.model_validate(data["data"]["transaction"])

    async def sell_cargo(self, ship: str, symbol: str, units: int) -> MarketTransaction:
        data = await self._request(
            "POST",
            f"/my/ships/{ship}/sell",
            json={"symbol": symbol, "units": units},
        )
        return MarketTransaction.model_validate(data["data"]["transaction"])

    async def jettison(self, ship: str, symbol: str, units: int) -> None:
        await self._request(
            "POST", f"/my/ships/{ship}/jettison", json={"symbol": symbol, "units": units}
        )

    async def refuel(self, ship: str, units: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if units is not None:
            body["units"] = units
        data = await self._request("POST", f"/my/ships/{ship}/refuel", json=body)
        return data["data"]

    async def get_market(self, system: str, waypoint: str) -> Market:
        data = await self._request("GET", f"/systems/{system}/waypoints/{waypoint}/market")
        return Market.model_validate(data["data"])

    async def get_waypoints(self, system: str, **filters: Any) -> list[Waypoint]:
        params: dict[str, Any] = {"limit": 20, **filters}
        all_waypoints: list[Waypoint] = []
        page = 1
        while True:
            params["page"] = page
            data = await self._request("GET", f"/systems/{system}/waypoints", params=params)
            batch = [Waypoint.model_validate(w) for w in data["data"]]
            all_waypoints.extend(batch)
            meta = data.get("meta", {})
            if len(all_waypoints) >= meta.get("total", len(all_waypoints)):
                break
            page += 1
        return all_waypoints

    async def get_waypoint(self, system: str, waypoint: str) -> Waypoint:
        data = await self._request("GET", f"/systems/{system}/waypoints/{waypoint}")
        return Waypoint.model_validate(data["data"])

    async def get_system(self, system: str) -> System:
        data = await self._request("GET", f"/systems/{system}")
        return System.model_validate(data["data"])

    async def list_contracts(self) -> list[Contract]:
        data = await self._request("GET", "/my/contracts")
        return [Contract.model_validate(c) for c in data["data"]]

    async def accept_contract(self, contract_id: str) -> Contract:
        data = await self._request("POST", f"/my/contracts/{contract_id}/accept")
        return Contract.model_validate(data["data"]["contract"])

    async def deliver_contract(
        self, contract_id: str, ship: str, trade: str, units: int
    ) -> Contract:
        data = await self._request(
            "POST",
            f"/my/contracts/{contract_id}/deliver",
            json={"shipSymbol": ship, "tradeSymbol": trade, "units": units},
        )
        return Contract.model_validate(data["data"]["contract"])

    async def fulfill_contract(self, contract_id: str) -> Contract:
        data = await self._request("POST", f"/my/contracts/{contract_id}/fulfill")
        return Contract.model_validate(data["data"]["contract"])

    async def negotiate_contract(self, ship: str) -> Contract:
        data = await self._request("POST", f"/my/ships/{ship}/negotiate/contract")
        return Contract.model_validate(data["data"]["contract"])

    async def buy_ship(self, ship_type: str, waypoint: str) -> Ship:
        data = await self._request(
            "POST",
            "/my/ships",
            json={"shipType": ship_type, "waypointSymbol": waypoint},
        )
        return Ship.model_validate(data["data"]["ship"])

    async def get_shipyard(self, system: str, waypoint: str) -> Shipyard:
        data = await self._request("GET", f"/systems/{system}/waypoints/{waypoint}/shipyard")
        return Shipyard.model_validate(data["data"])
