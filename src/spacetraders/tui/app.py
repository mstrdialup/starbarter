"""SpaceTraders TUI entry point."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

import aiosqlite
import structlog
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from spacetraders.db.connection import get_db, init_db
from spacetraders.tui.screens.contracts import ContractsScreen
from spacetraders.tui.screens.fleet import FleetScreen
from spacetraders.tui.screens.markets import MarketsScreen
from spacetraders.tui.screens.transactions import TransactionsScreen

log = structlog.get_logger()


class CommandQueuePanel(Static):
    DEFAULT_CSS = """
    CommandQueuePanel {
        height: 5;
        border-top: solid $primary-darken-2;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    async def refresh_commands(self, db: aiosqlite.Connection) -> None:
        from spacetraders.db import queries

        cmds = await queries.get_recent_commands(db, limit=10)
        icons = {"pending": "⏳", "running": "▶", "done": "✓", "failed": "✗"}
        lines = []
        for cmd in cmds:
            icon = icons.get(cmd.get("status", ""), "?")
            ship = cmd.get("ship_symbol") or "-"
            command = cmd.get("command", "?")
            status = cmd.get("status", "?")
            if status == "failed":
                result = cmd.get("result") or ""
                lines.append(f"{icon} [{cmd['id']}] {ship} {command} [red]{result[:40]}[/red]")
            else:
                lines.append(f"{icon} [{cmd['id']}] {ship} {command} ({status})")
        self.update("\n".join(lines) if lines else "(no commands)")


class SpaceTradersApp(App):
    TITLE = "SpaceTraders"
    CSS_PATH = "app.tcss"
    BINDINGS = [
        Binding("f", "switch_to_fleet", "Fleet", show=True),
        Binding("c", "switch_to_contracts", "Contracts", show=True),
        Binding("m", "switch_to_markets", "Markets", show=True),
        Binding("t", "switch_to_transactions", "Log", show=True),
        Binding("question_mark", "help_overlay", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, db: aiosqlite.Connection) -> None:
        super().__init__()
        self.db = db

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="status_bar", classes="status-bar")
        with TabbedContent(initial="fleet"):
            with TabPane("Fleet [f]", id="fleet"):
                yield FleetScreen()
            with TabPane("Contracts [c]", id="contracts"):
                yield ContractsScreen()
            with TabPane("Markets [m]", id="markets"):
                yield MarketsScreen()
            with TabPane("Log [t]", id="transactions"):
                yield TransactionsScreen()
        yield CommandQueuePanel(id="cmd_queue_panel")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self._refresh_status)
        self.set_interval(2.0, self._refresh_cmd_panel)

    async def _refresh_status(self) -> None:
        from spacetraders.db import queries

        agent = await queries.get_agent(self.db)
        pending_cmds = await queries.get_pending_commands(self.db)
        pending_count = len(pending_cmds)

        bot_status = "[dim]bot: unknown[/dim]"
        if agent:
            updated_at = agent.get("updated_at") or ""
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                age_s = (datetime.now(UTC) - dt).total_seconds()
                if age_s < 60:
                    bot_status = "[green]bot: online[/green]"
                else:
                    bot_status = f"[red]bot: offline ({round(age_s)}s ago)[/red]"
            except (ValueError, TypeError):
                pass

        reset_meta = await queries.get_reset_meta(self.db)
        reset_str = ""
        if not reset_meta:
            reset_str = "  [yellow]No active session — start st-bot to register.[/yellow]"

        self.query_one("#status_bar", Static).update(
            f"{bot_status}  |  pending commands: {pending_count}{reset_str}"
        )

    async def _refresh_cmd_panel(self) -> None:
        panel = self.query_one("#cmd_queue_panel", CommandQueuePanel)
        await panel.refresh_commands(self.db)

    def action_switch_to_fleet(self) -> None:
        self.query_one(TabbedContent).active = "fleet"

    def action_switch_to_contracts(self) -> None:
        self.query_one(TabbedContent).active = "contracts"

    def action_switch_to_markets(self) -> None:
        self.query_one(TabbedContent).active = "markets"

    def action_switch_to_transactions(self) -> None:
        self.query_one(TabbedContent).active = "transactions"

    def action_help_overlay(self) -> None:
        self.notify(
            "f=Fleet  c=Contracts  m=Markets  t=Log  q=Quit\n"
            "Fleet: o=Orbit d=Dock n=Navigate e=Extract s=Sell r=Refuel\n"
            "Contracts: a=Accept\n"
            "?=This help",
            title="Keybindings",
            timeout=8,
        )


async def _run_app() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )
    await init_db()
    db = await get_db()
    try:
        app = SpaceTradersApp(db)
        await app.run_async()
    finally:
        await db.close()


def run() -> None:
    asyncio.run(_run_app())
