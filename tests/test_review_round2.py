from datetime import timedelta
from email import policy
from email.parser import BytesParser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib

import httpx
import pytest
from typer.testing import CliRunner

from content_factory.cli import app
from content_factory.models import Asset, Result, State
from content_factory.scheduler import tick
from content_factory.storage import Store

TG = 'https://api.telegram.org/botfake-token'
GRAPH = 'https://graph.facebook.com/v25.0'
POSTIZ = 'https://postiz.test/api/public/v1'


def enable(tenant, monkeypatch, publisher):
    channel = tenant.channels[0]
    channel.publisher = publisher
    monkeypatch.setenv(channel.secret_ref, 'fake-token')
    if publisher == 'postiz':
        monkeypatch.setenv('CF_POSTIZ_URL', 'https://postiz.test')
    return channel


@pytest.mark.parametrize('fault', ['channel', 'media'])
def test_poison_slot_does_not_abort_tick(store, tenant, slot, now, client, fault):
    second = tenant.channels[0].model_copy(update={'id': 'second'})
    tenant.channels.append(second)
    store.register(tenant)
    store.add_slot(slot)
    good = slot.model_copy(update={'id': 'good', 'at': now + timedelta(seconds=1), 'channel_ids': ['second']})
    store.add_slot(good)
    if fault == 'channel':
        tenant.channels.pop(0)
    else:
        asset = Asset(tenant_slug=tenant.slug, source='https://media.test/a.jpg', kind='photo')
        store.add_asset(asset)
        with store.db:
            store.db.execute('INSERT INTO slot_asset VALUES(?,?,?,?)', (tenant.slug, slot.id, asset.id, 0))
            store.db.execute("UPDATE asset SET data='{}' WHERE id=?", (asset.id,))
    report = tick(store, tenant, clock=lambda: now + timedelta(seconds=1), client=client)
    assert report.failed == 1 and report.published == 1
    assert store.deliveries(tenant.slug, good.id)[0].state == State.PUBLISHED
    event = store.db.execute("SELECT details FROM event_log WHERE event='preflight_failed'").fetchone()
    assert slot.channel_ids[0] in event[0]


@pytest.mark.parametrize('failure', ['503', 'timeout'])
def test_meta_reconcile_recovers_after_read_error(respx_mock, store, tenant, slot, video, now, client, monkeypatch, failure):
    channel = enable(tenant, monkeypatch, 'meta')
    channel.type, channel.external_id = 'fb_page', 'page'
    slot.kind = 'reel'
    slot.media_ids = [video.id]
    store.add_asset(video)
    store.add_slot(slot)
    create = respx_mock.post(GRAPH + '/page/video_reels').mock(side_effect=[
        httpx.Response(200, json={'video_id': 'v1', 'upload_url': 'https://rupload.facebook.com/upload'}),
        httpx.Response(200, json={'success': True}),
    ])
    respx_mock.post('https://rupload.facebook.com/upload').respond(200, json={'success': True})
    assert tick(store, tenant, clock=lambda: now, client=client).accepted == 1
    read = respx_mock.get(GRAPH + '/v1')
    if failure == '503':
        read.respond(503, json={})
    else:
        read.mock(side_effect=httpx.ReadTimeout('lost read'))
    tick(store, tenant, clock=lambda: now, client=client)
    delivery = store.deliveries(tenant.slug)[0]
    assert delivery.state == State.ACCEPTED
    assert delivery.external_ids['sequence_complete'] is True
    assert store.db.execute("SELECT COUNT(*) FROM event_log WHERE event='reconcile_error'").fetchone()[0] == 1
    read.respond(200, json={'status': {'publishing_phase': {'status': 'complete'}}})
    tick(store, tenant, clock=lambda: now, client=client)
    assert store.deliveries(tenant.slug)[0].state == State.PUBLISHED
    assert create.call_count == 2


def test_cli_cancel_during_http_stops_next_request(respx_mock, store, tenant, slot, photo, now, client, monkeypatch, tmp_path):
    import yaml
    enable(tenant, monkeypatch, 'telegram')
    directory = tmp_path / 'tenants' / tenant.slug
    directory.mkdir(parents=True)
    (directory / 'tenant.yaml').write_text(yaml.safe_dump(tenant.model_dump(mode='json', by_alias=True)))
    (directory / 'policy.md').write_text('Policy')
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    slot.caption = 'x' * 1025
    store.add_slot(slot)
    runner = CliRunner()
    args = ['--db', str(store.path), '--tenants-root', str(tmp_path / 'tenants')]
    def response(request):
        status = runner.invoke(app, args + ['status', '--tenant', tenant.slug])
        assert status.exit_code == 0, status.output
        approved = runner.invoke(app, args + ['slot', 'approve', slot.id])
        assert approved.exit_code == 0, approved.output
        added = runner.invoke(app, args + ['slot', 'add', '--tenant', tenant.slug, '--kind', 'post',
                             '--at', (now + timedelta(days=1)).isoformat(), '--channels', slot.channel_ids[0]])
        assert added.exit_code == 0, added.output
        cancelled = runner.invoke(app, args + ['slot', 'cancel', slot.id])
        assert cancelled.exit_code == 0, cancelled.output
        return httpx.Response(200, json={'ok': True, 'result': {'message_id': 1}})
    respx_mock.post(TG + '/sendMessage').mock(side_effect=response)
    assert tick(store, tenant, clock=lambda: now, client=client).unknown == 1
    assert len(respx_mock.calls) == 1
    assert store.get_slot(tenant.slug, slot.id).cancelled


@pytest.mark.parametrize('provider,status,body,headers', [
    ('telegram', 429, {'ok': False, 'parameters': {'retry_after': 45}}, {}),
    ('telegram', 200, {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 45}}, {}),
    ('postiz', 429, {'message': 'API_LIMIT'}, {'Retry-After': '45'}),
    ('meta', 400, {'error': {'code': 4}}, {'Retry-After': '45'}),
    ('meta', 400, {'error': {'code': 17}}, {'Retry-After': '45'}),
    ('meta', 400, {'error': {'code': 32}}, {'Retry-After': '45'}),
    ('meta', 400, {'error': {'code': 613}}, {'Retry-After': '45'}),
])
def test_rate_rejection_is_deferred_then_retried(respx_mock, store, tenant, slot, photo, now, client, monkeypatch,
                                               provider, status, body, headers):
    channel = enable(tenant, monkeypatch, provider)
    if provider == 'telegram':
        path = TG + '/sendMessage'
        success = {'ok': True, 'result': {'message_id': 1}}
    elif provider == 'postiz':
        path = POSTIZ + '/posts'
        success = [{'postId': 'p1', 'integration': channel.external_id}]
        store.add_asset(photo)
        slot.media_ids = [photo.id]
        respx_mock.post(POSTIZ + '/upload-from-url').respond(200, json={'id': 'u1', 'path': 'https://postiz.test/u.jpg'})
    else:
        channel.type, channel.external_id = 'fb_page', 'page'
        path = GRAPH + '/page/feed'
        success = {'id': 'p1'}
    store.add_slot(slot)
    route = respx_mock.post(path).respond(status, json=body, headers=headers)
    report = tick(store, tenant, clock=lambda: now, client=client)
    delivery = store.deliveries(tenant.slug)[0]
    assert report.deferred == 1 and delivery.state.value == 'deferred'
    assert delivery.next_attempt_at >= now + timedelta(seconds=45)
    with Store(store.path) as reopened:
        tick(reopened, tenant, clock=lambda: now + timedelta(seconds=44), client=client)
    assert route.call_count == 1
    route.respond(200, json=success)
    tick(store, tenant, clock=lambda: now + timedelta(seconds=121), client=client)
    final = store.deliveries(tenant.slug)[0]
    assert final.id == delivery.id and final.attempts == 2
    assert final.state in (State.PUBLISHED, State.ACCEPTED)
    assert route.call_count == 2


def test_postiz_org_bucket_survives_ticks_and_key_aliases(respx_mock, store, tenant, slot, now, client, monkeypatch):
    channel = enable(tenant, monkeypatch, 'postiz')
    monkeypatch.setenv('CF_POSTIZ_API_LIMIT', '30')
    second = channel.model_copy(update={'id': 'second', 'secret_ref': 'ALIAS_KEY', 'external_id': 'integration2'})
    monkeypatch.setenv('ALIAS_KEY', 'fake-token')
    tenant.channels.append(second)
    store.register(tenant)
    slot.channel_ids.append(second.id)
    store.add_slot(slot)
    def response(request):
        integration = json.loads(request.content)['posts'][0]['integration']['id']
        return httpx.Response(200, json=[{'postId': integration, 'integration': integration}])
    route = respx_mock.post(POSTIZ + '/posts').mock(side_effect=response)
    respx_mock.get(POSTIZ + '/posts').respond(200, json={'posts': [{'id': channel.external_id, 'state': 'QUEUE'}]})
    first = tick(store, tenant, clock=lambda: now, client=client)
    assert first.accepted == 1 and first.deferred == 1
    with Store(store.path) as reopened:
        tick(reopened, tenant, clock=lambda: now + timedelta(seconds=119), client=client)
        assert route.call_count == 1
        tick(reopened, tenant, clock=lambda: now + timedelta(seconds=120), client=client)
    assert route.call_count == 2


@pytest.mark.parametrize('change', ['caption', 'media', 'channels', 'channel_target'])
def test_approval_hash_invalidates_changed_content(store, tenant, slot, photo, now, client, tmp_path, change):
    tenant.approval.mode = 'manual'
    file = tmp_path / 'photo.jpg'
    file.write_bytes(b'approved photo')
    photo.source = str(file)
    store.add_asset(photo)
    second = tenant.channels[0].model_copy(update={'id': 'second'})
    tenant.channels.append(second)
    store.register(tenant)
    slot.media_ids = [photo.id]
    store.add_slot(slot)
    store.approve(tenant.slug, slot.id)
    if change == 'caption':
        with store.db:
            store.db.execute("UPDATE slot SET caption='edited' WHERE id=?", (slot.id,))
    elif change == 'media':
        file.write_bytes(b'replaced photo')
    elif change == 'channels':
        with store.db:
            store.db.execute('INSERT INTO slot_channel VALUES(?,?,?)', (tenant.slug, slot.id, 'second'))
    else:
        tenant.channels[0].external_id = 'other-target'
    assert tick(store, tenant, clock=lambda: now, client=client).published == 0
    assert store.get_slot(tenant.slug, slot.id).approved_version is None
    assert not store.deliveries(tenant.slug)
    store.approve(tenant.slug, slot.id)
    assert tick(store, tenant, clock=lambda: now, client=client).published >= 1


@pytest.mark.parametrize('lateness', [None, 30])
def test_old_slots_are_missed_and_not_published(store, tenant, slot, now, client, lateness):
    if lateness is not None:
        tenant.schedule.max_lateness_minutes = lateness
    limit = lateness or 180
    slot.at = now - timedelta(minutes=limit, seconds=1)
    store.add_slot(slot)
    report = tick(store, tenant, clock=lambda: now, client=client)
    assert report.missed == 1 and report.published == 0
    assert store.get_slot(tenant.slug, slot.id).missed
    assert store.db.execute("SELECT COUNT(*) FROM event_log WHERE event='slot_missed'").fetchone()[0] == 1
    assert tick(store, tenant, clock=lambda: now, client=client).missed == 0


@pytest.mark.parametrize('kind', ['photo', 'video'])
def test_telegram_single_local_multipart_field(respx_mock, client, delivery, slot, tenant, tmp_path, kind):
    from content_factory.publishers.telegram import TelegramPublisher
    file = tmp_path / ('media.mp4' if kind == 'video' else 'media.jpg')
    file.write_bytes(b'file bytes')
    asset = Asset(tenant_slug=tenant.slug, source=str(file), kind=kind, width=10, height=20, duration=1)
    slot.media_ids = [asset.id]
    method = 'sendPhoto' if kind == 'photo' else 'sendVideo'
    route = respx_mock.post(TG + '/' + method).respond(200, json={'ok': True, 'result': {'message_id': 1}})
    TelegramPublisher(client, 'fake-token', 'chat').publish(delivery, slot, tenant.channels[0], [asset])
    request = route.calls[0].request
    message = BytesParser(policy=policy.default).parsebytes(
        b'Content-Type: ' + request.headers['content-type'].encode() + b'\r\n\r\n' + request.content)
    files = [part for part in message.iter_parts() if part.get_filename()]
    assert len(files) == 1 and files[0].get_param('name', header='content-disposition') == kind
    assert files[0].get_payload(decode=True) == b'file bytes'
    assert b'attach://' not in request.content


def test_tzdata_is_declared():
    metadata = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
    assert 'tzdata' in metadata['project']['dependencies']


def test_readme_quick_start_commands_with_dry_publisher(tmp_path):
    root = Path(__file__).parents[1]
    block = root.joinpath('README.md').read_text().split('```sh\n', 1)[1].split('```', 1)[0]
    # Installation is the test runner's prerequisite. Execute the documented runtime block verbatim;
    # the final pytest command would recursively launch this very test.
    commands = block[block.index('mkdir -p tenants'):block.rindex('pytest -q')]
    shutil.copytree(root / 'examples', tmp_path / 'examples')
    result = subprocess.run(['bash', '-euo', 'pipefail', '-c', commands], cwd=tmp_path, text=True,
                            capture_output=True, timeout=30,
                            env={'PATH': str(Path(sys.executable).parent) + os.pathsep + os.defpath,
                                 'CF_DB': str(tmp_path / 'demo.sqlite3'), 'LANG': 'C.UTF-8'})
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'DRY' in result.stderr + result.stdout
    assert 'published=1' in result.stdout
    assert 'published=0' in result.stdout and 'skipped=1' in result.stdout
    assert 'demo-feed=published' in result.stdout
    with Store(tmp_path / '.cf/demo.sqlite3') as db:
        assert len(db.deliveries('demo')) == 1
        assert db.deliveries('demo')[0].state == State.PUBLISHED


def test_upgrade_001_keeps_journal_and_foreign_keys(tmp_path, tenant, slot):
    root = Path(__file__).parents[1]
    old = tmp_path / 'migrations'
    old.mkdir()
    shutil.copy(root / 'migrations/001_core.sql', old)
    with Store(tmp_path / 'db.sqlite') as db:
        db.migrate(old)
        db.register(tenant)
        with db.db:
            db.db.execute('INSERT INTO slot VALUES(?,?,?,?,?,?,?,?)',
                          (slot.id, tenant.slug, slot.at.isoformat(), 'post', slot.caption, 1, 1, 0))
            db.db.execute('INSERT INTO slot_channel VALUES(?,?,?)', (tenant.slug, slot.id, slot.channel_ids[0]))
        delivery = db.begin_delivery(slot, slot.channel_ids[0], at=slot.at)
        from content_factory.models import Part
        db.checkpoint(delivery, Result(state=State.PUBLISHED, parts=[Part(
            tenant_slug=tenant.slug, delivery_id=delivery.id, kind='message', external_id='42')]))
        events = db.db.execute('SELECT * FROM event_log').fetchall()
        db.migrate()
        db.migrate()
        assert db.deliveries(tenant.slug)[0].state == State.PUBLISHED
        assert db.parts(tenant.slug, delivery.id)[0].external_id == '42'
        assert db.db.execute('SELECT * FROM event_log').fetchall() == events
        assert db.get_slot(tenant.slug, slot.id).approved_version is None
        assert not db.db.execute('PRAGMA foreign_key_check').fetchall()


def test_postiz_retry_after_cools_down_whole_org(respx_mock, store, tenant, slot, now, client, monkeypatch):
    channel = enable(tenant, monkeypatch, 'postiz')
    second = channel.model_copy(update={'id': 'second'})
    tenant.channels.append(second)
    store.register(tenant)
    slot.channel_ids.append(second.id)
    store.add_slot(slot)
    route = respx_mock.post(POSTIZ + '/posts').respond(429, headers={'Retry-After': '3600'}, json={})
    report = tick(store, tenant, clock=lambda: now, client=client)
    assert report.deferred == 2 and route.call_count == 1
    tick(store, tenant, clock=lambda: now + timedelta(minutes=5), client=client)
    assert route.call_count == 1
    assert all(d.state == State.DEFERRED for d in store.deliveries(tenant.slug))


def test_rate_limit_after_public_part_never_replays(respx_mock, store, tenant, slot, photo, now, client, monkeypatch):
    enable(tenant, monkeypatch, 'telegram')
    slot.caption = 'x' * 1025
    slot.media_ids = [photo.id]
    store.add_asset(photo)
    store.add_slot(slot)
    text = respx_mock.post(TG + '/sendMessage').respond(200, json={'ok': True, 'result': {'message_id': 1}})
    photo_route = respx_mock.post(TG + '/sendPhoto').respond(429, json={'parameters': {'retry_after': 1}})
    assert tick(store, tenant, clock=lambda: now, client=client).unknown == 1
    tick(store, tenant, clock=lambda: now + timedelta(minutes=2), client=client)
    assert text.call_count == photo_route.call_count == 1
    assert store.deliveries(tenant.slug)[0].state == State.UNKNOWN
    assert store.parts(tenant.slug, store.deliveries(tenant.slug)[0].id)[0].external_id == '1'


def test_deferred_retry_rechecks_cancel_approval_and_blackout(respx_mock, store, tenant, slot, now, client, monkeypatch):
    from content_factory.config import WeeklyBlackout
    enable(tenant, monkeypatch, 'telegram')
    store.add_slot(slot)
    route = respx_mock.post(TG + '/sendMessage').respond(429, json={'parameters': {'retry_after': 1}})
    assert tick(store, tenant, clock=lambda: now, client=client).deferred == 1
    tenant.approval.mode = 'manual'
    assert tick(store, tenant, clock=lambda: now + timedelta(seconds=2), client=client).blocked == 1
    store.approve(tenant.slug, slot.id)
    tenant.schedule.blackout = [WeeklyBlackout(type='weekly', **{'from': 'sun 00:00', 'to': 'mon 00:00'})]
    assert tick(store, tenant, clock=lambda: now + timedelta(seconds=2), client=client).blocked == 1
    tenant.schedule.blackout = []
    store.cancel(tenant.slug, slot.id)
    tick(store, tenant, clock=lambda: now + timedelta(seconds=2), client=client)
    assert route.call_count == 1
    assert store.deliveries(tenant.slug)[0].attempts == 1


@pytest.mark.parametrize('complete', [True, False])
def test_meta_sequence_marker_controls_unknown_recovery(respx_mock, client, delivery, complete):
    from content_factory.publishers.meta import MetaPublisher
    delivery.state = State.UNKNOWN
    delivery.external_ids = {'videos': ['v1']}
    if complete:
        delivery.external_ids['sequence_complete'] = True
    respx_mock.get(GRAPH + '/v1').respond(200, json={'status': {'publishing_phase': {'status': 'complete'}}})
    result = MetaPublisher(client, 'fake-token').reconcile(delivery)
    assert result.state == (State.PUBLISHED if complete else State.UNKNOWN)


def test_local_media_hash_is_stored_and_verified(store, tenant, slot, photo, tmp_path):
    from contextlib import ExitStack
    from content_factory.publishers.base import PublishRejected, media_file
    file = tmp_path / 'photo.jpg'
    file.write_bytes(b'original')
    photo.source = str(file)
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    store.add_slot(slot)
    pinned = store.media(slot)[0]
    assert pinned.size == 8 and len(pinned.sha256) == 64
    file.write_bytes(b'replaced')
    with ExitStack() as stack, pytest.raises(PublishRejected, match='media changed'):
        media_file(stack, pinned)


def test_maximum_lateness_boundary_is_inclusive(store, tenant, slot, now, client):
    slot.at = now - timedelta(minutes=180)
    store.add_slot(slot)
    assert tick(store, tenant, clock=lambda: now, client=client).published == 1


def test_timezone_fallback_without_system_database():
    code = """
import zoneinfo
zoneinfo.reset_tzpath([])
zoneinfo.ZoneInfo.clear_cache()
assert zoneinfo.ZoneInfo('Europe/Kyiv').key == 'Europe/Kyiv'
"""
    result = subprocess.run([sys.executable, '-c', code], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_approval_hashing_does_not_block_cancel(store, tenant, slot, photo, tmp_path, monkeypatch):
    file = tmp_path / 'photo.jpg'
    file.write_bytes(b'photo')
    photo.source = str(file)
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    store.add_slot(slot)
    original = store.pin_asset
    def pin(asset):
        with Store(store.path) as other:
            other.cancel(tenant.slug, slot.id)
        original(asset)
    monkeypatch.setattr(store, 'pin_asset', pin)
    with pytest.raises(ValueError, match='changed during approval'):
        store.approve(tenant.slug, slot.id)
    assert store.get_slot(tenant.slug, slot.id).cancelled
