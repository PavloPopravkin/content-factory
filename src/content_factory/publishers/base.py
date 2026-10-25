from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import mimetypes
from pathlib import Path
import subprocess
from typing import Any, Protocol

import httpx

from ..config import Channel
from ..models import Asset, Delivery, Part, Result, Slot, State


class PublisherError(RuntimeError):
    uncertain = False


class PublishRejected(PublisherError):
    pass


class PublishDeferred(PublisherError):
    def __init__(self, message: str, retry_after: float = 60):
        super().__init__(message)
        self.retry_after = max(1, retry_after) if math.isfinite(retry_after) else 60


class UnknownResult(PublisherError):
    uncertain = True


class PolicyBlocked(PublisherError):
    pass


class UnsupportedOperation(PublisherError):
    pass


class Publisher(Protocol):
    def publish(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result: ...
    def reconcile(self, delivery: Delivery) -> Result: ...
    def delete(self, part: Part) -> None: ...


class HttpPublisher:
    def __init__(self, client: httpx.Client, *, gate: Callable[[], None] = lambda: None,
                 checkpoint: Callable[[Result], None] = lambda result: None):
        self.client = client
        self.gate = gate
        self.checkpoint = checkpoint

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        self.gate()
        try:
            response = self.client.request(method, url, timeout=30.0, **kwargs)
        except httpx.RequestError as exc:
            # Deliberately omit request URLs and bodies: Telegram URLs contain the bot token.
            raise UnknownResult(f"transport {type(exc).__name__}; verify externally before retry") from None
        try:
            body = response.json()
        except (ValueError, UnicodeError):
            body = None
        error = body.get("error", {}) if isinstance(body, dict) else {}
        graph_throttle = (isinstance(error, dict) and error.get("code") in (4, 17, 32, 613)
                          and httpx.URL(url).host == "graph.facebook.com")
        telegram_throttle = (isinstance(body, dict) and body.get("ok") is False and body.get("error_code") == 429
                             and httpx.URL(url).host == "api.telegram.org")
        if (response.status_code == 429 or graph_throttle or telegram_throttle
                or (400 <= response.status_code < 500 and response.status_code != 408
                    and "Retry-After" in response.headers)):
            delays = [60.0]
            parameters = body.get("parameters", {}) if isinstance(body, dict) else {}
            if isinstance(parameters, dict) and isinstance(parameters.get("retry_after"), (int, float)):
                delays = [float(parameters["retry_after"])]
            header = response.headers.get("Retry-After")
            if header:
                try:
                    delay = float(header)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = 60.0
                delays = [max(delay, delays[0])] if parameters else [delay]
            raise PublishDeferred("provider rate limit; request rejected before acceptance", max(delays))
        if response.status_code >= 500 or response.status_code in (408,):
            raise UnknownResult(f"provider HTTP {response.status_code}; acceptance uncertain")
        if response.is_error:
            raise PublishRejected(f"provider HTTP {response.status_code}")
        try:
            return response.json()
        except (ValueError, UnicodeError):
            raise UnknownResult("provider returned invalid JSON") from None

    def save(self, delivery: Delivery, *, ids: dict | None = None,
             parts: list[Part] | None = None, state: State = State.SUBMITTING) -> Result:
        result = Result(state=state, external_ids=ids or {}, parts=parts or [])
        self.checkpoint(result)
        delivery.external_ids.update(result.external_ids)
        delivery.state = state
        return result

    @staticmethod
    def part(delivery: Delivery, kind: str, external_id: str | int, url: str | None = None) -> Part:
        return Part(tenant_slug=delivery.tenant_slug, delivery_id=delivery.id,
                    kind=kind, external_id=str(external_id), url=url)


def validate_context(delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> None:
    if delivery.state != State.SUBMITTING:
        raise PublishRejected("only a submitting delivery can publish; never resend an existing result")
    if (delivery.tenant_slug != slot.tenant_slug or delivery.slot_id != slot.id
            or delivery.channel_id != channel.id or channel.id not in slot.channel_ids
            or any(a.tenant_slug != slot.tenant_slug for a in media)
            or [a.id for a in media] != slot.media_ids):
        raise PublishRejected("tenant, slot, channel or media context mismatch")


def remote_url(asset: Asset) -> str:
    url = httpx.URL(asset.source)
    if url.scheme not in ("http", "https") or not url.host or url.username or url.password:
        raise PublishRejected("this provider requires an HTTP(S) media URL without credentials")
    return str(url)


def media_file(stack: ExitStack, asset: Asset) -> tuple:
    path = Path(asset.source)
    file = stack.enter_context(path.open("rb"))
    if asset.sha256 is not None:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
        if actual != asset.sha256 or (asset.size is not None and path.stat().st_size != asset.size):
            raise PublishRejected("media changed since approval/ingest")
        file.seek(0)
    return (path.name, file, mimetypes.guess_type(path.name)[0] or "application/octet-stream")


def video_metadata(asset: Asset) -> dict[str, int]:
    values = {k: v for k, v in asset.model_dump().items() if k in ("width", "height", "duration") and v}
    if len(values) < 3 and not asset.source.startswith(("http://", "https://")):
        try:
            output = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height:format=duration", "-of", "json", asset.source],
                capture_output=True, text=True, timeout=10, check=True,
            )
            data = json.loads(output.stdout)
            stream = data.get("streams", [{}])[0]
            for key in ("width", "height"):
                if stream.get(key):
                    values.setdefault(key, stream[key])
            if data.get("format", {}).get("duration"):
                values.setdefault("duration", float(data["format"]["duration"]))
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    return {k: max(1, math.ceil(float(v))) for k, v in values.items()}
