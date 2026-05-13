"""Per-ship async state machine."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import aiosqlite
import structlog

from spacetraders.api.client import SpaceTradersClient, SpaceTradersError
from spacetraders.db import queries

log = structlog.get_logger()

MINING_ROLES = {"EXCAVATOR", "SURVEYOR"}
HAULING_ROLES = {"HAULER", "COMMAND"}


def _seconds_until(iso_ts: str | None) -> float:
    if not iso_ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        delta = (dt - datetime.now(UTC)).total_seconds()
        return max(0.0, delta)
    except (ValueError, TypeError):
        return 0.0


async def _sell_all_cargo(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
) -> None:
    inventory = json.loads(ship_data.get("cargo_inventory") or "[]")
    for item in inventory:
        trade_symbol: str = item["symbol"]
        units: int = item["units"]
        if units <= 0:
            continue
        try:
            tx = await client.sell_cargo(symbol, trade_symbol, units)
            await queries.insert_transaction(
                db,
                ship_symbol=symbol,
                tx_type="SELL",
                trade_symbol=tx.trade_symbol,
                units=tx.units,
                price_per_unit=tx.price_per_unit,
                total=tx.total_price,
                waypoint=tx.waypoint_symbol,
                timestamp=tx.timestamp.isoformat(),
            )
            log.info(
                "sold_cargo", ship=symbol, good=trade_symbol, units=units, total=tx.total_price
            )
        except SpaceTradersError as exc:
            log.warning("sell_failed", ship=symbol, good=trade_symbol, error=str(exc))


async def run_ship_loop(
    ship_symbol: str,
    db_path: str,
    client: SpaceTradersClient,
    stop_event: asyncio.Event,
) -> None:
    log.info("ship_loop_start", ship=ship_symbol)

    from spacetraders.db.connection import get_db

    db: aiosqlite.Connection = await get_db(db_path)
    try:
        while not stop_event.is_set():
            try:
                ship_data = await queries.get_ship(db, ship_symbol)
                if ship_data is None:
                    await asyncio.sleep(5)
                    continue

                role = (ship_data.get("role") or "").upper()

                # Wait out transit
                if ship_data["nav_status"] == "IN_TRANSIT":
                    wait = _seconds_until(ship_data.get("arrival_time"))
                    if wait > 0:
                        log.info("ship_in_transit", ship=ship_symbol, wait_s=round(wait))
                        await asyncio.sleep(min(wait + 1, 30))
                        # Refresh ship from API after transit
                        updated = await client.get_ship(ship_symbol)
                        await queries.upsert_ship(db, updated)
                    continue

                # Wait out cooldown
                cooldown_wait = _seconds_until(ship_data.get("cooldown_expires"))
                if cooldown_wait > 0.5:
                    log.debug("ship_on_cooldown", ship=ship_symbol, wait_s=round(cooldown_wait))
                    await asyncio.sleep(min(cooldown_wait, 30))
                    continue

                if role in MINING_ROLES:
                    await _mining_tick(db, client, ship_symbol, ship_data)
                elif role in HAULING_ROLES:
                    await _hauling_tick(db, client, ship_symbol, ship_data)
                else:
                    # SATELLITE / PROBE — do nothing, market_poller handles it
                    await asyncio.sleep(30)

            except SpaceTradersError as exc:
                log.warning("ship_loop_api_error", ship=ship_symbol, error=str(exc))
                await asyncio.sleep(10)
            except Exception as exc:
                log.error("ship_loop_error", ship=ship_symbol, error=str(exc))
                await asyncio.sleep(15)
    finally:
        await db.close()
        log.info("ship_loop_stop", ship=ship_symbol)


async def _mining_tick(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
) -> None:
    cargo_units: int = ship_data.get("cargo_units") or 0
    cargo_capacity: int = ship_data.get("cargo_capacity") or 1
    nav_status: str = ship_data.get("nav_status") or ""
    ship_data.get("nav_waypoint") or ""

    # If cargo almost full, go sell
    if cargo_units >= cargo_capacity * 0.9:
        log.info("cargo_full_hauling", ship=symbol)
        await _haul_and_sell(db, client, symbol, ship_data)
        return

    # Need to be in orbit to extract
    if nav_status == "DOCKED":
        await client.orbit(symbol)
        ship_data["nav_status"] = "IN_ORBIT"

    try:
        extraction = await client.extract(symbol)
        log.info(
            "extracted",
            ship=symbol,
            good=extraction.yield_.symbol,
            units=extraction.yield_.units,
        )
        updated = await client.get_ship(symbol)
        await queries.upsert_ship(db, updated)
    except SpaceTradersError as exc:
        if exc.code == 4000:
            # Cooldown — the ship state will have cooldown_expires set now
            updated = await client.get_ship(symbol)
            await queries.upsert_ship(db, updated)
        else:
            log.warning("extract_error", ship=symbol, error=str(exc))
            await asyncio.sleep(5)


async def _haul_and_sell(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
) -> None:
    system = ship_data.get("nav_waypoint", "").rsplit("-", 1)[0]

    # Find a marketplace waypoint in this system
    marketplaces = await queries.get_waypoints_by_type(db, system, "ORBITAL_STATION")
    if not marketplaces:
        marketplaces = await queries.get_waypoints_by_type(db, system, "PLANET")
    if not marketplaces:
        log.warning("no_marketplace_found", ship=symbol, system=system)
        await asyncio.sleep(30)
        return

    target_wp = marketplaces[0]["symbol"]
    current_wp = ship_data.get("nav_waypoint", "")

    if current_wp != target_wp:
        nav_status = ship_data.get("nav_status", "")
        if nav_status == "DOCKED":
            await client.orbit(symbol)
        try:
            nav = await client.navigate(symbol, target_wp)
            updated = await client.get_ship(symbol)
            await queries.upsert_ship(db, updated)
            wait = _seconds_until(nav.arrival_time.isoformat() if nav.arrival_time else None)
            if wait > 0:
                await asyncio.sleep(wait + 1)
        except SpaceTradersError as exc:
            log.warning("navigate_error", ship=symbol, error=str(exc))
            return

    # Dock and sell
    updated_ship = await client.get_ship(symbol)
    await queries.upsert_ship(db, updated_ship)
    if updated_ship.nav.status != "DOCKED":
        await client.dock(symbol)

    fresh = await queries.get_ship(db, symbol)
    if fresh:
        await _sell_all_cargo(db, client, symbol, fresh)

    updated = await client.get_ship(symbol)
    await queries.upsert_ship(db, updated)


async def _hauling_tick(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
) -> None:
    # COMMAND/HAULER ships: if they have cargo, sell it; otherwise idle
    cargo_units: int = ship_data.get("cargo_units") or 0
    if cargo_units > 0:
        await _haul_and_sell(db, client, symbol, ship_data)
    else:
        await asyncio.sleep(10)
