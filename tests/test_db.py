"""Round-trip tests for DB queries."""

from __future__ import annotations

import pytest
import pytest_asyncio

from spacetraders.db import queries
from spacetraders.db.connection import get_db, init_db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest_asyncio.fixture
async def db(db_path):
    await init_db(db_path)
    conn = await get_db(db_path)
    yield conn
    await conn.close()


def _make_ship_data():
    return {
        "symbol": "TEST-1",
        "registration": {"role": "EXCAVATOR"},
        "nav": {
            "systemSymbol": "X1-AA",
            "waypointSymbol": "X1-AA-B1",
            "status": "IN_ORBIT",
            "flightMode": "CRUISE",
            "route": {},
        },
        "crew": {},
        "frame": {"symbol": "FRAME_MINER", "condition": 1.0},
        "reactor": {"symbol": "REACTOR_SOLAR_I", "condition": 1.0},
        "engine": {"symbol": "ENGINE_IMPULSE_DRIVE_I", "condition": 1.0},
        "cooldown": {"totalSeconds": 0, "remainingSeconds": 0},
        "modules": [],
        "mounts": [],
        "cargo": {"capacity": 40, "units": 0, "inventory": []},
        "fuel": {"current": 400, "capacity": 400, "consumed": {}},
    }


@pytest.mark.asyncio
async def test_upsert_and_read_ship(db):
    from spacetraders.api.models import Ship

    ship = Ship.model_validate(_make_ship_data())
    await queries.upsert_ship(db, ship)

    result = await queries.get_ship(db, "TEST-1")
    assert result is not None
    assert result["symbol"] == "TEST-1"
    assert result["role"] == "EXCAVATOR"
    assert result["fuel_current"] == 400
    assert result["cargo_capacity"] == 40


@pytest.mark.asyncio
async def test_get_all_ships_empty(db):
    ships = await queries.get_all_ships(db)
    assert ships == []


@pytest.mark.asyncio
async def test_command_queue_lifecycle(db):
    cmd_id = await queries.enqueue_command(db, "TEST-1", "orbit", {})
    assert cmd_id is not None

    pending = await queries.get_pending_commands(db)
    assert any(p["id"] == cmd_id for p in pending)

    claimed = await queries.claim_next_command(db)
    assert claimed is not None
    assert claimed["id"] == cmd_id
    assert claimed["command"] == "orbit"
    assert claimed["status"] == "running"

    claimed2 = await queries.claim_next_command(db)
    assert claimed2 is None

    await queries.complete_command(db, cmd_id, {"nav": "ok"})

    recent = await queries.get_recent_commands(db)
    done = next(r for r in recent if r["id"] == cmd_id)
    assert done["status"] == "done"
    assert "ok" in done["result"]


@pytest.mark.asyncio
async def test_command_queue_fail(db):
    cmd_id = await queries.enqueue_command(db, "TEST-1", "navigate", {"waypoint": "X1-AA-B2"})
    await queries.claim_next_command(db)
    await queries.fail_command(db, cmd_id, "403 Forbidden")

    recent = await queries.get_recent_commands(db)
    failed = next(r for r in recent if r["id"] == cmd_id)
    assert failed["status"] == "failed"
    assert "Forbidden" in failed["result"]


@pytest.mark.asyncio
async def test_market_snapshot(db):
    from spacetraders.api.models import MarketTradeGood

    good = MarketTradeGood.model_validate(
        {
            "symbol": "IRON_ORE",
            "type": "EXPORT",
            "tradeVolume": 100,
            "supply": "ABUNDANT",
            "activity": "STRONG",
            "purchasePrice": 32,
            "sellPrice": 38,
        }
    )
    await queries.insert_market_snapshot(db, "X1-AA-B1", [good])

    rows = await queries.get_market_latest(db, "X1-AA-B1")
    assert len(rows) == 1
    assert rows[0]["trade_symbol"] == "IRON_ORE"
    assert rows[0]["purchase_price"] == 32


@pytest.mark.asyncio
async def test_agent_upsert(db):
    from spacetraders.api.models import Agent

    agent = Agent.model_validate(
        {
            "symbol": "TESTER",
            "headquarters": "X1-AA-HQ",
            "credits": 50000,
            "shipCount": 3,
        }
    )
    await queries.upsert_agent(db, agent)
    result = await queries.get_agent(db)
    assert result is not None
    assert result["symbol"] == "TESTER"
    assert result["credits"] == 50000
