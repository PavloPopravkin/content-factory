from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import sqlite3
from typing import Iterator

from .config import Tenant
from .models import Asset, Delivery, Part, Result, Slot, State, new_id


def utc_text(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat()


class LockedError(RuntimeError):
    pass


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *args: object) -> None:
        self.db.close()

    @contextmanager
    def lock(self) -> Iterator[None]:
        with self.path.with_suffix(self.path.suffix + ".lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LockedError("another tick or migration holds the database lock") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def migrate(self, directory: Path | None = None) -> None:
        source = directory or files("content_factory").joinpath("migrations")
        checkout = Path(__file__).resolve().parents[2] / "migrations"
        if directory is None and checkout.is_dir() and (checkout.parent / "pyproject.toml").is_file():
            source = checkout
        migrations = []
        for path in sorted(source.iterdir(), key=lambda p: p.name):
            match = re.fullmatch(r"(\d{3})_.+\.sql", path.name)
            if match:
                sql = path.read_text()
                migrations.append((int(match[1]), path.name, hashlib.sha256(sql.encode()).hexdigest(), sql))

        def pending() -> list:
            exists = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
            applied = {r["version"]: r for r in self.db.execute("SELECT * FROM schema_migrations")} if exists else {}
            for version, name, checksum, _ in migrations:
                if version in applied and (applied[version]["checksum"] != checksum or applied[version]["name"] != name):
                    raise ValueError(f"migration {name} changed after application")
            return [m for m in migrations if m[0] not in applied]

        if not pending():
            return
        with self.lock():
            # Migration metadata is global; '__schema__' is a reserved non-tenant scope.
            self.db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY, tenant_slug TEXT NOT NULL DEFAULT '__schema__',
                name TEXT NOT NULL, checksum TEXT NOT NULL)""")
            self.db.commit()
            for version, name, checksum, sql in pending():
                try:
                    self.db.executescript("BEGIN IMMEDIATE;\n" + sql)
                    self.db.execute("INSERT INTO schema_migrations(version,name,checksum) VALUES(?,?,?)",
                                    (version, name, checksum))
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise

    def register(self, tenant: Tenant) -> None:
        with self.db:
            self.db.execute("""INSERT INTO tenant VALUES(?,?,?) ON CONFLICT(tenant_slug)
                DO UPDATE SET name=excluded.name,config=excluded.config""",
                (tenant.slug, tenant.name, tenant.model_dump_json(by_alias=True)))
            for channel in tenant.channels:
                self.db.execute("""INSERT INTO channel VALUES(?,?,?) ON CONFLICT(tenant_slug,id)
                    DO UPDATE SET config=excluded.config""", (tenant.slug, channel.id, channel.model_dump_json()))

    def _event(self, tenant: str, event: str, *, slot_id: str | None = None,
               delivery_id: str | None = None, details: dict | None = None) -> None:
        self.db.execute("INSERT INTO event_log VALUES(?,?,?,?,?,?,?)",
                        (new_id(), tenant, slot_id, delivery_id, utc_text(datetime.now(timezone.utc)),
                         event, json.dumps(details or {})))

    @staticmethod
    def pin_asset(asset: Asset) -> None:
        if not asset.source.startswith(("http://", "https://")):
            with Path(asset.source).open("rb") as file:
                asset.sha256 = hashlib.file_digest(file, "sha256").hexdigest()
                asset.size = Path(asset.source).stat().st_size

    def add_asset(self, asset: Asset) -> None:
        self.pin_asset(asset)
        with self.db:
            self.db.execute("INSERT INTO asset VALUES(?,?,?)", (asset.id, asset.tenant_slug, asset.model_dump_json()))

    def media(self, slot: Slot) -> list[Asset]:
        assets = []
        for asset_id in slot.media_ids:
            row = self.db.execute("SELECT data FROM asset WHERE tenant_slug=? AND id=?",
                                  (slot.tenant_slug, asset_id)).fetchone()
            if row is None:
                raise ValueError(f"asset {asset_id} does not belong to tenant {slot.tenant_slug}")
            asset = Asset.model_validate_json(row[0])
            if asset.tenant_slug != slot.tenant_slug or asset.id != asset_id:
                raise ValueError("asset payload tenant/id mismatch")
            assets.append(asset)
        return assets

    def add_slot(self, slot: Slot) -> None:
        self.media(slot)
        registered = {r[0] for r in self.db.execute("SELECT id FROM channel WHERE tenant_slug=?", (slot.tenant_slug,))}
        if not set(slot.channel_ids) <= registered:
            raise ValueError("slot references a channel outside its tenant")
        with self.db:
            self.db.execute("""INSERT INTO slot(id,tenant_slug,at,kind,caption,version,approved_version,cancelled)
                VALUES(?,?,?,?,?,?,?,?)""",
                            (slot.id, slot.tenant_slug, utc_text(slot.at), slot.kind, slot.caption,
                             slot.version, slot.approved_version, slot.cancelled))
            self.db.executemany("INSERT INTO slot_channel VALUES(?,?,?)",
                                [(slot.tenant_slug, slot.id, c) for c in slot.channel_ids])
            self.db.executemany("INSERT INTO slot_asset VALUES(?,?,?,?)",
                                [(slot.tenant_slug, slot.id, a, i) for i, a in enumerate(slot.media_ids)])
            self._event(slot.tenant_slug, "slot_added", slot_id=slot.id)

    def get_slot(self, tenant: str, slot_id: str) -> Slot:
        row = self.db.execute("SELECT * FROM slot WHERE tenant_slug=? AND id=?", (tenant, slot_id)).fetchone()
        if row is None:
            raise ValueError(f"slot {slot_id} not found for tenant {tenant}")
        data = dict(row)
        data["channel_ids"] = [r[0] for r in self.db.execute(
            "SELECT channel_id FROM slot_channel WHERE tenant_slug=? AND slot_id=? ORDER BY channel_id", (tenant, slot_id))]
        data["media_ids"] = [r[0] for r in self.db.execute(
            "SELECT asset_id FROM slot_asset WHERE tenant_slug=? AND slot_id=? ORDER BY position", (tenant, slot_id))]
        return Slot.model_validate(data)

    def slots(self, tenant: str) -> list[Slot]:
        return [self.get_slot(tenant, r[0]) for r in self.db.execute(
            "SELECT id FROM slot WHERE tenant_slug=? ORDER BY at,id", (tenant,)).fetchall()]

    def content_hash(self, slot: Slot, *, media: list[Asset] | None = None) -> str:
        if media is None:
            media = self.media(slot)
            for asset in media:
                self.pin_asset(asset)
        channels = [json.loads(self.db.execute("SELECT config FROM channel WHERE tenant_slug=? AND id=?",
                    (slot.tenant_slug, channel)).fetchone()[0]) for channel in sorted(slot.channel_ids)]
        payload = {"caption": slot.caption, "kind": slot.kind, "channels": channels,
                   "media": [a.model_dump(mode="json") for a in media]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def check_approval(self, slot: Slot) -> Slot:
        if slot.approved_version is not None:
            try:
                valid = slot.approved_hash == self.content_hash(slot)
            except (ValueError, OSError):
                valid = False
            if not valid:
                with self.db:
                    self.db.execute("UPDATE slot SET approved_version=NULL,approved_hash=NULL WHERE tenant_slug=? AND id=?",
                                    (slot.tenant_slug, slot.id))
                    self._event(slot.tenant_slug, "approval_reset", slot_id=slot.id)
                slot.approved_version = None
                slot.approved_hash = None
        return slot

    def approve(self, tenant: str, slot_id: str) -> None:
        slot = self.get_slot(tenant, slot_id)
        original_media = self.media(slot)
        media = [a.model_copy(deep=True) for a in original_media]
        # Hash large files before acquiring SQLite's writer lock so cancel stays responsive.
        for asset in media:
            self.pin_asset(asset)
        fingerprint = self.content_hash(slot, media=media)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if (self.get_slot(tenant, slot_id) != slot or self.media(slot) != original_media
                    or self.content_hash(slot, media=media) != fingerprint):
                raise ValueError("slot changed during approval; review and approve again")
            for asset in media:
                self.db.execute("UPDATE asset SET data=? WHERE tenant_slug=? AND id=?",
                                (asset.model_dump_json(), tenant, asset.id))
            self.db.execute("UPDATE slot SET approved_version=version,approved_hash=? WHERE tenant_slug=? AND id=?",
                            (fingerprint, tenant, slot_id))
            self._event(tenant, "slot_approved", slot_id=slot_id)

    def event(self, tenant: str, event: str, *, slot_id: str, delivery_id: str | None = None,
              details: dict | None = None) -> None:
        with self.db:
            self._event(tenant, event, slot_id=slot_id, delivery_id=delivery_id, details=details)

    def miss(self, slot: Slot) -> None:
        with self.db:
            self.db.execute("UPDATE slot SET missed=1 WHERE tenant_slug=? AND id=?", (slot.tenant_slug, slot.id))
            self._event(slot.tenant_slug, "slot_missed", slot_id=slot.id)

    def consume_postiz_token(self, tenant: str, scope: str, limit: int, at: datetime) -> float:
        """Persistent per-org bucket, deliberately limited to one burst token."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM publisher_bucket WHERE scope=?", (scope,)).fetchone()
            elapsed = max(0, (at - datetime.fromisoformat(row["updated_at"])).total_seconds()) if row else 0
            tokens = min(1.0, row["tokens"] + elapsed * limit / 3600) if row else 1.0
            wait = (1 - tokens) * 3600 / limit if tokens < 1 - 1e-9 else 0
            self.db.execute("""INSERT INTO publisher_bucket VALUES(?,?,?,?) ON CONFLICT(scope)
                DO UPDATE SET tokens=excluded.tokens,updated_at=excluded.updated_at""",
                (scope, tenant, tokens if wait else 0, utc_text(at)))
        return wait

    def defer(self, delivery: Delivery, *, at: datetime, error: str) -> None:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.parts(delivery.tenant_slug, delivery.id):
                raise ValueError("cannot defer a delivery with public parts")
            changed = self.db.execute("""UPDATE delivery SET state='deferred',next_attempt_at=?,error=?
                WHERE tenant_slug=? AND id=? AND state='submitting'""",
                (utc_text(at), error, delivery.tenant_slug, delivery.id)).rowcount
            if not changed:
                raise ValueError("only a submitting delivery can be deferred")
            self._event(delivery.tenant_slug, "deferred", slot_id=delivery.slot_id, delivery_id=delivery.id,
                        details={"error": error, "next_attempt_at": utc_text(at)})
        delivery.state = State.DEFERRED
        delivery.next_attempt_at = at

    def postpone_postiz(self, tenant: str, scope: str, limit: int, at: datetime, retry_after: float) -> None:
        # Negative tokens represent a provider-imposed cooldown shared by all key aliases.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM publisher_bucket WHERE scope=?", (scope,)).fetchone()
            elapsed = max(0, (at - datetime.fromisoformat(row["updated_at"])).total_seconds()) if row else 0
            tokens = min(1.0, row["tokens"] + elapsed * limit / 3600) if row else 1.0
            tokens = min(tokens, 1 - retry_after * limit / 3600)
            self.db.execute("""INSERT INTO publisher_bucket VALUES(?,?,?,?) ON CONFLICT(scope)
                DO UPDATE SET tokens=excluded.tokens,updated_at=excluded.updated_at""",
                (scope, tenant, tokens, utc_text(at)))

    def retry_delivery(self, delivery: Delivery, *, at: datetime) -> Delivery:
        # Only an explicit effect-free deferral is retryable. Keep the same unique fence.
        with self.db:
            changed = self.db.execute("""UPDATE delivery SET state='submitting',attempts=attempts+1,
                next_attempt_at=NULL,error=NULL,external_ids='{}',created_at=?
                WHERE tenant_slug=? AND id=? AND state='deferred'
                AND next_attempt_at<=?""", (utc_text(at), delivery.tenant_slug, delivery.id, utc_text(at))).rowcount
            if not changed:
                raise ValueError("delivery is not due for retry")
            self._event(delivery.tenant_slug, "retry_submitting", slot_id=delivery.slot_id, delivery_id=delivery.id)
        return next(d for d in self.deliveries(delivery.tenant_slug, delivery.slot_id) if d.id == delivery.id)

    def cancel(self, tenant: str, slot_id: str) -> None:
        self.get_slot(tenant, slot_id)
        with self.db:
            self.db.execute("UPDATE slot SET cancelled=1 WHERE tenant_slug=? AND id=?", (tenant, slot_id))
            self._event(tenant, "slot_cancelled", slot_id=slot_id)

    def revise(self, tenant: str, slot_id: str, *, caption: str, at: datetime) -> Slot:
        slot = self.get_slot(tenant, slot_id)
        if self.deliveries(tenant, slot_id):
            raise ValueError("cannot revise a slot after delivery started; create a new slot")
        candidate = Slot.model_validate({**slot.model_dump(), "caption": caption, "at": at,
                                        "version": slot.version + 1, "approved_version": None, "approved_hash": None})
        with self.db:
            self.db.execute("""UPDATE slot SET caption=?,at=?,version=?,approved_version=NULL,approved_hash=NULL
                WHERE tenant_slug=? AND id=?""", (candidate.caption, utc_text(candidate.at), candidate.version, tenant, slot_id))
            self._event(tenant, "slot_revised", slot_id=slot_id)
        return candidate

    def deliveries(self, tenant: str, slot_id: str | None = None) -> list[Delivery]:
        query = "SELECT * FROM delivery WHERE tenant_slug=?"
        params = [tenant]
        if slot_id:
            query += " AND slot_id=?"
            params.append(slot_id)
        result = []
        for row in self.db.execute(query + " ORDER BY created_at,id", params):
            data = dict(row)
            data["external_ids"] = json.loads(data["external_ids"])
            result.append(Delivery.model_validate(data))
        return result

    def begin_delivery(self, slot: Slot, channel_id: str, *, at: datetime | None = None) -> Delivery:
        persisted = self.get_slot(slot.tenant_slug, slot.id)
        if persisted.version != slot.version or channel_id not in persisted.channel_ids:
            raise ValueError("stale slot or channel outside slot")
        delivery = Delivery(tenant_slug=slot.tenant_slug, slot_id=slot.id, channel_id=channel_id,
                            delivery_key=f"{slot.tenant_slug}:{slot.id}:v{slot.version}:{channel_id}",
                            created_at=at or datetime.now(timezone.utc))
        with self.db:
            self.db.execute("""INSERT INTO delivery(id,tenant_slug,slot_id,channel_id,state,attempts,external_ids,error,delivery_key,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (delivery.id, delivery.tenant_slug, slot.id, channel_id, delivery.state,
                             delivery.attempts, "{}", None, delivery.delivery_key, utc_text(delivery.created_at)))
            self._event(slot.tenant_slug, "submitting", slot_id=slot.id, delivery_id=delivery.id)
        return delivery

    def checkpoint(self, delivery: Delivery, result: Result) -> None:
        if result.state == State.DEFERRED:
            raise ValueError("use defer() to record the retry deadline")
        for part in result.parts:
            if part.tenant_slug != delivery.tenant_slug or part.delivery_id != delivery.id:
                raise ValueError("part tenant/delivery mismatch")
        row = self.db.execute("SELECT state,external_ids FROM delivery WHERE tenant_slug=? AND id=?",
                              (delivery.tenant_slug, delivery.id)).fetchone()
        if row is None:
            raise ValueError("delivery does not belong to tenant")
        if result.state == State.SUBMITTING and row["state"] != State.SUBMITTING:
            raise ValueError("an existing result cannot return to submitting")
        if row["state"] == State.PUBLISHED and result.state != State.PUBLISHED:
            raise ValueError("published is terminal")
        merged = {**json.loads(row["external_ids"]), **result.external_ids}
        with self.db:
            self.db.execute("UPDATE delivery SET state=?,external_ids=?,error=? WHERE tenant_slug=? AND id=?",
                            (result.state, json.dumps(merged), result.error, delivery.tenant_slug, delivery.id))
            for part in result.parts:
                self.db.execute("""INSERT INTO part VALUES(?,?,?,?,?,?)
                    ON CONFLICT(tenant_slug,delivery_id,kind,external_id) DO NOTHING""",
                    (part.id, part.tenant_slug, part.delivery_id, part.kind, part.external_id, part.url))
            self._event(delivery.tenant_slug, result.state, slot_id=delivery.slot_id,
                        delivery_id=delivery.id, details={"error": result.error, "external_ids": merged})
        delivery.external_ids = merged
        delivery.state = result.state
        delivery.error = result.error

    def parts(self, tenant: str, delivery_id: str) -> list[Part]:
        return [Part.model_validate(dict(r)) for r in self.db.execute(
            "SELECT * FROM part WHERE tenant_slug=? AND delivery_id=? ORDER BY rowid", (tenant, delivery_id))]

    def history(self, tenant: str) -> list[Slot]:
        """One slot per attempted publication, at its real attempt time, including uncertain sends."""
        rows = self.db.execute("""SELECT slot_id,MIN(created_at) AS attempted_at FROM delivery
            WHERE tenant_slug=? GROUP BY slot_id""", (tenant,)).fetchall()
        return [self.get_slot(tenant, r["slot_id"]).model_copy(
            update={"at": datetime.fromisoformat(r["attempted_at"]), "cancelled": False}) for r in rows]
