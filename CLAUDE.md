# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (base)
pip install -e .

# Install with web server support
pip install -e ".[web]"

# Run the bot (SpaceTraders API caller, DB writer)
st-bot

# Run the TUI (reads DB, writes to command_queue)
st-tui

# Run the web server / PWA (reads DB, writes to command_queue)
st-web

# Run tests
pytest

# Run a single test
pytest tests/test_db.py::test_command_queue_lifecycle

# Lint and format
ruff check src tests
ruff format src tests
```

## Architecture

Two processes share a single SQLite database (WAL mode). The **bot** is the only process that calls the SpaceTraders API; the TUI and web server communicate with it exclusively through a `command_queue` table.

```
Bot process                   TUI / Web server
  API Client (httpx)   ←──→   Reads DB for display
  Rate limiter               Writes command_queue rows
  Ship state machines        Bot polls, executes, writes result back
  DB writer (sole writer)
```

**Key constraint:** All raw SQL must stay in `src/spacetraders/db/queries.py`. No SQL elsewhere.

## Module map

| Path | Responsibility |
|------|----------------|
| `src/spacetraders/config.py` | Env var config (`ST_TOKEN`, `ST_DB_PATH`, `ST_WEB_PORT`, `ST_ALLOWED_ORIGINS`) |
| `src/spacetraders/api/client.py` | Rate-limited httpx async client (2 req/s, handles 429 + 5xx retries) |
| `src/spacetraders/api/models.py` | Pydantic v2 models for all API responses |
| `src/spacetraders/db/connection.py` | `get_db()` / `init_db()` — opens aiosqlite, enables WAL |
| `src/spacetraders/db/schema.sql` | Full DDL |
| `src/spacetraders/db/queries.py` | All named read/write functions |
| `src/spacetraders/bot/main.py` | Supervisor: reset detection, TaskGroup, startup bootstrap |
| `src/spacetraders/bot/ships.py` | Per-ship async state machine (IDLE → MINING → SELLING …) |
| `src/spacetraders/bot/commands.py` | `command_queue` consumer |
| `src/spacetraders/tui/app.py` | Textual `App`, tab switching, DB polling every 2s |
| `src/spacetraders/tui/screens/` | Fleet, Contracts, Markets, Transactions screens |
| `src/spacetraders/tui/widgets/` | Command input modal, shared components |
| `src/spacetraders/web/main.py` | FastAPI app + uvicorn entry point |
| `src/spacetraders/web/routers/` | agent, ships, contracts, markets, transactions, commands, events (SSE) |
| `src/spacetraders/web/static/` | PWA — index.html, app.js, views/, CSS |

## Key conventions

- Python 3.11+: use `asyncio.TaskGroup`, not `asyncio.gather`.
- All DB timestamps are ISO 8601 UTC strings.
- Log with `structlog` to stderr (keeps TUI stdout clean).
- Every API response that updates ship state must be written to the DB immediately — including intermediate steps like orbit/dock that precede a navigate. If only the final step updates the DB, any failure in between leaves the DB stale and the web UI showing wrong state.
- `ruff` line-length is 100, target py311.
- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no need for `@pytest.mark.asyncio` decorator on individual tests (though it is harmless).

## SpaceTraders API gotchas

**Bodyless POSTs require `json={}`** — `orbit`, `dock`, `survey`, `fulfill_contract`, `negotiate_contract` send no body, but the default `Content-Type: application/json` header causes a 422 if the body is an empty string. Always pass `json={}`.

**`tradeGoods` (prices) only returned when a ship is present** — all other markets return empty `trade_goods`. Price discovery (navigating to unvisited markets) is required before trade routes can be computed.

**`MARKETPLACE` is a waypoint trait, not a type** — querying waypoints by type `MARKETPLACE` returns nothing. Filter with `traits LIKE '%"MARKETPLACE"%'` in the DB or `traits=MARKETPLACE` in the API.

**Refuel requires DOCKED** — the refuel API returns 400 if the ship is in orbit. Always dock first. The `refuel` command handler auto-docks if needed.

**Navigate error code 4204 = insufficient fuel** — catch this specifically in navigation failure handlers and attempt a dock+refuel at the current waypoint before giving up.

**Orbit is idempotent** — calling orbit on a ship already in orbit returns 200 without error.

## Bot state machine known failure modes

**Stale DB after failed navigate** — the pattern `orbit() → navigate()` is common. If navigate fails, the DB will still say DOCKED because only successful navigates trigger a `get_ship()` refresh. Always call `get_ship()` + `upsert_ship()` immediately after `orbit()` or `dock()`, before the subsequent navigate attempt.

**IN_TRANSIT loop** — if arrival time has already passed and the DB still says `IN_TRANSIT`, the ship loops forever without acting. The transit block must always call `get_ship()` after waiting (or when wait ≤ 0), not only when `wait > 0`.

**Price discovery infinite loop** — `get_unvisited_market_waypoints` returns the same target until the market poller collects data. If navigation to that target fails (e.g. no fuel), the function returns early without the target being marked visited, so the same target is retried on the next tick. Fix: handle fuel errors by docking and refueling at current waypoint.

**Credit guardrails** — `MIN_CREDIT_RESERVE = 10_000` (defined in `ships.py`) is the floor below which refueling and cargo purchases are skipped. The agent's credit balance is read from the `agent` table which is updated via SSE/`get_agent` calls — there is no atomic debit check, so two concurrent ships could both pass the floor check simultaneously.

## Web UI / SSE architecture

- `app.js` receives SSE events and merges ship updates into `window.ST.ships`.
- View components listen to DOM custom events (`st:ship_update`, `st:market_update`, etc.) dispatched by `app.js`.
- `navigate()` in `app.js` must dispatch `st:unmount` on the container before clearing `innerHTML`, otherwise old event listeners accumulate.
- The markets view has a `refreshSystemDropdown()` that updates only the `<select>` options without a full re-render — avoids race conditions with filter state.

## Configuration

Set these environment variables (or use a `.env` file sourced before running):

| Variable | Default | Notes |
|----------|---------|-------|
| `ST_TOKEN` | — | Required bearer token |
| `ST_DB_PATH` | `~/.spacetraders/spacetraders.db` | SQLite file location |
| `ST_WEB_PORT` | `8080` | Web server port |
| `ST_ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |

## Docker

```bash
cp .env.example .env  # set ST_TOKEN
docker compose up -d
docker compose logs -f bot   # bot activity
docker compose logs -f web   # web requests
docker compose down          # stop (data in ./data/ persists)
```

The SQLite file is bind-mounted to `./data/spacetraders.db`.
