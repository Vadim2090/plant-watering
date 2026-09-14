"""Environment readings (SPEC.md §5): the `EnvSource` interface, two implementations and the
fallback ladder. Nothing above this module knows which source is live.
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

import requests

log = logging.getLogger("plant.env")

TEMP_RANGE_C = (5.0, 40.0)
RH_RANGE = (10, 95)
LAST_READING_MAX_AGE_DAYS = 7

SOURCE_XIAOMI = "xiaomi_cloud"
SOURCE_WEATHER = "weather"

# MIoT property addresses for zhimi.airp.vb4 (Smart Air Purifier 4 Pro), SPEC §5.1.
XIAOMI_PROPS = {"temperature": (3, 7), "relative_humidity": (3, 1), "on": (2, 1)}
XIAOMI_MODEL_PREFIX = "zhimi.airp"

OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
HTTP_TIMEOUT_S = 15


@dataclass(frozen=True)
class Reading:
    temp_c: float
    rh: int
    source: str

    def to_state(self, at: datetime) -> dict:
        d: dict[str, Any] = asdict(self)
        d["at"] = at.isoformat(timespec="seconds")
        return d


class EnvSourceError(Exception):
    pass


class EnvSource(ABC):
    name: str = "abstract"

    @abstractmethod
    def read(self) -> Reading | None:
        """A reading, or None when the source is unreachable. Never raises."""


# ---------------------------------------------------------------------------------------------
# Validation and the indoor estimate - pure, tested directly
# ---------------------------------------------------------------------------------------------


def is_valid_reading(temp_c: float, rh: float) -> bool:
    return TEMP_RANGE_C[0] <= temp_c <= TEMP_RANGE_C[1] and RH_RANGE[0] <= rh <= RH_RANGE[1]


def outdoor_to_indoor(outdoor_mean_c: float, outdoor_rh: float) -> tuple[float, int]:
    """SPEC §5.2. Crude, and labelled as such everywhere it surfaces."""
    if outdoor_mean_c >= 18:
        indoor_c = outdoor_mean_c + 2  # warm flat, windows open
    else:
        indoor_c = 22.0  # heating season, thermostat wins
    if outdoor_mean_c < 12:
        indoor_rh = 35  # central heating dries the air
    else:
        indoor_rh = int(round(max(35, min(65, outdoor_rh))))
    return indoor_c, indoor_rh


# ---------------------------------------------------------------------------------------------
# §5.1 Xiaomi cloud
# ---------------------------------------------------------------------------------------------


def _mask(s: str | None) -> str:
    """For logs. Never print a device id, a username or a token."""
    if not s:
        return "<none>"
    return f"{s[:2]}...({len(s)} chars)"


XIAOMI_SERVICE_LOGIN = "https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true"


def xiaomi_login(username: str | None, password: str | None, user_id: str | None = None,
                 pass_token: str | None = None):
    """A logged-in `MiCloud`, or None.

    Two paths. A stored `passToken` (from one earlier interactive login) is tried first: it needs
    no password and never triggers Xiaomi's login captcha, which is what a headless VPS needs.
    The account password is the fallback, and the only path when no token is stored.
    """
    from micloud import MiCloud  # imported lazily: tests never need it

    cloud = MiCloud(username or "token-login", password or "token-login")
    if user_id and pass_token:
        try:
            cloud._init_session()
            cloud.session.cookies.update({"userId": str(user_id), "passToken": pass_token})
            r = cloud.session.get(XIAOMI_SERVICE_LOGIN, timeout=HTTP_TIMEOUT_S)
            j = json.loads(r.text.replace("&&&START&&&", ""))
            if j.get("code") == 0 and j.get("location"):
                cloud.user_id = str(j.get("userId") or user_id)
                cloud.ssecurity = j.get("ssecurity")
                cloud.cuser_id = j.get("cUserId")
                cloud.pass_token = j.get("passToken") or pass_token
                r3 = cloud._login_step3(j["location"])
                if r3.status_code == 200 and cloud.service_token:
                    return cloud
            log.warning("xiaomi passToken login rejected (code %s) - token expired? falling back to password",
                        j.get("code"))
        except Exception as e:
            log.warning("xiaomi passToken login failed: %s", type(e).__name__)
    if not (username and password):
        return None
    try:
        if cloud.login():
            return cloud
    except Exception as e:  # micloud raises its own exceptions on bad credentials or a captcha demand
        log.warning("xiaomi password login failed: %s", type(e).__name__)
    return None


class XiaomiCloudSource(EnvSource):
    name = SOURCE_XIAOMI

    def __init__(self, username: str | None, password: str | None, region: str, device_id: str,
                 user_id: str | None = None, pass_token: str | None = None):
        self.username = username
        self.password = password
        self.region = region
        self.device_id = device_id
        self.user_id = user_id
        self.pass_token = pass_token
        self._cloud = None

    def _login(self) -> bool:
        self._cloud = xiaomi_login(self.username, self.password, self.user_id, self.pass_token)
        return self._cloud is not None

    def _fetch_props(self) -> dict[str, Any]:
        params = [{"did": self.device_id, "siid": siid, "piid": piid} for siid, piid in XIAOMI_PROPS.values()]
        raw = self._cloud.request_country(
            "/miotspec/prop/get", self.region, {"data": json.dumps({"params": params})}
        )
        payload = json.loads(raw)
        if payload.get("code", 0) != 0:
            raise EnvSourceError(f"miot prop/get returned code {payload.get('code')}")
        out: dict[str, Any] = {}
        for item in payload.get("result", []):
            if item.get("code", 0) != 0:
                continue
            for key, (siid, piid) in XIAOMI_PROPS.items():
                if item.get("siid") == siid and item.get("piid") == piid:
                    out[key] = item.get("value")
        return out

    def read(self) -> Reading | None:
        # Log in once and keep the session; on failure re-login once, with a backoff.
        for attempt in range(2):
            try:
                if self._cloud is None and not self._login():
                    if attempt == 0:
                        time.sleep(5)
                        continue
                    return None
                props = self._fetch_props()
                temp = props.get("temperature")
                rh = props.get("relative_humidity")
                if temp is None or rh is None:
                    log.warning("xiaomi read returned no temperature/humidity (device off or region wrong)")
                    return None
                return Reading(temp_c=float(temp), rh=int(round(float(rh))), source=self.name)
            except Exception as e:
                log.warning("xiaomi read failed (attempt %d): %s", attempt + 1, type(e).__name__)
                self._cloud = None  # force a fresh login next time round
                if attempt == 0:
                    time.sleep(5)
        return None


def list_xiaomi_devices(username: str | None, password: str | None, region: str,
                        user_id: str | None = None, pass_token: str | None = None) -> list[dict]:
    """Devices on the account, for onboarding. Empty list on a wrong region - not an error."""
    cloud = xiaomi_login(username, password, user_id, pass_token)
    if cloud is None:
        raise EnvSourceError("login failed")
    devices = cloud.get_devices(country=region) or []
    return [
        {
            "did": str(d.get("did")),
            "name": d.get("name") or "",
            "model": d.get("model") or "",
            "online": bool(d.get("isOnline", False)),
        }
        for d in devices
    ]


def pick_purifier(devices: list[dict]) -> dict | None:
    """The Air Purifier 4 Pro if there is one; otherwise the only device; otherwise None."""
    purifiers = [d for d in devices if d["model"].startswith(XIAOMI_MODEL_PREFIX)]
    if len(purifiers) == 1:
        return purifiers[0]
    if purifiers:
        online = [d for d in purifiers if d["online"]]
        return (online or purifiers)[0]
    if len(devices) == 1:
        return devices[0]
    return None


# ---------------------------------------------------------------------------------------------
# §5.2 Open-Meteo fallback
# ---------------------------------------------------------------------------------------------


class WeatherSource(EnvSource):
    name = SOURCE_WEATHER

    def __init__(self, latitude: float, longitude: float, session: Optional[requests.Session] = None):
        self.latitude = latitude
        self.longitude = longitude
        self.session = session or requests.Session()

    def read(self) -> Reading | None:
        try:
            r = self.session.get(
                OPEN_METEO_FORECAST,
                params={
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "daily": "temperature_2m_mean,relative_humidity_2m_mean",
                    "timezone": "auto",
                    "past_days": 1,
                    "forecast_days": 1,
                },
                timeout=HTTP_TIMEOUT_S,
            )
            r.raise_for_status()
            daily = r.json()["daily"]
            temps = [v for v in daily["temperature_2m_mean"] if v is not None]
            rhs = [v for v in daily["relative_humidity_2m_mean"] if v is not None]
            if not temps or not rhs:
                return None
            # yesterday's completed mean is the most honest number; fall back to today's forecast
            indoor_c, indoor_rh = outdoor_to_indoor(float(temps[0]), float(rhs[0]))
            return Reading(temp_c=round(indoor_c, 1), rh=indoor_rh, source=self.name)
        except Exception as e:
            log.warning("weather read failed: %s", type(e).__name__)
            return None


def geocode_city(name: str, session: Optional[requests.Session] = None) -> dict | None:
    """Open-Meteo geocoding. Returns {name, country, admin1, latitude, longitude} or None."""
    s = session or requests.Session()
    try:
        r = s.get(OPEN_METEO_GEOCODE, params={"name": name, "count": 1, "language": "en", "format": "json"},
                  timeout=HTTP_TIMEOUT_S)
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None
        hit = results[0]
        return {
            "name": hit.get("name", name),
            "country": hit.get("country", ""),
            "admin1": hit.get("admin1", ""),
            "latitude": float(hit["latitude"]),
            "longitude": float(hit["longitude"]),
        }
    except Exception as e:
        log.warning("geocode failed: %s", type(e).__name__)
        return None


# ---------------------------------------------------------------------------------------------
# §5.3 The ladder
# ---------------------------------------------------------------------------------------------


@dataclass
class LadderResult:
    reading: Reading | None
    degraded: bool
    unreachable_since: str | None  # ISO timestamp of the last good reading when degraded
    new_last_reading: dict | None  # what to store in state, or None to leave it alone
    rung: str  # "fresh" | "cached" | "fallback" | "none"


def _parse_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def resolve_reading(
    primary: EnvSource | None,
    fallback: EnvSource | None,
    last_reading: dict | None,
    now: datetime,
    offset_c: float = 0.0,
) -> LadderResult:
    """Apply the §5.3 ladder in order. Never invents data: if every rung fails, `reading` is None."""
    # 1-2. the configured source, validated, offset applied
    if primary is not None:
        raw = primary.read()
        if raw is not None:
            if is_valid_reading(raw.temp_c, raw.rh):
                reading = Reading(temp_c=round(raw.temp_c + offset_c, 1), rh=int(raw.rh), source=raw.source)
                return LadderResult(reading, False, None, reading.to_state(now), "fresh")
            log.warning("discarding out-of-range reading %.1f C / %s%% from %s", raw.temp_c, raw.rh, raw.source)

    # 3. a recent cached reading
    last_at = _parse_at((last_reading or {}).get("at"))
    if last_reading and last_at is not None:
        if last_at.tzinfo is None and now.tzinfo is not None:
            last_at = last_at.replace(tzinfo=now.tzinfo)
        age = now - last_at
        if age < timedelta(days=LAST_READING_MAX_AGE_DAYS):
            reading = Reading(float(last_reading["temp_c"]), int(last_reading["rh"]), last_reading.get("source", "cached"))
            return LadderResult(reading, False, None, None, "cached")

    # 4. the weather fallback - degraded, and said so
    primary_is_weather = primary is not None and primary.name == SOURCE_WEATHER
    if fallback is not None and not primary_is_weather:
        raw = fallback.read()
        if raw is not None and is_valid_reading(raw.temp_c, raw.rh):
            since = (last_reading or {}).get("at")
            # do not overwrite last_reading: it marks when the sensor was last heard from
            return LadderResult(raw, True, since, None, "fallback")

    # 5. nothing. Skip the tick.
    return LadderResult(None, False, (last_reading or {}).get("at"), None, "none")
