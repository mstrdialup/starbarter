from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["contracts"])


def _enrich_contract(c: dict[str, Any]) -> dict[str, Any]:
    raw = c.get("terms") or "{}"
    try:
        terms = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        terms = {}
    c["terms"] = terms

    deliver = terms.get("deliver", [])
    c["deliver_progress"] = [
        {
            "trade_symbol": d.get("tradeSymbol", ""),
            "destination": d.get("destinationSymbol", ""),
            "required": d.get("unitsRequired", 0),
            "fulfilled": d.get("unitsFulfilled", 0),
        }
        for d in deliver
    ]
    return c


@router.get("/contracts")
async def list_contracts(db: aiosqlite.Connection = Depends(get_db)) -> list[dict[str, Any]]:
    contracts = await queries.get_contracts(db)
    return [_enrich_contract(c) for c in contracts]
