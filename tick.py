"""The daily tick (SPEC.md §9) and the plant operations it shares with the command handlers:
resolving a reading for a user, advancing `S` across calendar days, predicting the dry date and
recording a watering.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import model
from context import AppContext
from env_source import LadderResult, Reading, resolve_reading
from profiles import get_profile, window_factor_for_setup
from state import find_plant

COLD_WARNING_INTERVAL_DAYS = 7


# ---------------------------------------------------------------------------------------------
# Shared plant operations
# ---------------------------------------------------------------------------------------------


def parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def latitude_for(ctx: AppContext, user: dict) -> float:
    """The latitude daylight is computed for: the confirmed city if there is one, else the config."""
    city = (user.get("env_source") or {}).get("city") or {}
    try:
        return float(city.get("latitude", ctx.config.latitude))
    except (TypeError, ValueError):
        return ctx.config.latitude


def resolve_user_reading(ctx: AppContext, user: dict) -> LadderResult:
    """Run the §5.3 ladder for one user and store a fresh reading back into their env_source."""
    env = user.get("env_source") or {}
    primary = ctx.make_primary_source(env)
    result = resolve_reading(primary, ctx.fallback_source, env.get("last_reading"), ctx.now(),
                             float(env.get("offset_c") or 0.0))
    if result.new_last_reading is not None:
        env["last_reading"] = result.new_last_reading
        user["env_source"] = env
    return result


def conditions_for_day(d: date, reading: Reading, lat: float) -> model.DayConditions:
    return model.DayConditions(reading.temp_c, reading.rh, model.daylight_hours(d.timetuple().tm_yday, lat))


def advance_plant(plant: dict, reading: Reading, to_date: date, lat: float) -> int:
    """Advance `S` once per calendar day from `last_tick_date` (exclusive) to `to_date`
    (inclusive), holding the reading and letting daylight follow the calendar. Returns the
    number of days advanced."""
    profile = get_profile(plant.get("species"))
    wf = window_factor_for_setup(plant.get("setup") or {})
    start = parse_date(plant.get("last_tick_date")) or to_date
    days = []
    d = start + timedelta(days=1)
    while d <= to_date:
        days.append(conditions_for_day(d, reading, lat))
        d += timedelta(days=1)
    if days:
        plant["S"] = round(model.advance(float(plant["S"]), float(plant["B"]), days, wf, profile.params), 4)
    plant["last_tick_date"] = to_date.isoformat()
    return len(days)


def days_since_watered(plant: dict, today: date) -> int:
    lw = parse_date(plant.get("last_watered"))
    return (today - lw).days if lw else 999


def predict_dry_date(plant: dict, reading: Reading, today: date, lat: float) -> date:
    profile = get_profile(plant.get("species"))
    wf = window_factor_for_setup(plant.get("setup") or {})
    n = model.days_until_threshold(float(plant["S"]), float(plant["B"]), reading.temp_c, reading.rh,
                                   today.timetuple().tm_yday, lat, wf, profile.params)
    return today + timedelta(days=n)


def implied_interval_days(plant: dict, reading: Reading, today: date, lat: float) -> float:
    """Full pot to threshold under today's conditions - what the current `B` means in days."""
    profile = get_profile(plant.get("species"))
    wf = window_factor_for_setup(plant.get("setup") or {})
    return model.predicted_interval_days(float(plant["B"]), reading.temp_c, reading.rh,
                                         model.daylight_hours(today.timetuple().tm_yday, lat), wf, profile.params)


def record_watering(plant: dict, today: date, via: str) -> None:
    """A full pot from today. `last_tick_date` moves too: the days before the watering must not be
    subtracted from the fresh reservoir by a later catch-up."""
    plant["S"] = 1.0
    plant["last_watered"] = today.isoformat()
    plant["last_tick_date"] = today.isoformat()
    plant["history"].append({"date": today.isoformat(), "event": "watered", "via": via})


def current_reading(user: dict) -> Reading | None:
    last = (user.get("env_source") or {}).get("last_reading")
    if not last:
        return None
    return Reading(float(last["temp_c"]), int(last["rh"]), last.get("source", "cached"))


def in_away_window(away: dict | None, today: date) -> bool:
    if not away:
        return False
    a, b = parse_date(away.get("from")), parse_date(away.get("to"))
    return bool(a and b and a <= today <= b)


def alert_keyboard(ctx: AppContext, plant_id: str):
    t = ctx.t
    return [[
        (t("btn_still_wet"), f"ans:{plant_id}:{model.ANSWER_STILL_WET}"),
        (t("btn_just_right"), f"ans:{plant_id}:{model.ANSWER_JUST_RIGHT}"),
        (t("btn_bone_dry"), f"ans:{plant_id}:{model.ANSWER_BONE_DRY}"),
    ]]


def alert_text(ctx: AppContext, plant: dict, reading: Reading, today: date, degraded: bool,
               unreachable_since: str | None) -> str:
    text = ctx.t("alert", name=plant["name"], temp=f"{reading.temp_c:.0f}", rh=reading.rh,
                 days=ctx.strings.days(days_since_watered(plant, today)))
    if degraded:
        since = unreachable_since[:10] if unreachable_since else None
        since_txt = ctx.strings.date(date.fromisoformat(since)) if since else ctx.t("unknown_date")
        text += "\n\n" + ctx.t("alert_degraded", since=since_txt)
    return text


# ---------------------------------------------------------------------------------------------
# §9 The tick
# ---------------------------------------------------------------------------------------------


def _would_run_dry_during(plant: dict, reading: Reading, start: date, end: date, lat: float) -> bool:
    profile = get_profile(plant.get("species"))
    wf = window_factor_for_setup(plant.get("setup") or {})
    S = float(plant["S"])
    d = start
    while d <= end:
        c = conditions_for_day(d, reading, lat)
        S = model.step(S, model.daily_depletion(float(plant["B"]), c.temp_c, c.rh, c.daylight_h, wf, profile.params))
        if S <= profile.params.alert_threshold:
            return True
        d += timedelta(days=1)
    return False


def tick_user(ctx: AppContext, chat_id: int, user: dict, today: date, force: bool = False) -> list[str]:
    """One user's plants. Returns a list of event labels for the log. Does not save."""
    events: list[str] = []
    if not user.get("plants") or user.get("onboarding", {}).get("step") != "done":
        return events

    ladder = resolve_user_reading(ctx, user)
    if ladder.reading is None:
        ctx.log.warning("chat %s: no reading from any source - tick skipped, S unchanged", chat_id)
        return ["skipped:no_reading"]
    reading = ladder.reading
    events.append(f"reading:{ladder.rung}")
    lat = latitude_for(ctx, user)
    away = user.get("away")

    for plant in user["plants"]:
        profile = get_profile(plant.get("species"))
        last_tick = parse_date(plant.get("last_tick_date"))
        if last_tick is not None and last_tick >= today and not force:
            events.append(f"{plant['id']}:already_ticked")
            continue

        n = advance_plant(plant, reading, today, lat)
        events.append(f"{plant['id']}:advanced:{n}")

        # §9.3 - the last tick before an away window starts
        if away and not away.get("prewarned"):
            a, b = parse_date(away.get("from")), parse_date(away.get("to"))
            if a and b and today < a <= today + timedelta(days=1):
                if _would_run_dry_during(plant, reading, a, b, lat):
                    ctx.send(chat_id, ctx.t("away_prewarn", name=plant["name"], date=ctx.strings.date(a)), None)
                    away["prewarned"] = True
                    plant["history"].append({"date": today.isoformat(), "event": "away_prewarn"})
                    events.append(f"{plant['id']}:prewarned")

        gate = model.alert_gate(
            S=float(plant["S"]),
            days_since_watered=days_since_watered(plant, today),
            month=today.month,
            temp_c=reading.temp_c,
            in_away_window=in_away_window(away, today),
            has_pending_alert=plant.get("pending_alert") is not None,
            params=profile.params,
        )

        if gate.cold_warning:
            last_cold = parse_date(user.get("last_cold_warning"))
            if last_cold is None or (today - last_cold).days >= COLD_WARNING_INTERVAL_DAYS:
                ctx.send(chat_id, ctx.t("cold_warning", temp=f"{reading.temp_c:.0f}"), None)
                user["last_cold_warning"] = today.isoformat()
                plant["history"].append({"date": today.isoformat(), "event": "cold_warning", "temp_c": reading.temp_c})
                events.append(f"{plant['id']}:cold_warning")
            else:
                events.append(f"{plant['id']}:cold_suppressed")
            continue

        if gate.alert:
            text = alert_text(ctx, plant, reading, today, ladder.degraded, ladder.unreachable_since)
            msg_id = ctx.send(chat_id, text, alert_keyboard(ctx, plant["id"]))
            if msg_id is None:
                # nothing reached the user: leave no trace, so the next tick asks again
                ctx.log.warning("chat %s: alert for %s not delivered - will retry next tick", chat_id, plant["id"])
                events.append(f"{plant['id']}:alert_send_failed")
                continue
            plant["pending_alert"] = {
                "sent_at": ctx.now().isoformat(timespec="seconds"),
                "S_at_alert": float(plant["S"]),
                "message_id": msg_id,
                "degraded": ladder.degraded,
            }
            plant["history"].append({"date": today.isoformat(), "event": "alert", "S": float(plant["S"]),
                                     "temp_c": reading.temp_c, "rh": reading.rh, "degraded": ladder.degraded})
            events.append(f"{plant['id']}:alert")
        else:
            events.append(f"{plant['id']}:no_alert:{gate.reason}")
    return events


def run_tick(ctx: AppContext, today: date | None = None, force: bool = False) -> dict[str, list[str]]:
    """For every user, for every plant. Saves state once, at the end."""
    today = today or ctx.today()
    report: dict[str, list[str]] = {}
    with ctx.state.lock:
        for chat_id, user in list(ctx.state.users.items()):
            try:
                report[chat_id] = tick_user(ctx, int(chat_id), user, today, force)
            except Exception:  # one user's failure must not stop the others
                ctx.log.exception("tick failed for chat %s", chat_id)
                report[chat_id] = ["error"]
        ctx.state.save()
    ctx.log.info("tick %s: %s", today.isoformat(), report)
    return report


def scheduled_tick_date(now: datetime, alert_hour: int) -> date:
    """The calendar day of the most recent tick that should already have fired."""
    return now.date() if now.hour >= alert_hour else now.date() - timedelta(days=1)


def missed_tick(ctx: AppContext, now: datetime) -> bool:
    """True when a scheduled tick has passed since some plant's `last_tick_date`."""
    scheduled = scheduled_tick_date(now, ctx.config.alert_hour)
    with ctx.state.lock:
        for _, user, plant in ctx.state.iter_plants():
            if user.get("onboarding", {}).get("step") != "done":
                continue
            last = parse_date(plant.get("last_tick_date"))
            if last is None or last < scheduled:
                return True
    return False


def catch_up_if_missed(ctx: AppContext) -> bool:
    """On start-up: run the tick the process was down for, dated to that tick - never to a
    'today' whose ALERT_HOUR has not arrived yet."""
    now = ctx.now()
    if not missed_tick(ctx, now):
        return False
    run_tick(ctx, today=scheduled_tick_date(now, ctx.config.alert_hour))
    return True
