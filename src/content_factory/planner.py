from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import SunsetShabbat, Tenant, WeeklyBlackout
from .models import Kind, Slot
from .solar import sunset

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _weekly_minute(value: str) -> int:
    day, hm = value.split()
    h, m = map(int, hm.split(":"))
    return DAYS.index(day) * 1440 + h * 60 + m


def blackout_violations(at: datetime, tenant: Tenant) -> list[str]:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("admission requires an aware datetime")
    local = at.astimezone(ZoneInfo(tenant.timezone))
    utc = at.astimezone(timezone.utc)
    for rule in tenant.schedule.blackout:
        if isinstance(rule, WeeklyBlackout):
            minute = local.weekday() * 1440 + local.hour * 60 + local.minute
            start, end = _weekly_minute(rule.from_), _weekly_minute(rule.to)
            if (start <= minute < end if start < end else minute >= start or minute < end):
                return ["blackout: weekly"]
        elif isinstance(rule, SunsetShabbat):
            # Include adjacent weeks for margins that cross a civil date boundary.
            friday = local.date() - timedelta(days=(local.weekday() - 4) % 7)
            for offset in (-7, 0, 7):
                day = friday + timedelta(days=offset)
                start = sunset(day, rule.lat, rule.lon)
                end = sunset(day + timedelta(days=1), rule.lat, rule.lon)
                # Fail closed where a sunset is undefined (polar night/day).
                if start is None or end is None:
                    return ["blackout: sunset unavailable at configured coordinates"]
                if (start - timedelta(minutes=rule.margin_before_min) <= utc
                        < end + timedelta(minutes=rule.margin_after_min)):
                    return ["blackout: sunset_shabbat"]
    return []


def admit(slot: Slot, tenant: Tenant, existing: list[Slot]) -> list[str]:
    """Return [] on admission, otherwise stable human-readable policy violations."""
    if slot.tenant_slug != tenant.slug:
        return ["tenant mismatch"]
    violations = []
    if slot.missed:
        violations.append("slot missed")
    if slot.cancelled:
        violations.append("slot cancelled")
    local = slot.at.astimezone(ZoneInfo(tenant.timezone))
    others = [s for s in existing if s.tenant_slug == tenant.slug and s.id != slot.id and not s.cancelled]
    daily = sum(s.kind == slot.kind and s.at.astimezone(ZoneInfo(tenant.timezone)).date() == local.date()
                for s in others)
    if daily >= tenant.schedule.daily_caps[slot.kind]:
        violations.append(f"daily cap: {slot.kind}")
    # Gaps are elapsed time, not wall-clock subtraction across DST folds.
    if any(
        abs((s.at.astimezone(timezone.utc) - slot.at.astimezone(timezone.utc)).total_seconds())
        < tenant.schedule.min_gap_minutes * 60 for s in others
    ):
        violations.append("minimum gap between posts")
    minute = local.hour * 60 + local.minute
    start, end = (int(x.split(":")[0]) * 60 + int(x.split(":")[1]) for x in tenant.schedule.hours)
    if not (start <= minute < end if start < end else minute >= start or minute < end):
        violations.append("outside working hours")
    violations.extend(blackout_violations(slot.at, tenant))
    for channel_id in slot.channel_ids:
        try:
            channel = tenant.channel(channel_id)
            capability = "carousel" if slot.kind == Kind.POST and len(slot.media_ids) > 1 else slot.kind.value
            if capability not in channel.capabilities:
                violations.append(f"channel {channel_id} lacks capability {capability}")
        except ValueError:
            violations.append(f"unknown channel {channel_id}")
    if ((tenant.approval.mode == "manual" or slot.kind in tenant.approval.require_for_kinds)
            and slot.approved_version != slot.version):
        violations.append("approval required for current version")
    return violations
