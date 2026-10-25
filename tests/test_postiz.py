import json

import httpx
import pytest

from content_factory.models import State
from content_factory.publishers.base import PublishRejected, UnknownResult, UnsupportedOperation
from content_factory.publishers.postiz import PostizPublisher

BASE = "https://postiz.test/api/public/v1"


def setup(slot, tenant, *assets, channel_type="tg_channel"):
    channel = tenant.channels[0]
    channel.publisher = "postiz"
    channel.type = channel_type
    slot.media_ids = [a.id for a in assets]
    return channel


def test_upload_create_now_and_reconcile(respx_mock, client, delivery, slot, tenant, photo, now):
    channel = setup(slot, tenant, photo, channel_type="ig")
    upload = respx_mock.post(BASE + "/upload-from-url").respond(200, json={"id": "u1", "path": "https://postiz.test/u.jpg"})
    create = respx_mock.post(BASE + "/posts").respond(200, json=[{"postId": "p1", "integration": channel.external_id}])
    adapter = PostizPublisher(client, "fake-key", "https://postiz.test")
    result = adapter.publish(delivery, slot, channel, [photo])
    assert result.state == State.ACCEPTED
    payload = json.loads(create.calls[0].request.content)
    assert payload["type"] == "now"
    assert payload["posts"][0]["settings"] == {"__type": "instagram", "post_type": "post"}
    assert payload["posts"][0]["value"][0]["image"][0]["id"] == "u1"
    assert create.calls[0].request.headers["Authorization"] == "fake-key"
    assert json.loads(upload.calls[0].request.content)["adjust"] is False
    delivery.created_at = now
    listing = respx_mock.get(BASE + "/posts").respond(200, json={"posts": [
        {"id": "p1", "state": "PUBLISHED", "releaseId": "social1", "releaseURL": "https://social.test/1"}]})
    reconciled = adapter.reconcile(delivery)
    assert reconciled.state == State.PUBLISHED
    assert reconciled.parts[0].external_id == "social1"
    assert listing.calls[0].request.url.params["startDate"].startswith("2026-10-24")


def test_upload_local_mime(respx_mock, client, delivery, slot, tenant, video, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake-video")
    video.source = str(path)
    channel = setup(slot, tenant, video)
    upload = respx_mock.post(BASE + "/upload").respond(200, json={"id": "u1", "path": "https://postiz.test/u.mp4"})
    respx_mock.post(BASE + "/posts").respond(200, json=[{"postId": "p1", "integration": channel.external_id}])
    PostizPublisher(client, "key", "https://postiz.test/").publish(delivery, slot, channel, [video])
    assert b"Content-Type: video/mp4" in upload.calls[0].request.content
    assert b"fake-video" in upload.calls[0].request.content


@pytest.mark.parametrize("remote,state", [("QUEUE", State.ACCEPTED), ("PENDING", State.ACCEPTED),
                                         ("ERROR", State.FAILED), ("DRAFT", State.UNKNOWN), ("future-state", State.UNKNOWN)])
def test_state_mapping(respx_mock, client, delivery, remote, state):
    delivery.external_ids = {"post_id": "p1"}
    respx_mock.get(BASE + "/posts").respond(200, json={"posts": [{"id": "p1", "state": remote}]})
    assert PostizPublisher(client, "key", "https://postiz.test").reconcile(delivery).state == state


@pytest.mark.parametrize("posts", [[], [{"id": "p1", "state": "PUBLISHED"}]])
def test_missing_release_is_unknown(respx_mock, client, delivery, posts):
    delivery.external_ids = {"post_id": "p1"}
    respx_mock.get(BASE + "/posts").respond(200, json={"posts": posts})
    assert PostizPublisher(client, "key", "https://postiz.test").reconcile(delivery).state == State.UNKNOWN


def test_lost_post_id_does_not_query_or_resend(client, delivery):
    assert PostizPublisher(client, "key", "https://postiz.test").reconcile(delivery).state == State.UNKNOWN


@pytest.mark.parametrize("failure", ["timeout", "error", "malformed"])
def test_create_failures(respx_mock, client, delivery, slot, tenant, failure):
    channel = setup(slot, tenant)
    route = respx_mock.post(BASE + "/posts")
    expected = UnknownResult
    if failure == "timeout":
        route.mock(side_effect=httpx.ReadTimeout("lost"))
    elif failure == "error":
        route.respond(422, json={"error": "invalid"})
        expected = PublishRejected
    else:
        route.respond(200, json={"id": "wrong-shape"})
    with pytest.raises(expected):
        PostizPublisher(client, "key", "https://postiz.test").publish(delivery, slot, channel, [])


def test_delete_is_explicitly_unsupported(client, delivery):
    adapter = PostizPublisher(client, "key", "https://postiz.test")
    with pytest.raises(UnsupportedOperation, match="cannot delete"):
        adapter.delete(adapter.part(delivery, "post", "social1"))


@pytest.mark.parametrize("channel_type,kind,settings", [
    ("fb_page", "reel", {}), ("yt", "post", {}), ("tiktok", "post", {"content_posting_method": "UPLOAD"}),
])
def test_provider_settings_fail_fast(client, delivery, slot, tenant, channel_type, kind, settings):
    channel = setup(slot, tenant, channel_type=channel_type)
    channel.settings = settings
    slot.kind = kind
    with pytest.raises(PublishRejected):
        PostizPublisher(client, "key", "https://postiz.test").publish(delivery, slot, channel, [])
