from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ServerStatus(BaseModel):
    status: str
    version: str
    reset_date: str = Field(alias="resetDate")
    description: str = ""
    server_resets: dict[str, Any] = Field(default_factory=dict, alias="serverResets")

    model_config = {"populate_by_name": True}


class Agent(BaseModel):
    account_id: str = Field("", alias="accountId")
    symbol: str
    headquarters: str
    credits: int
    starting_faction: str = Field("", alias="startingFaction")
    ship_count: int = Field(0, alias="shipCount")

    model_config = {"populate_by_name": True}


class WaypointTrait(BaseModel):
    symbol: str
    name: str
    description: str = ""


class Waypoint(BaseModel):
    symbol: str
    type: str
    system_symbol: str = Field(alias="systemSymbol")
    x: int
    y: int
    traits: list[WaypointTrait] = Field(default_factory=list)
    faction: dict[str, Any] | None = None
    is_under_construction: bool = Field(False, alias="isUnderConstruction")
    chart: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


class System(BaseModel):
    symbol: str
    sector_symbol: str = Field("", alias="sectorSymbol")
    type: str
    x: int
    y: int
    waypoints: list[dict[str, Any]] = Field(default_factory=list)
    factions: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ShipNav(BaseModel):
    system_symbol: str = Field(alias="systemSymbol")
    waypoint_symbol: str = Field(alias="waypointSymbol")
    route: dict[str, Any] = Field(default_factory=dict)
    status: str
    flight_mode: str = Field("CRUISE", alias="flightMode")

    model_config = {"populate_by_name": True}

    @property
    def arrival_time(self) -> datetime | None:
        arrival = self.route.get("arrival")
        if arrival:
            return datetime.fromisoformat(arrival.replace("Z", "+00:00"))
        return None


class ShipFuel(BaseModel):
    current: int
    capacity: int
    consumed: dict[str, Any] = Field(default_factory=dict)


class CargoItem(BaseModel):
    symbol: str
    name: str = ""
    description: str = ""
    units: int


class ShipCargo(BaseModel):
    capacity: int
    units: int
    inventory: list[CargoItem] = Field(default_factory=list)


class Cooldown(BaseModel):
    ship_symbol: str = Field("", alias="shipSymbol")
    total_seconds: int = Field(0, alias="totalSeconds")
    remaining_seconds: int = Field(0, alias="remainingSeconds")
    expiration: datetime | None = None

    model_config = {"populate_by_name": True}

    @field_validator("expiration", mode="before")
    @classmethod
    def parse_expiration(cls, v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class ShipFrame(BaseModel):
    symbol: str
    condition: float = 1.0


class ShipEngine(BaseModel):
    symbol: str
    condition: float = 1.0


class ShipReactor(BaseModel):
    symbol: str
    condition: float = 1.0


class Ship(BaseModel):
    symbol: str
    registration: dict[str, Any] = Field(default_factory=dict)
    nav: ShipNav
    crew: dict[str, Any] = Field(default_factory=dict)
    frame: ShipFrame
    reactor: ShipReactor
    engine: ShipEngine
    cooldown: Cooldown
    modules: list[dict[str, Any]] = Field(default_factory=list)
    mounts: list[dict[str, Any]] = Field(default_factory=list)
    cargo: ShipCargo
    fuel: ShipFuel

    @property
    def role(self) -> str:
        return self.registration.get("role", "")

    @property
    def system_symbol(self) -> str:
        return self.nav.system_symbol


class ContractDeliverable(BaseModel):
    trade_symbol: str = Field(alias="tradeSymbol")
    destination_symbol: str = Field(alias="destinationSymbol")
    units_required: int = Field(alias="unitsRequired")
    units_fulfilled: int = Field(0, alias="unitsFulfilled")

    model_config = {"populate_by_name": True}


class ContractPayment(BaseModel):
    on_accepted: int = Field(0, alias="onAccepted")
    on_fulfilled: int = Field(0, alias="onFulfilled")

    model_config = {"populate_by_name": True}


class ContractTerms(BaseModel):
    deadline: datetime
    payment: ContractPayment
    deliver: list[ContractDeliverable] = Field(default_factory=list)

    @field_validator("deadline", mode="before")
    @classmethod
    def parse_deadline(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class Contract(BaseModel):
    id: str
    faction_symbol: str = Field("", alias="factionSymbol")
    type: str
    terms: ContractTerms
    accepted: bool = False
    fulfilled: bool = False
    deadline_to_accept: datetime | None = Field(None, alias="deadlineToAccept")

    model_config = {"populate_by_name": True}

    @field_validator("deadline_to_accept", mode="before")
    @classmethod
    def parse_deadline_to_accept(cls, v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class MarketTradeGood(BaseModel):
    symbol: str
    type: str
    trade_volume: int = Field(alias="tradeVolume")
    supply: str
    activity: str = ""
    purchase_price: int = Field(alias="purchasePrice")
    sell_price: int = Field(alias="sellPrice")

    model_config = {"populate_by_name": True}


class Market(BaseModel):
    symbol: str
    imports: list[dict[str, Any]] = Field(default_factory=list)
    exports: list[dict[str, Any]] = Field(default_factory=list)
    exchange: list[dict[str, Any]] = Field(default_factory=list)
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    trade_goods: list[MarketTradeGood] = Field(default_factory=list, alias="tradeGoods")

    model_config = {"populate_by_name": True}


class Survey(BaseModel):
    signature: str
    symbol: str
    deposits: list[dict[str, Any]] = Field(default_factory=list)
    expiration: datetime
    size: str

    @field_validator("expiration", mode="before")
    @classmethod
    def parse_expiration(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class ShipyardShip(BaseModel):
    type: str
    name: str = ""
    description: str = ""
    supply: str = ""
    purchase_price: int = Field(0, alias="purchasePrice")
    frame: dict[str, Any] = Field(default_factory=dict)
    reactor: dict[str, Any] = Field(default_factory=dict)
    engine: dict[str, Any] = Field(default_factory=dict)
    modules: list[dict[str, Any]] = Field(default_factory=list)
    mounts: list[dict[str, Any]] = Field(default_factory=list)
    crew: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class Shipyard(BaseModel):
    symbol: str
    ship_types: list[dict[str, Any]] = Field(default_factory=list, alias="shipTypes")
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    ships: list[ShipyardShip] = Field(default_factory=list)
    modifications_fee: int = Field(0, alias="modificationsFee")

    model_config = {"populate_by_name": True}


class ExtractionYield(BaseModel):
    symbol: str
    units: int


class Extraction(BaseModel):
    ship_symbol: str = Field(alias="shipSymbol")
    yield_: ExtractionYield = Field(alias="yield")

    model_config = {"populate_by_name": True}


class MarketTransaction(BaseModel):
    waypoint_symbol: str = Field(alias="waypointSymbol")
    ship_symbol: str = Field(alias="shipSymbol")
    trade_symbol: str = Field(alias="tradeSymbol")
    type: str
    units: int
    price_per_unit: int = Field(alias="pricePerUnit")
    total_price: int = Field(alias="totalPrice")
    timestamp: datetime

    model_config = {"populate_by_name": True}

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_ts(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class RegisterResponse(BaseModel):
    agent: Agent
    contract: Contract
    faction: dict[str, Any]
    ship: Ship
    token: str
