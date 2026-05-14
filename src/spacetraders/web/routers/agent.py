from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["agent"])


@router.get("/agent")
async def get_agent(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    agent = await queries.get_agent(db)
    return agent or {}


@router.get("/status")
async def get_status(db: aiosqlite.Connection = Depends(get_db)) -> dict[str, Any]:
    agent = await queries.get_agent(db)
    reset_meta = await queries.get_reset_meta(db)
    pending = await queries.get_pending_commands(db)

    bot_online = False
    bot_last_seen: str | None = None
    credits = 0
    ship_count = 0
    agent_symbol = ""

    if agent:
        agent_symbol = agent.get("symbol", "")
        credits = agent.get("credits", 0)
        ship_count = agent.get("ship_count", 0)
        updated_at = agent.get("updated_at") or ""
        bot_last_seen = updated_at
        try:
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_s = (datetime.now(UTC) - dt).total_seconds()
            bot_online = age_s < 90
        except (ValueError, TypeError):
            pass

    bot_control = await queries.get_bot_control(db)
    return {
        "db_reachable": True,
        "reset_date": reset_meta["reset_date"] if reset_meta else None,
        "agent_symbol": agent_symbol,
        "credits": credits,
        "ship_count": ship_count,
        "bot_last_seen": bot_last_seen,
        "bot_online": bot_online,
        "pending_commands": len(pending),
        "global_pause": bot_control.get("global_pause", "false") == "true",
        "mining_enabled": bot_control.get("mining_enabled", "true") == "true",
        "trading_enabled": bot_control.get("trading_enabled", "true") == "true",
        "price_discovery_enabled": bot_control.get("price_discovery_enabled", "true") == "true",
    }
