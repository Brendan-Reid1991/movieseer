from __future__ import annotations
from ._base import _CamelBase
from datetime import datetime, timezone
from enum import StrEnum, auto

from pydantic import field_validator

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type ContainerIdentifier = dict[str, str]


class Network(_CamelBase):
    id: str
    name: str
    created: datetime
    containers: ContainerIdentifier

    @field_validator("containers", mode="before")
    @classmethod
    def load_containers(cls, raw_containers: list[JsonValue]) -> ContainerIdentifier:
        return {summary["Name"]: _id for _id, summary in raw_containers.items()}


class ContainerStatus(StrEnum):
    created = auto()
    restarting = auto()
    running = auto()
    removing = auto()
    paused = auto()
    exited = auto()
    dead = auto()


class ContainerHealth(StrEnum):
    starting = auto()
    healthy = auto()
    unhealthy = auto()
    missing = auto()


class ContainerState(_CamelBase):
    id: str
    status: ContainerStatus
    health: ContainerHealth
    started_at: datetime

    @classmethod
    def from_attrs(cls, inspect_output: JsonValue) -> ContainerState:
        """Generate a container state from the output of Container.attrs."""
        state: JsonValue = inspect_output["State"]
        health = state.get("Health", {})
        return cls.model_validate(
            {
                "id": inspect_output["Id"],
                "status": state["Status"],
                "health": health.get("Status", ContainerHealth.missing),
                "started_at": state["StartedAt"],
            }
        )

    @property
    def uptime(self):
        return datetime.now(self.started_at.tzinfo) - self.started_at            
