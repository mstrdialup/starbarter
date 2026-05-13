"""Markets widget."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static


def _staleness(snapshot_ts: str | None) -> str:
    if not snapshot_ts:
        return "unknown"
    try:
        dt = datetime.fromisoformat(snapshot_ts.replace("Z", "+00:00"))
        age_s = (datetime.now(UTC) - dt).total_seconds()
        if age_s < 60:
            return f"{round(age_s)}s ago"
        if age_s < 3600:
            return f"{round(age_s / 60)}m ago"
        return f"{round(age_s / 3600)}h ago [red]stale[/red]"
    except (ValueError, TypeError):
        return "?"


def _compute_routes(rows: list[dict[str, Any]]) -> list[str]:
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
            spread = (imp.get("sell_price") or 0) - (exp.get("purchase_price") or 0)
            if spread > 0:
                routes.append(
                    f"  {symbol}: {exp['waypoint']} (buy {exp.get('purchase_price')}) → "
                    f"{imp['waypoint']} (sell {imp.get('sell_price')}) = +{spread}/unit"
                )
    routes.sort(key=lambda x: -int(x.split("+")[1].split("/")[0]))
    return routes[:5]


class MarketsScreen(Widget):
    DEFAULT_CSS = """
    MarketsScreen {
        layout: vertical;
        height: 1fr;
    }
    MarketsScreen DataTable {
        height: 1fr;
    }
    MarketsScreen #routes_panel {
        height: 8;
        border-top: solid $primary-darken-2;
        background: $surface;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield DataTable(id="market_table", cursor_type="row")
        yield Static(id="routes_panel")

    def on_mount(self) -> None:
        table = self.query_one("#market_table", DataTable)
        table.add_columns("Waypoint", "Good", "Type", "Supply", "Buy", "Sell", "Vol", "Updated")
        self.set_interval(5.0, self.refresh_data)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.app.call_later(self._async_refresh)

    async def _async_refresh(self) -> None:
        from spacetraders.db import queries

        db = self.app.db  # type: ignore[attr-defined]
        rows = await queries.get_all_market_latest(db)

        table = self.query_one("#market_table", DataTable)
        table.clear()

        for r in rows:
            age_s = 0.0
            ts = r.get("snapshot_ts")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    age_s = (datetime.now(UTC) - dt).total_seconds()
                except (ValueError, TypeError):
                    pass

            stale_open = "[red]" if age_s > 300 else ""
            stale_close = "[/red]" if age_s > 300 else ""

            table.add_row(
                r.get("waypoint", ""),
                f"{stale_open}{r.get('trade_symbol', '')}{stale_close}",
                r.get("type") or "?",
                r.get("supply") or "?",
                str(r.get("purchase_price") or "?"),
                str(r.get("sell_price") or "?"),
                str(r.get("trade_volume") or "?"),
                _staleness(r.get("snapshot_ts")),
            )

        routes = _compute_routes(rows)
        routes_panel = self.query_one("#routes_panel", Static)
        if routes:
            routes_panel.update("Profitable routes:\n" + "\n".join(routes))
        else:
            routes_panel.update("No profitable routes found yet.")
