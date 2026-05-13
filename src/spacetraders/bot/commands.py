"""Command queue consumer — executes TUI-issued commands against the API."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
import structlog

from spacetraders.api.client import SpaceTradersClient, SpaceTradersError
from spacetraders.db import queries

log = structlog.get_logger()


async def execute_command(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    cmd: dict[str, Any],
) -> None:
    command_id: int = cmd["id"]
    ship: str | None = cmd.get("ship_symbol")
    command: str = cmd["command"]
    params: dict[str, Any] = json.loads(cmd.get("params") or "{}")

    log.info("executing_command", id=command_id, command=command, ship=ship, params=params)

    try:
        result = await _dispatch(client, db, command, ship, params)
        await queries.complete_command(db, command_id, result)
        log.info("command_done", id=command_id, command=command)
    except SpaceTradersError as exc:
        log.warning("command_failed", id=command_id, command=command, error=str(exc))
        await queries.fail_command(db, command_id, str(exc))
    except Exception as exc:
        log.error("command_error", id=command_id, command=command, error=str(exc))
        await queries.fail_command(db, command_id, str(exc))


async def _dispatch(
    client: SpaceTradersClient,
    db: aiosqlite.Connection,
    command: str,
    ship: str | None,
    params: dict[str, Any],
) -> dict[str, Any]:
    if ship is None and command not in ("accept_contract",):
        raise ValueError(f"command {command!r} requires ship_symbol")

    if command == "navigate":
        waypoint = params["waypoint"]
        ship_data = await queries.get_ship(db, ship)  # type: ignore[arg-type]
        if ship_data and ship_data["nav_status"] == "DOCKED":
            await client.orbit(ship)  # type: ignore[arg-type]
        nav = await client.navigate(ship, waypoint)  # type: ignore[arg-type]
        updated = await client.get_ship(ship)  # type: ignore[arg-type]
        await queries.upsert_ship(db, updated)
        return {"nav": nav.model_dump()}

    if command == "dock":
        nav = await client.dock(ship)  # type: ignore[arg-type]
        return {"nav": nav.model_dump()}

    if command == "orbit":
        nav = await client.orbit(ship)  # type: ignore[arg-type]
        return {"nav": nav.model_dump()}

    if command == "buy":
        tx = await client.purchase_cargo(ship, params["symbol"], params["units"])  # type: ignore[arg-type]
        updated = await client.get_ship(ship)  # type: ignore[arg-type]
        await queries.upsert_ship(db, updated)
        await queries.insert_transaction(
            db,
            ship_symbol=ship,  # type: ignore[arg-type]
            tx_type="BUY",
            trade_symbol=tx.trade_symbol,
            units=tx.units,
            price_per_unit=tx.price_per_unit,
            total=tx.total_price,
            waypoint=tx.waypoint_symbol,
            timestamp=tx.timestamp.isoformat(),
        )
        return {"transaction": tx.model_dump()}

    if command == "sell":
        tx = await client.sell_cargo(ship, params["symbol"], params["units"])  # type: ignore[arg-type]
        updated = await client.get_ship(ship)  # type: ignore[arg-type]
        await queries.upsert_ship(db, updated)
        await queries.insert_transaction(
            db,
            ship_symbol=ship,  # type: ignore[arg-type]
            tx_type="SELL",
            trade_symbol=tx.trade_symbol,
            units=tx.units,
            price_per_unit=tx.price_per_unit,
            total=tx.total_price,
            waypoint=tx.waypoint_symbol,
            timestamp=tx.timestamp.isoformat(),
        )
        return {"transaction": tx.model_dump()}

    if command == "refuel":
        result = await client.refuel(ship)  # type: ignore[arg-type]
        updated = await client.get_ship(ship)  # type: ignore[arg-type]
        await queries.upsert_ship(db, updated)
        return result

    if command == "extract":
        extraction = await client.extract(ship)  # type: ignore[arg-type]
        updated = await client.get_ship(ship)  # type: ignore[arg-type]
        await queries.upsert_ship(db, updated)
        return {"extraction": extraction.model_dump()}

    if command == "accept_contract":
        contract_id = params["contract_id"]
        contract = await client.accept_contract(contract_id)
        await queries.upsert_contract(db, contract)
        return {"contract": contract.model_dump()}

    raise ValueError(f"Unknown command: {command!r}")
