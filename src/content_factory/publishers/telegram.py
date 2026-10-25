from contextlib import ExitStack
import json
from pathlib import Path
from typing import Any

import httpx

from ..config import Channel
from ..models import Asset, Delivery, Part, Result, Slot, State
from .base import HttpPublisher, PublishRejected, UnknownResult, media_file, validate_context, video_metadata


class TelegramPublisher(HttpPublisher):
    def __init__(self, client: httpx.Client, token: str, chat_id: str, *, base_url: str = "https://api.telegram.org", **kwargs: Any) -> None:
        super().__init__(client, **kwargs)
        self.base = f"{base_url.rstrip('/')}/bot{token}"
        self.chat_id = chat_id

    def _call(self, method: str, **kwargs: Any) -> Any:
        data = self.request("POST", f"{self.base}/{method}", **kwargs)
        if not isinstance(data, dict) or "ok" not in data:
            raise UnknownResult("Telegram response missing ok")
        if not data["ok"]:
            raise PublishRejected(f"Telegram error {data.get('error_code', 'unknown')}")
        if "result" not in data:
            raise UnknownResult("Telegram response missing result")
        return data["result"]

    def _messages(self, delivery: Delivery, result: Any, kind: str) -> list[Part]:
        messages = result if isinstance(result, list) else [result]
        valid = [m for m in messages if isinstance(m, dict) and m.get("message_id") is not None]
        parts = [self.part(delivery, kind, m["message_id"]) for m in valid]
        if parts:
            ids = delivery.external_ids.get("message_ids", []) + [p.external_id for p in parts]
            self.save(delivery, ids={"chat_id": self.chat_id, "message_ids": ids}, parts=parts)
        if not messages or len(valid) != len(messages):
            raise UnknownResult("Telegram response missing message_id")
        return parts

    def publish(self, delivery: Delivery, slot: Slot, channel: Channel, media: list[Asset]) -> Result:
        validate_context(delivery, slot, channel, media)
        if len(media) > 10:
            raise PublishRejected("Telegram album requires 2-10 items")
        # Validate files before sending a separate long caption.
        for asset in media:
            if not asset.source.startswith(("http://", "https://")):
                if not Path(asset.source).is_file():
                    raise PublishRejected("Telegram media file does not exist")
        parts = []
        caption = slot.caption
        if not media or len(caption) > 1024:
            # Plain text avoids entity parsing ambiguity; Telegram limits messages to 4096 characters.
            for start in range(0, len(caption), 4096):
                result = self._call("sendMessage", json={"chat_id": self.chat_id, "text": caption[start:start + 4096]})
                parts.extend(self._messages(delivery, result, "message"))
            if not media:
                if not caption:
                    raise PublishRejected("Telegram message is empty")
                return self.save(delivery, state=State.PUBLISHED, ids=delivery.external_ids, parts=parts)
            caption = ""
        with ExitStack() as stack:
            attachments = {}
            items = []
            for i, asset in enumerate(media):
                source = asset.source
                if not source.startswith(("http://", "https://")):
                    name = f"media{i}"
                    attachments[name] = media_file(stack, asset)
                    source = f"attach://{name}"
                item = {"type": "video" if asset.kind == "video" else "photo", "media": source}
                if asset.kind == "video":
                    item.update(video_metadata(asset))
                    item["supports_streaming"] = True
                if i == 0 and caption:
                    item["caption"] = caption
                items.append(item)
            if len(items) > 1:
                method = "sendMediaGroup"
                payload = {"chat_id": self.chat_id, "media": items}
            else:
                item = items[0].copy()
                kind = item.pop("type")
                source = item.pop("media")
                method = "sendVideo" if kind == "video" else "sendPhoto"
                payload = {"chat_id": self.chat_id, kind: source, **item}
            if attachments:
                data = {k: json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v) for k, v in payload.items()}
                result = self._call(method, data=data, files=attachments)
            else:
                result = self._call(method, json=payload)
            media_parts = self._messages(delivery, result, "media")
            parts.extend(media_parts)
            if len(media_parts) != len(media):
                raise UnknownResult("Telegram returned a different number of messages than requested")
        return self.save(delivery, state=State.PUBLISHED, ids=delivery.external_ids, parts=parts)

    def reconcile(self, delivery: Delivery) -> Result:
        # Bot API cannot read arbitrary channel history or look up a lost send response.
        return Result(state=State.UNKNOWN, external_ids=delivery.external_ids,
                      error="Telegram needs manual channel-history verification; never resend automatically")

    def delete(self, part: Part) -> None:
        self._call("deleteMessage", json={"chat_id": self.chat_id, "message_id": part.external_id})
