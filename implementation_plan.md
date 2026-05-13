# SpaceTraders TUI — Implementation Plan

## Architecture

Two separate processes sharing a SQLite database:

┌─────────────────────────┐      ┌──────────────────────────┐

│     Bot Process          │      │     TUI Process           │

│                          │      │                           │

│  API Client (httpx)      │      │  Textual App              │

│  Rate Limiter (global)   │◄────►│  Reads DB for display     │

│  Ship state machines     │ SQLite│  Writes to command\_queue  │

│  Strategy / decisions    │ (WAL)│  table for bot to execute │

│  DB writer               │      │                           │

└──────────────────────────┘      └──────────────────────────┘

The TUI never calls the SpaceTraders API directly. All commands go through a `command_queue` table. The bot polls this table, executes commands against the API, and writes results back to the DB. This keeps rate limiting in one place and prevents conflicts.

The SQLite DB runs in WAL mode so the bot can write while the TUI reads without locking.

---

## Phase 0: Project skeleton and DB schema

**Goal:** A working Python package structure, SQLite schema, and the ability to run `st-bot` and `st-tui` as separate entry points.

### Files to create

spacetraders/

├── pyproject.toml            \# Project metadata, dependencies, entry points

├── src/

│   └── spacetraders/

│       ├── \_\_init\_\_.py

│       ├── config.py         \# Token, DB path, base URL from env vars

│       ├── db/

│       │   ├── \_\_init\_\_.py

│       │   ├── schema.sql    \# Full DDL

│       │   ├── connection.py \# get\_db(), ensure WAL mode, run migrations

│       │   └── queries.py    \# Named query functions (read/write)

│       ├── api/

│       │   ├── \_\_init\_\_.py

│       │   ├── client.py     \# Rate-limited httpx.AsyncClient wrapper

│       │   └── models.py     \# Pydantic v2 models for API responses

│       ├── bot/

│       │   ├── \_\_init\_\_.py

│       │   ├── main.py       \# Bot entry point, supervisor loop

│       │   ├── ships.py      \# Per-ship state machine

│       │   └── commands.py   \# command\_queue consumer

│       └── tui/

│           ├── \_\_init\_\_.py

│           ├── app.py        \# Textual App subclass

│           ├── screens/      \# One file per screen

│           └── widgets/      \# Reusable Textual widgets

└── tests/

### Dependencies

\[project\]

requires-python \= "\>=3.11"

dependencies \= \[

    "httpx\>=0.27",

    "pydantic\>=2.0",

    "aiolimiter\>=1.1",

    "textual\>=0.80",

    "aiosqlite\>=0.20",

    "structlog",

\]

\[project.scripts\]

st-bot \= "spacetraders.bot.main:run"

st-tui \= "spacetraders.tui.app:run"

### SQLite schema (core tables)

\-- Metadata

CREATE TABLE reset\_meta (

    reset\_date TEXT PRIMARY KEY,

    registered\_at TEXT,

    agent\_symbol TEXT,

    token TEXT

);

\-- Universe (static per reset)

CREATE TABLE system (

    symbol TEXT PRIMARY KEY,

    type TEXT NOT NULL,

    x INTEGER NOT NULL,

    y INTEGER NOT NULL

);

CREATE TABLE waypoint (

    symbol TEXT PRIMARY KEY,

    system\_symbol TEXT NOT NULL REFERENCES system(symbol),

    type TEXT NOT NULL,

    x INTEGER NOT NULL,

    y INTEGER NOT NULL,

    traits TEXT NOT NULL DEFAULT '\[\]',  \-- JSON array

    faction TEXT,

    is\_charted INTEGER NOT NULL DEFAULT 0

);

CREATE INDEX idx\_wp\_system\_type ON waypoint(system\_symbol, type);

\-- Market snapshots (time series, most valuable table)

CREATE TABLE market\_snapshot (

    waypoint TEXT NOT NULL,

    trade\_symbol TEXT NOT NULL,

    snapshot\_ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    type TEXT,           \-- EXPORT / IMPORT / EXCHANGE

    supply TEXT,

    activity TEXT,

    purchase\_price INTEGER,

    sell\_price INTEGER,

    trade\_volume INTEGER,

    PRIMARY KEY (waypoint, trade\_symbol, snapshot\_ts)

);

CREATE INDEX idx\_mkt\_symbol\_ts ON market\_snapshot(trade\_symbol, snapshot\_ts DESC);

\-- Ships

CREATE TABLE ship (

    symbol TEXT PRIMARY KEY,

    role TEXT,

    frame TEXT,

    nav\_status TEXT,         \-- IN\_ORBIT / DOCKED / IN\_TRANSIT

    nav\_waypoint TEXT,

    nav\_flight\_mode TEXT,

    arrival\_time TEXT,       \-- NULL if not in transit

    fuel\_current INTEGER,

    fuel\_capacity INTEGER,

    cargo\_capacity INTEGER,

    cargo\_units INTEGER,

    cargo\_inventory TEXT,    \-- JSON array

    cooldown\_expires TEXT,

    condition\_frame REAL,

    condition\_engine REAL,

    condition\_reactor REAL,

    updated\_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))

);

\-- Contracts

CREATE TABLE contract (

    id TEXT PRIMARY KEY,

    faction TEXT,

    type TEXT,

    terms TEXT NOT NULL,     \-- JSON

    accepted INTEGER NOT NULL DEFAULT 0,

    fulfilled INTEGER NOT NULL DEFAULT 0,

    deadline TEXT,

    deadline\_to\_accept TEXT

);

\-- Surveys (ephemeral)

CREATE TABLE survey (

    signature TEXT PRIMARY KEY,

    waypoint TEXT NOT NULL,

    deposits TEXT NOT NULL,  \-- JSON array

    expiration TEXT NOT NULL,

    size TEXT

);

\-- Agent state

CREATE TABLE agent (

    symbol TEXT PRIMARY KEY,

    credits INTEGER NOT NULL DEFAULT 0,

    headquarters TEXT,

    ship\_count INTEGER NOT NULL DEFAULT 0,

    updated\_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))

);

\-- Command queue (TUI → Bot communication)

CREATE TABLE command\_queue (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    created\_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),

    ship\_symbol TEXT,

    command TEXT NOT NULL,       \-- e.g. "navigate", "buy", "sell", "dock", "orbit"

    params TEXT NOT NULL DEFAULT '{}',  \-- JSON

    status TEXT NOT NULL DEFAULT 'pending',  \-- pending / running / done / failed

    result TEXT,                 \-- JSON response or error

    completed\_at TEXT

);

\-- Transaction log (bookkeeping)

CREATE TABLE transaction\_log (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    ship\_symbol TEXT NOT NULL,

    type TEXT NOT NULL,          \-- BUY / SELL / DELIVER

    trade\_symbol TEXT,

    units INTEGER,

    price\_per\_unit INTEGER,

    total INTEGER,

    waypoint TEXT,

    timestamp TEXT NOT NULL

);

### Task list for Claude Code

1. Create the directory structure and all `__init__.py` files.  
2. Write `pyproject.toml` with dependencies and entry points.  
3. Write `config.py` — reads `ST_TOKEN` and `ST_DB_PATH` from env, defaults DB path to `~/.spacetraders/spacetraders.db`.  
4. Write `schema.sql` with the DDL above.  
5. Write `connection.py` — `get_db()` returns an `aiosqlite` connection with WAL mode enabled; `init_db()` runs `schema.sql` if tables don't exist.  
6. Stub `st-bot` and `st-tui` entry points that just print "ok" and exit.  
7. Verify: `pip install -e .` then `st-bot` and `st-tui` both run.

---

## Phase 1: API client with rate limiting

**Goal:** A single `SpaceTradersClient` class that handles auth, rate limiting, retries, and returns Pydantic models.

### Pydantic models (`models.py`)

Define models for the response objects the TUI and bot both need. Don't model the entire API — start with:

- `Agent`  
- `Ship`, `ShipNav`, `ShipCargo`, `ShipFuel`, `Cooldown`  
- `Contract`, `ContractTerms`, `ContractDeliverable`  
- `Market`, `MarketTradeGood`  
- `Waypoint`, `WaypointTrait`  
- `System`  
- `Survey`  
- `Shipyard`, `ShipyardShip`  
- `ServerStatus` (the `GET /v2` response)

Use `model_validator` and `field_alias` where the API's JSON keys don't match Python conventions. All timestamps should parse to `datetime`.

### Client (`client.py`)

class SpaceTradersClient:

    """

    Async HTTP client. One instance per process.

    Rate limited to 2 req/s sustained, 10 burst over 10s.

    """

    def \_\_init\_\_(self, token: str, base\_url: str \= "https://api.spacetraders.io/v2"):

        ...

    \# Low-level

    async def \_request(self, method, path, \*\*kwargs) \-\> dict: ...

    \# Typed methods — each returns a Pydantic model or list

    async def get\_status(self) \-\> ServerStatus: ...

    async def register(self, symbol, faction) \-\> ...: ...

    async def get\_agent(self) \-\> Agent: ...

    async def list\_ships(self) \-\> list\[Ship\]: ...

    async def get\_ship(self, symbol) \-\> Ship: ...

    async def orbit(self, ship) \-\> ShipNav: ...

    async def dock(self, ship) \-\> ShipNav: ...

    async def navigate(self, ship, waypoint) \-\> ShipNav: ...

    async def extract(self, ship, survey=None) \-\> ...: ...

    async def purchase\_cargo(self, ship, symbol, units) \-\> ...: ...

    async def sell\_cargo(self, ship, symbol, units) \-\> ...: ...

    async def refuel(self, ship) \-\> ...: ...

    async def get\_market(self, system, waypoint) \-\> Market: ...

    async def get\_waypoints(self, system, \*\*filters) \-\> list\[Waypoint\]: ...

    async def accept\_contract(self, contract\_id) \-\> Contract: ...

    async def deliver\_contract(self, contract\_id, ship, trade, units) \-\> Contract: ...

    async def fulfill\_contract(self, contract\_id) \-\> Contract: ...

    async def negotiate\_contract(self, ship) \-\> Contract: ...

    async def buy\_ship(self, ship\_type, waypoint) \-\> Ship: ...

    \# ... expand as needed

Rate limiting implementation:

- Use `aiolimiter.AsyncLimiter(2, 1)` as the global limiter.  
- On 429: read `retry-after` header, `await asyncio.sleep(retry_after)`, retry.  
- On 5xx: exponential backoff with jitter, max 3 retries.  
- Log every request via `structlog`: method, path, status, latency, `x-ratelimit-remaining`.

### Task list

1. Write `models.py` with the Pydantic models listed above.  
2. Write `client.py` with `_request()` implementing rate limiting and retries.  
3. Implement typed methods for: `get_status`, `register`, `get_agent`, `list_ships`, `get_ship`, `orbit`, `dock`, `navigate`, `extract`, `purchase_cargo`, `sell_cargo`, `refuel`, `get_market`, `get_waypoints`, `accept_contract`, `deliver_contract`, `fulfill_contract`, `buy_ship`.  
4. Write a smoke test script: register an agent (or use existing token), call `get_agent()`, `list_ships()`, print results.  
5. Verify rate limiting works: send 15 rapid requests, confirm only 429 retries happen (no crashes).

---

## Phase 2: DB query layer

**Goal:** Named functions in `queries.py` that the bot writes to and the TUI reads from. No raw SQL outside this file.

### Key functions

\# Writes (bot uses these)

async def upsert\_agent(db, agent: Agent): ...

async def upsert\_ship(db, ship: Ship): ...

async def upsert\_ships(db, ships: list\[Ship\]): ...

async def insert\_market\_snapshot(db, waypoint: str, goods: list\[MarketTradeGood\]): ...

async def upsert\_contract(db, contract: Contract): ...

async def upsert\_waypoint(db, waypoint: Waypoint): ...

async def upsert\_system(db, system: System): ...

async def insert\_survey(db, survey: Survey): ...

async def insert\_transaction(db, ...): ...

async def clear\_all\_reset\_data(db): ...

\# Reads (TUI uses these)

async def get\_agent(db) \-\> dict | None: ...

async def get\_all\_ships(db) \-\> list\[dict\]: ...

async def get\_ship(db, symbol: str) \-\> dict | None: ...

async def get\_contracts(db) \-\> list\[dict\]: ...

async def get\_market\_latest(db, waypoint: str) \-\> list\[dict\]: ...

async def get\_market\_history(db, trade\_symbol: str, limit=100) \-\> list\[dict\]: ...

async def get\_waypoints\_by\_type(db, system: str, wp\_type: str) \-\> list\[dict\]: ...

async def get\_pending\_commands(db) \-\> list\[dict\]: ...

async def get\_recent\_transactions(db, limit=50) \-\> list\[dict\]: ...

\# Command queue (TUI writes, bot reads)

async def enqueue\_command(db, ship\_symbol, command, params: dict): ...

async def claim\_next\_command(db) \-\> dict | None: ...

async def complete\_command(db, command\_id, result: dict): ...

async def fail\_command(db, command\_id, error: str): ...

### Task list

1. Write all functions in `queries.py`.  
2. Write tests: insert a ship, read it back, verify round-trip.  
3. Write tests for the command queue lifecycle: enqueue → claim → complete.

---

## Phase 3: Bot — minimal viable automation

**Goal:** A bot process that runs independently. On startup it bootstraps the DB with universe data, then runs ship state machines. It also polls `command_queue` for TUI-issued commands.

### Bot supervisor (`bot/main.py`)

async def run():

    1\. Load config (token, DB path)

    2\. Init DB

    3\. Call GET /v2 — check reset, compare to stored reset\_date

       \- If new reset: wipe DB, re-register, store new token

    4\. Fetch and persist: agent, ships, contracts

    5\. Fetch and persist: starter system waypoints

    6\. Launch concurrent tasks:

       a. command\_queue\_consumer() — polls every 1s

       b. For each ship: ship\_loop(ship\_symbol)

       c. market\_poller() — refreshes markets at probe locations every 60s

       d. agent\_poller() — refreshes credits every 30s

    7\. On shutdown (Ctrl-C): cancel tasks, close DB \+ client

### Ship state machine (`bot/ships.py`)

Each ship runs an async loop. States:

IDLE            → check role, pick a task

IN\_TRANSIT      → sleep until arrival\_time, then transition

ON\_COOLDOWN     → sleep until cooldown\_expires, then transition

MINING          → extract, handle cooldown, check cargo full

HAULING         → navigate to sell point, dock, sell, navigate back

SELLING         → dock, sell cargo, update DB

PROBING         → parked at a market, do nothing (market\_poller handles reads)

FULFILLING      → deliver contract goods

For Phase 3, implement only:

- `IDLE` → orbit → navigate → wait → dock → sell → orbit → navigate back  
- Basic mining loop: orbit at asteroid → extract → wait cooldown → repeat until cargo full → navigate to market → sell all → return  
- Command queue integration: if a command arrives for this ship, interrupt the current idle state and execute it

### Command queue consumer (`bot/commands.py`)

Supported commands for Phase 3:

| Command | Params | What it does |
| :---- | :---- | :---- |
| `navigate` | `{waypoint}` | orbit if docked, then navigate |
| `dock` | `{}` | dock |
| `orbit` | `{}` | orbit |
| `buy` | `{symbol, units}` | purchase cargo at current market |
| `sell` | `{symbol, units}` | sell cargo at current market |
| `refuel` | `{}` | refuel |
| `extract` | `{}` | extract at current asteroid |
| `accept_contract` | `{contract_id}` | accept a contract |

The consumer claims a command, calls the appropriate API client method, writes the result (or error) back to the command row, and updates the ship's state in the DB from the response.

### Task list

1. Write `bot/main.py` — supervisor loop with reset detection and task launching.  
2. Write `bot/ships.py` — ship loop with a basic mining→sell cycle.  
3. Write `bot/commands.py` — command queue consumer that executes the 8 commands listed above.  
4. Test: run the bot, verify it registers, fetches ships, begins mining, and sells ore. Check that the DB is populated.  
5. Test command queue: insert a row manually (`INSERT INTO command_queue ...`), verify the bot picks it up and executes.

---

## Phase 4: TUI — core screens

**Goal:** A Textual app with a tabbed layout showing fleet, contracts, markets, and a command bar.

### App structure (`tui/app.py`)

class SpaceTradersApp(textual.app.App):

    TITLE \= "SpaceTraders"

    CSS\_PATH \= "app.tcss"

    BINDINGS \= \[

        ("f", "switch\_tab('fleet')", "Fleet"),

        ("c", "switch\_tab('contracts')", "Contracts"),

        ("m", "switch\_tab('markets')", "Markets"),

        ("t", "switch\_tab('transactions')", "Log"),

        ("q", "quit", "Quit"),

    \]

### Screen 1: Fleet overview (`screens/fleet.py`)

┌─ Agent: MYCALL | Credits: 342,100 | Ships: 12 ──────────────────────┐

│                                                                       │

│  Ship           Role       Status      Location        Fuel   Cargo   │

│  MYCALL-1       COMMAND    DOCKED      X1-DF55-A1      850/1200  12/80│

│  MYCALL-2       EXCAVATOR  IN\_TRANSIT  → X1-DF55-B3    40/100   0/40  │

│  MYCALL-3       HAULER     IN\_ORBIT    X1-DF55-C2      300/400  38/60 │

│  MYCALL-4       SATELLITE  DOCKED      X1-DF55-D1      0/0      0/0   │

│  ...                                                                   │

│                                                                       │

│  \[Selected: MYCALL-1\]                                                 │

│  Cargo: IRON\_ORE ×12                                                  │

│  Cooldown: ready                                                      │

│  Condition: frame 0.95 | engine 0.98 | reactor 1.00                   │

│                                                                       │

│  Commands: \[o\]rbit \[d\]ock \[n\]avigate \[e\]xtract \[s\]ell \[r\]efuel        │

└───────────────────────────────────────────────────────────────────────┘

Implementation:

- `DataTable` for the ship list, refreshed every 2s from DB.  
- Detail pane below the table showing selected ship's cargo, cooldown, condition.  
- Keybindings for commands: pressing `n` opens an input modal asking for a waypoint symbol, then writes to `command_queue`.  
- Ship rows color-coded by status: green \= ready, yellow \= in transit, red \= on cooldown or low fuel.

### Screen 2: Contracts (`screens/contracts.py`)

┌─ Active Contracts ───────────────────────────────────────────────────┐

│                                                                       │

│  ID          Type          Faction   Deadline          Status         │

│  ct\_abc123   PROCUREMENT   COSMIC    2026-05-15T12:00  In Progress   │

│    → Deliver 40 IRON\_ORE to X1-DF55-B1 (28/40 fulfilled)            │

│                                                                       │

│  ct\_def456   PROCUREMENT   COSMIC    2026-05-14T08:00  Not Accepted  │

│    → Deliver 20 COPPER\_ORE to X1-DF55-C3 (0/20 fulfilled)           │

│    Payment: 12,000 on accept \+ 38,000 on fulfill                     │

│                                                                       │

│  Commands: \[a\]ccept selected                                          │

└───────────────────────────────────────────────────────────────────────┘

Implementation:

- `DataTable` or `ListView` for contracts, refreshed from DB.  
- Delivery progress shown as `unitsFulfilled / unitsRequired`.  
- `a` key enqueues an `accept_contract` command.

### Screen 3: Markets (`screens/markets.py`)

┌─ Markets in X1-DF55 ─────────────────────────────────────────────────┐

│                                                                       │

│  Waypoint      Good           Type     Supply     Buy    Sell  Vol    │

│  X1-DF55-A1    IRON\_ORE       EXPORT   ABUNDANT   32     38   100    │

│  X1-DF55-A1    COPPER\_ORE     EXPORT   HIGH       45     52   100    │

│  X1-DF55-B1    IRON\_ORE       IMPORT   SCARCE     58     64    60    │

│  X1-DF55-B1    MACHINERY      EXPORT   MODERATE   120    135   40    │

│  X1-DF55-C2    FUEL           EXCHANGE ABUNDANT   10     12   200    │

│  ...                                                                   │

│                                                                       │

│  Last updated: 45s ago (via MYCALL-4 at X1-DF55-A1)                  │

│                                                                       │

│  Profitable routes:                                                   │

│    IRON\_ORE: A1 (buy 32\) → B1 (sell 64\) \= \+32/unit                  │

│    COPPER\_ORE: A1 (buy 45\) → C3 (sell 78\) \= \+33/unit                │

└───────────────────────────────────────────────────────────────────────┘

Implementation:

- Sortable `DataTable` of latest market snapshots from DB.  
- Bottom section computes simple spread: for each good that appears as EXPORT somewhere and IMPORT elsewhere, show the buy→sell delta.  
- Filter by system (default: agent's headquarters system).

### Screen 4: Transaction log (`screens/transactions.py`)

- Scrollable table of recent `transaction_log` rows.  
- Shows ship, type, good, units, price, total, timestamp.  
- Running total of profit/loss at the bottom.

### Shared: status bar and command queue feedback

- Footer bar shows: pending commands count, bot connection status (is the bot updating the DB? check `agent.updated_at` recency), current rate limit state.  
- When a command completes or fails, show a Textual `Notification` toast.

### Task list

1. Write `app.tcss` — color scheme, layout rules.  
2. Write `tui/app.py` — main App class with tab switching and DB polling.  
3. Write `screens/fleet.py` — ship table \+ detail pane \+ command keys.  
4. Write `screens/contracts.py` — contract list \+ accept action.  
5. Write `screens/markets.py` — market table \+ route calculator.  
6. Write `screens/transactions.py` — transaction log table.  
7. Write `widgets/command_input.py` — modal for entering parameters (e.g. waypoint symbol for navigate, units for buy/sell).  
8. Implement DB polling: a `set_interval(2.0)` timer that re-queries the DB and updates all visible tables.  
9. Test: start the bot, then start the TUI, verify data appears. Issue a `navigate` command from the TUI, confirm the bot executes it and the ship moves in the fleet view.

---

## Phase 5: Polish and operational features

**Goal:** Handle the rough edges that make the difference between a demo and a tool you actually use.

### Reset handling in the TUI

- On startup, TUI reads `reset_meta` table. If empty or stale, show a banner: "No active session — start the bot to register."  
- TUI polls `agent.updated_at`; if it stops advancing for \>60s, show a warning: "Bot may be offline."

### Command queue UX

- Show a small panel (collapsible) of recent command\_queue entries with status indicators: ⏳ pending, ▶ running, ✓ done, ✗ failed.  
- Failed commands show the error message on hover/select.

### Keybinding help overlay

- `?` key opens a help screen listing all keybindings per tab.

### Fuel and cooldown warnings

- Ship table highlights ships with \<20% fuel in red.  
- Ships on cooldown show a countdown (computed from `cooldown_expires` minus current time, updated every second).

### Market staleness indicator

- Markets not refreshed in \>5 minutes show as "stale" in the table.  
- Markets with no probe present show as "no sensor" with a note to deploy a probe.

### Task list

1. Add reset detection to TUI startup.  
2. Add bot-offline warning banner.  
3. Add command queue status panel.  
4. Add fuel/cooldown visual indicators to fleet screen.  
5. Add market staleness column.  
6. Add `?` help overlay.  
7. Write `app.tcss` refinements: consistent color palette, readable contrast, padding.

---

## Execution order for Claude Code

Give Claude Code these phases in order. Each phase should end with a working, testable state:

1. **Phase 0** — Run `pip install -e .` and both entry points work.  
2. **Phase 1** — Run the smoke test script; API calls succeed.  
3. **Phase 2** — Run query round-trip tests.  
4. **Phase 3** — Run `st-bot`; it registers, mines, sells. Insert a command row; it gets executed.  
5. **Phase 4** — Run `st-tui` alongside the bot; data appears, commands work.  
6. **Phase 5** — Visual polish and edge cases.

Each phase prompt to Claude Code should include:

- The relevant section of this plan  
- The project files from this Claude project (for API/game reference)  
- A note to read existing code before modifying (avoid duplicate work)  
- "Run the code and fix any errors before marking done"

---

## Prompting notes for Claude Code

When prompting each phase, include these standing instructions:

- Python 3.11+ — use `asyncio.TaskGroup` not `asyncio.gather`.  
- Use `aiosqlite` for all DB access. Enable WAL mode on every connection.  
- All timestamps in the DB are ISO 8601 UTC strings.  
- Every API response that updates ship state should write to the DB immediately — the TUI depends on fresh data.  
- Use `structlog` for all logging. Log to stderr so the TUI (stdout) isn't polluted.  
- `config.py` reads `ST_TOKEN` and `ST_DB_PATH` from environment variables, with sensible defaults.  
- Don't over-abstract early. A function is fine; a class hierarchy is not needed until Phase 5+.  
- Run `ruff check` and `ruff format` before finishing each phase.

