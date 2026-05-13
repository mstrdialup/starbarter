"""Fleet overview widget."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Static


def _seconds_until(iso_ts: str | None) -> float:
    if not iso_ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0.0, (dt - datetime.now(UTC)).total_seconds())
    except (ValueError, TypeError):
        return 0.0


def _status_style(ship: dict[str, Any]) -> str:
    status = ship.get("nav_status", "")
    fuel_pct = (ship.get("fuel_current") or 0) / max(ship.get("fuel_capacity") or 1, 1)
    cooldown = _seconds_until(ship.get("cooldown_expires"))
    if cooldown > 0.5:
        return "red"
    if fuel_pct < 0.2 and (ship.get("fuel_capacity") or 0) > 0:
        return "red"
    if status == "IN_TRANSIT":
        return "yellow"
    return "green"


class FleetScreen(Widget):
    BINDINGS = [
        Binding("o", "cmd_orbit", "Orbit"),
        Binding("d", "cmd_dock", "Dock"),
        Binding("n", "cmd_navigate", "Navigate"),
        Binding("e", "cmd_extract", "Extract"),
        Binding("s", "cmd_sell", "Sell"),
        Binding("r", "cmd_refuel", "Refuel"),
    ]

    DEFAULT_CSS = """
    FleetScreen {
        layout: vertical;
        height: 1fr;
    }
    FleetScreen DataTable {
        height: 1fr;
    }
    FleetScreen #ship_detail {
        height: 6;
        border-top: solid $primary-darken-2;
        background: $surface;
        padding: 0 1;
    }
    FleetScreen #agent_bar {
        height: 1;
        background: $primary-darken-3;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="agent_bar")
        yield DataTable(id="ship_table", cursor_type="row")
        yield Static(id="ship_detail")

    def on_mount(self) -> None:
        table = self.query_one("#ship_table", DataTable)
        table.add_columns("Ship", "Role", "Status", "Location", "Fuel", "Cargo")
        self.set_interval(2.0, self.refresh_data)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.app.call_later(self._async_refresh)

    async def _async_refresh(self) -> None:
        from spacetraders.db import queries

        db = self.app.db  # type: ignore[attr-defined]
        ships = await queries.get_all_ships(db)
        agent = await queries.get_agent(db)

        if agent:
            credits = f"{agent['credits']:,}"
            self.query_one("#agent_bar", Static).update(
                f"Agent: {agent['symbol']} | Credits: {credits} | Ships: {agent['ship_count']}"
            )

        table = self.query_one("#ship_table", DataTable)
        table.clear()

        for ship in ships:
            status = ship.get("nav_status", "?")
            location = ship.get("nav_waypoint", "?")
            if status == "IN_TRANSIT":
                wait = _seconds_until(ship.get("arrival_time"))
                location = f"→ {location} ({round(wait)}s)"

            fuel_cur = ship.get("fuel_current") or 0
            fuel_cap = ship.get("fuel_capacity") or 0
            cargo_cur = ship.get("cargo_units") or 0
            cargo_cap = ship.get("cargo_capacity") or 0

            style = _status_style(ship)
            table.add_row(
                f"[{style}]{ship['symbol']}[/]",
                ship.get("role") or "?",
                f"[{style}]{status}[/]",
                location,
                f"{fuel_cur}/{fuel_cap}",
                f"{cargo_cur}/{cargo_cap}",
                key=ship["symbol"],
            )

        await self._update_detail(ships)

    async def _update_detail(self, ships: list[dict[str, Any]]) -> None:
        table = self.query_one("#ship_table", DataTable)
        detail = self.query_one("#ship_detail", Static)

        if not ships or table.cursor_row < 0:
            detail.update("")
            return

        idx = min(table.cursor_row, len(ships) - 1)
        ship = ships[idx]

        cooldown_s = _seconds_until(ship.get("cooldown_expires"))
        cooldown_str = f"{round(cooldown_s)}s" if cooldown_s > 0.5 else "ready"

        inventory = json.loads(ship.get("cargo_inventory") or "[]")
        cargo_str = ", ".join(f"{i['symbol']} ×{i['units']}" for i in inventory) or "(empty)"

        cf = ship.get("condition_frame") or 1.0
        ce = ship.get("condition_engine") or 1.0
        cr = ship.get("condition_reactor") or 1.0

        detail.update(
            f"[bold]{ship['symbol']}[/bold]  {ship.get('role', '')}  {ship.get('nav_status', '')}\n"
            f"Cargo: {cargo_str}\n"
            f"Cooldown: {cooldown_str}\n"
            f"Condition: frame {cf:.2f} | engine {ce:.2f} | reactor {cr:.2f}"
        )

    async def _enqueue(self, command: str, params: dict[str, Any]) -> None:
        from spacetraders.db import queries

        table = self.query_one("#ship_table", DataTable)
        ships = await queries.get_all_ships(self.app.db)  # type: ignore[attr-defined]
        if not ships or table.cursor_row < 0:
            return
        idx = min(table.cursor_row, len(ships) - 1)
        ship_symbol = ships[idx]["symbol"]
        await queries.enqueue_command(self.app.db, ship_symbol, command, params)  # type: ignore[attr-defined]
        self.app.notify(f"Queued {command} for {ship_symbol}")

    async def action_cmd_orbit(self) -> None:
        await self._enqueue("orbit", {})

    async def action_cmd_dock(self) -> None:
        await self._enqueue("dock", {})

    async def action_cmd_extract(self) -> None:
        await self._enqueue("extract", {})

    async def action_cmd_refuel(self) -> None:
        await self._enqueue("refuel", {})

    async def action_cmd_navigate(self) -> None:
        from spacetraders.tui.widgets.command_input import CommandInputModal

        waypoint = await self.app.push_screen_wait(
            CommandInputModal("Navigate to waypoint:", placeholder="X1-DF55-B3")
        )
        if waypoint:
            await self._enqueue("navigate", {"waypoint": waypoint})

    async def action_cmd_sell(self) -> None:
        from spacetraders.tui.widgets.command_input import CommandInputModal

        symbol = await self.app.push_screen_wait(
            CommandInputModal("Sell trade symbol:", placeholder="IRON_ORE")
        )
        if not symbol:
            return
        units_str = await self.app.push_screen_wait(
            CommandInputModal("Units to sell:", placeholder="10")
        )
        if units_str and units_str.isdigit():
            await self._enqueue("sell", {"symbol": symbol, "units": int(units_str)})
