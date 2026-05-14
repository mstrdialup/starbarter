# SpaceTraders Bot

A SpaceTraders.io bot with three interfaces: a terminal TUI, a browser PWA,
and a Docker-based deployment that runs both. The bot and interfaces share a
SQLite database; the bot is the only process that talks to the SpaceTraders API.

---

## Prerequisites

- Python 3.11+
- pip
- Docker + Docker Compose (for containerized deployment only)

---

## Quick start (local, no Docker)

### 1. Install

```bash
git clone <your-repo>
cd spacetraders
pip install -e ".[web]"
```

### 2. Register an agent

If you don't have a token yet, register one:

```bash
curl -X POST https://api.spacetraders.io/v2/register \
  -H "Content-Type: application/json" \
  -d '{"symbol": "MYCALLSIGN", "faction": "COSMIC"}'
```

Save the `token` from the response. You won't see it again.

### 3. Configure

```bash
export ST_TOKEN=your_token_here
export ST_DB_PATH=~/.spacetraders/spacetraders.db
```

Or create a `.env` file and `source` it. See `.env.example` for all options.

### 4. Run the bot

```bash
st-bot
```

On first run the bot will:
- Initialize the SQLite database
- Verify the token against `GET /v2`
- Fetch your agent, ships, and starter system waypoints
- Begin the mining → sell loop

Leave this running. The bot is the only process that writes to the SpaceTraders
API.

### 5. Run the TUI (separate terminal)

```bash
st-tui
```

The TUI reads the same database file. Use the keyboard bindings below to
navigate and issue commands.

### 6. Run the web server (optional)

```bash
st-web
```

Open `http://localhost:8080` in a browser. The PWA can be installed to your
home screen from Chrome on Android via the browser menu → "Add to Home Screen".

---

## Docker deployment

This runs the bot and web server as separate containers sharing a SQLite
volume. No local Python required.

### 1. Configure

```bash
cp .env.example .env
# Edit .env and set ST_TOKEN
```

### 2. Start

```bash
docker compose up -d
```

### 3. Check logs

```bash
docker compose logs -f bot    # bot activity
docker compose logs -f web    # web server requests
```

### 4. Access

- PWA: `http://localhost:8080`
- API: `http://localhost:8080/api/status`

The SQLite file is bind-mounted to `./data/spacetraders.db` on the host. It
persists across container rebuilds.

### 5. Use the TUI against the containerized DB

From the host (simplest):
```bash
ST_DB_PATH=./data/spacetraders.db st-tui
```

Or inside the bot container:
```bash
docker compose exec bot st-tui
```

### 6. Stop

```bash
docker compose down
```

Data in `./data/` is preserved. To wipe everything: `docker compose down -v`
then delete `./data/`.

---

## Configuration reference

All settings are read from environment variables. Set them in your shell,
a `.env` file, or `docker-compose.yml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `ST_TOKEN` | — | **Required.** Bearer token from registration. |
| `ST_DB_PATH` | `~/.spacetraders/spacetraders.db` | Path to the SQLite database file. |
| `ST_WEB_PORT` | `8080` | Port the web server listens on. |
| `ST_ALLOWED_ORIGINS` | `*` | CORS allowed origins. Lock this down if exposing externally. |

---

## TUI keybindings

| Key | Action |
|-----|--------|
| `f` | Fleet view |
| `c` | Contracts view |
| `m` | Markets view |
| `t` | Transaction log |
| `?` | Help overlay |
| `q` | Quit |

**Fleet view commands (with a ship selected):**

| Key | Command |
|-----|---------|
| `o` | Orbit |
| `d` | Dock |
| `n` | Navigate (prompts for waypoint) |
| `e` | Extract |
| `s` | Sell all cargo |
| `r` | Refuel |

**Contracts view:**

| Key | Command |
|-----|---------|
| `a` | Accept selected contract |

Commands are written to the `command_queue` table and executed by the bot
process. The status panel (⏳ pending → ▶ running → ✓ done / ✗ failed) shows
execution progress.

---

## PWA commands

The command modal opens when you click a command button in the Fleet view.
Supported commands:

| Command | Required input |
|---------|---------------|
| Navigate | Waypoint symbol (e.g. `X1-DF55-B3`) |
| Dock | None — confirm only |
| Orbit | None — confirm only |
| Extract | None — confirm only |
| Buy | Trade symbol + units |
| Sell | Trade symbol + units |
| Refuel | Optional: from cargo checkbox |
| Accept contract | Contract ID (pre-filled) |

---

## Reset handling

SpaceTraders resets the game universe every ~2 weeks. On each reset:

- All ships, credits, contracts, and market data are wiped server-side.
- Your token stops working (returns 401).
- You need a new token from [my.spacetraders.io](https://my.spacetraders.io)
  or a fresh `POST /v2/register`.

When the bot starts and detects a new reset (by comparing `resetDate` from
`GET /v2` against the stored value), it:

1. Wipes all per-reset tables in the database.
2. Registers a new agent (or uses a new token you provide).
3. Re-bootstraps the universe data and begins fresh.

Update `ST_TOKEN` in your `.env` before restarting if you've pre-registered
via the dashboard.

---

## Database

The SQLite file lives at `ST_DB_PATH`. WAL mode is enabled so the bot can
write while the TUI/web server reads without locking.

To inspect it directly:

```bash
sqlite3 ~/.spacetraders/spacetraders.db

# Useful queries
SELECT symbol, nav_status, nav_waypoint, fuel_current, cargo_units FROM ship;
SELECT credits FROM agent;
SELECT trade_symbol, sell_price, snapshot_ts FROM market_snapshot
  WHERE waypoint = 'X1-DF55-A1'
  ORDER BY snapshot_ts DESC LIMIT 10;
SELECT command, status, created_at, completed_at FROM command_queue
  ORDER BY id DESC LIMIT 20;
```

To back up mid-reset:
```bash
cp ~/.spacetraders/spacetraders.db ~/backups/st-$(date +%Y%m%d).db
# or from Docker:
cp ./data/spacetraders.db ./backups/st-$(date +%Y%m%d).db
```

---

## Project structure

```
spacetraders/
├── src/spacetraders/
│   ├── config.py           # Env var config
│   ├── api/
│   │   ├── client.py       # Rate-limited httpx client (2 req/s)
│   │   └── models.py       # Pydantic v2 models for API responses
│   ├── db/
│   │   ├── connection.py   # get_db(), WAL mode, schema init
│   │   ├── schema.sql      # Full DDL
│   │   └── queries.py      # All DB reads and writes (no raw SQL elsewhere)
│   ├── bot/
│   │   ├── main.py         # Supervisor, reset detection, TaskGroup
│   │   ├── ships.py        # Per-ship state machine (mining → sell)
│   │   └── commands.py     # command_queue consumer
│   ├── tui/
│   │   ├── app.py          # Textual App, tab switching, DB polling
│   │   ├── screens/        # Fleet, Contracts, Markets, Transactions
│   │   └── widgets/        # Command input modal, shared components
│   └── web/
│       ├── main.py         # FastAPI app, uvicorn entry point
│       ├── routers/        # agent, ships, contracts, markets,
│       │   ...             # transactions, commands, events (SSE)
│       └── static/         # PWA — index.html, app.js, views/, CSS
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

---

## Troubleshooting

**Bot exits immediately with 401**
Your token has expired (a reset happened). Get a new token from
[my.spacetraders.io](https://my.spacetraders.io), update `ST_TOKEN`, restart.

**TUI shows no data / "No active session" banner**
The bot hasn't run yet, or hasn't finished bootstrapping. Start `st-bot`
and wait ~30 seconds for the initial fetch to complete.

**PWA shows "BOT OFFLINE" in the status bar**
The bot process isn't running or has crashed. Check `docker compose logs bot`
or the bot's terminal output. The status bar checks `agent.updated_at`; if
it hasn't advanced in 90 seconds, it flags as offline.

**Market data is stale (rows showing red in Markets view)**
No probe is parked at that marketplace. The market poller only refreshes
markets where you have a ship present. Buy a `SHIP_PROBE` (~25k credits)
and navigate it to the marketplace to restore live price data.

**"Ship is in transit" error on a command**
The command was issued while the ship was moving. The bot will reject it
with a `failed` status in the command queue. Wait for the ship to arrive
(watch the countdown in Fleet view) and reissue.

**Rate limit errors (429) in bot logs**
This is handled automatically — the bot backs off and retries. If you see
sustained 429s, another process may be sharing the same token. Only one
`st-bot` instance should run per token at a time.

---

## Resources

- [SpaceTraders docs](https://docs.spacetraders.io)
- [Interactive API explorer](https://spacetraders.stoplight.io)
- [Player dashboard / token management](https://my.spacetraders.io)
- [Community Discord](https://discord.gg/UpEfRRjsCT)
- [Leaderboard](https://flwi-spacetraders-rust-leaderboard.fly.dev)
