ALTER TABLE slot ADD COLUMN approved_hash TEXT;
ALTER TABLE slot ADD COLUMN missed INTEGER NOT NULL DEFAULT 0 CHECK(missed IN (0,1));
-- Approval from 001 did not pin content. Require a new approval after upgrading.
UPDATE slot SET approved_version=NULL;

-- Keep the original name in child foreign keys while widening the state check.
PRAGMA defer_foreign_keys=ON;
CREATE TABLE delivery_v2 (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('submitting','accepted','published','failed','unknown','deferred')),
    attempts INTEGER NOT NULL CHECK(attempts >= 1),
    external_ids TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(external_ids)),
    error TEXT,
    delivery_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    next_attempt_at TEXT,
    CHECK((state='deferred' AND next_attempt_at IS NOT NULL) OR (state!='deferred' AND next_attempt_at IS NULL)),
    UNIQUE (tenant_slug, id),
    UNIQUE (tenant_slug, slot_id, channel_id),
    FOREIGN KEY (tenant_slug, slot_id, channel_id) REFERENCES slot_channel(tenant_slug, slot_id, channel_id)
);
INSERT INTO delivery_v2 SELECT *,NULL FROM delivery;
-- Rebuild children too: DROP of a referenced parent records deferred FK violations in SQLite.
CREATE TEMP TABLE saved_parts AS SELECT * FROM part;
CREATE TEMP TABLE saved_events AS SELECT * FROM event_log;
DROP TABLE part;
DROP TABLE event_log;
DROP TABLE delivery;
ALTER TABLE delivery_v2 RENAME TO delivery;
CREATE TABLE part (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT,
    UNIQUE (tenant_slug, delivery_id, kind, external_id),
    FOREIGN KEY (tenant_slug, delivery_id) REFERENCES delivery(tenant_slug, id)
);
CREATE TABLE event_log (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL REFERENCES tenant(tenant_slug),
    slot_id TEXT,
    delivery_id TEXT,
    at TEXT NOT NULL,
    event TEXT NOT NULL,
    details TEXT NOT NULL CHECK(json_valid(details)),
    FOREIGN KEY (tenant_slug, slot_id) REFERENCES slot(tenant_slug, id),
    FOREIGN KEY (tenant_slug, delivery_id) REFERENCES delivery(tenant_slug, id)
);
INSERT INTO part SELECT * FROM saved_parts;
INSERT INTO event_log SELECT * FROM saved_events;
DROP TABLE saved_parts;
DROP TABLE saved_events;
CREATE TABLE publisher_bucket (
    scope TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL REFERENCES tenant(tenant_slug),
    tokens REAL NOT NULL,
    updated_at TEXT NOT NULL
);
