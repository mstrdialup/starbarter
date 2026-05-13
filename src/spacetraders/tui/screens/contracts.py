"""Contracts widget."""

from __future__ import annotations

import json
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Static


def _parse_terms(terms_json: str) -> dict[str, Any]:
    try:
        return json.loads(terms_json)
    except (json.JSONDecodeError, TypeError):
        return {}


class ContractsScreen(Widget):
    BINDINGS = [
        Binding("a", "accept_contract", "Accept"),
    ]

    DEFAULT_CSS = """
    ContractsScreen {
        layout: vertical;
        height: 1fr;
    }
    ContractsScreen DataTable {
        height: 1fr;
    }
    ContractsScreen #contract_detail {
        height: 8;
        border-top: solid $primary-darken-2;
        background: $surface;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield DataTable(id="contract_table", cursor_type="row")
        yield Static(id="contract_detail")

    def on_mount(self) -> None:
        table = self.query_one("#contract_table", DataTable)
        table.add_columns("ID", "Type", "Faction", "Deadline", "Status")
        self.set_interval(2.0, self.refresh_data)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.app.call_later(self._async_refresh)

    async def _async_refresh(self) -> None:
        from spacetraders.db import queries

        db = self.app.db  # type: ignore[attr-defined]
        contracts = await queries.get_contracts(db)

        table = self.query_one("#contract_table", DataTable)
        table.clear()

        for c in contracts:
            if c.get("fulfilled"):
                status = "[green]Fulfilled[/green]"
            elif c.get("accepted"):
                status = "[yellow]In Progress[/yellow]"
            else:
                status = "[dim]Not Accepted[/dim]"

            deadline = (c.get("deadline") or "")[:16].replace("T", " ")
            short_id = c["id"][:12]

            table.add_row(
                short_id, c.get("type", "?"), c.get("faction", "?"), deadline, status, key=c["id"]
            )

        await self._update_detail(contracts)

    async def _update_detail(self, contracts: list[dict[str, Any]]) -> None:
        table = self.query_one("#contract_table", DataTable)
        detail = self.query_one("#contract_detail", Static)

        if not contracts or table.cursor_row < 0:
            detail.update("")
            return

        idx = min(table.cursor_row, len(contracts) - 1)
        c = contracts[idx]
        terms = _parse_terms(c.get("terms") or "{}")
        deliverables = terms.get("deliver", [])
        payment = terms.get("payment", {})

        lines = [f"[bold]{c['id']}[/bold]  {c.get('type', '')}  ({c.get('faction', '')})"]
        for d in deliverables:
            lines.append(
                f"  → Deliver {d.get('unitsRequired', 0)} {d.get('tradeSymbol', '')} "
                f"to {d.get('destinationSymbol', '')} "
                f"({d.get('unitsFulfilled', 0)}/{d.get('unitsRequired', 0)} done)"
            )
        if payment:
            lines.append(
                f"  Payment: {payment.get('onAccepted', 0):,} on accept + "
                f"{payment.get('onFulfilled', 0):,} on fulfill"
            )

        detail.update("\n".join(lines))

    async def action_accept_contract(self) -> None:
        from spacetraders.db import queries

        table = self.query_one("#contract_table", DataTable)
        contracts = await queries.get_contracts(self.app.db)  # type: ignore[attr-defined]
        if not contracts or table.cursor_row < 0:
            return
        idx = min(table.cursor_row, len(contracts) - 1)
        c = contracts[idx]
        if c.get("accepted"):
            self.app.notify("Contract already accepted.")
            return
        await queries.enqueue_command(
            self.app.db,
            None,
            "accept_contract",
            {"contract_id": c["id"]},  # type: ignore[attr-defined]
        )
        self.app.notify(f"Queued accept_contract for {c['id'][:12]}")
