from __future__ import annotations

from collections.abc import AsyncGenerator

import aiosqlite

from spacetraders.db.connection import get_db as _get_db


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    db = await _get_db()
    try:
        yield db
    finally:
        await db.close()
