from contextlib import ExitStack
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import os
from typing import Any

import httpx

from ..config import Channel
from ..models import Asset, Delivery, Kind, Part, Result, Slot, State
from .base import HttpPublisher, PublishRejected, UnknownResult, UnsupportedOperation, media_file, remote_url, validate_context

PROVIDERS = {"fb_page": "facebook", "ig": "instagram", "tg_channel": "telegram",
             "yt": "youtube", "tiktok": "tiktok", "linkedin": "linkedin"}


class PostizPublisher(HttpPublisher):
    def __init__(self, client: httpx.Client, key: str, url: str, **kwargs: Any) -> None:
        super().__init__(client, **kwargs)
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host or parsed.username or parsed.password:
            raise ValueError("Postiz URL must be HTTP(S) without embedded credentials")
        self.base = url.rstrip("/") + "/api/public/v1"
        self.headers = {"Authorization": key}
        self.rate_scope = hashlib.sha256((self.base + "\0" + key).encode()).hexdigest()
        self.api_limit = int(os.environ.get("CF_POSTIZ_API_LIMIT", os.environ.get("API_LIMIT", "30")))
        if self.api_limit < 1:
            raise ValueError("CF_POSTIZ_API_LIMIT must be a positive integer")
        self.reserve_post: Callable[[], None] = lambda: None

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        return self.request(method, self.base + path, headers=self.headers, **kwargs)

    def publish(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        validate_context(delivery, slot, channel, media)
        if channel.type == "fb_page" and slot.kind == Kind.REEL:
            raise PublishRejected("Postiz cannot guarantee FB Reel semantics; use meta publisher")
        settings = {"__type": PROVIDERS[channel.type], **channel.settings}
        if channel.type in ("ig", "fb_page"):
            settings["post_type"] = "story" if slot.kind == Kind.STORY else "post"
        if channel.type == "yt" and not all(settings.get(k) for k in ("title", "type")):
            raise PublishRejected("Postiz YouTube requires channel.settings.title and type")
        if channel.type == "tiktok" and settings.get("content_posting_method") != "DIRECT_POST":
            raise PublishRejected("Postiz TikTok requires settings.content_posting_method=DIRECT_POST")
        images = []
        for asset in media:
            if asset.source.startswith(("http://", "https://")):
                uploaded = self._call("POST", "/upload-from-url", json={"url": remote_url(asset), "adjust": False})
            else:
                with ExitStack() as stack:
                    uploaded = self._call("POST", "/upload", files={"file": media_file(stack, asset)})
            if not isinstance(uploaded, dict) or not uploaded.get("id") or not uploaded.get("path"):
                raise UnknownResult("Postiz upload response missing id/path")
            images.append({"id": uploaded["id"], "path": uploaded["path"]})
            self.save(delivery, ids={"uploads": images.copy()})
        payload = {"type": "now", "date": datetime.now(timezone.utc).isoformat(), "shortLink": False, "tags": [],
                   "posts": [{"integration": {"id": channel.external_id},
                              "value": [{"content": slot.caption, "image": images}], "settings": settings}]}
        self.reserve_post()
        created = self._call("POST", "/posts", json=payload)
        if (not isinstance(created, list) or len(created) != 1
                or not isinstance(created[0], dict) or not created[0].get("postId")
                or created[0].get("integration") != channel.external_id):
            raise UnknownResult("Postiz create response missing postId or integration mismatch")
        return self.save(delivery, ids={"post_id": created[0]["postId"]}, state=State.ACCEPTED)

    def reconcile(self, delivery: Delivery) -> Result:
        post_id = delivery.external_ids.get("post_id")
        if not post_id:
            return Result(state=State.UNKNOWN, external_ids=delivery.external_ids,
                          error="Postiz response lost before postId; manual verification required")
        created = delivery.created_at or datetime.now(timezone.utc)
        payload = self._call("GET", "/posts", params={"startDate": (created - timedelta(days=1)).isoformat(),
                                                      "endDate": (created + timedelta(days=1)).isoformat()})
        if not isinstance(payload, dict) or not isinstance(payload.get("posts"), list):
            raise UnknownResult("Postiz list response missing posts")
        post = next((p for p in payload["posts"] if p.get("id") == post_id), None)
        if post is None:
            return Result(state=State.UNKNOWN, error="Postiz post not found; verify manually")
        state = str(post.get("state", "")).upper()
        if state == "PUBLISHED":
            release = post.get("releaseId")
            if not release:
                return Result(state=State.UNKNOWN, error="Postiz PUBLISHED without releaseId")
            part = self.part(delivery, "post", release, post.get("releaseURL"))
            return Result(state=State.PUBLISHED, external_ids={"release_id": release}, parts=[part])
        if state == "ERROR":
            return Result(state=State.FAILED, error="Postiz reports publication ERROR")
        if state in ("QUEUE", "PENDING", "PROCESSING"):
            return Result(state=State.ACCEPTED)
        return Result(state=State.UNKNOWN, error=f"unrecognized Postiz state {state!r}")

    def delete(self, part: Part) -> None:
        # DELETE /posts only removes the internal schedule, not the social object.
        raise UnsupportedOperation("Postiz Public API cannot delete published social objects")
