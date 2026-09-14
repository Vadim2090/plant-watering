"""Fakes for the handler tests: a fixed clock, a capturing `send`, scripted env sources."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import build_config
from context import AppContext
from env_source import EnvSource, Reading
from locales import get_strings
from state import State, new_plant

TZ = ZoneInfo("Europe/Belgrade")
CHAT = 42


class FakeSource(EnvSource):
    def __init__(self, name: str, readings=None):
        self.name = name
        self.readings = list(readings or [])
        self.calls = 0

    def read(self):
        self.calls += 1
        if not self.readings:
            return None
        r = self.readings.pop(0)
        return r


class Sent:
    def __init__(self):
        self.messages: list[tuple[int, str, object]] = []
        self.cleared: list[tuple[int, int]] = []
        self.fail = False  # simulate Telegram refusing delivery: send returns None

    def __call__(self, chat_id, text, keyboard=None):
        if self.fail:
            return None
        self.messages.append((chat_id, text, keyboard))
        return len(self.messages)

    def clear(self, chat_id, message_id):
        self.cleared.append((chat_id, message_id))

    @property
    def texts(self):
        return [m[1] for m in self.messages]

    @property
    def last(self):
        return self.messages[-1]

    def buttons(self, index=-1):
        kb = self.messages[index][2] or []
        return [data for row in kb for _, data in row]


class Clock:
    def __init__(self, when: datetime):
        self.when = when

    def __call__(self):
        return self.when

    def advance(self, **kw):
        self.when += timedelta(**kw)


def make_config(**overrides):
    values = {"TELEGRAM_BOT_TOKEN": "test-token", "ALLOWED_CHAT_IDS": str(CHAT)}
    values.update(overrides)
    return build_config(values)


def make_ctx(tmp_path, now: datetime | None = None, primary: EnvSource | None = None,
             fallback: EnvSource | None = None, config=None, vision=None, probe=None) -> tuple[AppContext, Sent, Clock]:
    config = config or make_config(STATE_PATH=str(tmp_path / "state.json"))
    clock = Clock(now or datetime(2026, 7, 15, 9, 0, tzinfo=TZ))
    sent = Sent()
    state = State.load(config.state_path)
    ctx = AppContext(
        config=config,
        state=state,
        strings=get_strings(config.bot_locale),
        send=sent,
        now=clock,
        make_primary_source=lambda env: primary,
        fallback_source=fallback,
        clear_buttons=sent.clear,
        vision=vision,
        save_photo=lambda chat_id, plant_id, jpeg: f"{tmp_path}/photos/{chat_id}/{plant_id}.jpg",
        probe_xiaomi=probe,
    )
    return ctx, sent, clock


def seed_user(ctx: AppContext, S: float = 0.6, B: float = 0.058, last_watered: date | None = None,
              last_tick: date | None = None, last_reading: dict | None = None, source_type="xiaomi_cloud",
              light="medium") -> dict:
    """A fully onboarded user with one plant, in state."""
    today = ctx.today()
    last_watered = last_watered or (today - timedelta(days=8))
    last_tick = last_tick or (today - timedelta(days=1))
    user = ctx.state.ensure_user(CHAT, "en", ctx.now())
    user["onboarding"] = {"step": "done", "draft": {}}
    user["env_source"] = {"type": source_type, "device_id": "1" if source_type == "xiaomi_cloud" else None,
                          "offset_c": 0.0, "city": None, "last_reading": last_reading}
    setup = {"pot_material": "plastic", "pot_diameter_cm": 25, "substrate": "potting_soil", "fit": "balanced",
             "light": light, "reported_interval_days": None}
    plant = new_plant("monstera-1", "Monstera", "monstera_deliciosa", setup, B, S,
                      last_watered.isoformat(), last_tick.isoformat(), None)
    plant["history"].append({"date": last_watered.isoformat(), "event": "watered", "via": "setup"})
    user["plants"] = [plant]
    ctx.state.save()
    return user


def reading(temp=24.0, rh=47, source="xiaomi_cloud"):
    return Reading(temp_c=temp, rh=rh, source=source)
