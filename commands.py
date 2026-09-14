"""Command and callback handlers (SPEC.md §10). Telegram-agnostic: everything goes through the
context's `send`, so the same code runs under pytest with a fake."""

from __future__ import annotations

from datetime import date

import model
import onboarding
from context import AppContext
from state import find_plant, is_onboarded
from tick import (
    current_reading,
    days_since_watered,
    implied_interval_days,
    in_away_window,
    latitude_for,
    parse_date,
    predict_dry_date,
    record_watering,
    resolve_user_reading,
)

STATS_WINDOW = 10


def _user(ctx: AppContext, chat_id: int) -> dict:
    return ctx.state.ensure_user(chat_id, ctx.config.bot_locale, ctx.now())


# ---------------------------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------------------------


def dispatch_message(ctx: AppContext, chat_id: int, text: str) -> None:
    text = (text or "").strip()
    with ctx.state.lock:
        user = _user(ctx, chat_id)
        if text.startswith("/"):
            parts = text.split()
            command = parts[0].split("@")[0].lower()
            args = parts[1:]
            handler = COMMANDS.get(command)
            if handler is None:
                ctx.send(chat_id, ctx.t("unknown_command"), None)
                return
            handler(ctx, chat_id, user, args)
            return
        if onboarding.handle_text(ctx, chat_id, user, text):
            return
        if not is_onboarded(user):
            onboarding.resume(ctx, chat_id, user)
            return
        ctx.send(chat_id, ctx.t("hint_commands"), None)


def dispatch_photo(ctx: AppContext, chat_id: int, jpeg: bytes) -> None:
    with ctx.state.lock:
        user = _user(ctx, chat_id)
        if not onboarding.handle_photo(ctx, chat_id, user, jpeg):
            ctx.send(chat_id, ctx.t("photo_unexpected"), None)


def dispatch_callback(ctx: AppContext, chat_id: int, message_id: int | None, data: str) -> None:
    parts = (data or "").split(":")
    with ctx.state.lock:
        user = _user(ctx, chat_id)
        if len(parts) == 3 and parts[0] == onboarding.CB_PREFIX:
            onboarding.handle_callback(ctx, chat_id, user, parts[1], parts[2])
        elif len(parts) == 3 and parts[0] == "ans":
            handle_answer(ctx, chat_id, user, message_id, parts[1], parts[2])
        elif data == "away:clear":
            user["away"] = None
            ctx.state.save()
            if ctx.clear_buttons and message_id is not None:
                ctx.clear_buttons(chat_id, message_id)
            ctx.send(chat_id, ctx.t("away_cleared"), None)
        else:
            ctx.log.warning("unknown callback data")


# ---------------------------------------------------------------------------------------------
# The three buttons (§6.5)
# ---------------------------------------------------------------------------------------------


def handle_answer(ctx: AppContext, chat_id: int, user: dict, message_id: int | None,
                  plant_id: str, answer: str) -> None:
    plant = find_plant(user, plant_id)
    if plant is None or answer not in model.ANSWERS:
        ctx.send(chat_id, ctx.t("answer_unknown_plant"), None)
        return
    pending = plant.get("pending_alert")
    if pending is None:
        if ctx.clear_buttons and message_id is not None:
            ctx.clear_buttons(chat_id, message_id)
        ctx.send(chat_id, ctx.t("answer_nothing_pending"), None)
        return
    pending_mid = pending.get("message_id")
    if message_id is not None and pending_mid is not None and message_id != pending_mid:
        # buttons left on an older alert must not score the one that is actually open
        if ctx.clear_buttons:
            ctx.clear_buttons(chat_id, message_id)
        ctx.send(chat_id, ctx.t("answer_stale_alert"), None)
        return

    today = ctx.today()
    B_before = float(plant["B"])
    result = model.apply_answer(B_before, float(plant["S"]), answer)
    plant["B"] = round(result.B_after, 4)
    plant["S"] = round(result.S_after, 4)
    plant["history"].append({"date": today.isoformat(), "event": "answer", "answer": answer,
                             "B_before": B_before, "B_after": plant["B"]})
    if result.watered:
        record_watering(plant, today, "alert")
    plant["pending_alert"] = None
    ctx.state.save()

    if ctx.clear_buttons and message_id is not None:
        ctx.clear_buttons(chat_id, message_id)

    reading = current_reading(user)
    if answer == model.ANSWER_STILL_WET:
        nxt = predict_dry_date(plant, reading, today, latitude_for(ctx, user)) if reading else None
        text = ctx.t("answer_still_wet", date=ctx.strings.date(nxt) if nxt else ctx.t("soon"))
    elif answer == model.ANSWER_JUST_RIGHT:
        text = ctx.t("answer_just_right") + "\n\n" + ctx.t("watering_method")
    else:
        text = ctx.t("answer_bone_dry") + "\n\n" + ctx.t("watering_method")
    if reading and reading.rh < 40 and answer != model.ANSWER_STILL_WET:
        text += "\n\n" + ctx.t("low_humidity_note", rh=reading.rh)
    ctx.send(chat_id, text, None)


# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------


def cmd_start(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    if is_onboarded(user):
        cmd_status(ctx, chat_id, user, args)
    elif user.get("onboarding", {}).get("step", "welcome") != "welcome" and user["onboarding"].get("draft"):
        onboarding.resume(ctx, chat_id, user)
    else:
        onboarding.start_wizard(ctx, chat_id, user)


def cmd_setup(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    onboarding.start_wizard(ctx, chat_id, user)


def _require_plant(ctx: AppContext, chat_id: int, user: dict) -> dict | None:
    if not is_onboarded(user):
        ctx.send(chat_id, ctx.t("not_set_up"), None)
        return None
    return user["plants"][0]


def s_in_words(ctx: AppContext, S: float, threshold: float) -> str:
    if S <= threshold:
        return ctx.t("s_dry")
    if S <= threshold + 0.15:
        return ctx.t("s_close")
    if S <= 0.7:
        return ctx.t("s_drying")
    return ctx.t("s_full")


def cmd_status(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    plant = _require_plant(ctx, chat_id, user)
    if plant is None:
        return
    today = ctx.today()
    reading = current_reading(user)
    if reading is None:
        ladder = resolve_user_reading(ctx, user)
        reading = ladder.reading
        ctx.state.save()
    t = ctx.t
    lines = [t("status_title", name=plant["name"]),
             t("status_s", words=s_in_words(ctx, float(plant["S"]), model.DEFAULT_PARAMS.alert_threshold),
               pct=int(round(float(plant["S"]) * 100)))]
    if reading:
        src_key = "source_xiaomi" if reading.source == "xiaomi_cloud" else "source_weather" if reading.source == "weather" else "source_cached"
        lines.append(t("status_reading", temp=f"{reading.temp_c:.0f}", rh=reading.rh, source=t(src_key)))
        dry = predict_dry_date(plant, reading, today, latitude_for(ctx, user))
        lines.append(t("status_prediction", date=ctx.strings.date(dry)) if dry > today else t("status_predicted_dry"))
    else:
        lines.append(t("status_no_reading"))
    lines.append(t("status_watered", days=ctx.strings.days(days_since_watered(plant, today))))
    if plant.get("pending_alert"):
        lines.append(t("status_pending"))
    away = user.get("away")
    if away and (in_away_window(away, today) or (parse_date(away.get("from")) or today) > today):
        lines.append(t("status_away", frm=away["from"], to=away["to"]))
    ctx.send(chat_id, "\n".join(lines), None)


def cmd_watered(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    plant = _require_plant(ctx, chat_id, user)
    if plant is None:
        return
    today = ctx.today()
    pending = plant.get("pending_alert")
    had_pending = pending is not None
    if had_pending and pending.get("message_id") is not None and ctx.clear_buttons:
        ctx.clear_buttons(chat_id, pending["message_id"])  # those buttons no longer mean anything
    record_watering(plant, today, "command")
    plant["pending_alert"] = None  # a watering answers the question, without scoring it
    ctx.state.save()
    reading = current_reading(user)
    if reading:
        dry = predict_dry_date(plant, reading, today, latitude_for(ctx, user))
        text = ctx.t("watered_ok", date=ctx.strings.date(dry))
    else:
        text = ctx.t("watered_ok_no_reading")
    if had_pending:
        text += "\n" + ctx.t("watered_unscored")
    ctx.send(chat_id, text, None)


def alert_outcomes(history: list[dict]) -> list[tuple[dict, str | None]]:
    """Every alert paired with the answer that scored it - None when it was closed without one
    (a `/watered`, or never answered). The §1 metric is a share of *alerts*, so unanswered ones
    stay in the denominator."""
    outcomes: list[list] = []
    for h in history:
        if h.get("event") == "alert":
            outcomes.append([h, None])
        elif h.get("event") == "answer" and outcomes and outcomes[-1][1] is None:
            outcomes[-1][1] = h.get("answer")
    return [(a, ans) for a, ans in outcomes]


def cmd_stats(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    plant = _require_plant(ctx, chat_id, user)
    if plant is None:
        return
    outcomes = alert_outcomes(plant["history"])
    recent = outcomes[-STATS_WINDOW:]
    answered_total = sum(1 for _, a in outcomes if a is not None)
    t = ctx.t
    lines = [t("stats_title", name=plant["name"])]
    if not recent:
        lines.append(t("stats_no_alerts"))
    else:
        answers = [a for _, a in recent]
        hit = model.hit_rate(answers) or 0.0
        just = sum(1 for a in answers if a == model.ANSWER_JUST_RIGHT)
        wet = sum(1 for a in answers if a == model.ANSWER_STILL_WET)
        dry = sum(1 for a in answers if a == model.ANSWER_BONE_DRY)
        unanswered = sum(1 for a in answers if a is None)
        lines.append(t("stats_hit_rate", just=just, total=len(recent), pct=int(round(hit * 100))))
        lines.append(t("stats_breakdown", wet=wet, dry=dry, unanswered=unanswered))
        lines.append(t("stats_target_met") if hit >= 0.8 and len(recent) >= 3 else t("stats_target"))
    lines.append("")
    lines.append(t("stats_b", b=f"{float(plant['B']):.4f}"))
    reading = current_reading(user)
    if reading:
        interval = implied_interval_days(plant, reading, ctx.today(), latitude_for(ctx, user))
        lines.append(t("stats_interval", days=ctx.strings.days(int(round(interval))), temp=f"{reading.temp_c:.0f}", rh=reading.rh))
    lines.append(t("stats_alerts_total", n=len(outcomes), answered=answered_total))
    ctx.send(chat_id, "\n".join(lines), None)


def cmd_away(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    if _require_plant(ctx, chat_id, user) is None:
        return
    today = ctx.today()
    if not args:
        away = user.get("away")
        if away and (parse_date(away.get("to")) or today) >= today:
            ctx.send(chat_id, ctx.t("away_current", frm=away["from"], to=away["to"]),
                     [[(ctx.t("btn_away_clear"), "away:clear")]])
        else:
            ctx.send(chat_id, ctx.t("away_none"), None)
        return
    if len(args) != 2:
        ctx.send(chat_id, ctx.t("away_usage"), None)
        return
    a, b = parse_date(args[0]), parse_date(args[1])
    if a is None or b is None or b < a:
        ctx.send(chat_id, ctx.t("away_usage"), None)
        return
    if b < today:
        ctx.send(chat_id, ctx.t("away_in_past"), None)
        return
    user["away"] = {"from": a.isoformat(), "to": b.isoformat(), "prewarned": False}
    ctx.state.save()
    ctx.send(chat_id, ctx.t("away_set", frm=ctx.strings.date(a), to=ctx.strings.date(b)), None)


def cmd_help(ctx: AppContext, chat_id: int, user: dict, args: list[str]) -> None:
    ctx.send(chat_id, ctx.t("help"), None)


COMMANDS = {
    "/start": cmd_start,
    "/setup": cmd_setup,
    "/status": cmd_status,
    "/watered": cmd_watered,
    "/stats": cmd_stats,
    "/away": cmd_away,
    "/help": cmd_help,
}
