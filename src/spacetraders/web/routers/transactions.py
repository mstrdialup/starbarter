from __future__ import annotations

from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Query

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["transactions"])


@router.get("/transactions")
async def list_transactions(
    limit: int = Query(default=100, le=500),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return await queries.get_recent_transactions(db, limit=limit)


@router.get("/transactions/summary")
async def transaction_summary(
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    return await queries.get_transaction_summary(db)
