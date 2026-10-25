import json
from types import SimpleNamespace

import httpx
import pytest

from content_factory.models import State
from content_factory.publishers.base import PolicyBlocked, PublishRejected, UnknownResult
from content_factory.publishers.telegram import TelegramPublisher

BASE = "https://api.telegram.org/bottest-token"


def setup(slot, tenant, *media):
    slot.media_ids = [a.id for a in media]
    return tenant.channels[0]


def test_send_message_and_delete(respx_mock, client, delivery, slot, tenant):
    route = respx_mock.post(BASE + "/sendMessage").respond(200, json={"ok": True, "result": {"message_id": 11}})
    adapter = TelegramPublisher(client, "test-token", "-100")
    result = adapter.publish(delivery, slot, setup(slot, tenant), [])
    assert result.state == State.PUBLISHED
    assert result.parts[0].external_id == "11"
    assert json.loads(route.calls[0].request.content) == {"chat_id": "-100", "text": "Hello"}
    deleted = respx_mock.post(BASE + "/deleteMessage").respond(200, json={"ok": True, "result": True})
    adapter.delete(result.parts[0])
    assert json.loads(deleted.calls[0].request.content)["message_id"] == "11"


def test_mixed_album_records_every_id(respx_mock, client, delivery, slot, tenant, photo, video):
    route = respx_mock.post(BASE + "/sendMediaGroup").respond(200, json={"ok": True, "result": [{"message_id": 21}, {"message_id": 22}]})
    checkpoints = []
    adapter = TelegramPublisher(client, "test-token", "-100", checkpoint=checkpoints.append)
    result = adapter.publish(delivery, slot, setup(slot, tenant, photo, video), [photo, video])
    payload = json.loads(route.calls[0].request.content)
    assert [m["type"] for m in payload["media"]] == ["photo", "video"]
    assert payload["media"][0]["caption"] == "Hello"
    assert payload["media"][1]["width"] == 1080
    assert result.external_ids["message_ids"] == ["21", "22"]
    assert [p.external_id for p in checkpoints[0].parts] == ["21", "22"]


def test_long_caption_precedes_album(respx_mock, client, delivery, slot, tenant, photo):
    slot.caption = "x" * 1025
    second = photo.model_copy(update={"id": "second"})
    text = respx_mock.post(BASE + "/sendMessage").respond(200, json={"ok": True, "result": {"message_id": 1}})
    album = respx_mock.post(BASE + "/sendMediaGroup").respond(200, json={"ok": True, "result": [{"message_id": 2}, {"message_id": 3}]})
    result = TelegramPublisher(client, "test-token", "chat").publish(delivery, slot, setup(slot, tenant, photo, second), [photo, second])
    assert text.called and album.called
    assert [call.request.url.path.split("/")[-1] for call in respx_mock.calls] == ["sendMessage", "sendMediaGroup"]
    assert all("caption" not in m for m in json.loads(album.calls[0].request.content)["media"])
    assert len(result.parts) == 3


def test_caption_1024_stays_in_media(respx_mock, client, delivery, slot, tenant, photo):
    slot.caption = "x" * 1024
    route = respx_mock.post(BASE + "/sendPhoto").respond(200, json={"ok": True, "result": {"message_id": 1}})
    TelegramPublisher(client, "test-token", "chat").publish(delivery, slot, setup(slot, tenant, photo), [photo])
    assert len(json.loads(route.calls[0].request.content)["caption"]) == 1024


def test_video_local_ffprobe_multipart(respx_mock, client, delivery, slot, tenant, tmp_path, video, monkeypatch):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fake-mp4")
    video.source = str(path)
    video.width = video.height = video.duration = None
    def probe(args, **kwargs):
        assert args[0] == "ffprobe"
        return SimpleNamespace(stdout=json.dumps({"streams": [{"width": 640, "height": 480}], "format": {"duration": "3.2"}}))
    monkeypatch.setattr("content_factory.publishers.base.subprocess.run", probe)
    route = respx_mock.post(BASE + "/sendVideo").respond(200, json={"ok": True, "result": {"message_id": 7}})
    result = TelegramPublisher(client, "test-token", "chat").publish(delivery, slot, setup(slot, tenant, video), [video])
    body = route.calls[0].request.content
    assert b'name="width"\r\n\r\n640' in body
    assert b'name="height"\r\n\r\n480' in body
    assert b'name="duration"\r\n\r\n4' in body
    assert b"fake-mp4" in body and result.parts[0].external_id == "7"


def test_video_without_ffprobe(respx_mock, client, delivery, slot, tenant, tmp_path, video, monkeypatch):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"fake")
    video.source = str(path)
    video.width = video.height = video.duration = None
    def missing(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr("content_factory.publishers.base.subprocess.run", missing)
    respx_mock.post(BASE + "/sendVideo").respond(200, json={"ok": True, "result": {"message_id": 7}})
    assert TelegramPublisher(client, "test-token", "chat").publish(
        delivery, slot, setup(slot, tenant, video), [video]).state == State.PUBLISHED


@pytest.mark.parametrize("status,body,error", [
    (400, {"ok": False}, PublishRejected),
    (200, {"ok": False, "error_code": 403}, PublishRejected),
    (500, {}, UnknownResult),
    (200, {"ok": True, "result": {}}, UnknownResult),
])
def test_failures(respx_mock, client, delivery, slot, tenant, status, body, error):
    respx_mock.post(BASE + "/sendMessage").respond(status, json=body)
    with pytest.raises(error):
        TelegramPublisher(client, "test-token", "chat").publish(delivery, slot, setup(slot, tenant), [])


def test_timeout_and_reconcile(respx_mock, client, delivery, slot, tenant):
    respx_mock.post(BASE + "/sendMessage").mock(side_effect=httpx.ReadTimeout("secret response lost"))
    adapter = TelegramPublisher(client, "test-token", "chat")
    with pytest.raises(UnknownResult, match="ReadTimeout") as error:
        adapter.publish(delivery, slot, setup(slot, tenant), [])
    assert "test-token" not in str(error.value)
    assert adapter.reconcile(delivery).state == State.UNKNOWN


def test_gate_before_every_call(respx_mock, client, delivery, slot, tenant, photo):
    slot.caption = "x" * 1025
    checkpoints = []
    calls = 0
    def gate():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PolicyBlocked("blackout")
    respx_mock.post(BASE + "/sendMessage").respond(200, json={"ok": True, "result": {"message_id": 1}})
    adapter = TelegramPublisher(client, "test-token", "chat", gate=gate, checkpoint=checkpoints.append)
    with pytest.raises(PolicyBlocked):
        adapter.publish(delivery, slot, setup(slot, tenant, photo), [photo])
    assert checkpoints[0].parts[0].external_id == "1"
    assert len(respx_mock.calls) == 1


def test_album_too_large_and_published_never_sent(client, delivery, slot, tenant, photo):
    media = [photo.model_copy(update={"id": str(i)}) for i in range(11)]
    adapter = TelegramPublisher(client, "test-token", "chat")
    with pytest.raises(PublishRejected, match="2-10"):
        adapter.publish(delivery, slot, setup(slot, tenant, *media), media)
    delivery.state = State.PUBLISHED
    with pytest.raises(PublishRejected, match="never resend"):
        adapter.publish(delivery, slot, setup(slot, tenant), [])


def test_partial_album_response_not_hidden_by_long_caption(respx_mock, client, delivery, slot, tenant, photo):
    slot.caption = "x" * 1025
    second = photo.model_copy(update={"id": "second"})
    respx_mock.post(BASE + "/sendMessage").respond(200, json={"ok": True, "result": {"message_id": 1}})
    respx_mock.post(BASE + "/sendMediaGroup").respond(200, json={"ok": True, "result": [{"message_id": 2}]})
    checkpoints = []
    with pytest.raises(UnknownResult, match="different number"):
        TelegramPublisher(client, "test-token", "chat", checkpoint=checkpoints.append).publish(
            delivery, slot, setup(slot, tenant, photo, second), [photo, second])
    assert [p.external_id for c in checkpoints for p in c.parts] == ["1", "2"]


def test_malformed_album_still_records_known_message_ids(respx_mock, client, delivery, slot, tenant, photo):
    second = photo.model_copy(update={"id": "second"})
    respx_mock.post(BASE + "/sendMediaGroup").respond(200, json={"ok": True, "result": [{"message_id": 9}, {}]})
    checkpoints = []
    with pytest.raises(UnknownResult, match="missing message_id"):
        TelegramPublisher(client, "test-token", "chat", checkpoint=checkpoints.append).publish(
            delivery, slot, setup(slot, tenant, photo, second), [photo, second])
    assert checkpoints[0].parts[0].external_id == "9"
