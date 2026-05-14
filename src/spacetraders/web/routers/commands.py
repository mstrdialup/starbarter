from __future__ import annotations

from typing import Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator

from spacetraders.db import queries
from spacetraders.web.deps import get_db

router = APIRouter(tags=["commands"])

# ---------------------------------------------------------------------------
# Request model — discriminated by command field
# ---------------------------------------------------------------------------


class NavigateParams(BaseModel):
    waypoint: str


class BuySellParams(BaseModel):
    symbol: str
    units: int


class RefuelParams(BaseModel):
    from_cargo: bool = False


class ContractParams(BaseModel):
    contract_id: str


class EmptyParams(BaseModel):
    pass


class CommandRequest(BaseModel):
    ship_symbol: str | None = None
    command: str
    params: dict[str, Any] = {}

    @model_validator(mode="after")
    def validate_params(self) -> CommandRequest:
        cmd = self.command
        p = self.params
        if cmd == "navigate":
            NavigateParams.model_validate(p)
        elif cmd in ("buy", "sell"):
            BuySellParams.model_validate(p)
        elif cmd == "refuel":
            RefuelParams.model_validate(p)
        elif cmd == "accept_contract":
            if self.ship_symbol is None:
                pass  # no ship needed
            ContractParams.model_validate(p)
        elif cmd in ("dock", "orbit", "extract"):
            pass
        else:
            raise ValueError(f"Unknown command: {cmd!r}")
        return self


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/commands")
async def list_commands(
    limit: int = 50,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return await queries.get_recent_commands(db, limit=limit)


@router.post("/commands", status_code=status.HTTP_201_CREATED)
async def enqueue_command(
    body: CommandRequest,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    cmd_id = await queries.enqueue_command(db, body.ship_symbol, body.command, body.params)
    cmd = await queries.get_command(db, cmd_id)
    return cmd  # type: ignore[return-value]


@router.delete("/commands/{command_id}")
async def cancel_command(
    command_id: int,
    db: aiosqlite.Connection = Depends(get_db),
) -> dict[str, Any]:
    cmd = await queries.get_command(db, command_id)
    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found")
    if cmd["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel command with status '{cmd['status']}'",
        )
    await queries.cancel_command(db, command_id)
    return {"id": command_id, "status": "cancelled"}
