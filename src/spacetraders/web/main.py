from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from spacetraders import config
from spacetraders.db.connection import get_db, init_db
from spacetraders.web.routers import (
    agent,
    commands,
    contracts,
    events,
    markets,
    ships,
    transactions,
)

log = structlog.get_logger()

_STATIC_DIR = Path(__file__).parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
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
        await db.execute("SELECT reset_date FROM reset_meta LIMIT 1")
        log.info("web_startup", db=config.DB_PATH, port=config.WEB_PORT)
    except Exception as exc:
        log.warning("db_check_failed", error=str(exc))
    finally:
        await db.close()
    yield
    log.info("web_shutdown")


app = FastAPI(title="SpaceTraders", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router, prefix="/api")
app.include_router(ships.router, prefix="/api")
app.include_router(contracts.router, prefix="/api")
app.include_router(markets.router, prefix="/api")
app.include_router(transactions.router, prefix="/api")
app.include_router(commands.router, prefix="/api")
app.include_router(events.router)

if (_STATIC_DIR / "app").exists():
    app.mount("/app", StaticFiles(directory=str(_STATIC_DIR / "app")), name="app-static")

if (_STATIC_DIR / "icons").exists():
    app.mount("/icons", StaticFiles(directory=str(_STATIC_DIR / "icons")), name="icons")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(str(_STATIC_DIR / "manifest.json"))


@app.get("/sw.js")
async def service_worker():
    return FileResponse(str(_STATIC_DIR / "sw.js"), media_type="application/javascript")


@app.get("/{full_path:path}")
async def serve_pwa(full_path: str):
    return FileResponse(str(_INDEX_HTML))


def run() -> None:
    uvicorn.run(
        "spacetraders.web.main:app",
        host="0.0.0.0",
        port=config.WEB_PORT,
        reload=False,
    )
