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

# Minimum credit balance to maintain — operations that would breach this floor are skipped.
MIN_CREDIT_RESERVE = 10_000

# Per-ship set of waypoints that are beyond this ship's maximum fuel range.
# Populated at runtime; reset on bot restart.
_permanently_unreachable: dict[str, set[str]] = {}


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
    waypoint = ship_data.get("nav_waypoint") or "?"
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
            await queries.insert_bot_activity(
                db, symbol, "sold",
                f"{units}x {trade_symbol} for {tx.total_price:,} cr at {waypoint}",
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
                ctrl = await queries.get_bot_control(db)

                ship_data = await queries.get_ship(db, ship_symbol)
                if ship_data is None:
                    await asyncio.sleep(5)
                    continue

                # Global pause / per-ship pause
                if ctrl.get("global_pause") == "true" or ship_data.get("paused"):
                    await queries.update_ship_last_action(db, ship_symbol, "Paused")
                    await asyncio.sleep(2)
                    continue

                role = (ship_data.get("role") or "").upper()

                # Wait out transit
                if ship_data["nav_status"] == "IN_TRANSIT":
                    wait = _seconds_until(ship_data.get("arrival_time"))
                    if wait > 0:
                        log.info("ship_in_transit", ship=ship_symbol, wait_s=round(wait))
                        await queries.update_ship_last_action(
                            db, ship_symbol,
                            f"→ {ship_data.get('nav_waypoint', '?')} (ETA {round(wait)}s)",
                        )
                        await asyncio.sleep(min(wait + 1, 30))
                    # Always refresh from API after transit (including when arrival is overdue)
                    updated = await client.get_ship(ship_symbol)
                    await queries.upsert_ship(db, updated)
                    continue

                # Wait out cooldown
                cooldown_wait = _seconds_until(ship_data.get("cooldown_expires"))
                if cooldown_wait > 0.5:
                    log.debug("ship_on_cooldown", ship=ship_symbol, wait_s=round(cooldown_wait))
                    await queries.update_ship_last_action(
                        db, ship_symbol, f"Cooldown {round(cooldown_wait)}s"
                    )
                    await asyncio.sleep(min(cooldown_wait, 30))
                    continue

                if role in MINING_ROLES:
                    if ctrl.get("mining_enabled", "true") == "false":
                        await queries.update_ship_last_action(db, ship_symbol, "Mining paused")
                        await asyncio.sleep(10)
                        continue
                    await _mining_tick(db, client, ship_symbol, ship_data)
                elif role in HAULING_ROLES:
                    await _hauling_tick(db, client, ship_symbol, ship_data, ctrl=ctrl)
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
    current_wp = ship_data.get("nav_waypoint") or ""

    # If cargo almost full, go sell
    if cargo_units >= cargo_capacity * 0.9:
        log.info("cargo_full_hauling", ship=symbol)
        await _haul_and_sell(db, client, symbol, ship_data)
        return

    # Need to be in orbit to extract
    if nav_status == "DOCKED":
        await client.orbit(symbol)
        orbited = await client.get_ship(symbol)
        await queries.upsert_ship(db, orbited)
        nav_status = orbited.nav.status

    await queries.update_ship_last_action(db, symbol, f"Extracting at {current_wp}")

    try:
        extraction = await client.extract(symbol)
        log.info(
            "extracted",
            ship=symbol,
            good=extraction.yield_.symbol,
            units=extraction.yield_.units,
        )
        await queries.insert_bot_activity(
            db, symbol, "extracted",
            f"{extraction.yield_.units}x {extraction.yield_.symbol} at {current_wp}",
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
            await queries.insert_bot_activity(db, symbol, "error", f"extract failed: {exc}")
            await asyncio.sleep(5)


async def _refuel_if_needed(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
) -> None:
    """Refuel the ship if fuel is below 80% capacity. Must be docked."""
    ship_data = await queries.get_ship(db, symbol)
    if not ship_data:
        return
    fuel_current: int = ship_data.get("fuel_current") or 0
    fuel_capacity: int = ship_data.get("fuel_capacity") or 0
    if fuel_capacity == 0:
        return
    if fuel_current / fuel_capacity < 0.8:
        agent = await queries.get_agent(db)
        credits: int = agent["credits"] if agent else 0
        if credits <= MIN_CREDIT_RESERVE:
            log.warning("low_credits_skip_refuel", ship=symbol, credits=credits, reserve=MIN_CREDIT_RESERVE)
            await queries.insert_bot_activity(db, symbol, "warning", "skipped refuel: below credit reserve")
            return
        try:
            await client.refuel(symbol)
            updated = await client.get_ship(symbol)
            await queries.upsert_ship(db, updated)
            log.info("refueled", ship=symbol, fuel=updated.fuel.current, capacity=updated.fuel.capacity)
            await queries.insert_bot_activity(
                db, symbol, "refueled",
                f"{updated.fuel.current}/{updated.fuel.capacity} at {ship_data.get('nav_waypoint', '?')}",
            )
        except SpaceTradersError as exc:
            log.warning("refuel_failed", ship=symbol, error=str(exc))


async def _haul_and_sell(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
    target_wp: str | None = None,
) -> None:
    system = ship_data.get("nav_waypoint", "").rsplit("-", 1)[0]

    if target_wp is None:
        marketplaces = await queries.get_market_waypoints(db, system)
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
            orbited = await client.get_ship(symbol)
            await queries.upsert_ship(db, orbited)
        await queries.update_ship_last_action(db, symbol, f"Hauling to {target_wp}")
        await queries.insert_bot_activity(db, symbol, "navigating", f"→ {target_wp}")
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
    await queries.update_ship_last_action(db, symbol, f"Selling at {target_wp}")
    updated_ship = await client.get_ship(symbol)
    await queries.upsert_ship(db, updated_ship)
    if updated_ship.nav.status != "DOCKED":
        await client.dock(symbol)
        updated_ship = await client.get_ship(symbol)
        await queries.upsert_ship(db, updated_ship)

    await _refuel_if_needed(db, client, symbol)

    fresh = await queries.get_ship(db, symbol)
    if fresh:
        await _sell_all_cargo(db, client, symbol, fresh)

    updated = await client.get_ship(symbol)
    await queries.upsert_ship(db, updated)


def _is_fuel_error(exc: SpaceTradersError) -> bool:
    """True for any 'insufficient fuel' API error (code 4204 or message match)."""
    msg = str(exc).lower()
    return exc.code == 4204 or "more fuel" in msg or ("fuel" in msg and "navigation" in msg)


async def _price_discovery(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
    system: str,
) -> None:
    """Navigate to markets that have no price data yet so the market poller can collect prices."""
    unreachable = _permanently_unreachable.setdefault(symbol, set())

    all_unvisited = await queries.get_unvisited_market_waypoints(db, system)
    # Filter out waypoints known to be beyond max fuel range
    candidates = [w for w in all_unvisited if w["symbol"] not in unreachable]

    if not candidates:
        if all_unvisited:
            log.info(
                "all_unvisited_out_of_range",
                ship=symbol, skipped=len(all_unvisited), system=system,
            )
        else:
            log.info("no_trade_route_found", ship=symbol, system=system)
        await asyncio.sleep(60)
        return

    # Sort candidates by distance from current position (closest first)
    current_wp = ship_data.get("nav_waypoint", "")
    ref = await queries.get_waypoint_coords(db, current_wp)
    if ref:
        cx, cy = ref
        candidates.sort(key=lambda w: (w["x"] - cx) ** 2 + (w["y"] - cy) ** 2)

    target = candidates[0]["symbol"]
    log.info("price_discovery_navigate", ship=symbol, target=target, remaining=len(candidates))
    await queries.insert_bot_activity(
        db, symbol, "discovery", f"exploring {target} ({len(candidates)} unvisited)"
    )
    await queries.update_ship_last_action(db, symbol, f"Discovery → {target}")

    current_wp = ship_data.get("nav_waypoint", "")
    if current_wp == target:
        # Already there — just wait for the market poller
        pass
    else:
        if ship_data.get("nav_status") == "DOCKED":
            await client.orbit(symbol)
            orbited = await client.get_ship(symbol)
            await queries.upsert_ship(db, orbited)

        nav_succeeded = False
        try:
            nav = await client.navigate(symbol, target)
            updated = await client.get_ship(symbol)
            await queries.upsert_ship(db, updated)
            wait = _seconds_until(nav.arrival_time.isoformat() if nav.arrival_time else None)
            if wait > 0:
                log.info("transit_price_discovery", ship=symbol, wait_s=round(wait), target=target)
                await asyncio.sleep(wait + 1)
            nav_succeeded = True
        except SpaceTradersError as exc:
            log.warning(
                "price_discovery_nav_failed",
                ship=symbol, target=target, error=str(exc), code=exc.code,
            )
            if _is_fuel_error(exc):
                # Dock and force-refuel to full, then retry once
                log.info("price_discovery_refuel_attempt", ship=symbol, target=target)
                try:
                    fresh = await queries.get_ship(db, symbol)
                    if fresh and fresh.get("nav_status") != "DOCKED":
                        await client.dock(symbol)
                        docked = await client.get_ship(symbol)
                        await queries.upsert_ship(db, docked)
                    agent = await queries.get_agent(db)
                    if (agent or {}).get("credits", 0) > MIN_CREDIT_RESERVE:
                        await client.refuel(symbol)
                        refueled = await client.get_ship(symbol)
                        await queries.upsert_ship(db, refueled)
                        log.info(
                            "refueled_for_discovery",
                            ship=symbol,
                            fuel=refueled.fuel.current,
                            capacity=refueled.fuel.capacity,
                        )
                    await client.orbit(symbol)
                    orbited = await client.get_ship(symbol)
                    await queries.upsert_ship(db, orbited)
                except SpaceTradersError as refuel_exc:
                    log.warning("refuel_for_discovery_failed", ship=symbol, error=str(refuel_exc))
                    return

                # Retry navigation after refueling
                try:
                    nav = await client.navigate(symbol, target)
                    updated = await client.get_ship(symbol)
                    await queries.upsert_ship(db, updated)
                    wait = _seconds_until(nav.arrival_time.isoformat() if nav.arrival_time else None)
                    if wait > 0:
                        await asyncio.sleep(wait + 1)
                    nav_succeeded = True
                except SpaceTradersError as exc2:
                    log.warning(
                        "price_discovery_nav_retry_failed",
                        ship=symbol, target=target, error=str(exc2), code=exc2.code,
                    )
                    if _is_fuel_error(exc2):
                        # Still can't reach even at full fuel — permanently out of range
                        unreachable.add(target)
                        log.warning(
                            "waypoint_permanently_unreachable",
                            ship=symbol, target=target,
                        )
                        await queries.insert_bot_activity(
                            db, symbol, "warning",
                            f"{target} out of range (beyond fuel capacity), skipped",
                        )
            else:
                await asyncio.sleep(10)

        if not nav_succeeded:
            return

    # Wait for the market poller to collect prices at this location (polls every 60s)
    log.info("waiting_for_market_data", ship=symbol, waypoint=target)
    for _ in range(9):
        await asyncio.sleep(10)
        if await queries.get_market_latest(db, target):
            log.info("market_data_collected", ship=symbol, waypoint=target)
            return
    log.warning("market_data_timeout", ship=symbol, waypoint=target)


async def _hauling_tick(
    db: aiosqlite.Connection,
    client: SpaceTradersClient,
    symbol: str,
    ship_data: dict[str, Any],
    ctrl: dict[str, str] | None = None,
) -> None:
    ctrl = ctrl or {}
    cargo_units: int = ship_data.get("cargo_units") or 0
    cargo_capacity: int = ship_data.get("cargo_capacity") or 40

    # If we already have cargo from a previous run, sell it first
    if cargo_units > 0:
        await _haul_and_sell(db, client, symbol, ship_data)
        return

    system = ship_data.get("nav_waypoint", "").rsplit("-", 1)[0]

    # Feature toggle: trading
    if ctrl.get("trading_enabled", "true") == "false":
        await queries.update_ship_last_action(db, symbol, "Trading paused")
        await asyncio.sleep(30)
        return

    route = await queries.get_best_trade_route(db, system, cargo_capacity)
    if route is None:
        # Feature toggle: price discovery
        if ctrl.get("price_discovery_enabled", "true") == "false":
            await queries.update_ship_last_action(db, symbol, "Trading paused")
            await asyncio.sleep(30)
            return
        await _price_discovery(db, client, symbol, ship_data, system)
        return

    log.info(
        "trade_route_selected",
        ship=symbol,
        buy=route["buy_waypoint"],
        sell=route["sell_waypoint"],
        good=route["trade_symbol"],
        units=route["units"],
        profit_per_unit=route["profit_per_unit"],
    )
    buy_short = route["buy_waypoint"].split("-")[-1]
    sell_short = route["sell_waypoint"].split("-")[-1]
    await queries.insert_bot_activity(
        db, symbol, "trade_route",
        f"{route['trade_symbol']} {buy_short}→{sell_short} +{route['profit_per_unit']}/unit",
    )

    # Navigate to buy location if not already there
    current_wp = ship_data.get("nav_waypoint", "")
    if current_wp != route["buy_waypoint"]:
        if ship_data.get("nav_status") == "DOCKED":
            await client.orbit(symbol)
            orbited = await client.get_ship(symbol)
            await queries.upsert_ship(db, orbited)
        await queries.update_ship_last_action(db, symbol, f"→ {route['buy_waypoint']}")
        await queries.insert_bot_activity(db, symbol, "navigating", f"→ {route['buy_waypoint']}")
        try:
            nav = await client.navigate(symbol, route["buy_waypoint"])
            updated = await client.get_ship(symbol)
            await queries.upsert_ship(db, updated)
            wait = _seconds_until(nav.arrival_time.isoformat() if nav.arrival_time else None)
            if wait > 0:
                log.info("transit_to_buy", ship=symbol, wait_s=round(wait))
                await asyncio.sleep(wait + 1)
        except SpaceTradersError as exc:
            log.warning("navigate_to_buy_failed", ship=symbol, error=str(exc))
            await asyncio.sleep(10)
            return

    # Dock and buy
    await queries.update_ship_last_action(db, symbol, f"Buying {route['trade_symbol']} at {route['buy_waypoint']}")
    fresh = await client.get_ship(symbol)
    await queries.upsert_ship(db, fresh)
    if fresh.nav.status != "DOCKED":
        await client.dock(symbol)
        fresh = await client.get_ship(symbol)
        await queries.upsert_ship(db, fresh)

    await _refuel_if_needed(db, client, symbol)

    agent = await queries.get_agent(db)
    credits: int = agent["credits"] if agent else 0
    purchase_cost = route["buy_price"] * route["units"]
    if credits - purchase_cost < MIN_CREDIT_RESERVE:
        log.warning(
            "low_credits_skip_trade",
            ship=symbol,
            credits=credits,
            purchase_cost=purchase_cost,
            reserve=MIN_CREDIT_RESERVE,
        )
        await queries.insert_bot_activity(db, symbol, "warning", "skipped trade: below credit reserve")
        await asyncio.sleep(60)
        return

    try:
        tx = await client.purchase_cargo(symbol, route["trade_symbol"], route["units"])
        await queries.insert_transaction(
            db,
            ship_symbol=symbol,
            tx_type="BUY",
            trade_symbol=tx.trade_symbol,
            units=tx.units,
            price_per_unit=tx.price_per_unit,
            total=tx.total_price,
            waypoint=tx.waypoint_symbol,
            timestamp=tx.timestamp.isoformat(),
        )
        log.info("bought_cargo", ship=symbol, good=route["trade_symbol"], units=route["units"])
        await queries.insert_bot_activity(
            db, symbol, "bought",
            f"{tx.units}x {tx.trade_symbol} for {tx.total_price:,} cr at {route['buy_waypoint']}",
        )
    except SpaceTradersError as exc:
        log.warning("buy_failed", ship=symbol, error=str(exc))
        await asyncio.sleep(10)
        return

    updated = await client.get_ship(symbol)
    await queries.upsert_ship(db, updated)

    # Sell at the intended destination from the route
    fresh_data = await queries.get_ship(db, symbol)
    if fresh_data:
        await _haul_and_sell(db, client, symbol, fresh_data, target_wp=route["sell_waypoint"])
