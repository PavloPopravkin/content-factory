from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from content_factory.config import load_tenant
from content_factory.models import Asset, Delivery, Slot
from content_factory.storage import Store


@pytest.fixture(autouse=True)
def offline_http(respx_mock):
    # respx rejects every unregistered HTTP request, even in tests that forgot to opt in.
    yield respx_mock


@pytest.fixture
def tenant():
    config = load_tenant(Path(__file__).parents[1] / "examples/tenants/demo/tenant.yaml")
    config.schedule.blackout = []
    config.schedule.min_gap_minutes = 0
    config.approval.mode = "auto"
    config.approval.require_for_kinds = []
    return config


@pytest.fixture
def now():
    return datetime(2026, 10, 25, 10, tzinfo=timezone.utc)


@pytest.fixture
def slot(tenant, now):
    return Slot(tenant_slug=tenant.slug, at=now, kind="post", channel_ids=[tenant.channels[0].id], caption="Hello")


@pytest.fixture
def delivery(slot):
    return Delivery(tenant_slug=slot.tenant_slug, slot_id=slot.id, channel_id=slot.channel_ids[0], delivery_key="test-key")


@pytest.fixture
def store(tmp_path, tenant):
    with Store(tmp_path / "factory.sqlite3") as db:
        db.migrate()
        db.register(tenant)
        yield db


@pytest.fixture
def photo(tenant):
    return Asset(tenant_slug=tenant.slug, source="https://media.test/photo.jpg", kind="photo")


@pytest.fixture
def video(tenant):
    return Asset(tenant_slug=tenant.slug, source="https://media.test/video.mp4", kind="video", width=1080, height=1920, duration=12)


@pytest.fixture
def client():
    with httpx.Client(timeout=1, trust_env=False) as client:
        yield client
