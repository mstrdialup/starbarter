-- Metadata about the current reset
CREATE TABLE IF NOT EXISTS reset_meta (
    reset_date TEXT PRIMARY KEY,
    registered_at TEXT,
    agent_symbol TEXT,
    token TEXT
);

-- Universe: systems (static per reset)
CREATE TABLE IF NOT EXISTS system (
    symbol TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL
);

-- Universe: waypoints
CREATE TABLE IF NOT EXISTS waypoint (
    symbol TEXT PRIMARY KEY,
    system_symbol TEXT NOT NULL REFERENCES system(symbol),
    type TEXT NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    traits TEXT NOT NULL DEFAULT '[]',
    faction TEXT,
    is_charted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wp_system_type ON waypoint(system_symbol, type);

-- Market snapshots (time series)
CREATE TABLE IF NOT EXISTS market_snapshot (
    waypoint TEXT NOT NULL,
    trade_symbol TEXT NOT NULL,
    snapshot_ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    type TEXT,
    supply TEXT,
    activity TEXT,
    purchase_price INTEGER,
    sell_price INTEGER,
    trade_volume INTEGER,
    PRIMARY KEY (waypoint, trade_symbol, snapshot_ts)
);

CREATE INDEX IF NOT EXISTS idx_mkt_symbol_ts ON market_snapshot(trade_symbol, snapshot_ts DESC);

-- Ships
CREATE TABLE IF NOT EXISTS ship (
    symbol TEXT PRIMARY KEY,
    role TEXT,
    frame TEXT,
    nav_status TEXT,
    nav_waypoint TEXT,
    nav_flight_mode TEXT,
    arrival_time TEXT,
    fuel_current INTEGER,
    fuel_capacity INTEGER,
    cargo_capacity INTEGER,
    cargo_units INTEGER,
    cargo_inventory TEXT,
    cooldown_expires TEXT,
    condition_frame REAL,
    condition_engine REAL,
    condition_reactor REAL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Contracts
CREATE TABLE IF NOT EXISTS contract (
    id TEXT PRIMARY KEY,
    faction TEXT,
    type TEXT,
    terms TEXT NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    fulfilled INTEGER NOT NULL DEFAULT 0,
    deadline TEXT,
    deadline_to_accept TEXT
);

-- Surveys (ephemeral, expire quickly)
CREATE TABLE IF NOT EXISTS survey (
    signature TEXT PRIMARY KEY,
    waypoint TEXT NOT NULL,
    deposits TEXT NOT NULL,
    expiration TEXT NOT NULL,
    size TEXT
);

-- Agent state
CREATE TABLE IF NOT EXISTS agent (
    symbol TEXT PRIMARY KEY,
    credits INTEGER NOT NULL DEFAULT 0,
    headquarters TEXT,
    ship_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Command queue (TUI → Bot)
CREATE TABLE IF NOT EXISTS command_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ship_symbol TEXT,
    command TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    completed_at TEXT
);

-- Transaction log
CREATE TABLE IF NOT EXISTS transaction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ship_symbol TEXT NOT NULL,
    type TEXT NOT NULL,
    trade_symbol TEXT,
    units INTEGER,
    price_per_unit INTEGER,
    total INTEGER,
    waypoint TEXT,
    timestamp TEXT NOT NULL
);
