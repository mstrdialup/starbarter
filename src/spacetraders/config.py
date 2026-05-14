import os
from pathlib import Path


def _default_db_path() -> str:
    return str(Path.home() / ".spacetraders" / "spacetraders.db")


TOKEN: str = os.environ.get("ST_TOKEN", "")
DB_PATH: str = os.environ.get("ST_DB_PATH", _default_db_path())
BASE_URL: str = os.environ.get("ST_BASE_URL", "https://api.spacetraders.io/v2")
WEB_PORT: int = int(os.environ.get("ST_WEB_PORT", "8080"))
ALLOWED_ORIGINS: list[str] = os.environ.get("ST_ALLOWED_ORIGINS", "*").split(",")
