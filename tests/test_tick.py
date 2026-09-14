"""SPEC.md §12.2 - gate and ladder, through the real tick with fakes."""

from datetime import date, datetime, timedelta

import pytest

import model
from env_source import Reading, is_valid_reading, outdoor_to_indoor, resolve_reading
from tick import run_tick
from tests.helpers import CHAT, TZ, FakeSource, make_ctx, reading, seed_user


def plant_of(ctx):
    return ctx.state.get_user(CHAT)["plants"][0]


def alerts(sent):
    return [m for m in sent.messages if "I think the soil is dry" in m[1]]


# --- gate ------------------------------------------------------------------------------------


def test_no_alert_three_days_after_watering_in_july(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=3))
    run_tick(ctx)
    assert alerts(sent) == []
    assert plant_of(ctx)["pending_alert"] is None


def test_alert_fires_in_july_when_gate_passes(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.3, last_watered=today - timedelta(days=8))
    run_tick(ctx)
    assert len(alerts(sent)) == 1
    p = plant_of(ctx)
    assert p["pending_alert"] is not None
    assert p["history"][-1]["event"] == "alert"
    assert sorted(sent.buttons()) == sorted([f"ans:monstera-1:{a}" for a in model.ANSWERS])
    assert "27 °C and 50%" in sent.last[1]


def test_no_alert_eight_days_after_watering_in_january(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, now=datetime(2026, 1, 15, 9, tzinfo=TZ),
                            primary=FakeSource("xiaomi_cloud", [reading(22, 33)]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=8))
    run_tick(ctx)
    assert alerts(sent) == []


def test_cold_reading_sends_warning_instead_of_alert(tmp_path):
    ctx, sent, clock = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(11, 50), reading(11, 50), reading(11, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12))
    run_tick(ctx)
    assert alerts(sent) == []
    assert any("11 °C" in t and "holding off" in t for t in sent.texts)
    # at most once a week
    clock.advance(days=1)
    run_tick(ctx)
    assert sum(1 for t in sent.texts if "holding off" in t) == 1
    clock.advance(days=7)
    run_tick(ctx)
    assert sum(1 for t in sent.texts if "holding off" in t) == 2


def test_no_alert_inside_away_window_but_S_advances(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    user = seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12))
    user["away"] = {"from": (today - timedelta(days=1)).isoformat(), "to": (today + timedelta(days=5)).isoformat(),
                    "prewarned": False}
    run_tick(ctx)
    assert alerts(sent) == []
    assert plant_of(ctx)["S"] < 0.2


def test_prewarn_the_day_before_an_away_window(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    user = seed_user(ctx, S=0.6, last_watered=today - timedelta(days=3))
    user["away"] = {"from": (today + timedelta(days=1)).isoformat(), "to": (today + timedelta(days=10)).isoformat(),
                    "prewarned": False}
    run_tick(ctx)
    assert any("water it thoroughly before you go" in t.lower() for t in sent.texts)
    assert user["away"]["prewarned"] is True


def test_no_second_alert_while_one_is_pending(tmp_path):
    ctx, sent, clock = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50), reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12))
    run_tick(ctx)
    clock.advance(days=1)
    run_tick(ctx)
    assert len(alerts(sent)) == 1


def test_tick_is_idempotent_within_a_day(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50), reading(27, 50)]))
    seed_user(ctx, S=0.6)
    run_tick(ctx)
    s1 = plant_of(ctx)["S"]
    run_tick(ctx)
    assert plant_of(ctx)["S"] == s1


# --- ladder ----------------------------------------------------------------------------------


def test_out_of_range_reading_is_discarded_and_last_reading_reused(tmp_path):
    now = datetime(2026, 7, 15, 9, tzinfo=TZ)
    ctx, sent, _ = make_ctx(tmp_path, now=now, primary=FakeSource("xiaomi_cloud", [reading(55, 50)]),
                            fallback=FakeSource("weather", [reading(30, 40, "weather")]))
    last = {"temp_c": 24.0, "rh": 47, "at": (now - timedelta(days=2)).isoformat(), "source": "xiaomi_cloud"}
    seed_user(ctx, S=0.2, last_watered=now.date() - timedelta(days=12), last_reading=last)
    report = run_tick(ctx)
    assert "reading:cached" in report[str(CHAT)]
    user = ctx.state.get_user(CHAT)
    assert user["env_source"]["last_reading"] == last  # untouched
    assert "24 °C and 47%" in sent.last[1]
    assert "haven't been able to reach the sensor" not in sent.last[1]


def test_stale_last_reading_falls_back_to_weather_with_notice(tmp_path):
    now = datetime(2026, 7, 15, 9, tzinfo=TZ)
    ctx, sent, _ = make_ctx(tmp_path, now=now, primary=FakeSource("xiaomi_cloud", []),
                            fallback=FakeSource("weather", [reading(29, 45, "weather")]))
    since = now - timedelta(days=8)
    last = {"temp_c": 24.0, "rh": 47, "at": since.isoformat(), "source": "xiaomi_cloud"}
    seed_user(ctx, S=0.2, last_watered=now.date() - timedelta(days=12), last_reading=last)
    report = run_tick(ctx)
    assert "reading:fallback" in report[str(CHAT)]
    text = sent.last[1]
    assert "29 °C and 45%" in text
    assert "haven't been able to reach the sensor since 7 July" in text
    assert plant_of(ctx)["pending_alert"]["degraded"] is True
    # the stale reading still marks when the sensor was last heard from
    assert ctx.state.get_user(CHAT)["env_source"]["last_reading"] == last


def test_both_sources_fail_skips_tick_entirely(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", []), fallback=FakeSource("weather", []))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12), last_tick=today - timedelta(days=1))
    report = run_tick(ctx)
    assert report[str(CHAT)] == ["skipped:no_reading"]
    p = plant_of(ctx)
    assert p["S"] == 0.2
    assert p["last_tick_date"] == (today - timedelta(days=1)).isoformat()
    assert sent.messages == []


def test_fresh_reading_is_stored_with_offset(tmp_path):
    ctx, _, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(24.3, 47)]))
    user = seed_user(ctx, S=0.6)
    user["env_source"]["offset_c"] = -1.0
    run_tick(ctx)
    last = user["env_source"]["last_reading"]
    assert last["temp_c"] == 23.3 and last["rh"] == 47 and last["source"] == "xiaomi_cloud"
    assert last["at"].startswith("2026-07-15T09:00")


def test_weather_configured_user_is_never_flagged_degraded(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]),
                            fallback=FakeSource("weather", [reading(29, 45, "weather")]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12), source_type="weather")
    run_tick(ctx)
    assert "haven't been able to reach" not in sent.last[1]


# --- catch-up --------------------------------------------------------------------------------


def test_process_down_three_days_catches_up(tmp_path):
    ctx, _, _ = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.9, last_watered=today - timedelta(days=4), last_tick=today - timedelta(days=3))
    report = run_tick(ctx)
    assert "monstera-1:advanced:3" in report[str(CHAT)]
    p = plant_of(ctx)
    D = model.daily_depletion(0.058, 27, 50, 15.3)
    assert p["S"] == pytest.approx(0.9 - 3 * D, abs=0.01)
    assert p["last_tick_date"] == today.isoformat()


def test_missed_tick_detection(tmp_path):
    from tick import missed_tick
    ctx, _, clock = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud"))
    today = ctx.today()
    seed_user(ctx, last_tick=today)
    assert missed_tick(ctx, clock()) is False
    clock.advance(days=1)  # 09:00 next day: the scheduled tick is today, last was yesterday
    assert missed_tick(ctx, clock()) is True
    clock.when = clock.when.replace(hour=7)  # before ALERT_HOUR: yesterday's tick is the last scheduled
    assert missed_tick(ctx, clock()) is False


# --- pure ladder pieces ----------------------------------------------------------------------


def test_is_valid_reading_bounds():
    assert is_valid_reading(5, 10) and is_valid_reading(40, 95)
    assert not is_valid_reading(4.9, 50) and not is_valid_reading(41, 50)
    assert not is_valid_reading(22, 9) and not is_valid_reading(22, 96)


def test_outdoor_to_indoor():
    assert outdoor_to_indoor(25, 70) == (27, 65)
    assert outdoor_to_indoor(14, 80) == (22, 65)
    assert outdoor_to_indoor(-2, 85) == (22, 35)
    assert outdoor_to_indoor(20, 20) == (22, 35)


def test_resolve_reading_without_any_source_returns_none():
    r = resolve_reading(None, None, None, datetime(2026, 7, 15, tzinfo=TZ))
    assert r.reading is None and r.rung == "none"


# --- review fixes (Codex pass, 2026-09-13) ---------------------------------------------------


def test_undelivered_alert_leaves_no_pending_and_retries_next_tick(tmp_path):
    ctx, sent, clock = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50), reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12))
    sent.fail = True
    report = run_tick(ctx)
    assert "monstera-1:alert_send_failed" in report[str(CHAT)]
    p = plant_of(ctx)
    assert p["pending_alert"] is None and not any(h["event"] == "alert" for h in p["history"])
    sent.fail = False
    clock.advance(days=1)
    run_tick(ctx)
    assert len(alerts(sent)) == 1 and plant_of(ctx)["pending_alert"] is not None


def test_watering_before_the_tick_does_not_lose_days_from_the_fresh_pot(tmp_path):
    import commands
    ctx, sent, clock = make_ctx(tmp_path, now=datetime(2026, 7, 15, 7, 30, tzinfo=TZ),
                                primary=FakeSource("xiaomi_cloud", [reading(27, 50), reading(27, 50)]))
    today = ctx.today()
    seed_user(ctx, S=0.3, last_watered=today - timedelta(days=9), last_tick=today - timedelta(days=2))
    commands.dispatch_message(ctx, CHAT, "/watered")  # 07:30, before the 09:00 tick
    p = plant_of(ctx)
    assert p["S"] == 1.0 and p["last_tick_date"] == today.isoformat()
    clock.when = clock.when.replace(hour=9)
    run_tick(ctx)
    assert plant_of(ctx)["S"] == 1.0  # the two missed days precede the watering; nothing to subtract
    clock.advance(days=1)
    run_tick(ctx)
    assert plant_of(ctx)["S"] == pytest.approx(1.0 - model.daily_depletion(0.058, 27, 50, 15.3), abs=0.01)


def test_startup_catch_up_is_dated_to_the_missed_tick_not_today(tmp_path):
    from tick import catch_up_if_missed, scheduled_tick_date
    now = datetime(2026, 7, 15, 7, 0, tzinfo=TZ)  # restarted before ALERT_HOUR
    ctx, sent, _ = make_ctx(tmp_path, now=now, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = now.date()
    seed_user(ctx, S=0.40, last_watered=today - timedelta(days=8), last_tick=today - timedelta(days=2))
    assert scheduled_tick_date(now, 9) == today - timedelta(days=1)
    assert catch_up_if_missed(ctx) is True
    p = plant_of(ctx)
    assert p["last_tick_date"] == (today - timedelta(days=1)).isoformat()  # one day, not two
    assert p["S"] == pytest.approx(0.40 - model.daily_depletion(0.058, 27, 50, 15.3), abs=0.01)  # ~0.29
    assert alerts(sent) == []  # S crosses 0.25 only with today's tick, which has not fired yet
    assert catch_up_if_missed(ctx) is False


def test_daylight_uses_the_confirmed_city_latitude(tmp_path):
    from tick import latitude_for
    ctx, _, _ = make_ctx(tmp_path, now=datetime(2026, 1, 15, 9, tzinfo=TZ),
                         primary=FakeSource("weather", [reading(22, 33, "weather")]))
    user = seed_user(ctx, S=0.9, source_type="weather")
    user["env_source"]["city"] = {"name": "Helsinki", "country": "Finland", "latitude": 60.17, "longitude": 24.94}
    assert latitude_for(ctx, user) == 60.17
    run_tick(ctx)
    expected = 0.9 - model.daily_depletion(0.058, 22, 33, model.daylight_hours(15, 60.17))
    not_expected = 0.9 - model.daily_depletion(0.058, 22, 33, model.daylight_hours(15, 44.8))
    assert plant_of(ctx)["S"] == pytest.approx(expected, abs=1e-3)
    assert abs(expected - not_expected) > 0.002  # the two latitudes really differ in January


def test_cached_reading_exactly_seven_days_old_is_stale():
    now = datetime(2026, 7, 15, 9, tzinfo=TZ)
    last = {"temp_c": 24.0, "rh": 47, "at": (now - timedelta(days=7)).isoformat(), "source": "xiaomi_cloud"}
    r = resolve_reading(FakeSource("xiaomi_cloud", []), FakeSource("weather", [reading(29, 45, "weather")]), last, now)
    assert r.rung == "fallback" and r.degraded
    last["at"] = (now - timedelta(days=6, hours=23)).isoformat()
    r = resolve_reading(FakeSource("xiaomi_cloud", []), FakeSource("weather", [reading(29, 45, "weather")]), last, now)
    assert r.rung == "cached"
