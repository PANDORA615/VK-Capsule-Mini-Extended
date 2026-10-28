from typing import Literal

from pydantic import BaseModel, Field

from capsule.storage import Store


class Zone(BaseModel):
    enabled: bool = True
    color: str = Field(default="#b49aff", pattern=r"^#[0-9a-fA-F]{6}$")
    brightness: int = Field(default=60, ge=0, le=100)
    effect: Literal["steady", "breathe", "pulse"] = "steady"


class Lights:
    def __init__(self, store: Store):
        self.store = store
        data = store.read()
        self.zones = {name: Zone(**data.get(name, {})) for name in ("front", "top")}

    def status(self):
        return {
            "zones": {name: zone.model_dump() for name, zone in self.zones.items()},
            "backend": "virtual",
            "hardware_verification_required": True,
        }

    def set(self, name: str, value: Zone):
        if name not in self.zones:
            raise ValueError("Unknown light zone")
        self.zones[name] = value
        self.store.write({name: zone.model_dump() for name, zone in self.zones.items()})
        return self.status()
