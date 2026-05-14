from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from spacetraders.db import queries
from spacetraders.db.connection import get_db as _get_db

router = APIRouter(tags=["events"])


@router.get("/events")
async def event_stream(request: Request) -> EventSourceResponse:
    async def generate():
        last_agent_ts: str | None = None
        last_command_id: int | None = None
        last_market_ts: str | None = None
        tick = 0

        db = await _get_db()
        try:
            while True:
                if await request.is_disconnected():
                    break

                agent = await queries.get_agent(db)
                if agent:
                    ts = agent.get("updated_at")
                    if ts != last_agent_ts:
                        last_agent_ts = ts
                        yield {"event": "agent_update", "data": json.dumps(agent)}

                commands = await queries.get_recent_commands(db, limit=5)
                if commands:
                    latest_id = commands[0]["id"]
                    if latest_id != last_command_id:
                        last_command_id = latest_id
                        for cmd in commands:
                            if cmd["status"] in ("done", "failed", "cancelled"):
                                yield {
                                    "event": "command_update",
                                    "data": json.dumps(cmd),
                                }
                                break

                # Ship updates every other tick (4s)
                if tick % 2 == 0:
                    ships = await queries.get_all_ships(db)
                    for ship in ships:
                        yield {"event": "ship_update", "data": json.dumps(ship)}

                # Market updates every 5th tick (10s)
                if tick % 5 == 0:
                    market_rows = await queries.get_all_market_latest(db)
                    if market_rows:
                        latest_ts = market_rows[0].get("snapshot_ts")
                        if latest_ts != last_market_ts:
                            last_market_ts = latest_ts
                            yield {"event": "market_update", "data": json.dumps({"updated": True})}

                yield {"event": "keepalive", "data": "{}"}
                tick += 1
                await asyncio.sleep(2)
        finally:
            await db.close()

    return EventSourceResponse(generate())
