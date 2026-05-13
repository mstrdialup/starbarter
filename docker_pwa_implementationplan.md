# SpaceTraders Docker + PWA — Implementation Plan

## What's being added

The existing codebase has `st-bot` (bot supervisor + ship state machines) and
`st-tui` (Textual terminal UI), both sharing a SQLite DB. This plan adds:

1. **`st-web`** — a FastAPI server that reads the same DB and exposes a JSON
   API plus serves a PWA frontend.
2. **Dockerfile** — single image containing all three processes.
3. **docker-compose.yml** — runs the bot and web server as separate services
   sharing a volume-mounted SQLite file.

The PWA replicates the four TUI views (Fleet, Contracts, Markets, Transactions)
as browser pages, plus a command interface for issuing ship orders.

---

## Architecture

```
docker-compose
├── service: bot
│   └── runs: st-bot
│       └── reads/writes: /data/spacetraders.db (volume)
│
└── service: web
    └── runs: st-web (uvicorn)
        ├── /api/*        JSON endpoints — reads DB, writes command_queue
        ├── /events       SSE stream — pushes DB change notifications
        └── /             Static files — PWA HTML/JS/CSS
            └── reads: /data/spacetraders.db (same volume, read-heavy)

Host machine
└── ./data/spacetraders.db  ← persisted across container rebuilds
```

Both services share the SQLite file via a named volume. WAL mode (already
enabled in `connection.py`) allows the bot to write while the web server
reads without contention. No inter-process communication needed beyond the DB.

---

## New files

```
spacetraders/
├── src/spacetraders/
│   └── web/
│       ├── __init__.py
│       ├── main.py           # FastAPI app + uvicorn entry point
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── agent.py      # GET /api/agent
│       │   ├── ships.py      # GET /api/ships, POST /api/commands
│       │   ├── contracts.py  # GET /api/contracts
│       │   ├── markets.py    # GET /api/markets
│       │   ├── transactions.py # GET /api/transactions
│       │   ├── commands.py   # GET /api/commands (queue status)
│       │   └── events.py     # GET /events (SSE)
│       └── static/           # Served at /
│           ├── index.html    # Shell — loads the PWA
│           ├── manifest.json # PWA install metadata
│           ├── sw.js         # Service worker (cache shell only)
│           ├── icons/        # PWA icons (192px, 512px)
│           └── app/
│               ├── app.js    # Main JS — routing, SSE client, state
│               ├── views/
│               │   ├── fleet.js
│               │   ├── contracts.js
│               │   ├── markets.js
│               │   └── transactions.js
│               └── components/
│                   ├── table.js       # Reusable sortable table
│                   ├── command-modal.js
│                   └── status-bar.js
├── Dockerfile
├── docker-compose.yml
└── .env.example              # ST_TOKEN=, ST_DB_PATH=, ST_WEB_PORT=
```

Add to `pyproject.toml`:

```toml
[project.scripts]
st-bot = "spacetraders.bot.main:run"
st-tui = "spacetraders.tui.app:run"
st-web = "spacetraders.web.main:run"   # new

[project.optional-dependencies]
web = [
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "sse-starlette>=1.8",
]
```

Install with `pip install -e ".[web]"`.

---

## Phase 0: FastAPI scaffold and entry point

**Goal:** `st-web` starts, serves a placeholder page at `/`, and has a
working `/api/status` endpoint. Proves the web layer can reach the DB.

### `web/main.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import uvicorn

from spacetraders.config import settings
from spacetraders.db.connection import get_db
from spacetraders.web.routers import agent, ships, contracts, markets, transactions, commands, events

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB is accessible; log startup
    async with get_db() as db:
        row = await db.execute_fetchall("SELECT reset_date FROM reset_meta LIMIT 1")
    yield

app = FastAPI(title="SpaceTraders", lifespan=lifespan)

# API routers
app.include_router(agent.router,       prefix="/api")
app.include_router(ships.router,       prefix="/api")
app.include_router(contracts.router,   prefix="/api")
app.include_router(markets.router,     prefix="/api")
app.include_router(transactions.router,prefix="/api")
app.include_router(commands.router,    prefix="/api")
app.include_router(events.router)

# PWA static files — must come last
app.mount("/app", StaticFiles(directory="src/spacetraders/web/static/app"), name="app")

@app.get("/{full_path:path}")
async def serve_pwa(full_path: str):
    # All non-API routes return the PWA shell
    return FileResponse("src/spacetraders/web/static/index.html")

def run():
    uvicorn.run(
        "spacetraders.web.main:app",
        host="0.0.0.0",
        port=settings.web_port,
        reload=False,
    )
```

### `/api/status` endpoint

Returns a health snapshot used by the PWA status bar:

```json
{
  "db_reachable": true,
  "reset_date": "2025-03-01",
  "agent_symbol": "MYCALL",
  "credits": 342100,
  "ship_count": 12,
  "bot_last_seen": "2026-05-13T15:44:01Z",
  "bot_online": true,
  "pending_commands": 2
}
```

`bot_online` is `true` if `agent.updated_at` is within the last 90 seconds
(the agent poller runs every 30s, so three missed polls = offline).

### Task list

1. Add `web` optional dependencies to `pyproject.toml`.
2. Create the full `web/` directory structure with empty `__init__.py` files.
3. Write `web/main.py` as above.
4. Write the `/api/status` endpoint in `web/routers/agent.py`.
5. Create a placeholder `static/index.html` that just renders "SpaceTraders".
6. Run `st-web` and confirm: `curl localhost:8080/api/status` returns valid JSON.

---

## Phase 1: API endpoints

**Goal:** All read endpoints are working. The PWA will poll these.
Every endpoint reads from the existing `db/queries.py` functions —
no new DB logic, just HTTP wrappers.

### Endpoint reference

#### Agent

```
GET /api/agent
→ {symbol, credits, headquarters, ship_count, updated_at}
```

#### Ships

```
GET /api/ships
→ [{symbol, role, nav_status, nav_waypoint, arrival_time,
    fuel_current, fuel_capacity, cargo_units, cargo_capacity,
    cargo_inventory, cooldown_expires, condition_frame,
    condition_engine, condition_reactor}, ...]

GET /api/ships/{symbol}
→ single ship object (same shape)
```

#### Contracts

```
GET /api/contracts
→ [{id, faction, type, terms, accepted, fulfilled, deadline,
    deadline_to_accept, deliver_progress: [{trade_symbol,
    destination, required, fulfilled}]}, ...]
```

#### Markets

```
GET /api/markets?system={symbol}
→ [{waypoint, trade_symbol, type, supply, activity,
    purchase_price, sell_price, trade_volume, snapshot_ts,
    staleness_seconds}, ...]

GET /api/markets/routes?system={symbol}
→ [{trade_symbol, buy_waypoint, buy_price, sell_waypoint,
    sell_price, spread, spread_pct}, ...]
  Sorted by spread descending. Same logic as the TUI markets widget.
```

#### Transactions

```
GET /api/transactions?limit=100
→ [{id, ship_symbol, type, trade_symbol, units,
    price_per_unit, total, waypoint, timestamp}, ...]

GET /api/transactions/summary
→ {total_revenue, total_cost, net_profit,
   by_good: [{trade_symbol, units, revenue, cost, profit}]}
```

#### Command queue

```
GET /api/commands?limit=50
→ [{id, ship_symbol, command, params, status, result,
    created_at, completed_at}, ...]
  Most recent first. The PWA uses this for the command status panel.
```

### Task list

1. Write all router files with the endpoints above.
2. Each endpoint calls an existing `queries.py` function; add any missing
   read functions to `queries.py` (the routes summary query and
   staleness_seconds calculation are likely new).
3. Add CORS middleware for local development:
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(CORSMiddleware, allow_origins=["*"],
                      allow_methods=["*"], allow_headers=["*"])
   ```
   (Locked down to specific origin in production via env var.)
4. Test each endpoint with curl. Verify fleet, market, transaction data
   all return populated JSON when the bot is running.

---

## Phase 2: Command endpoint

**Goal:** The PWA can issue commands. One endpoint handles all commands,
writing to `command_queue` via the existing `enqueue_command()` query.

```
POST /api/commands
Content-Type: application/json

{
  "ship_symbol": "MYCALL-1",
  "command": "navigate",
  "params": {"waypoint": "X1-DF55-B3"}
}

→ 201 Created
{
  "id": 42,
  "ship_symbol": "MYCALL-1",
  "command": "navigate",
  "params": {"waypoint": "X1-DF55-B3"},
  "status": "pending",
  "created_at": "2026-05-13T15:44:01Z"
}
```

Validation rules (enforced server-side before writing to the queue):

| Command | Required params | Optional params |
|---------|----------------|-----------------|
| `navigate` | `waypoint: str` | — |
| `dock` | — | — |
| `orbit` | — | — |
| `buy` | `symbol: str`, `units: int` | — |
| `sell` | `symbol: str`, `units: int` | — |
| `refuel` | — | `from_cargo: bool` |
| `extract` | — | — |
| `accept_contract` | `contract_id: str` | — |

Use a Pydantic model with a `command` discriminator field to validate params.
Return 422 if the command or params are invalid — don't write bad rows to
the queue.

Also add:

```
DELETE /api/commands/{id}
```

Cancels a `pending` command (sets status to `cancelled`). Returns 409 if
the command is already `running`, `done`, or `failed`.

Add `cancelled` as a valid status to `command_queue` in the schema and
in `queries.py`.

### Task list

1. Write the `POST /api/commands` endpoint with Pydantic validation.
2. Write the `DELETE /api/commands/{id}` endpoint.
3. Add `cancelled` status handling to `queries.py` (`cancel_command(db, id)`).
4. Test: POST a navigate command, confirm it appears in the queue, confirm
   the bot picks it up and executes it, confirm status transitions to `done`.
5. Test: POST an invalid command (bad params), confirm 422 with a clear error.

---

## Phase 3: SSE stream

**Goal:** The PWA receives real-time DB change notifications without polling.
The bot updates the DB every few seconds; the SSE stream lets the frontend
react immediately instead of waiting for its next poll cycle.

### `GET /events`

Returns an `text/event-stream` response. The server polls the DB every
2 seconds and pushes events to all connected clients when state changes.

Event types:

```
event: agent_update
data: {"credits": 342100, "ship_count": 12}

event: ship_update
data: {"symbol": "MYCALL-1", "nav_status": "DOCKED", ...}

event: command_update
data: {"id": 42, "status": "done", "result": {...}}

event: market_update
data: {"waypoint": "X1-DF55-A1", "snapshot_ts": "..."}

event: keepalive
data: {}
```

Implementation using `sse-starlette`:

```python
from sse_starlette.sse import EventSourceResponse
import asyncio

@router.get("/events")
async def event_stream(request: Request):
    async def generate():
        last_agent_ts = None
        last_command_ts = None
        while True:
            if await request.is_disconnected():
                break

            async with get_db() as db:
                agent = await queries.get_agent(db)
                if agent and agent["updated_at"] != last_agent_ts:
                    last_agent_ts = agent["updated_at"]
                    yield {"event": "agent_update", "data": json.dumps(agent)}

                commands = await queries.get_recent_commands(db, limit=1)
                if commands and commands[0]["completed_at"] != last_command_ts:
                    last_command_ts = commands[0]["completed_at"]
                    yield {"event": "command_update",
                           "data": json.dumps(commands[0])}

            yield {"event": "keepalive", "data": "{}"}
            await asyncio.sleep(2)

    return EventSourceResponse(generate())
```

### Task list

1. Write `web/routers/events.py` with the SSE generator above.
2. The PWA will connect to this in Phase 4; for now, verify the stream works
   with `curl -N localhost:8080/events` and confirm events appear as the
   bot updates the DB.

---

## Phase 4: PWA frontend

**Goal:** A fully functional single-page app served from `/`, installable
as a PWA on Android and desktop. Four views matching the TUI. No build step —
vanilla JS using ES modules, served directly by FastAPI's StaticFiles.

### Design direction

The aesthetic should match the game: dark space theme, monospaced data-dense
tables, muted greens and ambers for status indicators, sharp accents for
alerts. Think mission control, not consumer app. The one thing someone
should remember: it looks like you're actually operating a fleet.

Specific choices:
- Background: near-black (`#0a0c10`) with a very subtle starfield CSS
  background (radial gradients, not canvas — no JS for decoration).
- Font: `JetBrains Mono` (from Google Fonts) for tables and data; 
  `Syne` for headings and labels. Both load from a single `<link>` in
  `index.html`.
- Status colors matching the TUI: green = ready/healthy, amber = in
  transit/warning, red = critical/error, dim gray = offline/stale.
- Navigation: a fixed left sidebar on desktop, a bottom tab bar on mobile
  (CSS media query at 768px breakpoint).

### `index.html`

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0a0c10">
  <title>SpaceTraders</title>
  <link rel="manifest" href="/manifest.json">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="/app/app.css">
</head>
<body>
  <div id="app">
    <nav id="sidebar">
      <div class="logo">ST</div>
      <a href="#fleet"        class="nav-item" data-view="fleet">       Fleet       </a>
      <a href="#contracts"    class="nav-item" data-view="contracts">   Contracts   </a>
      <a href="#markets"      class="nav-item" data-view="markets">     Markets     </a>
      <a href="#transactions" class="nav-item" data-view="transactions">Log         </a>
    </nav>
    <main id="view-container"></main>
    <footer id="status-bar"></footer>
  </div>
  <div id="modal-overlay" hidden></div>
  <script type="module" src="/app/app.js"></script>
</body>
</html>
```

### `app/app.js`

Responsibilities:
- Client-side router: reads `location.hash`, renders the matching view.
- SSE client: connects to `/events`, dispatches custom DOM events when
  data changes. Views listen for these events to re-render affected parts.
- Global state: a plain JS object (`window.ST`) holding the last-fetched
  data per view. Views read from this on render; SSE updates it.
- Status bar: re-renders on every SSE event using `/api/status`.

```javascript
// Router
const VIEWS = { fleet, contracts, markets, transactions };

function navigate(viewName) {
  document.querySelectorAll('.nav-item').forEach(el =>
    el.classList.toggle('active', el.dataset.view === viewName));
  const container = document.getElementById('view-container');
  container.innerHTML = '';
  VIEWS[viewName]?.mount(container);
}

window.addEventListener('hashchange', () =>
  navigate(location.hash.slice(1) || 'fleet'));

// SSE
const sse = new EventSource('/events');
sse.addEventListener('agent_update', e => {
  window.ST.agent = JSON.parse(e.data);
  document.dispatchEvent(new CustomEvent('st:agent_update'));
});
sse.addEventListener('command_update', e => {
  document.dispatchEvent(new CustomEvent('st:command_update',
    { detail: JSON.parse(e.data) }));
});
// ... other event types

navigate(location.hash.slice(1) || 'fleet');
```

### Fleet view (`app/views/fleet.js`)

Layout (desktop): ship table on left 60%, detail pane on right 40%.
Layout (mobile): ship table full width, detail pane slides up from bottom
on row tap.

Ship table columns: Symbol | Role | Status | Location | Fuel | Cargo | Condition

Color rules (applied as CSS classes):
- `status-ready` (green) — DOCKED or IN_ORBIT with no cooldown and fuel > 20%
- `status-transit` (amber) — IN_TRANSIT; show countdown to arrival
- `status-cooldown` (amber) — IN_ORBIT/DOCKED with active cooldown; show countdown
- `status-critical` (red) — fuel < 20% OR condition_frame < 0.5

Detail pane (shown on row select):
- Full cargo inventory as a mini-table
- Cooldown countdown (live, JS `setInterval` every second)
- Frame/engine/reactor condition bars (CSS `width` set from value)
- Command buttons: Orbit | Dock | Navigate | Extract | Sell All | Refuel
  - Each button opens the command modal with pre-filled ship symbol
  - Disabled if the command is invalid for current nav_status
    (e.g. Dock disabled when IN_TRANSIT)

### Contracts view (`app/views/contracts.js`)

Table: ID (truncated) | Type | Faction | Deadline | Payment | Status

Clicking a row expands to show delivery progress:
```
IRON_ORE → X1-DF55-B1   ████████░░░░  28 / 40 units
```
Progress bar is a CSS `<progress>` element styled to match the theme.

"Accept" button appears for unaccepted contracts. Issues
`POST /api/commands` with `accept_contract`.

Deadline column turns amber when < 6 hours remain, red when < 1 hour.

### Markets view (`app/views/markets.js`)

Two sub-tabs: **Prices** and **Routes**.

Prices tab: sortable table of all market_snapshot rows for the current
system. Columns: Waypoint | Good | Type | Supply | Activity | Buy | Sell |
Vol | Age. "Age" is staleness in seconds, red if > 300.

Routes tab: fetches `/api/markets/routes` and displays spread table.
Columns: Good | Buy At | Buy Price | Sell At | Sell Price | Spread | Spread %.
Sorted by Spread % descending by default.

System selector: a `<select>` populated from distinct system symbols in
the DB. Defaults to agent headquarters system.

### Transactions view (`app/views/transactions.js`)

Scrollable table of last 200 transactions. Columns: Time | Ship | Type |
Good | Units | Price | Total.

Summary row pinned at the top:
```
Revenue: 1,240,000 cr   Cost: 880,000 cr   Profit: 360,000 cr
```

BUY rows show cost in red, SELL rows show revenue in green.

### Command modal (`app/components/command-modal.js`)

A centered modal overlay. Opens with a pre-selected command type and ship.
Fields rendered per command type:

| Command | Fields shown |
|---------|-------------|
| navigate | Waypoint symbol (text input) |
| buy / sell | Trade symbol (text), Units (number) |
| refuel | "From cargo?" (checkbox) |
| dock / orbit / extract | No fields — confirm only |
| accept_contract | Contract ID (pre-filled, read-only) |

On submit: POST to `/api/commands`, show spinner, wait for response.
On success: dismiss modal, dispatch `st:command_queued` event so the
status bar updates.
On error: show error message inline, keep modal open.

### Status bar (`app/components/status-bar.js`)

Fixed footer. Polls `/api/status` every 10s and re-renders on SSE events.

```
MYCALL  |  342,100 cr  |  12 ships  |  ● BOT ONLINE  |  2 pending cmds  |  [reset: 2025-03-01]
```

Bot offline: `● BOT OFFLINE` in red if `bot_online` is false.
Pending commands: amber if > 0, shows count.

### PWA assets

**`manifest.json`**:
```json
{
  "name": "SpaceTraders",
  "short_name": "ST",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0a0c10",
  "theme_color": "#0a0c10",
  "icons": [
    {"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"}
  ]
}
```

**`sw.js`** (minimal — cache the app shell only):
```javascript
const CACHE = 'st-v1';
const SHELL = ['/', '/app/app.js', '/app/app.css'];

self.addEventListener('install', e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL))));

self.addEventListener('fetch', e => {
  // Only cache GET requests for shell files; pass API calls through
  if (e.request.method !== 'GET') return;
  if (e.request.url.includes('/api/') || e.request.url.includes('/events'))
    return;
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request))
  );
});
```

### Icon generation

Generate two PNG icons (192×192 and 512×512). A simple dark background with
"ST" in the Syne font is sufficient. Use the `cairosvg` or `Pillow` library
in a one-off script to produce them, or hand-draw minimal SVGs and convert.

### Task list

1. Write `app.css` — CSS custom properties for the color palette, layout
   (sidebar + main + footer), typography, table styles, status color classes,
   modal overlay, progress bars. Mobile breakpoint at 768px.
2. Write `app.js` — router, SSE client, global state, service worker
   registration.
3. Write `views/fleet.js` — table + detail pane + command button wiring.
4. Write `views/contracts.js` — contract table + progress bars.
5. Write `views/markets.js` — prices and routes sub-tabs.
6. Write `views/transactions.js` — transaction table + summary row.
7. Write `components/command-modal.js` — dynamic fields + POST + spinner.
8. Write `components/status-bar.js` — status footer.
9. Write `manifest.json`, `sw.js`, generate icons.
10. Test on desktop browser: all four views render, SSE events update the
    fleet view in real-time, issuing a navigate command from the modal results
    in the ship entering IN_TRANSIT.
11. Test on Android Chrome: install to home screen via "Add to Home Screen",
    verify standalone display mode, verify touch targets are large enough
    (minimum 44×44px tap area).

---

## Phase 5: Dockerfile and docker-compose

**Goal:** The entire system runs from `docker compose up` with no local
Python required. SQLite file persists on the host.

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps (none beyond Python base for this project)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[web]"

# Copy source
COPY src/ src/

# Non-root user
RUN useradd -m stuser && chown -R stuser /app
USER stuser

# DB directory (will be volume-mounted)
RUN mkdir -p /data

EXPOSE 8080
```

This image contains all three entry points (`st-bot`, `st-tui`, `st-web`).
`docker-compose.yml` selects which one to run per service.

### `docker-compose.yml`

```yaml
services:
  bot:
    build: .
    command: st-bot
    volumes:
      - spacetraders-data:/data
    environment:
      - ST_TOKEN=${ST_TOKEN}
      - ST_DB_PATH=/data/spacetraders.db
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  web:
    build: .
    command: st-web
    volumes:
      - spacetraders-data:/data
    environment:
      - ST_DB_PATH=/data/spacetraders.db
      - ST_WEB_PORT=8080
      - ST_ALLOWED_ORIGINS=${ST_ALLOWED_ORIGINS:-*}
    ports:
      - "${ST_WEB_PORT:-8080}:8080"
    depends_on:
      - bot
    restart: unless-stopped

volumes:
  spacetraders-data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ./data   # persists on host at ./data/spacetraders.db
```

### `.env.example`

```bash
# Required
ST_TOKEN=your_bearer_token_here

# Optional overrides
ST_DB_PATH=/data/spacetraders.db
ST_WEB_PORT=8080
ST_ALLOWED_ORIGINS=*   # lock down to your IP/domain in production
```

### Running the TUI against the containerized DB

When you want the terminal interface while the stack is running in Docker:

```bash
# Shell into the bot container (DB is at /data/spacetraders.db)
docker compose exec bot st-tui

# Or run the TUI on the host, pointing at the bind-mounted DB file
ST_DB_PATH=./data/spacetraders.db st-tui
```

The second option is useful because Textual renders better in a real local
terminal than in `docker exec`.

### Production hardening notes (implement if exposing beyond localhost)

- Add an `ST_SECRET_KEY` env var and implement a minimal auth layer:
  a simple Bearer token check in FastAPI middleware. The game token is not
  suitable for this — use a separate secret.
- Lock `ST_ALLOWED_ORIGINS` to your specific domain or LAN IP.
- Run behind a reverse proxy (Caddy or nginx) for HTTPS. The compose file
  can include a `caddy` service with automatic Let's Encrypt if you have
  a domain.
- Do not expose port 8080 publicly without auth. On a home network behind
  NAT, the default config is acceptable.

### Task list

1. Write `Dockerfile` as above. Build it: `docker build -t spacetraders .`
2. Create `./data/` directory (add `./data/*.db` to `.gitignore`, but keep
   the directory with a `.gitkeep`).
3. Write `docker-compose.yml` and `.env.example`.
4. Test: copy `.env.example` to `.env`, fill in `ST_TOKEN`, run
   `docker compose up`. Verify:
   - Bot registers and starts mining.
   - `curl localhost:8080/api/status` returns a valid response.
   - Browser at `localhost:8080` loads the PWA.
   - Fleet view shows ships and updates in real-time.
5. Test restart resilience: `docker compose restart bot`. Confirm the
   bot picks up from the existing DB (no re-registration, no data loss).
6. Test `docker exec` TUI: `docker compose exec bot st-tui`. Confirm
   the TUI renders and shows live data.
7. Add `./data/` and `./data/*.db` to `.gitignore`.

---

## Execution order for Claude Code

Each phase ends at a testable checkpoint:

1. **Phase 0** — `st-web` starts; `/api/status` returns valid JSON.
2. **Phase 1** — All GET endpoints return correct data; verified with curl.
3. **Phase 2** — POST a command via curl; bot executes it; status goes to `done`.
4. **Phase 3** — `curl -N /events` shows a live stream of events.
5. **Phase 4** — PWA loads in browser; all four views work; command modal
   issues a command that the bot executes; SSE updates the fleet view
   without a page reload; installs to Android home screen.
6. **Phase 5** — `docker compose up` runs the full stack; everything
   from phases 1–4 works inside Docker.

### Standing instructions for Claude Code

- Read existing `db/queries.py` before adding any new query functions.
  The goal is wrappers, not rewrites.
- All FastAPI path operations use `async def` and `async with get_db()`.
- No frontend build step. Vanilla JS ES modules only. No npm, no bundler.
- CSS custom properties for all colors — no hardcoded hex outside `:root {}`.
- Test each phase before moving to the next. Fix errors before proceeding.
- `ruff check` and `ruff format` on all Python before marking a phase done.
