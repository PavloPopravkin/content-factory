"""NOAA solar calculator equations, sunset with standard 90.833° refraction correction."""
from datetime import date, datetime, time, timedelta, timezone
import calendar
import math


def sunset(day: date, lat: float, lon: float) -> datetime | None:
    # NOAA's equation-of-time/declination approximation; output is UTC, including date rollover.
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / (366 if calendar.isleap(day.year) else 365) * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma)
                      - 0.032077 * math.sin(gamma) - 0.014615 * math.cos(2 * gamma)
                      - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    latitude = math.radians(lat)
    denominator = math.cos(latitude) * math.cos(decl)
    if abs(denominator) < 1e-12:
        return None
    cos_hour = (math.cos(math.radians(90.833)) / denominator
                - math.tan(latitude) * math.tan(decl))
    if not -1 <= cos_hour <= 1:
        return None
    minutes = 720 - 4 * lon - eqtime + 4 * math.degrees(math.acos(cos_hour))
    return datetime.combine(day, time(), timezone.utc) + timedelta(minutes=minutes)
