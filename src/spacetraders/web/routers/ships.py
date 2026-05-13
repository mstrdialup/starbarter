from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["ships"])


def _enrich_ship(ship: dict[str, Any]) -> dict[str, Any]:
    raw = ship.get("cargo_inventory") or "[]"
    try:
        ship["cargo_inventory"] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        ship["cargo_inventory"] = []
    return ship


@router.get("/ships")
async def list_ships(db: aiosqlite.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    ships = await queries.get_all_ships(db)
    return [_enrich_ship(s) for s in ships]


@router.get("/ships/{symbol}")
async def get_ship(symbol: str, db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    ship = await queries.get_ship(db, symbol.upper())
    if ship is None:
        raise HTTPException(status_code=404, detail="Ship not found")
    return _enrich_ship(ship)
