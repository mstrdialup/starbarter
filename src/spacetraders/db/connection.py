import asyncio
from pathlib import Path

import aiosqlite

from spacetraders import config

_SCHEMA_SQL = Path(__file__).parent / "schema.sql"

_lock = asyncio.Lock()
_initialised: set[str] = set()


async def get_db(db_path: str | None = None) -> aiosqlite.Connection:
    path = db_path or config.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA synchronous=NORMAL")
    return db


async def init_db(db_path: str | None = None) -> None:
    path = db_path or config.DB_PATH
    async with _lock:
        if path in _initialised:
            return
        schema = _SCHEMA_SQL.read_text()
        db = await get_db(path)
        try:
            await db.executescript(schema)
            await db.commit()
        finally:
            await db.close()
        _initialised.add(path)
