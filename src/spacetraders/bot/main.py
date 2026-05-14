"""Bot entry point — supervisor loop."""

from __future__ import annotations

import asyncio
import sys

import structlog

from spacetraders import config
from spacetraders.api.client import SpaceTradersClient, SpaceTradersError
from spacetraders.db import queries
from spacetraders.db.connection import get_db, init_db

log = structlog.get_logger()

_AGENT_SYMBOL = "STARBARTER"
_FACTION = "COSMIC"


def _configure_logging() -> None:
    import logging

    import structlog

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


async def _bootstrap(db, client: SpaceTradersClient) -> str:
    """Register or re-use existing token. Returns agent symbol."""
    token = config.TOKEN
    if not token:
        log.info("registering_new_agent", symbol=_AGENT_SYMBOL)
        try:
            reg = await client.register(_AGENT_SYMBOL, _FACTION)
            token = reg.token
            log.info("registered", symbol=reg.agent.symbol, token=token[:8] + "...")
        except SpaceTradersError as exc:
            if exc.code == 4111:
                log.info("agent_already_exists_using_stored_token")
            else:
                raise

    agent = await client.get_agent()
    await queries.upsert_agent(db, agent)
    return agent.symbol


async def _fetch_and_store_universe(db, client: SpaceTradersClient, system_symbol: str) -> None:
    log.info("fetching_system", system=system_symbol)
    system = await client.get_system(system_symbol)
    await queries.upsert_system(db, system)
    log.info("fetching_waypoints", system=system_symbol)
    waypoints = await client.get_waypoints(system_symbol)
    for wp in waypoints:
        await queries.upsert_waypoint(db, wp)
    log.info("waypoints_stored", count=len(waypoints))


async def _command_queue_consumer(
    db_path: str,
    client: SpaceTradersClient,
    stop_event: asyncio.Event,
) -> None:
    from spacetraders.bot.commands import execute_command

    db = await get_db(db_path)
    try:
        while not stop_event.is_set():
            cmd = await queries.claim_next_command(db)
            if cmd:
                await execute_command(db, client, cmd)
            else:
                await asyncio.sleep(1)
    finally:
        await db.close()


async def _market_poller(
    db_path: str,
    client: SpaceTradersClient,
    system_symbol: str,
    stop_event: asyncio.Event,
) -> None:
    db = await get_db(db_path)
    try:
        while not stop_event.is_set():
            try:
                waypoints = await queries.get_market_waypoints(db, system_symbol)
                for wp in waypoints:
                    wp_symbol = wp["symbol"]
                    try:
                        market = await client.get_market(system_symbol, wp_symbol)
                        if market.trade_goods:
                            await queries.insert_market_snapshot(db, wp_symbol, market.trade_goods)
                    except SpaceTradersError:
                        pass
            except Exception as exc:
                log.warning("market_poller_error", error=str(exc))
            await asyncio.sleep(60)
    finally:
        await db.close()


async def _agent_poller(
    db_path: str,
    client: SpaceTradersClient,
    stop_event: asyncio.Event,
) -> None:
    db = await get_db(db_path)
    try:
        while not stop_event.is_set():
            try:
                agent = await client.get_agent()
                await queries.upsert_agent(db, agent)
            except Exception as exc:
                log.warning("agent_poller_error", error=str(exc))
            await asyncio.sleep(30)
    finally:
        await db.close()


async def _check_reset(db, client: SpaceTradersClient) -> bool:
    """Return True if a new reset was detected (DB wiped)."""
    try:
        status = await client.get_status()
    except Exception as exc:
        log.warning("status_check_failed", error=str(exc))
        return False

    reset_date = status.reset_date
    stored = await queries.get_reset_meta(db)

    if stored and stored["reset_date"] == reset_date:
        return False

    if stored:
        log.warning("new_reset_detected", old=stored["reset_date"], new=reset_date)
        await queries.clear_all_reset_data(db)

    return True


async def _main() -> None:
    _configure_logging()
    db_path = config.DB_PATH
    await init_db(db_path)

    async with SpaceTradersClient(token=config.TOKEN) as client:
        db = await get_db(db_path)
        try:
            new_reset = await _check_reset(db, client)
            if new_reset:
                log.info("post_reset_bootstrap")

            agent_symbol = await _bootstrap(db, client)

            # Fetch ships and contracts
            ships = await client.list_ships()
            await queries.upsert_ships(db, ships)
            log.info("ships_loaded", count=len(ships))

            contracts = await client.list_contracts()
            for c in contracts:
                await queries.upsert_contract(db, c)
            log.info("contracts_loaded", count=len(contracts))

            # Determine home system
            agent = await queries.get_agent(db)
            hq = (agent or {}).get("headquarters", "")
            system_symbol = "-".join(hq.split("-")[:2]) if hq else ""
            if system_symbol:
                await _fetch_and_store_universe(db, client, system_symbol)

            # Store reset meta
            status = await client.get_status()
            await queries.upsert_reset_meta(db, status.reset_date, agent_symbol, config.TOKEN)
        finally:
            await db.close()

        stop_event = asyncio.Event()
        log.info("launching_tasks")

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_command_queue_consumer(db_path, client, stop_event))
            tg.create_task(_market_poller(db_path, client, system_symbol, stop_event))
            tg.create_task(_agent_poller(db_path, client, stop_event))
            for ship in ships:
                from spacetraders.bot.ships import run_ship_loop

                tg.create_task(run_ship_loop(ship.symbol, db_path, client, stop_event))


def run() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("bot_shutdown")
