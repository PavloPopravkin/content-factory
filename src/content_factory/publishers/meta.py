from pathlib import Path
import json
import re
import time
from typing import Any

import httpx

from ..config import Channel
from ..models import Asset, Delivery, Kind, Part, Result, Slot, State
from .base import HttpPublisher, PublishRejected, UnknownResult, remote_url, validate_context


class MetaPublisher(HttpPublisher):
    def __init__(self, client: httpx.Client, token: str, *, graph_version: str = "v25.0",
                 poll_attempts: int = 5, poll_interval: float = 60, **kwargs: Any) -> None:
        super().__init__(client, **kwargs)
        if not re.fullmatch(r"v\d+\.\d+", graph_version):
            raise ValueError("Graph version must look like v25.0")
        if poll_attempts < 1 or poll_interval < 0:
            raise ValueError("invalid polling limits")
        self.base = f"https://graph.facebook.com/{graph_version}"
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}
        self.poll_attempts = poll_attempts
        self.poll_interval = poll_interval

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        data = self.request(method, f"{self.base}/{path}", headers=self.headers, **kwargs)
        if isinstance(data, dict) and "error" in data:
            raise PublishRejected(f"Meta error code {data['error'].get('code', 'unknown')}")
        if not isinstance(data, dict):
            raise UnknownResult("Meta response must be an object")
        return data

    @staticmethod
    def _id(data: dict, key: str = "id") -> str:
        if not data.get(key):
            raise UnknownResult(f"Meta response missing {key}")
        return str(data[key])

    def _photo(self, delivery: Delivery, page: str, asset: Asset) -> str:
        data = self._call("POST", f"{page}/photos", data={"url": remote_url(asset), "published": "false"})
        photo_id = self._id(data)
        uploads = delivery.external_ids.get("photo_uploads", []) + [photo_id]
        self.save(delivery, ids={"network": "facebook", "page_id": page, "photo_uploads": uploads})
        return photo_id

    def _upload_video(self, delivery: Delivery, page: str, asset: Asset, edge: str, caption: str) -> list[Part]:
        start = self._call("POST", f"{page}/{edge}", data={"upload_phase": "start"})
        video_id = self._id(start, "video_id")
        upload_url = start.get("upload_url")
        sessions = delivery.external_ids.get("video_sessions", []) + [video_id]
        self.save(delivery, ids={"network": "facebook", "page_id": page, "video_sessions": sessions})
        # Never send a token to an arbitrary URL returned by a compromised endpoint.
        parsed = httpx.URL(upload_url or "")
        if parsed.scheme != "https" or parsed.host != "rupload.facebook.com" or parsed.username or parsed.password:
            raise PublishRejected("unexpected Meta upload host")
        headers = {"Authorization": f"OAuth {self.token}"}
        if asset.source.startswith(("http://", "https://")):
            uploaded = self.request("POST", upload_url, headers={**headers, "file_url": remote_url(asset)})
        else:
            path = Path(asset.source)
            with path.open("rb") as file:
                uploaded = self.request("POST", upload_url, headers={**headers, "offset": "0",
                                        "file_size": str(path.stat().st_size),
                                        "Content-Type": "application/octet-stream"}, content=file)
        if not isinstance(uploaded, dict) or uploaded.get("success") is not True:
            raise PublishRejected("Meta video upload rejected")
        finish = {"upload_phase": "finish", "video_id": video_id}
        if edge == "video_reels":
            finish.update(video_state="PUBLISHED", description=caption)
        finished = self._call("POST", f"{page}/{edge}", data=finish)
        if finished.get("success") is not True:
            raise PublishRejected("Meta video finish rejected")
        objects = delivery.external_ids.get("videos", []) + [video_id]
        parts = [self.part(delivery, "video", video_id)]
        ids = {"videos": objects}
        if finished.get("post_id") is not None:
            post_id = str(finished["post_id"])
            parts.append(self.part(delivery, "story" if edge == "video_stories" else "post", post_id))
            ids["video_post_ids"] = {**delivery.external_ids.get("video_post_ids", {}), video_id: post_id}
        self.save(delivery, ids=ids, parts=parts)
        return parts

    def _facebook(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        page = channel.external_id
        parts = []
        if slot.kind == Kind.STORY:
            if not media:
                raise PublishRejected("Facebook stories require media")
            for asset in media:
                if asset.kind == "video":
                    parts.extend(self._upload_video(delivery, page, asset, "video_stories", ""))
                else:
                    photo_id = self._photo(delivery, page, asset)
                    response = self._call("POST", f"{page}/photo_stories", data={"photo_id": photo_id})
                    post_id = self._id(response, "post_id")
                    part = self.part(delivery, "story", post_id)
                    self.save(delivery, parts=[part], ids={"story_ids": delivery.external_ids.get("story_ids", []) + [post_id]})
                    parts.append(part)
            return Result(state=State.ACCEPTED if delivery.external_ids.get("videos") else State.PUBLISHED,
                          external_ids=delivery.external_ids, parts=parts)
        if slot.kind == Kind.REEL:
            if len(media) != 1 or media[0].kind != "video":
                raise PublishRejected("Facebook reel requires exactly one video")
            parts = self._upload_video(delivery, page, media[0], "video_reels", slot.caption)
            return Result(state=State.ACCEPTED, external_ids=delivery.external_ids,
                          parts=parts)
        if any(a.kind == "video" for a in media):
            if len(media) != 1:
                raise PublishRejected("Facebook feed cannot mix photos and videos")
            data = self._call("POST", f"{page}/videos", data={"file_url": remote_url(media[0]), "description": slot.caption})
            video_id = self._id(data)
            part = self.part(delivery, "video", video_id)
            return self.save(delivery, state=State.ACCEPTED, ids={"network": "facebook", "page_id": page, "videos": [video_id]}, parts=[part])
        payload = {"message": slot.caption}
        if media:
            payload["attached_media"] = json.dumps([{"media_fbid": self._photo(delivery, page, a)} for a in media])
        response = self._call("POST", f"{page}/feed", data=payload)
        post_id = self._id(response)
        return self.save(delivery, state=State.PUBLISHED, ids={"network": "facebook", "page_id": page, "post_id": post_id},
                         parts=[self.part(delivery, "post", post_id)])

    def _wait_container(self, container_id: str) -> None:
        for attempt in range(self.poll_attempts):
            data = self._call("GET", container_id, params={"fields": "status_code,status"})
            state = data.get("status_code")
            if state == "FINISHED":
                return
            if state in ("ERROR", "EXPIRED"):
                raise PublishRejected(f"Instagram container {state}")
            if state != "IN_PROGRESS":
                raise UnknownResult(f"unexpected Instagram container status {state!r}")
            if attempt + 1 < self.poll_attempts:
                time.sleep(self.poll_interval)
        raise UnknownResult("Instagram container polling exhausted; verify before any new publication")

    def _container(self, delivery: Delivery, ig_id: str, payload: dict) -> str:
        response = self._call("POST", f"{ig_id}/media", data=payload)
        container_id = self._id(response)
        self.save(delivery, ids={"network": "instagram", "ig_id": ig_id, "containers": delivery.external_ids.get("containers", []) + [container_id]})
        self._wait_container(container_id)
        return container_id

    def _instagram(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        if not 1 <= len(media) <= 10:
            raise PublishRejected("Instagram requires 1-10 media items")
        if slot.kind in (Kind.STORY, Kind.REEL) and len(media) != 1:
            raise PublishRejected("Instagram reel/story requires one media item per slot")
        if slot.kind == Kind.REEL and media[0].kind != "video":
            raise PublishRejected("Instagram reel requires a video")
        ig_id = channel.external_id
        children = []
        for asset in media:
            payload = {"video_url" if asset.kind == "video" else "image_url": remote_url(asset)}
            if len(media) > 1:
                payload["is_carousel_item"] = "true"
                if asset.kind == "video":
                    payload["media_type"] = "VIDEO"
            else:
                payload["caption"] = slot.caption
                if slot.kind == Kind.STORY:
                    payload["media_type"] = "STORIES"
                elif asset.kind == "video":
                    payload["media_type"] = "REELS"
            children.append(self._container(delivery, ig_id, payload))
        if len(children) > 1:
            container_id = self._container(delivery, ig_id, {"media_type": "CAROUSEL",
                                            "children": ",".join(children), "caption": slot.caption})
        else:
            container_id = children[0]
        self.save(delivery, ids={"container_id": container_id})
        response = self._call("POST", f"{ig_id}/media_publish", data={"creation_id": container_id})
        media_id = self._id(response)
        return self.save(delivery, state=State.PUBLISHED, ids={"media_id": media_id},
                         parts=[self.part(delivery, "media", media_id)])

    def publish(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        validate_context(delivery, slot, channel, media)
        if channel.type == "fb_page":
            return self._facebook(delivery, slot, channel, media)
        if channel.type == "ig":
            return self._instagram(delivery, slot, channel, media)
        raise PublishRejected("Meta publisher supports only fb_page and ig")

    def reconcile(self, delivery: Delivery) -> Result:
        ids = delivery.external_ids
        if ids.get("network") == "instagram":
            if ids.get("media_id"):
                data = self._call("GET", ids["media_id"], params={"fields": "id"})
                media_id = self._id(data)
                return Result(state=State.PUBLISHED, parts=[self.part(delivery, "media", media_id)])
            if ids.get("container_id"):
                data = self._call("GET", ids["container_id"], params={"fields": "status_code,status"})
                if data.get("status_code") in ("ERROR", "EXPIRED"):
                    return Result(state=State.FAILED, error="Instagram container failed/expired")
            return Result(state=State.UNKNOWN, error="Instagram media ID unknown; inspect account manually")
        if ids.get("videos"):
            published = []
            for video_id in ids["videos"]:
                data = self._call("GET", video_id, params={"fields": "status"})
                status = data.get("status", {})
                if status.get("video_status") == "error":
                    return Result(state=State.FAILED, error="Meta video processing failed")
                done = (status.get("publishing_phase", {}).get("status") == "complete"
                        or status.get("video_status") == "published")
                if not done:
                    return Result(state=State.ACCEPTED if delivery.state == State.ACCEPTED else State.UNKNOWN)
                published.append(self.part(delivery, "video", video_id))
            # If a response was lost in a multi-story sequence, known videos do not prove the entire slot completed.
            if delivery.state == State.UNKNOWN:
                return Result(state=State.UNKNOWN, parts=published, error="partial sequence requires manual verification")
            return Result(state=State.PUBLISHED, parts=published)
        if ids.get("post_id"):
            data = self._call("GET", ids["post_id"], params={"fields": "id"})
            return Result(state=State.PUBLISHED, parts=[self.part(delivery, "post", self._id(data))])
        return Result(state=State.UNKNOWN, error="Meta result cannot be inferred safely; inspect account manually")

    def delete(self, part: Part) -> None:
        response = self._call("DELETE", part.external_id)
        if response.get("success") is not True:
            raise PublishRejected("Meta delete not confirmed")
