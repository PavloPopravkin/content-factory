import json
from urllib.parse import parse_qs

import httpx
import pytest

from content_factory.models import Kind, State
from content_factory.publishers.base import PolicyBlocked, PublishRejected, UnknownResult
from content_factory.publishers.meta import MetaPublisher

BASE = "https://graph.facebook.com/v25.0"
UPLOAD = "https://rupload.facebook.com/video-upload/v25.0/v1"


def setup(slot, tenant, *assets, network="fb_page", kind=Kind.POST):
    channel = tenant.channels[0]
    channel.type = network
    channel.publisher = "meta"
    channel.external_id = "account"
    slot.kind = kind
    slot.media_ids = [a.id for a in assets]
    return channel


def body(route, index=0):
    return {k: v[0] for k, v in parse_qs(route.calls[index].request.content.decode()).items()}


def adapter(client, **kwargs):
    return MetaPublisher(client, "fake-token", poll_attempts=2, poll_interval=0, **kwargs)


def test_fb_carousel_unpublished_then_feed(respx_mock, client, delivery, slot, tenant, photo):
    other = photo.model_copy(update={"id": "photo2"})
    channel = setup(slot, tenant, photo, other)
    photos = respx_mock.post(BASE + "/account/photos").mock(side_effect=[httpx.Response(200, json={"id": "ph1"}), httpx.Response(200, json={"id": "ph2"})])
    feed = respx_mock.post(BASE + "/account/feed").respond(200, json={"id": "post1"})
    checkpoints = []
    result = adapter(client, checkpoint=checkpoints.append).publish(delivery, slot, channel, [photo, other])
    assert result.state == State.PUBLISHED
    assert photos.call_count == 2
    assert body(photos)["published"] == "false"
    assert json.loads(body(feed)["attached_media"]) == [{"media_fbid": "ph1"}, {"media_fbid": "ph2"}]
    assert checkpoints[0].external_ids["photo_uploads"] == ["ph1"]
    assert result.parts[0].external_id == "post1"
    assert feed.calls[0].request.headers["Authorization"] == "Bearer fake-token"


@pytest.mark.parametrize("kind,edge", [(Kind.REEL, "video_reels"), (Kind.STORY, "video_stories")])
def test_fb_three_phase_video(respx_mock, client, delivery, slot, tenant, video, kind, edge):
    channel = setup(slot, tenant, video, kind=kind)
    phases = respx_mock.post(BASE + f"/account/{edge}").mock(side_effect=[
        httpx.Response(200, json={"video_id": "v1", "upload_url": UPLOAD}),
        httpx.Response(200, json={"success": True}),
    ])
    upload = respx_mock.post(UPLOAD).respond(200, json={"success": True})
    result = adapter(client).publish(delivery, slot, channel, [video])
    assert body(phases)["upload_phase"] == "start"
    assert body(phases, 1)["upload_phase"] == "finish"
    if kind == Kind.REEL:
        assert body(phases, 1)["video_state"] == "PUBLISHED"
    assert upload.calls[0].request.headers["file_url"] == video.source
    assert upload.calls[0].request.headers["Authorization"] == "OAuth fake-token"
    assert result.state == State.ACCEPTED
    delivery.state = State.ACCEPTED
    respx_mock.get(BASE + "/v1").respond(200, json={"status": {"video_status": "ready", "publishing_phase": {"status": "complete"}}})
    assert adapter(client).reconcile(delivery).state == State.PUBLISHED


def test_fb_video_binary_upload(respx_mock, client, delivery, slot, tenant, video, tmp_path):
    path = tmp_path / "video.mp4"
    path.write_bytes(b"test-data")
    video.source = str(path)
    channel = setup(slot, tenant, video, kind=Kind.REEL)
    respx_mock.post(BASE + "/account/video_reels").mock(side_effect=[
        httpx.Response(200, json={"video_id": "v1", "upload_url": UPLOAD}), httpx.Response(200, json={"success": True})])
    upload = respx_mock.post(UPLOAD).respond(200, json={"success": True})
    adapter(client).publish(delivery, slot, channel, [video])
    assert upload.calls[0].request.content == b"test-data"
    assert upload.calls[0].request.headers["file_size"] == "9"


def test_fb_photo_stories_record_each_part(respx_mock, client, delivery, slot, tenant, photo):
    second = photo.model_copy(update={"id": "second"})
    channel = setup(slot, tenant, photo, second, kind=Kind.STORY)
    respx_mock.post(BASE + "/account/photos").mock(side_effect=[httpx.Response(200, json={"id": "p1"}), httpx.Response(200, json={"id": "p2"})])
    stories = respx_mock.post(BASE + "/account/photo_stories").mock(side_effect=[httpx.Response(200, json={"post_id": "s1", "success": True}), httpx.Response(200, json={"post_id": "s2", "success": True})])
    result = adapter(client).publish(delivery, slot, channel, [photo, second])
    assert [p.external_id for p in result.parts] == ["s1", "s2"]
    assert result.state == State.PUBLISHED
    assert body(stories, 1)["photo_id"] == "p2"


def test_fb_regular_video(respx_mock, client, delivery, slot, tenant, video):
    channel = setup(slot, tenant, video)
    route = respx_mock.post(BASE + "/account/videos").respond(200, json={"id": "v1"})
    result = adapter(client).publish(delivery, slot, channel, [video])
    assert result.state == State.ACCEPTED
    assert body(route)["file_url"] == video.source


@pytest.mark.parametrize("kind,media_kind,expected_type", [
    (Kind.POST, "photo", None), (Kind.REEL, "video", "REELS"),
    (Kind.STORY, "photo", "STORIES"), (Kind.STORY, "video", "STORIES"),
])
def test_ig_single_media(respx_mock, client, delivery, slot, tenant, photo, video, kind, media_kind, expected_type):
    asset = video if media_kind == "video" else photo
    channel = setup(slot, tenant, asset, network="ig", kind=kind)
    create = respx_mock.post(BASE + "/account/media").respond(200, json={"id": "c1"})
    respx_mock.get(BASE + "/c1").mock(side_effect=[httpx.Response(200, json={"status_code": "IN_PROGRESS"}), httpx.Response(200, json={"status_code": "FINISHED"})])
    publish = respx_mock.post(BASE + "/account/media_publish").respond(200, json={"id": "m1"})
    result = adapter(client).publish(delivery, slot, channel, [asset])
    assert body(create).get("media_type") == expected_type
    assert body(publish)["creation_id"] == "c1"
    assert result.parts[0].external_id == "m1" and result.state == State.PUBLISHED


def test_ig_carousel(respx_mock, client, delivery, slot, tenant, photo, video):
    channel = setup(slot, tenant, photo, video, network="ig")
    create = respx_mock.post(BASE + "/account/media").mock(side_effect=[httpx.Response(200, json={"id": x}) for x in ("child1", "child2", "parent")])
    for id_ in ("child1", "child2", "parent"):
        respx_mock.get(BASE + "/" + id_).respond(200, json={"status_code": "FINISHED"})
    respx_mock.post(BASE + "/account/media_publish").respond(200, json={"id": "m1"})
    adapter(client).publish(delivery, slot, channel, [photo, video])
    assert body(create)["is_carousel_item"] == "true"
    assert body(create, 1)["media_type"] == "VIDEO"
    assert body(create, 2)["children"] == "child1,child2"
    assert body(create, 2)["media_type"] == "CAROUSEL"


@pytest.mark.parametrize("status,error", [("ERROR", PublishRejected), ("EXPIRED", PublishRejected),
                                         ("IN_PROGRESS", UnknownResult), ("surprise", UnknownResult)])
def test_ig_polling_failure(respx_mock, client, delivery, slot, tenant, photo, status, error):
    channel = setup(slot, tenant, photo, network="ig")
    respx_mock.post(BASE + "/account/media").respond(200, json={"id": "c1"})
    respx_mock.get(BASE + "/c1").respond(200, json={"status_code": status})
    with pytest.raises(error):
        adapter(client).publish(delivery, slot, channel, [photo])
    assert not any(call.request.url.path.endswith("media_publish") for call in respx_mock.calls)


@pytest.mark.parametrize("network", ["fb_page", "ig"])
def test_timeout_is_unknown(respx_mock, client, delivery, slot, tenant, photo, network):
    channel = setup(slot, tenant, photo, network=network)
    edge = "photos" if network == "fb_page" else "media"
    respx_mock.post(BASE + f"/account/{edge}").mock(side_effect=httpx.ReadTimeout("lost"))
    with pytest.raises(UnknownResult):
        adapter(client).publish(delivery, slot, channel, [photo])


def test_meta_4xx_typed_error(respx_mock, client, delivery, slot, tenant):
    channel = setup(slot, tenant)
    respx_mock.post(BASE + "/account/feed").respond(403, json={"error": {"code": 190}})
    with pytest.raises(PublishRejected, match="403"):
        adapter(client).publish(delivery, slot, channel, [])


def test_upload_host_not_trusted(respx_mock, client, delivery, slot, tenant, video):
    channel = setup(slot, tenant, video, kind=Kind.REEL)
    respx_mock.post(BASE + "/account/video_reels").respond(200, json={"video_id": "v1", "upload_url": "https://evil.test/upload"})
    with pytest.raises(PublishRejected, match="upload host"):
        adapter(client).publish(delivery, slot, channel, [video])
    assert len(respx_mock.calls) == 1


def test_configurable_graph_version(respx_mock, client, delivery, slot, tenant):
    channel = setup(slot, tenant)
    respx_mock.post("https://graph.facebook.com/v24.0/account/feed").respond(200, json={"id": "p1"})
    assert MetaPublisher(client, "token", graph_version="v24.0").publish(delivery, slot, channel, []).state == State.PUBLISHED
    with pytest.raises(ValueError, match="version"):
        MetaPublisher(client, "token", graph_version="../evil")


def test_meta_delete_and_reconcile(respx_mock, client, delivery):
    pub = adapter(client)
    delivery.external_ids = {"network": "instagram", "media_id": "m1"}
    respx_mock.get(BASE + "/m1").respond(200, json={"id": "m1"})
    result = pub.reconcile(delivery)
    assert result.state == State.PUBLISHED
    delete = respx_mock.delete(BASE + "/m1").respond(200, json={"success": True})
    pub.delete(result.parts[0])
    assert delete.called


def test_ig_lost_response_cannot_invent_media_id(respx_mock, client, delivery):
    delivery.external_ids = {"network": "instagram", "container_id": "c1"}
    respx_mock.get(BASE + "/c1").respond(200, json={"status_code": "PUBLISHED"})
    assert adapter(client).reconcile(delivery).state == State.UNKNOWN


def test_ready_video_is_not_published(respx_mock, client, delivery):
    delivery.state = State.ACCEPTED
    delivery.external_ids = {"videos": ["v1"]}
    respx_mock.get(BASE + "/v1").respond(200, json={"status": {"video_status": "ready"}})
    assert adapter(client).reconcile(delivery).state == State.ACCEPTED


def test_gate_blocks_between_upload_and_publish(respx_mock, client, delivery, slot, tenant, photo):
    channel = setup(slot, tenant, photo)
    def gate():
        if delivery.external_ids.get("photo_uploads"):
            raise PolicyBlocked("blackout")
    respx_mock.post(BASE + "/account/photos").respond(200, json={"id": "p1"})
    with pytest.raises(PolicyBlocked):
        adapter(client, gate=gate).publish(delivery, slot, channel, [photo])
    assert len(respx_mock.calls) == 1


def test_video_story_retains_returned_post_id(respx_mock, client, delivery, slot, tenant, video):
    channel = setup(slot, tenant, video, kind=Kind.STORY)
    respx_mock.post(BASE + "/account/video_stories").mock(side_effect=[
        httpx.Response(200, json={"video_id": "v1", "upload_url": UPLOAD}),
        httpx.Response(200, json={"success": True, "post_id": "story1"}),
    ])
    respx_mock.post(UPLOAD).respond(200, json={"success": True})
    checkpoints = []
    result = adapter(client, checkpoint=checkpoints.append).publish(delivery, slot, channel, [video])
    assert [(p.kind, p.external_id) for p in result.parts] == [("video", "v1"), ("story", "story1")]
    assert checkpoints[-1].external_ids["video_post_ids"] == {"v1": "story1"}
