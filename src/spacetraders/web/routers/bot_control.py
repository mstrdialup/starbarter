from __future__ import annotations

from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["bot-control"])

_VALID_KEYS = frozenset(
    {"global_pause", "mining_enabled", "trading_enabled", "price_discovery_enabled"}
)


class ControlRequest(BaseModel):
    key: str
    value: str  # "true" or "false"


class ShipPauseRequest(BaseModel):
    paused: bool


@router.get("/bot-control")
async def get_bot_control(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    flags = await queries.get_bot_control(db)
    ships = await queries.get_all_ships(db)
    return {
        "flags": flags,
        "ships": [{"symbol": s["symbol"], "paused": bool(s.get("paused"))} for s in ships],
    }


@router.post("/bot-control")
async def set_bot_control(
    body: ControlRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    if body.key not in _VALID_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid key: {body.key!r}")
    if body.value not in ("true", "false"):
        raise HTTPException(status_code=400, detail="value must be 'true' or 'false'")
    await queries.set_bot_control(db, body.key, body.value)
    return {"key": body.key, "value": body.value}


@router.post("/bot-control/ship/{symbol}/pause")
async def pause_ship(
    symbol: str,
    body: ShipPauseRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    ship = await queries.get_ship(db, symbol)
    if ship is None:
        raise HTTPException(status_code=404, detail="Ship not found")
    await queries.update_ship_pause(db, symbol, body.paused)
    return {"symbol": symbol, "paused": body.paused}


@router.get("/activity")
async def get_activity(
    limit: int = 100,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return await queries.get_bot_activity(db, limit=limit)
