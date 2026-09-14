"""Configuration: `.env` load plus loud validation (SPEC.md §3).

A missing required key aborts start-up with a message naming the key. Real environment variables
override the file, so a systemd unit can set anything without touching `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

DEFAULT_ENV_PATH = ".env"

KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "ALLOWED_CHAT_IDS",
    "BOT_LOCALE",
    "XIAOMI_USERNAME",
    "XIAOMI_PASSWORD",
    "XIAOMI_REGION",
    "XIAOMI_DEVICE_ID",
    "XIAOMI_USER_ID",
    "XIAOMI_PASS_TOKEN",
    "PERSONAL_OPENAI_API_KEY",
    "LATITUDE",
    "LONGITUDE",
    "TIMEZONE",
    "ALERT_HOUR",
    "STATE_PATH",
)

XIAOMI_REGIONS = ("de", "cn", "ru", "sg", "us", "i2")
LOCALES = ("en", "ru")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    allowed_chat_ids: frozenset[int]
    bot_locale: str
    xiaomi_username: str | None
    xiaomi_password: str | None
    xiaomi_region: str
    xiaomi_device_id: str | None
    xiaomi_user_id: str | None
    xiaomi_pass_token: str | None
    openai_api_key: str | None
    latitude: float
    longitude: float
    timezone: str
    alert_hour: int
    state_path: str

    @property
    def has_xiaomi(self) -> bool:
        """Either login path: account password, or a stored passToken (no captcha, no password)."""
        return bool(self.xiaomi_username and self.xiaomi_password) or self.has_xiaomi_token

    @property
    def has_xiaomi_token(self) -> bool:
        return bool(self.xiaomi_user_id and self.xiaomi_pass_token)

    @property
    def has_vision(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def photo_dir(self) -> Path:
        return Path(self.state_path).parent / "photos"

    def is_allowed(self, chat_id: int) -> bool:
        return not self.allowed_chat_ids or chat_id in self.allowed_chat_ids


def parse_env_file(path: str | os.PathLike) -> dict[str, str]:
    """Minimal dotenv: `KEY=value`, optional `export`, `#` comments, single or double quotes."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return out
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            # strip an inline comment on unquoted values
            hash_at = value.find(" #")
            if hash_at >= 0:
                value = value[:hash_at].rstrip()
        out[key] = value
    return out


def _opt(values: Mapping[str, str], key: str) -> str | None:
    v = values.get(key, "").strip()
    return v or None


def build_config(values: Mapping[str, str]) -> Config:
    token = _opt(values, "TELEGRAM_BOT_TOKEN")
    if not token:
        raise ConfigError("TELEGRAM_BOT_TOKEN is required (get one from @BotFather) - put it in .env")

    allowed: set[int] = set()
    for part in (values.get("ALLOWED_CHAT_IDS") or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            allowed.add(int(part))
        except ValueError as e:
            raise ConfigError(f"ALLOWED_CHAT_IDS must be comma-separated integers, got {part!r}") from e

    locale = (_opt(values, "BOT_LOCALE") or "en").lower()
    if locale not in LOCALES:
        raise ConfigError(f"BOT_LOCALE must be one of {LOCALES}, got {locale!r}")

    region = (_opt(values, "XIAOMI_REGION") or "de").lower()
    if region not in XIAOMI_REGIONS:
        raise ConfigError(f"XIAOMI_REGION must be one of {XIAOMI_REGIONS}, got {region!r}")

    username = _opt(values, "XIAOMI_USERNAME")
    password = _opt(values, "XIAOMI_PASSWORD")
    if bool(username) != bool(password):
        raise ConfigError("XIAOMI_USERNAME and XIAOMI_PASSWORD must be set together")
    user_id = _opt(values, "XIAOMI_USER_ID")
    pass_token = _opt(values, "XIAOMI_PASS_TOKEN")
    if bool(user_id) != bool(pass_token):
        raise ConfigError("XIAOMI_USER_ID and XIAOMI_PASS_TOKEN must be set together")

    def _float(key: str, default: float) -> float:
        v = _opt(values, key)
        if v is None:
            return default
        try:
            return float(v)
        except ValueError as e:
            raise ConfigError(f"{key} must be a number, got {v!r}") from e

    lat = _float("LATITUDE", 44.8)
    lon = _float("LONGITUDE", 20.5)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ConfigError("LATITUDE/LONGITUDE out of range")

    hour_raw = _opt(values, "ALERT_HOUR")
    try:
        hour = int(hour_raw) if hour_raw is not None else 9
    except ValueError as e:
        raise ConfigError(f"ALERT_HOUR must be an integer 0-23, got {hour_raw!r}") from e
    if not 0 <= hour <= 23:
        raise ConfigError(f"ALERT_HOUR must be 0-23, got {hour}")

    tz = _opt(values, "TIMEZONE") or "Europe/Belgrade"
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(tz)
    except Exception as e:  # ZoneInfoNotFoundError or a missing tzdata
        raise ConfigError(f"TIMEZONE {tz!r} is not a known IANA zone") from e

    return Config(
        telegram_bot_token=token,
        allowed_chat_ids=frozenset(allowed),
        bot_locale=locale,
        xiaomi_username=username,
        xiaomi_password=password,
        xiaomi_region=region,
        xiaomi_device_id=_opt(values, "XIAOMI_DEVICE_ID"),
        xiaomi_user_id=user_id,
        xiaomi_pass_token=pass_token,
        openai_api_key=_opt(values, "PERSONAL_OPENAI_API_KEY"),
        latitude=lat,
        longitude=lon,
        timezone=tz,
        alert_hour=hour,
        state_path=_opt(values, "STATE_PATH") or "data/state.json",
    )


def load_config(env_path: str | os.PathLike = DEFAULT_ENV_PATH, environ: Mapping[str, str] | None = None) -> Config:
    """`.env` first, then the process environment on top."""
    values = parse_env_file(env_path)
    env = os.environ if environ is None else environ
    for key in KEYS:
        if key in env and env[key] != "":
            values[key] = env[key]
    return build_config(values)
