from datetime import datetime, timedelta

import httpx
import pytest

from content_factory.config import WeeklyBlackout
from content_factory.models import Kind, Result, State
from content_factory.publishers.dry import DryPublisher
from content_factory.scheduler import publisher_for, tick
from content_factory.storage import LockedError, Store

TG = "https://api.telegram.org/botfake-token"


def telegram(tenant, monkeypatch):
    tenant.channels[0].publisher = "telegram"
    monkeypatch.setenv(tenant.channels[0].secret_ref, "fake-token")


def test_dry_tick_idempotent(store, tenant, slot, now, client):
    store.add_slot(slot)
    first = tick(store, tenant, clock=lambda: now, client=client)
    assert first.published == 1
    assert store.deliveries(tenant.slug)[0].state == State.PUBLISHED
    assert len(store.parts(tenant.slug, store.deliveries(tenant.slug)[0].id)) == 1
    second = tick(store, tenant, clock=lambda: now, client=client)
    assert second.published == 0 and second.skipped == 1
    assert store.deliveries(tenant.slug)[0].attempts == 1


def test_unapproved_revision_then_approval(store, tenant, slot, now, client):
    tenant.approval.mode = "manual"
    store.add_slot(slot)
    assert tick(store, tenant, clock=lambda: now, client=client).blocked == 1
    assert store.deliveries(tenant.slug) == []
    store.approve(tenant.slug, slot.id)
    revised = store.revise(tenant.slug, slot.id, caption="changed", at=now)
    assert tick(store, tenant, clock=lambda: now, client=client).blocked == 1
    store.approve(tenant.slug, slot.id)
    assert tick(store, tenant, clock=lambda: now, client=client).published == 1
    assert store.get_slot(tenant.slug, slot.id).approved_version == revised.version


def test_cancelled_and_future_ignored(store, tenant, slot, now, client):
    slot.at = now + timedelta(minutes=1)
    store.add_slot(slot)
    assert tick(store, tenant, clock=lambda: now, client=client).published == 0
    store.cancel(tenant.slug, slot.id)
    assert tick(store, tenant, clock=lambda: now + timedelta(hours=1), client=client).published == 0
    assert not store.deliveries(tenant.slug)


def test_cap_does_not_block_same_slot_second_channel(store, tenant, slot, now, client):
    second = tenant.channels[0].model_copy(update={"id": "second"})
    tenant.channels.append(second)
    tenant.schedule.daily_caps[Kind.POST] = 1
    store.register(tenant)
    slot.channel_ids.append(second.id)
    store.add_slot(slot)
    report = tick(store, tenant, clock=lambda: now, client=client)
    assert report.published == 2 and report.blocked == 0
    extra = slot.model_copy(update={"id": "extra-slot", "channel_ids": [second.id]})
    store.add_slot(extra)
    assert tick(store, tenant, clock=lambda: now, client=client).blocked == 1


def test_backlog_respects_real_time_gap(store, tenant, slot, now, client):
    tenant.schedule.min_gap_minutes = 30
    slot.at = now - timedelta(days=1)
    later = slot.model_copy(update={"id": "later", "at": slot.at + timedelta(hours=1)})
    store.add_slot(slot)
    store.add_slot(later)
    first = tick(store, tenant, clock=lambda: now, client=client)
    assert first.published == 1 and first.blocked == 1
    assert tick(store, tenant, clock=lambda: now + timedelta(minutes=30), client=client).published == 1


def test_blackout_at_actual_time_not_old_schedule(store, tenant, slot, client):
    tenant.schedule.blackout = [WeeklyBlackout.model_validate({"type": "weekly", "from": "fri 15:00", "to": "sat 21:00"})]
    slot.at = datetime.fromisoformat("2026-10-22T10:00:00+03:00")
    store.add_slot(slot)
    now = datetime.fromisoformat("2026-10-23T16:00:00+03:00")
    assert tick(store, tenant, clock=lambda: now, client=client).blocked == 1
    assert not store.deliveries(tenant.slug)


def test_timeout_is_unknown_and_never_auto_retried(respx_mock, store, tenant, slot, now, client, monkeypatch):
    telegram(tenant, monkeypatch)
    store.add_slot(slot)
    send = respx_mock.post(TG + "/sendMessage").mock(side_effect=httpx.ReadTimeout("lost"))
    assert tick(store, tenant, clock=lambda: now, client=client).unknown == 1
    assert store.deliveries(tenant.slug)[0].state == State.UNKNOWN
    assert tick(store, tenant, clock=lambda: now, client=client).skipped == 1
    assert send.call_count == 1


def test_committed_before_external_call(respx_mock, store, tenant, slot, now, client, monkeypatch):
    telegram(tenant, monkeypatch)
    store.add_slot(slot)
    def response(request):
        with Store(store.path) as observer:
            deliveries = observer.deliveries(tenant.slug)
            assert len(deliveries) == 1 and deliveries[0].state == State.SUBMITTING
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    respx_mock.post(TG + "/sendMessage").mock(side_effect=response)
    assert tick(store, tenant, clock=lambda: now, client=client).published == 1


def test_partial_album_retains_caption_message(respx_mock, store, tenant, slot, photo, now, client, monkeypatch):
    telegram(tenant, monkeypatch)
    second = photo.model_copy(update={"id": "second"})
    for asset in (photo, second):
        store.add_asset(asset)
    slot.media_ids = [photo.id, second.id]
    slot.caption = "x" * 1025
    store.add_slot(slot)
    text = respx_mock.post(TG + "/sendMessage").respond(200, json={"ok": True, "result": {"message_id": 41}})
    album = respx_mock.post(TG + "/sendMediaGroup").mock(side_effect=httpx.ReadTimeout("lost"))
    assert tick(store, tenant, clock=lambda: now, client=client).unknown == 1
    delivery = store.deliveries(tenant.slug)[0]
    assert [p.external_id for p in store.parts(tenant.slug, delivery.id)] == ["41"]
    assert delivery.external_ids["message_ids"] == ["41"]
    tick(store, tenant, clock=lambda: now, client=client)
    assert text.call_count == album.call_count == 1


def test_recheck_blackout_between_meta_steps(respx_mock, store, tenant, slot, photo, client, monkeypatch):
    channel = tenant.channels[0]
    channel.publisher, channel.type, channel.external_id = "meta", "fb_page", "page"
    monkeypatch.setenv(channel.secret_ref, "fake-token")
    tenant.schedule.blackout = [WeeklyBlackout.model_validate({"type": "weekly", "from": "fri 15:00", "to": "sat 21:00"})]
    moment = [datetime.fromisoformat("2026-10-23T14:59:59+03:00")]
    slot.at = moment[0] - timedelta(minutes=1)
    slot.media_ids = [photo.id]
    store.add_asset(photo)
    store.add_slot(slot)
    def response(request):
        moment[0] += timedelta(seconds=2)
        return httpx.Response(200, json={"id": "uploaded-photo"})
    respx_mock.post("https://graph.facebook.com/v25.0/page/photos").mock(side_effect=response)
    report = tick(store, tenant, clock=lambda: moment[0], client=client)
    assert report.unknown == 1
    assert len(respx_mock.calls) == 1
    delivery = store.deliveries(tenant.slug)[0]
    assert delivery.external_ids["photo_uploads"] == ["uploaded-photo"]
    assert "blackout" in delivery.error


def test_recheck_cancellation_between_requests(respx_mock, store, tenant, slot, photo, now, client, monkeypatch):
    telegram(tenant, monkeypatch)
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    slot.caption = "x" * 1025
    store.add_slot(slot)
    def response(request):
        store.cancel(tenant.slug, slot.id)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    respx_mock.post(TG + "/sendMessage").mock(side_effect=response)
    assert tick(store, tenant, clock=lambda: now, client=client).unknown == 1
    assert len(respx_mock.calls) == 1


def test_crash_fence_recovered_unknown_without_publish(store, tenant, slot, now, client):
    store.add_slot(slot)
    store.begin_delivery(slot, slot.channel_ids[0], at=now)
    report = tick(store, tenant, clock=lambda: now, client=client)
    assert report.published == 0
    assert store.deliveries(tenant.slug)[0].state == State.UNKNOWN


def test_accepted_reconciles_without_post(respx_mock, store, tenant, slot, now, client, monkeypatch):
    channel = tenant.channels[0]
    channel.publisher = "postiz"
    monkeypatch.setenv(channel.secret_ref, "fake-key")
    monkeypatch.setenv("CF_POSTIZ_URL", "https://postiz.test")
    store.add_slot(slot)
    create = respx_mock.post("https://postiz.test/api/public/v1/posts").respond(200, json=[{"postId": "p1", "integration": channel.external_id}])
    assert tick(store, tenant, clock=lambda: now, client=client).accepted == 1
    respx_mock.get("https://postiz.test/api/public/v1/posts").respond(200, json={"posts": [{"id": "p1", "state": "PUBLISHED", "releaseId": "social1"}]})
    report = tick(store, tenant, clock=lambda: now, client=client)
    assert report.reconciled == 1 and create.call_count == 1
    assert store.deliveries(tenant.slug)[0].state == State.PUBLISHED


def test_reconcile_never_turns_read_error_into_failed(respx_mock, store, tenant, slot, now, client, monkeypatch):
    channel = tenant.channels[0]
    channel.publisher = "postiz"
    monkeypatch.setenv(channel.secret_ref, "fake-key")
    monkeypatch.setenv("CF_POSTIZ_URL", "https://postiz.test")
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0], at=now)
    store.checkpoint(delivery, Result(state=State.ACCEPTED, external_ids={"post_id": "p1"}))
    respx_mock.get("https://postiz.test/api/public/v1/posts").respond(401, json={})
    tick(store, tenant, clock=lambda: now, client=client)
    assert store.deliveries(tenant.slug)[0].state == State.UNKNOWN


def test_missing_secret_preflight_no_fence(store, tenant, slot, now, client, monkeypatch):
    tenant.channels[0].publisher = "telegram"
    monkeypatch.delenv(tenant.channels[0].secret_ref, raising=False)
    store.add_slot(slot)
    assert tick(store, tenant, clock=lambda: now, client=client).failed == 1
    assert store.deliveries(tenant.slug) == []


def test_other_tenant_history_not_counted(store, tenant, slot, now, client):
    other = tenant.model_copy(deep=True)
    other.slug = "other"
    store.register(other)
    other_slot = slot.model_copy(update={"id": "other-slot", "tenant_slug": other.slug})
    store.add_slot(other_slot)
    assert tick(store, other, clock=lambda: now, client=client).published == 1
    tenant.schedule.daily_caps[Kind.POST] = 1
    tenant.schedule.min_gap_minutes = 60
    store.add_slot(slot)
    assert tick(store, tenant, clock=lambda: now, client=client).published == 1


def test_tick_file_lock(store, tenant, slot, now, client):
    store.add_slot(slot)
    with store.lock():
        with pytest.raises(LockedError):
            tick(store, tenant, clock=lambda: now, client=client)


def test_unexpected_exception_leaves_durable_unknown(store, tenant, slot, now, client):
    class Broken(DryPublisher):
        def publish(self, *args):
            raise RuntimeError("unexpected")
    def factory(channel, session, gate, checkpoint):
        return Broken(session, gate=gate, checkpoint=checkpoint)
    store.add_slot(slot)
    with pytest.raises(RuntimeError, match="unexpected"):
        tick(store, tenant, clock=lambda: now, client=client, factory=factory)
    assert store.deliveries(tenant.slug)[0].state == State.UNKNOWN


def test_definitive_rejection_is_failed_and_not_retried(respx_mock, store, tenant, slot, now, client, monkeypatch):
    telegram(tenant, monkeypatch)
    store.add_slot(slot)
    rejected = respx_mock.post(TG + "/sendMessage").respond(403, json={"ok": False})
    assert tick(store, tenant, clock=lambda: now, client=client).failed == 1
    tick(store, tenant, clock=lambda: now, client=client)
    assert rejected.call_count == 1 and store.deliveries(tenant.slug)[0].state == State.FAILED


def test_reconciliation_obeys_blackout(respx_mock, store, tenant, slot, client, monkeypatch):
    channel = tenant.channels[0]
    channel.publisher = "postiz"
    monkeypatch.setenv(channel.secret_ref, "fake-key")
    monkeypatch.setenv("CF_POSTIZ_URL", "https://postiz.test")
    tenant.schedule.blackout = [WeeklyBlackout.model_validate({"type": "weekly", "from": "fri 15:00", "to": "sat 21:00"})]
    slot.at = datetime.fromisoformat("2026-10-22T10:00:00+03:00")
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0], at=slot.at)
    store.checkpoint(delivery, Result(state=State.ACCEPTED, external_ids={"post_id": "p1"}))
    report = tick(store, tenant, clock=lambda: datetime.fromisoformat("2026-10-23T16:00:00+03:00"), client=client)
    assert report.reconciled == 0 and len(respx_mock.calls) == 0
    assert store.deliveries(tenant.slug)[0].state == State.ACCEPTED
