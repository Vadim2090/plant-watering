"""The onboarding wizard (SPEC.md §7): an explicit state machine over inline buttons.

Every callback carries its step (`ob:<step>:<value>`), and the step plus the draft live in the
state file before the bot waits for an answer - so a restart mid-wizard resumes where it left off.
Every question carries a "Don't know" option that maps to the neutral factor.
"""

from __future__ import annotations

from datetime import date, timedelta

import model
from context import AppContext
from profiles import (
    DEFAULT_SPECIES,
    INTERVAL_DAYS,
    LAST_WATERED_DAYS_AGO,
    UNKNOWN_LAST_WATERED_DAYS,
    factors_for_setup,
    get_profile,
    window_factor_for_setup,
)
from env_source import Reading
from state import find_plant, new_plant
from tick import advance_plant, implied_interval_days, latitude_for, predict_dry_date, resolve_user_reading

CB_PREFIX = "ob"

# Step keys
WELCOME = "welcome"
PHOTO_REVIEW = "photo_review"
POT_MATERIAL = "pot_material"
POT_DIAMETER = "pot_diameter"
SUBSTRATE = "substrate"
FIT = "fit"
LIGHT = "light"
LAST_WATERED = "last_watered"
USUAL_INTERVAL = "usual_interval"
ENV_SOURCE = "env_source"
XIAOMI_CONFIRM = "xiaomi_confirm"
CITY = "city"
DONE = "done"

FACT_STEPS = [POT_MATERIAL, POT_DIAMETER, SUBSTRATE, FIT]
QUESTION_ORDER = FACT_STEPS + [LIGHT, LAST_WATERED, USUAL_INTERVAL]

# step -> [(button string id, stored value)]
OPTIONS: dict[str, list[tuple[str, str]]] = {
    POT_MATERIAL: [("opt_terracotta", "terracotta"), ("opt_plastic", "plastic"), ("opt_dont_know", "unknown")],
    POT_DIAMETER: [("opt_d_lt20", "lt20"), ("opt_d_20_30", "20_30"), ("opt_d_30_40", "30_40"),
                   ("opt_d_gt40", "gt40"), ("opt_dont_know", "unknown")],
    SUBSTRATE: [("opt_aroid", "aroid_mix"), ("opt_soil", "potting_soil"), ("opt_peat", "peat_heavy"),
                ("opt_dont_know", "unknown")],
    FIT: [("opt_root_bound", "root_bound"), ("opt_balanced", "balanced"), ("opt_small_in_big", "small_in_big"),
          ("opt_dont_know", "unknown")],
    LIGHT: [("opt_bright", "bright"), ("opt_medium", "medium"), ("opt_low", "low")],
    LAST_WATERED: [("opt_today", "today"), ("opt_yesterday", "yesterday"), ("opt_2_3_days", "two_three_days"),
                   ("opt_week", "week"), ("opt_dont_remember", "unknown")],
    USUAL_INTERVAL: [("opt_weekly", "weekly"), ("opt_ten_days", "ten_days"), ("opt_two_weeks", "two_weeks"),
                     ("opt_less_often", "less_often"), ("opt_dont_know", "unknown")],
    ENV_SOURCE: [("opt_src_xiaomi", "xiaomi"), ("opt_src_weather", "weather")],
}
PROMPT_KEY = {step: f"q_{step}" for step in OPTIONS}

DIAMETER_CM = {"lt20": 17, "20_30": 25, "30_40": 35, "gt40": 45, "unknown": None}


def cb(step: str, value: str) -> str:
    return f"{CB_PREFIX}:{step}:{value}"


def _ob(user: dict) -> dict:
    user.setdefault("onboarding", {"step": WELCOME, "draft": {}})
    user["onboarding"].setdefault("draft", {})
    return user["onboarding"]


def _set_step(ctx: AppContext, user: dict, step: str) -> None:
    _ob(user)["step"] = step
    ctx.state.save()


def _keyboard(ctx: AppContext, step: str, per_row: int = 2):
    buttons = [(ctx.t(label), cb(step, value)) for label, value in OPTIONS[step]]
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _next_plant_id(user: dict) -> str:
    return f"monstera-{len(user.get('plants', [])) + 1}"


# ---------------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------------


def start_wizard(ctx: AppContext, chat_id: int, user: dict, plant_id: str | None = None) -> None:
    """`/start` on a new chat or `/setup` on a known one."""
    ob = _ob(user)
    existing = user.get("plants") or []
    ob["draft"] = {"plant_id": plant_id or (existing[0]["id"] if existing else _next_plant_id(user))}
    ob["step"] = WELCOME
    ctx.state.save()
    if ctx.vision is None:
        # no API key: the photo step does not exist (§3), so do not invite a photo
        ctx.send(chat_id, ctx.t("welcome_no_photo"), None)
        ask(ctx, chat_id, user, POT_MATERIAL)
        return
    ctx.send(chat_id, ctx.t("welcome"), [[(ctx.t("btn_skip_photo"), cb(WELCOME, "skip"))]])


def ask(ctx: AppContext, chat_id: int, user: dict, step: str) -> None:
    """Send the prompt for `step` and persist the step before waiting."""
    if step == ENV_SOURCE and not ctx.config.has_xiaomi:
        _ob(user)["draft"][ENV_SOURCE] = "weather"
        return ask(ctx, chat_id, user, CITY)
    if step == CITY:
        _set_step(ctx, user, CITY)
        ctx.send(chat_id, ctx.t("q_city"), [[(ctx.t("btn_city_default"), cb(CITY, "default"))]])
        return
    if step == DONE:
        return finish(ctx, chat_id, user)
    _set_step(ctx, user, step)
    ctx.send(chat_id, ctx.t(PROMPT_KEY[step]), _keyboard(ctx, step))


def resume(ctx: AppContext, chat_id: int, user: dict) -> None:
    """Re-send the current step's prompt (after a restart, or a stale button tap)."""
    ob = _ob(user)
    step = ob.get("step", WELCOME)
    draft = ob["draft"]
    if step == WELCOME:
        if ctx.vision is None:
            ask(ctx, chat_id, user, POT_MATERIAL)
        else:
            ctx.send(chat_id, ctx.t("welcome"), [[(ctx.t("btn_skip_photo"), cb(WELCOME, "skip"))]])
    elif step == PHOTO_REVIEW:
        if draft.get("photo_proposal"):
            _send_photo_review(ctx, chat_id, draft["photo_proposal"])
        else:
            ask(ctx, chat_id, user, POT_MATERIAL)
    elif step == XIAOMI_CONFIRM:
        if draft.get("xiaomi_device_id") and draft.get("xiaomi_reading"):
            _send_xiaomi_confirm(ctx, chat_id, draft["xiaomi_reading"])
        else:
            _probe_xiaomi(ctx, chat_id, user)
    else:
        ask(ctx, chat_id, user, step)


def _first_missing_fact(draft: dict) -> str:
    for step in FACT_STEPS:
        if step not in draft:
            return step
    return LIGHT


def _after(step: str) -> str:
    order = QUESTION_ORDER + [ENV_SOURCE, DONE]
    return order[order.index(step) + 1]


# ---------------------------------------------------------------------------------------------
# Photo (§8)
# ---------------------------------------------------------------------------------------------


def handle_photo(ctx: AppContext, chat_id: int, user: dict, jpeg: bytes) -> bool:
    """A photo during `welcome`. Returns False when the photo was not expected."""
    ob = _ob(user)
    if ob.get("step") != WELCOME or ctx.vision is None:
        return False
    draft = ob["draft"]
    if ctx.save_photo is not None:
        try:
            draft["photo_path"] = ctx.save_photo(chat_id, draft.get("plant_id", "monstera-1"), jpeg)
        except Exception:
            ctx.log.exception("could not save photo")
    proposal = ctx.vision(jpeg)
    if not proposal:
        ctx.send(chat_id, ctx.t("photo_failed"), None)
        ask(ctx, chat_id, user, POT_MATERIAL)
        return True
    draft["photo_proposal"] = proposal
    _set_step(ctx, user, PHOTO_REVIEW)
    _send_photo_review(ctx, chat_id, proposal)
    return True


def _send_photo_review(ctx: AppContext, chat_id: int, proposal: dict) -> None:
    ctx.send(chat_id, _proposal_summary(ctx, proposal),
             [[(ctx.t("btn_photo_ok"), cb(PHOTO_REVIEW, "ok")), (ctx.t("btn_photo_fix"), cb(PHOTO_REVIEW, "fix"))]])


def _proposal_summary(ctx: AppContext, p: dict) -> str:
    t = ctx.t

    def label(key: str, value) -> str:
        if value in (None, "unclear"):
            return t("val_unclear")
        return t(f"val_{key}_{value}") if key != "pot_diameter_cm" else f"~{value} cm"

    lines = [t("photo_intro")]
    if p.get("species_guess") == "other":
        lines.append(t("photo_not_monstera"))
    lines += [
        t("photo_line", field=t("field_pot_material"), value=label("pot_material", p.get("pot_material"))),
        t("photo_line", field=t("field_pot_diameter"), value=label("pot_diameter_cm", p.get("pot_diameter_cm"))),
        t("photo_line", field=t("field_substrate"), value=label("substrate", p.get("substrate"))),
        t("photo_line", field=t("field_fit"), value=label("fit", p.get("fit"))),
    ]
    if p.get("notes"):
        lines.append("")
        lines.append(str(p["notes"]))
    lines.append("")
    lines.append(t("photo_confirm_hint"))
    return "\n".join(lines)


def _apply_proposal(draft: dict, p: dict) -> None:
    for key in ("pot_material", "substrate", "fit"):
        if p.get(key) not in (None, "unclear"):
            draft[key] = p[key]
    if isinstance(p.get("pot_diameter_cm"), int):
        cm = p["pot_diameter_cm"]
        draft[POT_DIAMETER] = "lt20" if cm < 20 else "20_30" if cm < 30 else "30_40" if cm < 40 else "gt40"


# ---------------------------------------------------------------------------------------------
# Callbacks and free text
# ---------------------------------------------------------------------------------------------


def handle_callback(ctx: AppContext, chat_id: int, user: dict, step: str, value: str) -> None:
    ob = _ob(user)
    draft = ob["draft"]
    current = ob.get("step", WELCOME)
    if step != current:
        # a stale button from an earlier message - re-ask the live step instead of acting on it
        resume(ctx, chat_id, user)
        return

    if step == WELCOME:
        ask(ctx, chat_id, user, POT_MATERIAL)
        return

    if step == PHOTO_REVIEW:
        if value == "ok":
            _apply_proposal(draft, draft.get("photo_proposal") or {})
            ask(ctx, chat_id, user, _first_missing_fact(draft))
        else:
            ask(ctx, chat_id, user, POT_MATERIAL)
        return

    if step in OPTIONS and step != ENV_SOURCE:
        valid = {v for _, v in OPTIONS[step]}
        if value not in valid:
            resume(ctx, chat_id, user)
            return
        draft[step] = value
        ask(ctx, chat_id, user, _first_missing_fact(draft) if step in FACT_STEPS else _after(step))
        return

    if step == ENV_SOURCE:
        if value == "xiaomi":
            _probe_xiaomi(ctx, chat_id, user)
        else:
            draft[ENV_SOURCE] = "weather"
            ask(ctx, chat_id, user, CITY)
        return

    if step == XIAOMI_CONFIRM:
        if value == "use":
            draft[ENV_SOURCE] = "xiaomi"
            finish(ctx, chat_id, user)
        else:
            draft[ENV_SOURCE] = "weather"
            draft.pop("xiaomi_device_id", None)
            draft.pop("xiaomi_reading", None)
            ask(ctx, chat_id, user, CITY)
        return

    if step == CITY:
        if value == "default":
            draft["city"] = None
            finish(ctx, chat_id, user)
        elif value == "yes" and draft.get("city_candidate"):
            draft["city"] = draft.pop("city_candidate")
            finish(ctx, chat_id, user)
        else:
            draft.pop("city_candidate", None)
            ask(ctx, chat_id, user, CITY)
        return


def handle_text(ctx: AppContext, chat_id: int, user: dict, text: str) -> bool:
    """Free text is only meaningful at the city step. Returns False otherwise."""
    ob = _ob(user)
    if ob.get("step") != CITY:
        return False
    from env_source import geocode_city

    hit = geocode_city(text.strip())
    if not hit:
        ctx.send(chat_id, ctx.t("city_not_found"), [[(ctx.t("btn_city_default"), cb(CITY, "default"))]])
        return True
    ob["draft"]["city_candidate"] = hit
    ctx.state.save()
    where = ", ".join(x for x in (hit["name"], hit.get("admin1"), hit.get("country")) if x)
    ctx.send(chat_id, ctx.t("city_confirm", place=where),
             [[(ctx.t("btn_city_yes"), cb(CITY, "yes")), (ctx.t("btn_city_retry"), cb(CITY, "retry"))]])
    return True


def _probe_xiaomi(ctx: AppContext, chat_id: int, user: dict) -> None:
    draft = _ob(user)["draft"]
    result = None
    if ctx.probe_xiaomi is not None:
        try:
            result = ctx.probe_xiaomi()
        except Exception:
            ctx.log.exception("xiaomi probe failed")
    if result is None:
        ctx.send(chat_id, ctx.t("xiaomi_not_found", region=ctx.config.xiaomi_region), None)
        draft[ENV_SOURCE] = "weather"
        ask(ctx, chat_id, user, CITY)
        return
    device_id, reading = result
    draft["xiaomi_device_id"] = device_id
    # keep the reading the user is about to confirm: finish() seeds from it, no second cloud read
    draft["xiaomi_reading"] = {"temp_c": reading.temp_c, "rh": reading.rh, "source": reading.source}
    _set_step(ctx, user, XIAOMI_CONFIRM)
    _send_xiaomi_confirm(ctx, chat_id, draft["xiaomi_reading"])


def _send_xiaomi_confirm(ctx: AppContext, chat_id: int, reading: dict) -> None:
    ctx.send(chat_id, ctx.t("xiaomi_found", temp=f"{float(reading['temp_c']):.1f}", rh=reading["rh"]),
             [[(ctx.t("btn_xiaomi_use"), cb(XIAOMI_CONFIRM, "use")),
               (ctx.t("btn_xiaomi_weather"), cb(XIAOMI_CONFIRM, "weather"))]])


# ---------------------------------------------------------------------------------------------
# Step 10 - finish
# ---------------------------------------------------------------------------------------------


def build_setup(draft: dict) -> dict:
    interval_key = draft.get(USUAL_INTERVAL, "unknown")
    return {
        "pot_material": draft.get(POT_MATERIAL, "unknown"),
        "pot_diameter_cm": DIAMETER_CM.get(draft.get(POT_DIAMETER, "unknown")),
        "substrate": draft.get(SUBSTRATE, "unknown"),
        "fit": draft.get(FIT, "unknown"),
        "light": draft.get(LIGHT, "medium"),
        "reported_interval_days": INTERVAL_DAYS.get(interval_key),
    }


def finish(ctx: AppContext, chat_id: int, user: dict) -> None:
    ob = _ob(user)
    draft = ob["draft"]
    today = ctx.today()
    profile = get_profile(DEFAULT_SPECIES)

    # environment source
    city = draft.get("city")
    source_type = "xiaomi_cloud" if draft.get(ENV_SOURCE) == "xiaomi" else "weather"
    previous = user.get("env_source") or {}
    user["env_source"] = {
        "type": source_type,
        "device_id": draft.get("xiaomi_device_id") if source_type == "xiaomi_cloud" else None,
        "offset_c": float(previous.get("offset_c") or 0.0),
        "city": city,
        "last_reading": previous.get("last_reading") if previous.get("type") == source_type else None,
    }
    lat = latitude_for(ctx, user)

    # today's reading: the one the user just confirmed on the purifier, otherwise the ladder
    probe = draft.get("xiaomi_reading") if source_type == "xiaomi_cloud" else None
    if probe:
        offset = float(user["env_source"]["offset_c"])
        reading = Reading(round(float(probe["temp_c"]) + offset, 1), int(probe["rh"]), probe.get("source", "xiaomi_cloud"))
        user["env_source"]["last_reading"] = reading.to_state(ctx.now())
    else:
        reading = resolve_user_reading(ctx, user).reading

    # seed B. The reported interval is blended in only under a real reading - it is an estimate
    # of B under today's conditions, and without a reading there are no conditions to divide by.
    setup = build_setup(draft)
    mat_f, sub_f, fit_f = factors_for_setup(setup)
    wf = window_factor_for_setup(setup)
    if reading is not None:
        daylight = model.daylight_hours(today.timetuple().tm_yday, lat)
        B = model.seed_B(mat_f, sub_f, fit_f, setup["reported_interval_days"], reading.temp_c, reading.rh,
                         daylight, wf, profile.params)
    else:
        B = model.seed_B(mat_f, sub_f, fit_f, params=profile.params)

    # initial S: full on last_watered, run forward to today - but only on a real reading. With
    # none, last_tick_date stays on the watering day and the first tick catches up (§5.3 step 5).
    days_ago = LAST_WATERED_DAYS_AGO.get(draft.get(LAST_WATERED, "unknown"))
    if days_ago is None:
        days_ago = UNKNOWN_LAST_WATERED_DAYS
    last_watered = today - timedelta(days=days_ago)

    plant_id = draft.get("plant_id") or "monstera-1"
    plant = find_plant(user, plant_id)
    if plant is None:
        plant = new_plant(plant_id, profile.display_name, profile.key, setup, round(B, 4), 1.0,
                          last_watered.isoformat(), last_watered.isoformat(), draft.get("photo_path"))
        plant["history"].append({"date": last_watered.isoformat(), "event": "watered", "via": "setup"})
        user.setdefault("plants", []).append(plant)
    else:
        plant.update({"setup": setup, "B": round(B, 4), "S": 1.0, "last_watered": last_watered.isoformat(),
                      "last_tick_date": last_watered.isoformat(), "pending_alert": None})
        if draft.get("photo_path"):
            plant["photo_path"] = draft["photo_path"]
        plant["history"].append({"date": today.isoformat(), "event": "setup", "B_seeded": round(B, 4)})
    if reading is not None:
        advance_plant(plant, reading, today, lat)

    ob["step"] = DONE
    ob["draft"] = {}
    ctx.state.save()

    t = ctx.t
    lines = [
        t("done_title"),
        t("done_setup", material=t(f"val_pot_material_{setup['pot_material']}"),
          substrate=t(f"val_substrate_{setup['substrate']}"), fit=t(f"val_fit_{setup['fit']}"),
          light=t(f"val_light_{setup['light']}")),
        t("done_source_xiaomi") if source_type == "xiaomi_cloud" else t("done_source_weather"),
    ]
    if reading is None:
        lines.append(t("done_no_reading"))
    else:
        dry = predict_dry_date(plant, reading, today, lat)
        interval = implied_interval_days(plant, reading, today, lat)
        lines.append(t("done_reading", temp=f"{reading.temp_c:.0f}", rh=reading.rh))
        lines.append(t("done_interval", days=ctx.strings.days(int(round(interval)))))
        lines.append("")
        lines.append(t("done_prediction", date=ctx.strings.date(dry)))
    ctx.send(chat_id, "\n".join(lines), None)
