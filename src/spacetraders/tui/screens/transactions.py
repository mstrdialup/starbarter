"""Transaction log widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static


class TransactionsScreen(Widget):
    DEFAULT_CSS = """
    TransactionsScreen {
        layout: vertical;
        height: 1fr;
    }
    TransactionsScreen DataTable {
        height: 1fr;
    }
    TransactionsScreen #tx_summary {
        height: 2;
        border-top: solid $primary-darken-2;
        background: $surface;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield DataTable(id="tx_table", cursor_type="row")
        yield Static(id="tx_summary")

    def on_mount(self) -> None:
        table = self.query_one("#tx_table", DataTable)
        table.add_columns("Ship", "Type", "Good", "Units", "Price/u", "Total", "Waypoint", "Time")
        self.set_interval(2.0, self.refresh_data)
        self.refresh_data()

    def refresh_data(self) -> None:
        self.app.call_later(self._async_refresh)

    async def _async_refresh(self) -> None:
        from spacetraders.db import queries

        db = self.app.db  # type: ignore[attr-defined]
        txs = await queries.get_recent_transactions(db, limit=100)

        table = self.query_one("#tx_table", DataTable)
        table.clear()

        total_pnl = 0
        for tx in txs:
            tx_type = tx.get("type", "?")
            total = tx.get("total") or 0
            if tx_type == "SELL":
                total_pnl += total
                color = "green"
            elif tx_type == "BUY":
                total_pnl -= total
                color = "red"
            else:
                color = "white"

            ts = (tx.get("timestamp") or "")[:16].replace("T", " ")
            table.add_row(
                tx.get("ship_symbol", "?"),
                f"[{color}]{tx_type}[/{color}]",
                tx.get("trade_symbol") or "?",
                str(tx.get("units") or "?"),
                str(tx.get("price_per_unit") or "?"),
                f"[{color}]{total:,}[/{color}]",
                tx.get("waypoint") or "?",
                ts,
            )

        pnl_color = "green" if total_pnl >= 0 else "red"
        self.query_one("#tx_summary", Static).update(
            f"Net P&L (last 100): [{pnl_color}]{total_pnl:+,}[/{pnl_color}]"
        )
