from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from content_factory.config import SunsetShabbat, WeeklyBlackout
from content_factory.models import Kind
from content_factory.planner import admit, blackout_violations
from content_factory.solar import sunset


def test_admitted_is_pure(tenant, slot):
    before = slot.model_dump_json(), tenant.model_dump_json(by_alias=True)
    assert admit(slot, tenant, []) == []
    assert (slot.model_dump_json(), tenant.model_dump_json(by_alias=True)) == before


@pytest.mark.parametrize("kind", list(Kind))
def test_daily_cap(tenant, slot, kind):
    tenant.schedule.daily_caps[kind] = 1
    slot.kind = kind
    existing = slot.model_copy(update={"id": "other"})
    assert f"daily cap: {kind}" in admit(slot, tenant, [existing])
    assert admit(slot, tenant, [slot]) == []
    assert admit(slot, tenant, [existing.model_copy(update={"tenant_slug": "other"})]) == []
    assert admit(slot, tenant, [existing.model_copy(update={"cancelled": True})]) == []


def test_daily_cap_uses_local_day(tenant, slot):
    tenant.schedule.daily_caps[Kind.POST] = 1
    slot.at = datetime.fromisoformat("2026-06-01T22:30:00+00:00")  # June 2 Kyiv.
    yesterday = slot.model_copy(update={"id": "other", "at": datetime.fromisoformat("2026-06-01T20:30:00+00:00")})
    assert admit(slot, tenant, [yesterday]) == []
    today = yesterday.model_copy(update={"at": datetime.fromisoformat("2026-06-02T10:00:00+00:00")})
    assert "daily cap: post" in admit(slot, tenant, [today])


@pytest.mark.parametrize("zone,day,start,end", [
    ("Europe/Kyiv", "2026-03-29", "00:30", "20:30"),
    ("Europe/Kyiv", "2026-10-25", "00:30", "21:30"),
    ("America/New_York", "2026-03-08", "06:30", "23:30"),
    ("America/New_York", "2026-11-01", "05:30", "23:30"),
])
def test_caps_on_dst_change_days(tenant, slot, zone, day, start, end):
    tenant.timezone = zone
    tenant.schedule.daily_caps[Kind.POST] = 1
    slot.at = datetime.fromisoformat(f"{day}T{start}:00+00:00")
    other = slot.model_copy(update={"id": "other", "at": datetime.fromisoformat(f"{day}T{end}:00+00:00")})
    assert "daily cap: post" in admit(slot, tenant, [other])


@pytest.mark.parametrize("zone,first,second", [
    ("Europe/Kyiv", "2026-10-25T03:30:00+03:00", "2026-10-25T03:30:00+02:00"),
    ("America/New_York", "2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00"),
    ("Europe/Kyiv", "2026-03-29T02:30:00+02:00", "2026-03-29T04:30:00+03:00"),
])
def test_gap_is_elapsed_across_dst(tenant, slot, zone, first, second):
    tenant.timezone = zone
    slot.at = datetime.fromisoformat(second).astimezone(ZoneInfo(zone))
    other = slot.model_copy(update={"id": "other", "at": datetime.fromisoformat(first).astimezone(ZoneInfo(zone))})
    tenant.schedule.min_gap_minutes = 60
    assert admit(slot, tenant, [other]) == []
    tenant.schedule.min_gap_minutes = 61
    assert "minimum gap between posts" in admit(slot, tenant, [other])


def test_gap_applies_to_every_kind(tenant, slot):
    tenant.schedule.min_gap_minutes = 60
    other = slot.model_copy(update={"id": "other", "kind": Kind.REEL, "at": slot.at - timedelta(minutes=59)})
    assert "minimum gap between posts" in admit(slot, tenant, [other])


@pytest.mark.parametrize("hours,at,allowed", [
    (("09:00", "18:00"), "09:00", True),
    (("09:00", "18:00"), "18:00", False),
    (("22:00", "06:00"), "23:00", True),
    (("22:00", "06:00"), "05:59", True),
    (("22:00", "06:00"), "12:00", False),
    (("00:00", "24:00"), "23:59", True),
])
def test_working_hours(tenant, slot, hours, at, allowed):
    tenant.timezone = "UTC"
    tenant.schedule.hours = hours
    slot.at = datetime.fromisoformat(f"2026-10-25T{at}:00+00:00")
    assert ("outside working hours" not in admit(slot, tenant, [])) == allowed


@pytest.mark.parametrize("at,blocked", [
    ("2026-10-23T14:59:59+03:00", False),
    ("2026-10-23T15:00:00+03:00", True),
    ("2026-10-24T20:59:59+03:00", True),
    ("2026-10-24T21:00:00+03:00", False),
])
def test_weekly_edges(tenant, at, blocked):
    tenant.schedule.blackout = [WeeklyBlackout.model_validate({"type": "weekly", "from": "fri 15:00", "to": "sat 21:00"})]
    assert bool(blackout_violations(datetime.fromisoformat(at), tenant)) == blocked


def test_weekly_wraps_week(tenant):
    tenant.timezone = "UTC"
    tenant.schedule.blackout = [WeeklyBlackout.model_validate({"type": "weekly", "from": "sun 22:00", "to": "mon 06:00"})]
    assert blackout_violations(datetime.fromisoformat("2026-10-26T05:59:00Z"), tenant)
    assert not blackout_violations(datetime.fromisoformat("2026-10-26T06:00:00Z"), tenant)


@pytest.mark.parametrize("zone,lat,lon,day,expected_utc", [
    ("Europe/Kyiv", 50.4501, 30.5234, date(2026, 10, 23), "2026-10-23T14:53:00+00:00"),
    ("America/New_York", 35.2271, -80.8431, date(2026, 10, 23), "2026-10-23T22:36:00+00:00"),
    ("Europe/Kyiv", 50.4501, 30.5234, date(2026, 6, 19), "2026-06-19T18:13:00+00:00"),
    ("America/New_York", 35.2271, -80.8431, date(2026, 6, 19), "2026-06-20T00:40:00+00:00"),
])
def test_sunset_shabbat_kyiv_charlotte(tenant, zone, lat, lon, day, expected_utc):
    tenant.timezone = zone
    rule = SunsetShabbat(type="sunset_shabbat", lat=lat, lon=lon, margin_before_min=30, margin_after_min=70)
    tenant.schedule.blackout = [rule]
    friday = sunset(day, lat, lon)
    saturday = sunset(day + timedelta(days=1), lat, lon)
    # Independently fixed approximate sunset times; NOAA approximation tolerance 5 minutes.
    assert abs((friday - datetime.fromisoformat(expected_utc)).total_seconds()) < 300
    start = friday - timedelta(minutes=30)
    end = saturday + timedelta(minutes=70)
    assert not blackout_violations(start - timedelta(microseconds=1), tenant)
    assert blackout_violations(start, tenant) == ["blackout: sunset_shabbat"]
    assert blackout_violations(end - timedelta(microseconds=1), tenant)
    assert not blackout_violations(end, tenant)


def test_polar_sunset_fails_closed(tenant, now):
    tenant.schedule.blackout = [SunsetShabbat(type="sunset_shabbat", lat=90, lon=0, margin_before_min=0, margin_after_min=0)]
    assert "sunset unavailable" in blackout_violations(now, tenant)[0]


def test_approval_is_versioned(tenant, slot):
    tenant.approval.mode = "manual"
    assert "approval required for current version" in admit(slot, tenant, [])
    slot.approved_version = slot.version
    assert admit(slot, tenant, []) == []
    slot.version += 1
    assert "approval required for current version" in admit(slot, tenant, [])


def test_kind_specific_approval(tenant, slot):
    tenant.approval.require_for_kinds = [Kind.REEL]
    assert admit(slot, tenant, []) == []
    slot.kind = Kind.REEL
    assert "approval required for current version" in admit(slot, tenant, [])


def test_tenant_cancel_and_capability(tenant, slot):
    slot.tenant_slug = "foreign"
    assert admit(slot, tenant, []) == ["tenant mismatch"]
    slot.tenant_slug = tenant.slug
    slot.cancelled = True
    assert "slot cancelled" in admit(slot, tenant, [])
    slot.cancelled = False
    slot.channel_ids = ["missing"]
    assert admit(slot, tenant, []) == ["unknown channel missing"]
    slot.channel_ids = [tenant.channels[0].id]
    slot.media_ids = ["a", "b"]
    tenant.channels[0].capabilities = ["post"]
    assert admit(slot, tenant, []) == [f"channel {slot.channel_ids[0]} lacks capability carousel"]


def test_rejects_naive_time(tenant):
    with pytest.raises(ValueError, match="aware"):
        blackout_violations(datetime(2026, 10, 25), tenant)
