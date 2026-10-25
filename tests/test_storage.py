from datetime import timedelta
import sqlite3

import pytest

from content_factory.models import Asset, Delivery, Part, Result, State
from content_factory.storage import LockedError, Store


def test_migrations_wal_idempotence_and_tenant_columns(store):
    store.migrate()
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2
    tables = [r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        columns = {r[1]: r for r in store.db.execute(f"PRAGMA table_info({table})")}
        assert columns["tenant_slug"][3] == 1, table
    assert not store.db.execute("PRAGMA foreign_key_check").fetchall()


def test_migration_rollback_and_checksum(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    first = migrations / "001_one.sql"
    first.write_text("CREATE TABLE example (tenant_slug TEXT NOT NULL);")
    second = migrations / "002_broken.sql"
    second.write_text("CREATE TABLE rolled_back (tenant_slug TEXT NOT NULL); INVALID SQL;")
    with Store(tmp_path / "db.sqlite") as db:
        with pytest.raises(sqlite3.OperationalError):
            db.migrate(migrations)
        assert db.db.execute("SELECT version FROM schema_migrations").fetchall()[0][0] == 1
        assert not db.db.execute("SELECT name FROM sqlite_master WHERE name='rolled_back'").fetchall()
        first.write_text("CREATE TABLE example (tenant_slug TEXT NOT NULL, x INTEGER);")
        with pytest.raises(ValueError, match="changed"):
            db.migrate(migrations)


def test_ordered_migrations(tmp_path):
    directory = tmp_path / "migrations"
    directory.mkdir()
    (directory / "002_second.sql").write_text("ALTER TABLE first ADD COLUMN n INTEGER;")
    (directory / "001_first.sql").write_text("CREATE TABLE first (tenant_slug TEXT NOT NULL);")
    with Store(tmp_path / "db.sqlite") as db:
        db.migrate(directory)
        assert [r[0] for r in db.db.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]


def test_roundtrip_approval_revision_cancel(store, slot, photo):
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    store.add_slot(slot)
    assert store.get_slot(slot.tenant_slug, slot.id).model_dump() == slot.model_dump()
    assert store.media(slot) == [photo]
    store.approve(slot.tenant_slug, slot.id)
    assert store.get_slot(slot.tenant_slug, slot.id).approved_version == 1
    updated = store.revise(slot.tenant_slug, slot.id, caption="Changed", at=slot.at + timedelta(hours=1))
    assert updated.version == 2 and updated.approved_version is None
    assert store.get_slot(slot.tenant_slug, slot.id) == updated
    store.cancel(slot.tenant_slug, slot.id)
    assert store.get_slot(slot.tenant_slug, slot.id).cancelled
    events = [r[0] for r in store.db.execute("SELECT event FROM event_log ORDER BY rowid")]
    assert events == ["slot_added", "slot_approved", "slot_revised", "slot_cancelled"]


def test_slot_rejects_cross_tenant_asset_and_channel(store, tenant, slot, photo):
    other = tenant.model_copy(deep=True)
    other.slug = "other"
    store.register(other)
    photo.tenant_slug = other.slug
    store.add_asset(photo)
    slot.media_ids = [photo.id]
    with pytest.raises(ValueError, match="does not belong"):
        store.add_slot(slot)
    slot.media_ids = []
    slot.channel_ids = ["foreign-channel"]
    with pytest.raises(ValueError, match="outside"):
        store.add_slot(slot)


def test_composite_fks_prevent_cross_tenant_links(store, tenant, slot, photo):
    other = tenant.model_copy(deep=True)
    other.slug = "other"
    other.channels[0].id = "other-feed"
    store.register(other)
    photo.tenant_slug = other.slug
    store.add_asset(photo)
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0])
    statements = [
        ("INSERT INTO slot_asset VALUES(?,?,?,?)", (tenant.slug, slot.id, photo.id, 0)),
        ("INSERT INTO slot_channel VALUES(?,?,?)", (tenant.slug, slot.id, "other-feed")),
        ("INSERT INTO part VALUES(?,?,?,?,?,?)", ("p", other.slug, delivery.id, "message", "1", None)),
        ("INSERT INTO event_log VALUES(?,?,?,?,?,?,?)", ("e", other.slug, slot.id, None, "today", "test", "{}")),
        ("UPDATE delivery SET tenant_slug=? WHERE id=?", (other.slug, delivery.id)),
    ]
    for sql, params in statements:
        with pytest.raises(sqlite3.IntegrityError), store.db:
            store.db.execute(sql, params)
    with pytest.raises(ValueError, match="not found"):
        store.get_slot(other.slug, slot.id)
    assert store.deliveries(other.slug) == []
    assert store.parts(other.slug, delivery.id) == []


def test_outbox_fence_and_terminal_state(store, slot):
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0], at=slot.at)
    assert store.deliveries(slot.tenant_slug)[0].state == State.SUBMITTING
    with Store(store.path) as second_connection:
        assert second_connection.deliveries(slot.tenant_slug)[0].delivery_key == delivery.delivery_key
    with pytest.raises(sqlite3.IntegrityError):
        store.begin_delivery(slot, slot.channel_ids[0])
    part = Part(tenant_slug=slot.tenant_slug, delivery_id=delivery.id, kind="message", external_id="42")
    result = Result(state=State.PUBLISHED, external_ids={"message_id": 42}, parts=[part])
    store.checkpoint(delivery, result)
    store.checkpoint(delivery, result)
    assert len(store.parts(slot.tenant_slug, delivery.id)) == 1
    with pytest.raises(ValueError, match="terminal"):
        store.checkpoint(delivery, Result(state=State.UNKNOWN))
    with pytest.raises(ValueError, match="after delivery"):
        store.revise(slot.tenant_slug, slot.id, caption="changed", at=slot.at)
    assert store.history(slot.tenant_slug)[0].at == slot.at


def test_part_context_check(store, slot):
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0])
    part = Part(tenant_slug="other", delivery_id=delivery.id, kind="message", external_id="42")
    with pytest.raises(ValueError, match="mismatch"):
        store.checkpoint(delivery, Result(state=State.PUBLISHED, parts=[part]))


def test_file_lock(store):
    with Store(store.path) as other:
        with store.lock():
            with pytest.raises(LockedError), other.lock():
                pytest.fail("second lock admitted")
        with other.lock():
            pass


def test_no_result_can_regress_to_submitting(store, slot):
    store.add_slot(slot)
    delivery = store.begin_delivery(slot, slot.channel_ids[0])
    store.checkpoint(delivery, Result(state=State.UNKNOWN))
    with pytest.raises(ValueError, match="return to submitting"):
        store.checkpoint(delivery, Result(state=State.SUBMITTING))
