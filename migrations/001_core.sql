CREATE TABLE tenant (
    tenant_slug TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    config TEXT NOT NULL CHECK(json_valid(config))
);
CREATE TABLE channel (
    tenant_slug TEXT NOT NULL REFERENCES tenant(tenant_slug),
    id TEXT NOT NULL,
    config TEXT NOT NULL CHECK(json_valid(config)),
    PRIMARY KEY (tenant_slug, id)
);
CREATE TABLE asset (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL REFERENCES tenant(tenant_slug),
    data TEXT NOT NULL CHECK(json_valid(data)),
    UNIQUE (tenant_slug, id)
);
CREATE TABLE slot (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL REFERENCES tenant(tenant_slug),
    at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('post','reel','story')),
    caption TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    approved_version INTEGER CHECK(approved_version <= version),
    cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)),
    UNIQUE (tenant_slug, id)
);
CREATE INDEX slot_due ON slot(tenant_slug, at);
CREATE TABLE slot_channel (
    tenant_slug TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    PRIMARY KEY (tenant_slug, slot_id, channel_id),
    FOREIGN KEY (tenant_slug, slot_id) REFERENCES slot(tenant_slug, id),
    FOREIGN KEY (tenant_slug, channel_id) REFERENCES channel(tenant_slug, id)
);
CREATE TABLE slot_asset (
    tenant_slug TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (tenant_slug, slot_id, asset_id),
    UNIQUE (tenant_slug, slot_id, position),
    FOREIGN KEY (tenant_slug, slot_id) REFERENCES slot(tenant_slug, id),
    FOREIGN KEY (tenant_slug, asset_id) REFERENCES asset(tenant_slug, id)
);
CREATE TABLE delivery (
    id TEXT PRIMARY KEY NOT NULL,
    tenant_slug TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('submitting','accepted','published','failed','unknown')),
    attempts INTEGER NOT NULL CHECK(attempts >= 1),
    external_ids TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(external_ids)),
    error TEXT,
    delivery_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE (tenant_slug, id),
    UNIQUE (tenant_slug, slot_id, channel_id),
    FOREIGN KEY (tenant_slug, slot_id, channel_id) REFERENCES slot_channel(tenant_slug, slot_id, channel_id)
);
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
