from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Kind(StrEnum):
    POST = "post"
    REEL = "reel"
    STORY = "story"


class State(StrEnum):
    SUBMITTING = "submitting"
    ACCEPTED = "accepted"
    PUBLISHED = "published"
    FAILED = "failed"
    UNKNOWN = "unknown"
    DEFERRED = "deferred"


def new_id() -> str:
    return str(uuid4())


class Asset(Model):
    id: str = Field(default_factory=new_id)
    tenant_slug: str
    source: str
    kind: str = Field(pattern=r"^(photo|video)$")
    sha256: str | None = None
    size: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, gt=0)
    height: int | None = Field(default=None, gt=0)
    duration: float | None = Field(default=None, gt=0)


class Slot(Model):
    id: str = Field(default_factory=new_id)
    tenant_slug: str
    at: AwareDatetime
    kind: Kind
    channel_ids: list[str] = Field(min_length=1)
    caption: str = ""
    media_ids: list[str] = Field(default_factory=list)
    version: int = Field(default=1, ge=1)
    approved_version: int | None = Field(default=None, ge=1)
    cancelled: bool = False
    approved_hash: str | None = None
    missed: bool = False

    @model_validator(mode="after")
    def unique_references(self) -> "Slot":
        if self.approved_version is not None and self.approved_version > self.version:
            raise ValueError("approved_version cannot exceed version")
        if len(set(self.channel_ids)) != len(self.channel_ids):
            raise ValueError("channel_ids must be unique")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("media_ids must be unique")
        return self


class Delivery(Model):
    id: str = Field(default_factory=new_id)
    tenant_slug: str
    slot_id: str
    channel_id: str
    delivery_key: str
    state: State = State.SUBMITTING
    attempts: int = 1
    external_ids: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: AwareDatetime | None = None
    next_attempt_at: AwareDatetime | None = None


class Part(Model):
    id: str = Field(default_factory=new_id)
    tenant_slug: str
    delivery_id: str
    kind: str
    external_id: str
    url: str | None = None


class Result(Model):
    state: State
    external_ids: dict[str, Any] = Field(default_factory=dict)
    parts: list[Part] = Field(default_factory=list)
    error: str | None = None
