"""All SQL queries live here. No raw SQL elsewhere."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from spacetraders.api.models import (
    Agent,
    Contract,
    MarketTradeGood,
    Ship,
    Survey,
    System,
    Waypoint,
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    return dict(row)


# ---------------------------------------------------------------------------
# Writes (bot uses these)
# ---------------------------------------------------------------------------


async def upsert_agent(db: aiosqlite.Connection, agent: Agent) -> None:
    await db.execute(
        """
        INSERT INTO agent (symbol, credits, headquarters, ship_count, updated_at)
        VALUES (:symbol, :credits, :hq, :ship_count, :now)
        ON CONFLICT(symbol) DO UPDATE SET
            credits = excluded.credits,
            headquarters = excluded.headquarters,
            ship_count = excluded.ship_count,
            updated_at = excluded.updated_at
        """,
        {
            "symbol": agent.symbol,
            "credits": agent.credits,
            "hq": agent.headquarters,
            "ship_count": agent.ship_count,
            "now": _now_iso(),
        },
    )
    await db.commit()


async def upsert_ship(db: aiosqlite.Connection, ship: Ship) -> None:
    cooldown_expires: str | None = None
    if ship.cooldown.expiration:
        cooldown_expires = ship.cooldown.expiration.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    arrival_time: str | None = None
    at = ship.nav.arrival_time
    if at:
        arrival_time = at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    await db.execute(
        """
        INSERT INTO ship (
            symbol, role, frame, nav_status, nav_waypoint, nav_flight_mode,
            arrival_time, fuel_current, fuel_capacity, cargo_capacity,
            cargo_units, cargo_inventory, cooldown_expires,
            condition_frame, condition_engine, condition_reactor, updated_at
        )
        VALUES (
            :symbol, :role, :frame, :nav_status, :nav_waypoint, :nav_flight_mode,
            :arrival_time, :fuel_current, :fuel_capacity, :cargo_capacity,
            :cargo_units, :cargo_inventory, :cooldown_expires,
            :condition_frame, :condition_engine, :condition_reactor, :now
        )
        ON CONFLICT(symbol) DO UPDATE SET
            role = excluded.role,
            frame = excluded.frame,
            nav_status = excluded.nav_status,
            nav_waypoint = excluded.nav_waypoint,
            nav_flight_mode = excluded.nav_flight_mode,
            arrival_time = excluded.arrival_time,
            fuel_current = excluded.fuel_current,
            fuel_capacity = excluded.fuel_capacity,
            cargo_capacity = excluded.cargo_capacity,
            cargo_units = excluded.cargo_units,
            cargo_inventory = excluded.cargo_inventory,
            cooldown_expires = excluded.cooldown_expires,
            condition_frame = excluded.condition_frame,
            condition_engine = excluded.condition_engine,
            condition_reactor = excluded.condition_reactor,
            updated_at = excluded.updated_at
        """,
        {
            "symbol": ship.symbol,
            "role": ship.role,
            "frame": ship.frame.symbol,
            "nav_status": ship.nav.status,
            "nav_waypoint": ship.nav.waypoint_symbol,
            "nav_flight_mode": ship.nav.flight_mode,
            "arrival_time": arrival_time,
            "fuel_current": ship.fuel.current,
            "fuel_capacity": ship.fuel.capacity,
            "cargo_capacity": ship.cargo.capacity,
            "cargo_units": ship.cargo.units,
            "cargo_inventory": json.dumps(
                [{"symbol": i.symbol, "units": i.units} for i in ship.cargo.inventory]
            ),
            "cooldown_expires": cooldown_expires,
            "condition_frame": ship.frame.condition,
            "condition_engine": ship.engine.condition,
            "condition_reactor": ship.reactor.condition,
            "now": _now_iso(),
        },
    )
    await db.commit()


async def upsert_ships(db: aiosqlite.Connection, ships: list[Ship]) -> None:
    for ship in ships:
        await upsert_ship(db, ship)


async def insert_market_snapshot(
    db: aiosqlite.Connection, waypoint: str, goods: list[MarketTradeGood]
) -> None:
    ts = _now_iso()
    await db.executemany(
        """
        INSERT INTO market_snapshot
            (waypoint, trade_symbol, snapshot_ts, type, supply, activity,
             purchase_price, sell_price, trade_volume)
        VALUES
            (:waypoint, :trade_symbol, :ts, :type, :supply, :activity,
             :purchase_price, :sell_price, :trade_volume)
        ON CONFLICT DO NOTHING
        """,
        [
            {
                "waypoint": waypoint,
                "trade_symbol": g.symbol,
                "ts": ts,
                "type": g.type,
                "supply": g.supply,
                "activity": g.activity,
                "purchase_price": g.purchase_price,
                "sell_price": g.sell_price,
                "trade_volume": g.trade_volume,
            }
            for g in goods
        ],
    )
    await db.commit()


async def upsert_contract(db: aiosqlite.Connection, contract: Contract) -> None:
    deadline = contract.terms.deadline.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    deadline_to_accept: str | None = None
    if contract.deadline_to_accept:
        deadline_to_accept = contract.deadline_to_accept.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    await db.execute(
        """
        INSERT INTO contract
            (id, faction, type, terms, accepted, fulfilled, deadline, deadline_to_accept)
        VALUES
            (:id, :faction, :type, :terms, :accepted, :fulfilled, :deadline, :deadline_to_accept)
        ON CONFLICT(id) DO UPDATE SET
            accepted = excluded.accepted,
            fulfilled = excluded.fulfilled,
            terms = excluded.terms,
            deadline = excluded.deadline,
            deadline_to_accept = excluded.deadline_to_accept
        """,
        {
            "id": contract.id,
            "faction": contract.faction_symbol,
            "type": contract.type,
            "terms": contract.terms.model_dump_json(),
            "accepted": int(contract.accepted),
            "fulfilled": int(contract.fulfilled),
            "deadline": deadline,
            "deadline_to_accept": deadline_to_accept,
        },
    )
    await db.commit()


async def upsert_waypoint(db: aiosqlite.Connection, waypoint: Waypoint) -> None:
    faction_symbol: str | None = None
    if waypoint.faction:
        faction_symbol = waypoint.faction.get("symbol")

    charted = 0 if waypoint.chart is None else 1

    await db.execute(
        """
        INSERT INTO waypoint (symbol, system_symbol, type, x, y, traits, faction, is_charted)
        VALUES (:symbol, :system_symbol, :type, :x, :y, :traits, :faction, :is_charted)
        ON CONFLICT(symbol) DO UPDATE SET
            type = excluded.type,
            traits = excluded.traits,
            faction = excluded.faction,
            is_charted = excluded.is_charted
        """,
        {
            "symbol": waypoint.symbol,
            "system_symbol": waypoint.system_symbol,
            "type": waypoint.type,
            "x": waypoint.x,
            "y": waypoint.y,
            "traits": json.dumps([t.symbol for t in waypoint.traits]),
            "faction": faction_symbol,
            "is_charted": charted,
        },
    )
    await db.commit()


async def upsert_system(db: aiosqlite.Connection, system: System) -> None:
    await db.execute(
        """
        INSERT INTO system (symbol, type, x, y)
        VALUES (:symbol, :type, :x, :y)
        ON CONFLICT(symbol) DO UPDATE SET type = excluded.type
        """,
        {"symbol": system.symbol, "type": system.type, "x": system.x, "y": system.y},
    )
    await db.commit()


async def insert_survey(db: aiosqlite.Connection, survey: Survey) -> None:
    expiration = survey.expiration.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    await db.execute(
        """
        INSERT OR REPLACE INTO survey (signature, waypoint, deposits, expiration, size)
        VALUES (:sig, :waypoint, :deposits, :expiration, :size)
        """,
        {
            "sig": survey.signature,
            "waypoint": survey.symbol,
            "deposits": json.dumps(survey.deposits),
            "expiration": expiration,
            "size": survey.size,
        },
    )
    await db.commit()


async def insert_transaction(
    db: aiosqlite.Connection,
    ship_symbol: str,
    tx_type: str,
    trade_symbol: str | None,
    units: int | None,
    price_per_unit: int | None,
    total: int | None,
    waypoint: str | None,
    timestamp: str,
) -> None:
    await db.execute(
        """
        INSERT INTO transaction_log
            (ship_symbol, type, trade_symbol, units, price_per_unit, total, waypoint, timestamp)
        VALUES
            (:ship, :type, :trade, :units, :ppu, :total, :wp, :ts)
        """,
        {
            "ship": ship_symbol,
            "type": tx_type,
            "trade": trade_symbol,
            "units": units,
            "ppu": price_per_unit,
            "total": total,
            "wp": waypoint,
            "ts": timestamp,
        },
    )
    await db.commit()


async def upsert_reset_meta(
    db: aiosqlite.Connection,
    reset_date: str,
    agent_symbol: str,
    token: str,
) -> None:
    await db.execute(
        """
        INSERT INTO reset_meta (reset_date, registered_at, agent_symbol, token)
        VALUES (:reset_date, :now, :agent_symbol, :token)
        ON CONFLICT(reset_date) DO UPDATE SET
            agent_symbol = excluded.agent_symbol,
            token = excluded.token
        """,
        {"reset_date": reset_date, "now": _now_iso(), "agent_symbol": agent_symbol, "token": token},
    )
    await db.commit()


async def clear_all_reset_data(db: aiosqlite.Connection) -> None:
    tables = [
        "reset_meta",
        "system",
        "waypoint",
        "market_snapshot",
        "ship",
        "contract",
        "survey",
        "agent",
        "command_queue",
        "transaction_log",
    ]
    for table in tables:
        await db.execute(f"DELETE FROM {table}")  # noqa: S608
    await db.commit()


# ---------------------------------------------------------------------------
# Reads (TUI uses these)
# ---------------------------------------------------------------------------


async def get_agent(db: aiosqlite.Connection) -> dict[str, Any] | None:
    async with db.execute("SELECT * FROM agent ORDER BY updated_at DESC LIMIT 1") as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def get_all_ships(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with db.execute("SELECT * FROM ship ORDER BY symbol") as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_ship(db: aiosqlite.Connection, symbol: str) -> dict[str, Any] | None:
    async with db.execute("SELECT * FROM ship WHERE symbol = ?", (symbol,)) as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def get_contracts(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with db.execute("SELECT * FROM contract ORDER BY deadline") as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_market_latest(db: aiosqlite.Connection, waypoint: str) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT ms.*
        FROM market_snapshot ms
        INNER JOIN (
            SELECT trade_symbol, MAX(snapshot_ts) AS max_ts
            FROM market_snapshot WHERE waypoint = ?
            GROUP BY trade_symbol
        ) latest ON ms.trade_symbol = latest.trade_symbol AND ms.snapshot_ts = latest.max_ts
        WHERE ms.waypoint = ?
        ORDER BY ms.trade_symbol
        """,
        (waypoint, waypoint),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_all_market_latest(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT ms.*
        FROM market_snapshot ms
        INNER JOIN (
            SELECT waypoint, trade_symbol, MAX(snapshot_ts) AS max_ts
            FROM market_snapshot
            GROUP BY waypoint, trade_symbol
        ) latest ON ms.waypoint = latest.waypoint
            AND ms.trade_symbol = latest.trade_symbol
            AND ms.snapshot_ts = latest.max_ts
        ORDER BY ms.waypoint, ms.trade_symbol
        """
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_market_history(
    db: aiosqlite.Connection, trade_symbol: str, limit: int = 100
) -> list[dict[str, Any]]:
    async with db.execute(
        """
        SELECT * FROM market_snapshot
        WHERE trade_symbol = ?
        ORDER BY snapshot_ts DESC
        LIMIT ?
        """,
        (trade_symbol, limit),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_waypoints_by_type(
    db: aiosqlite.Connection, system: str, wp_type: str
) -> list[dict[str, Any]]:
    async with db.execute(
        "SELECT * FROM waypoint WHERE system_symbol = ? AND type = ?",
        (system, wp_type),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_pending_commands(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    async with db.execute(
        "SELECT * FROM command_queue WHERE status IN ('pending','running') ORDER BY id"
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_recent_transactions(
    db: aiosqlite.Connection, limit: int = 50
) -> list[dict[str, Any]]:
    async with db.execute(
        "SELECT * FROM transaction_log ORDER BY id DESC LIMIT ?", (limit,)
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_reset_meta(db: aiosqlite.Connection) -> dict[str, Any] | None:
    async with db.execute("SELECT * FROM reset_meta ORDER BY reset_date DESC LIMIT 1") as cur:
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def get_recent_commands(db: aiosqlite.Connection, limit: int = 20) -> list[dict[str, Any]]:
    async with db.execute("SELECT * FROM command_queue ORDER BY id DESC LIMIT ?", (limit,)) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Command queue (TUI writes, bot reads)
# ---------------------------------------------------------------------------


async def enqueue_command(
    db: aiosqlite.Connection,
    ship_symbol: str | None,
    command: str,
    params: dict[str, Any],
) -> int:
    cur = await db.execute(
        """
        INSERT INTO command_queue (ship_symbol, command, params, status)
        VALUES (?, ?, ?, 'pending')
        """,
        (ship_symbol, command, json.dumps(params)),
    )
    await db.commit()
    return cur.lastrowid  # type: ignore[return-value]


async def claim_next_command(db: aiosqlite.Connection) -> dict[str, Any] | None:
    async with db.execute(
        "SELECT * FROM command_queue WHERE status = 'pending' ORDER BY id LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    row_dict = _row_to_dict(row)
    await db.execute("UPDATE command_queue SET status = 'running' WHERE id = ?", (row_dict["id"],))
    await db.commit()
    row_dict["status"] = "running"
    return row_dict


async def complete_command(
    db: aiosqlite.Connection, command_id: int, result: dict[str, Any]
) -> None:
    await db.execute(
        """
        UPDATE command_queue
        SET status = 'done', result = ?, completed_at = ?
        WHERE id = ?
        """,
        (json.dumps(result), _now_iso(), command_id),
    )
    await db.commit()


async def fail_command(db: aiosqlite.Connection, command_id: int, error: str) -> None:
    await db.execute(
        """
        UPDATE command_queue
        SET status = 'failed', result = ?, completed_at = ?
        WHERE id = ?
        """,
        (json.dumps({"error": error}), _now_iso(), command_id),
    )
    await db.commit()


async def delete_expired_surveys(db: aiosqlite.Connection) -> None:
    now = _now_iso()
    await db.execute("DELETE FROM survey WHERE expiration <= ?", (now,))
    await db.commit()


async def get_usable_surveys(db: aiosqlite.Connection, waypoint: str) -> list[dict[str, Any]]:
    now = _now_iso()
    async with db.execute(
        "SELECT * FROM survey WHERE waypoint = ? AND expiration > ? ORDER BY expiration",
        (waypoint, now),
    ) as cur:
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]
