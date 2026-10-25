from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re

from pydantic import Field, field_validator, model_validator
import yaml

from .models import Kind, Model


class Languages(Model):
    content: list[str] = Field(min_length=1)
    ops: str
    contributors: list[str] = Field(min_length=1)


class Brand(Model):
    logo: str
    font: str
    subtitle_style: str


class WeeklyBlackout(Model):
    type: Literal["weekly"]
    from_: str = Field(alias="from")
    to: str

    @field_validator("from_", "to")
    @classmethod
    def valid_boundary(cls, value: str) -> str:
        if not re.fullmatch(r"(mon|tue|wed|thu|fri|sat|sun) ([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("expected weekday HH:MM, e.g. fri 15:00")
        return value

    @model_validator(mode="after")
    def nonempty(self) -> "WeeklyBlackout":
        if self.from_ == self.to:
            raise ValueError("weekly blackout boundaries must differ")
        return self


class SunsetShabbat(Model):
    type: Literal["sunset_shabbat"]
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    margin_before_min: int = Field(ge=0)
    margin_after_min: int = Field(ge=0)


Blackout = Annotated[WeeklyBlackout | SunsetShabbat, Field(discriminator="type")]


class Schedule(Model):
    daily_caps: dict[Kind, int]
    min_gap_minutes: int = Field(ge=0)
    hours: tuple[str, str]
    blackout: list[Blackout] = Field(default_factory=list)

    @field_validator("daily_caps")
    @classmethod
    def valid_caps(cls, value: dict[Kind, int]) -> dict[Kind, int]:
        if set(value) != set(Kind) or any(v < 0 for v in value.values()):
            raise ValueError("daily_caps needs nonnegative post, reel and story limits")
        return value

    @field_validator("hours")
    @classmethod
    def valid_hours(cls, value: tuple[str, str]) -> tuple[str, str]:
        if any(not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d|24:00", x) for x in value):
            raise ValueError("hours must be [HH:MM, HH:MM], end may be 24:00")
        if value[0] == "24:00" or value[0] == value[1]:
            raise ValueError("hours must define a nonempty interval; use 00:00, 24:00 for all day")
        return value


class Approval(Model):
    mode: Literal["auto", "manual"]
    require_for_kinds: list[Kind] = Field(default_factory=list)


class Channel(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    type: Literal["fb_page", "ig", "tg_channel", "yt", "tiktok", "linkedin"]
    publisher: Literal["meta", "telegram", "postiz", "dry"]
    external_id: str = Field(min_length=1)
    secret_ref: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    voice: str | None = None
    capabilities: list[Literal["post", "carousel", "reel", "story"]] = Field(min_length=1)
    # Provider-specific DTO values (YouTube/TikTok etc.) pass through to Postiz.
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def compatible_publisher(self) -> "Channel":
        if self.publisher == "telegram" and self.type != "tg_channel":
            raise ValueError("telegram publisher requires tg_channel")
        if self.publisher == "meta" and self.type not in ("fb_page", "ig"):
            raise ValueError("meta publisher requires fb_page or ig")
        return self


class Tenant(Model):
    schema_version: Literal[1]
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    timezone: str
    languages: Languages
    brand: Brand
    policy_file: str
    schedule: Schedule
    approval: Approval
    channels: list[Channel] = Field(min_length=1)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone {value}") from exc
        return value

    @model_validator(mode="after")
    def unique_channels(self) -> "Tenant":
        if len({c.id for c in self.channels}) != len(self.channels):
            raise ValueError("channel ids must be unique")
        return self

    def channel(self, channel_id: str) -> Channel:
        for channel in self.channels:
            if channel.id == channel_id:
                return channel
        raise ValueError(f"unknown channel {channel_id!r} for tenant {self.slug}")


def load_tenant(path: str | Path) -> Tenant:
    path = Path(path)
    if path.is_dir():
        path /= "tenant.yaml"
    try:
        tenant = Tenant.model_validate(yaml.safe_load(path.read_text()))
        directory = path.resolve().parent
        policy = (directory / tenant.policy_file).resolve()
        if not policy.is_relative_to(directory) or policy.suffix.lower() != ".md":
            raise ValueError("policy_file must be a markdown file inside the tenant directory")
        if not policy.is_file() or not policy.read_text().strip():
            raise ValueError(f"policy_file is missing or empty: {tenant.policy_file}")
        return tenant
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"Invalid tenant config {path}: {exc}") from exc
