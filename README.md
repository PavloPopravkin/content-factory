# Content Factory

A Python 3.12 core for tenant-isolated content planning and publishing. Phase 1 includes tenant config,
SQLite storage, deterministic admission, a delivery journal, publisher adapters and a CLI.
See [ARCHITECTURE.md](ARCHITECTURE.md) and [MANIFEST.md](MANIFEST.md) for the product direction.

## Quick start

Requires Python 3.12+ on Linux or macOS. No social accounts, API keys, ffmpeg or external services are needed
for this dry demonstration. Run from the repository root on a fresh checkout:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
mkdir -p tenants
cp -R examples/tenants/demo tenants/demo
export CF_DB=.cf/demo.sqlite3

# Disable blackout only in this local dry-only copy so the demo works on any weekday.
python - <<'PY'
from pathlib import Path
import yaml
path = Path('tenants/demo/tenant.yaml')
config = yaml.safe_load(path.read_text())
assert all(channel['publisher'] == 'dry' for channel in config['channels'])
config['schedule']['blackout'] = []
path.write_text(yaml.safe_dump(config, sort_keys=False))
PY

cf tenant validate tenants/demo/tenant.yaml
cf db migrate
SLOT_ID=$(cf slot add --tenant demo \
  --at "$(python -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).isoformat())')" \
  --kind post --channels demo-feed --caption 'Hello from Content Factory')
cf slot approve "$SLOT_ID"
cf tick --tenant demo
cf status --tenant demo
cf tick --tenant demo
pytest -q
```

The first tick prints a `DRY` log and `published=1`. The second prints `published=0` and `skipped=1`.
The full example in `examples/tenants/demo/` retains both weekly and sunset blackout rules.
A normal tenant must keep its blackout policy enabled. No worker or cron is installed by these commands.

## CLI

Global options precede the command. `--db` / `CF_DB` defaults to `.cf/content_factory.sqlite3`;
`--tenants-root` / `CF_TENANTS_ROOT` defaults to `tenants`.

```sh
cf tenant validate tenants/demo/tenant.yaml
cf db migrate
cf slot add --tenant demo --at '2026-10-26T10:00:00+02:00' --kind post \
  --channels demo-feed --caption 'A caption' --media ./photo.jpg --media ./second.jpg
cf slot approve SLOT_ID --tenant demo
cf slot cancel SLOT_ID --tenant demo
cf tick --tenant demo
cf status --tenant demo
```

`--channels` accepts comma-separated channel IDs. Repeat `--media` for local paths or HTTP(S) URLs.
Times must contain a UTC offset. Cancel stops unsent channels and retains published objects and their ledger.
Approval/cancel infer the tenant from the globally unique slot ID if `--tenant` is omitted. This local operator
CLI is not an authentication or authorization service.

## Configuration and admission

`tenants/<slug>/tenant.yaml` uses `schema_version: 1`; unknown fields, invalid timezones, malformed hours,
missing/escaping policy files, duplicate channels and incompatible publishers fail validation.
Languages use lists for `content` and `contributors` and a string for `ops`.
Secrets are environment variable references such as `secret_ref: FOUNDATION_TELEGRAM_TOKEN`, never tokens in YAML.
The `dry` publisher accepts the same config shape but does not read its secret reference.

`admit(slot, tenant, existing)` is pure and returns `[]` or human-readable violations. Working hours and weekly
blackout are start-inclusive/end-exclusive in the tenant's IANA timezone. Hours can cross midnight;
`["00:00", "24:00"]` means all day. Daily caps count slots per kind, once across their channels.
Minimum gaps apply between all publication kinds and use elapsed UTC time across DST changes.
Multiple images/videos in a `post` require the channel's `carousel` capability.
Manual approval, or a kind-specific approval requirement, binds to the exact slot version.
`Store.revise()` increments the version and clears approval; slots with an existing delivery cannot be revised.

Sunset blackout uses the offline [NOAA solar equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF),
from Friday sunset minus `margin_before_min` to Saturday sunset plus `margin_after_min`.
These are approximate astronomical sunsets with standard refraction, not a religious calendar service.
At polar coordinates without a sunset, admission fails closed. Tests cover Kyiv, Charlotte, UTC date rollover,
and the spring/autumn DST changes in Kyiv and New York.

The Markdown policy is required and available for future curator work. Phase 1 does not interpret prose as
executable rules or check consent/content facts; deterministic rules come from the validated YAML.

## Storage and delivery semantics

Plain SQL in `migrations/NNN_*.sql` is applied in order with checksums and a transaction per migration.
Migrations ship inside the wheel. SQLite uses WAL, foreign keys and a database-wide POSIX file lock for ticks,
migrations and CLI mutations. Every table has `tenant_slug NOT NULL`; all domain links use composite tenant FKs.
`schema_migrations` is global metadata with reserved scope `__schema__`.

A committed `submitting` delivery with a unique key is written **before** the adapter's first HTTP request.
The `(tenant, slot, channel)` fence also prevents a later version from silently republishing the same slot.
Every returned message/story/media ID is checkpointed as a part as soon as it is known, including IDs from
an incomplete multi-request publication. Event records and checkpoints commit atomically.

- `accepted` means the provider accepted asynchronous work, not that a social object is live.
- `published` is terminal and is never resent.
- A timeout, connection loss, malformed response or ambiguous server error becomes `unknown`.
- An interrupted `submitting` fence becomes `unknown` on the next tick.
- Existing deliveries, including `failed` and `unknown`, are never automatically submitted again.
- Tick reconciles `accepted`/`unknown` through read-only adapter hooks when it can identify the external job.
  Telegram lost responses and Meta responses without final IDs need manual verification. No ID is invented.

Admission runs at actual send time, against attempted publication history, before **each HTTP request**.
Attempted/uncertain/failed slots conservatively consume caps and gaps; queued slots do not deadlock one another.
Read-only reconciliation also respects blackout. If blackout or cancellation interrupts a sequence, known parts
remain in the journal and the delivery stays uncertain. A remote job already accepted may finish independently;
the factory cannot recall it by applying a later blackout.

A verified failed publication can be replaced by a new slot after operator review. There is deliberately no
blind retry or manual resolution CLI in phase 1. Inspect `cf status` and the journal before replacing a slot.

## Publisher adapters

All requests use synchronous `httpx`, explicit 30-second timeouts, no transport retries, and no redirect following
in the scheduler. Errors are typed exceptions. Provider errors omit request bodies, credentials and token-bearing
URLs. Inject an `httpx.Client`, gate and checkpoint callback for tests or embedding; use tick for journaled sends.

| Adapter | Implemented | Configuration / limits |
| --- | --- | --- |
| `dry` | Log and record a deterministic fake published part | No credentials or network |
| `telegram` | Text, photo, video, mixed albums, deletion of each message | `tg_channel`; bot token in `secret_ref`; `external_id` is chat ID |
| `meta` | FB text/photos/carousel, feed video, three-phase Reels and video Stories, photo Stories; IG image/carousel/Reel/Story with bounded status polling; reconcile and delete | `fb_page` or FB-linked `ig`; Page token in `secret_ref`; `CF_META_GRAPH_VERSION` defaults to `v25.0` |
| `postiz` | File/URL upload, create `type: now` for one integration, read state and release IDs | `CF_POSTIZ_URL=https://your-host`; org key in `secret_ref`; `external_id` is integration ID |

Telegram albums require 2-10 items; one item uses `sendPhoto`/`sendVideo`. Captions over 1024 characters are
sent first as separate plain-text messages (split at 4096). Every message ID is recorded. Video dimensions and
duration use stored metadata or local `ffprobe` when available. Remote media is not probed over the network.

Meta video upload sessions and IG containers are checkpointed before proceeding. IG defaults to five polls at
60-second intervals; exhaustion stops with `unknown`. FB video upload/finish returns `accepted`; reconciliation
requires explicit publication status, rather than treating a merely processed video as published. IG Reel/Story
uses one media item per slot; FB supports multiple stories and records each part. Meta URL-based photo/IG uploads
need externally accessible publishing derivatives. This package does not expose local originals publicly.

Postiz uses `/api/public/v1` and `Authorization: <key>` without `Bearer`, as in the
[Public API contract](https://docs.postiz.com/public-api/posts/create). `PUBLISHED` requires a `releaseId`;
`ERROR` maps to failed; unrecognized states remain unknown. FB Reels require the direct Meta adapter.
Optional non-secret `channel.settings` passes provider DTO fields through to Postiz. For example, YouTube needs
`title` and `type`; TikTok needs its provider settings including `content_posting_method: DIRECT_POST`.
Postiz's DELETE API removes the internal schedule, not a published social object, so `delete(part)` explicitly
raises `UnsupportedOperation` in that adapter.

## Verification and scope

```sh
python -m pip install -e '.[dev]'
pytest -q
```

The suite mocks HTTP with respx and rejects unregistered requests. It covers policy boundaries, tenant FKs,
migrations/rollback, versioned approval, durable partial sends, timeout recovery, lock exclusion, adapters and CLI.
**No real social API publication has been tested.** App permissions, provider-specific media requirements and
production smoke tests remain deployment work. This is a deterministic core, not a production service yet.

AI curator, ingress bot, admin UI, OAuth onboarding, media rendering, private object storage, webhook processing,
notifications, automatic retries and operator reconciliation UI are outside phase 1. No fake implementation of
these features is exposed. See [DEBT.md](DEBT.md) for follow-up work.

## License

MIT. Postiz is a separate AGPL-3.0 project used through its public API, not modified or bundled.
