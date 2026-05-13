from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, Query

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["markets"])


def _add_staleness(row: dict[str, Any]) -> dict[str, Any]:
    ts = row.get("snapshot_ts")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            row["staleness_seconds"] = round((datetime.now(UTC) - dt).total_seconds())
        except (ValueError, TypeError):
            row["staleness_seconds"] = None
    else:
        row["staleness_seconds"] = None
    return row


def _compute_routes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exports: dict[str, dict[str, Any]] = {}
    imports: dict[str, dict[str, Any]] = {}
    for r in rows:
        symbol = r.get("trade_symbol", "")
        tp = (r.get("type") or "").upper()
        if tp == "EXPORT":
            cur_buy = exports[symbol].get("purchase_price") or 0 if symbol in exports else None
            if cur_buy is None or (r.get("purchase_price") or 0) < cur_buy:
                exports[symbol] = r
        elif tp == "IMPORT":
            cur_sell = imports[symbol].get("sell_price") or 0 if symbol in imports else None
            if cur_sell is None or (r.get("sell_price") or 0) > cur_sell:
                imports[symbol] = r

    routes = []
    for symbol, exp in exports.items():
        if symbol in imports:
            imp = imports[symbol]
            buy_price = exp.get("purchase_price") or 0
            sell_price = imp.get("sell_price") or 0
            spread = sell_price - buy_price
            if spread > 0:
                spread_pct = round(spread / buy_price * 100, 1) if buy_price else 0
                routes.append(
                    {
                        "trade_symbol": symbol,
                        "buy_waypoint": exp["waypoint"],
                        "buy_price": buy_price,
                        "sell_waypoint": imp["waypoint"],
                        "sell_price": sell_price,
                        "spread": spread,
                        "spread_pct": spread_pct,
                    }
                )
    routes.sort(key=lambda x: -x["spread_pct"])
    return routes


@router.get("/markets")
async def list_markets(
    system: str | None = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    if system:
        rows = await queries.get_all_market_latest_for_system(db, system.upper())
    else:
        rows = await queries.get_all_market_latest(db)
    return [_add_staleness(r) for r in rows]


@router.get("/markets/routes")
async def market_routes(
    system: str | None = Query(default=None),
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    if system:
        rows = await queries.get_all_market_latest_for_system(db, system.upper())
    else:
        rows = await queries.get_all_market_latest(db)
    return _compute_routes(rows)
