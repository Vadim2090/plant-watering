"""The wizard end-to-end with fakes, the three buttons, /watered, /stats, /away, restart resume."""

from datetime import datetime, timedelta

import pytest

import commands
import model
from env_source import Reading
from state import State
from tests.helpers import CHAT, TZ, FakeSource, make_config, make_ctx, reading, seed_user


def tap(ctx, sent, step, value, message_id=None):
    commands.dispatch_callback(ctx, CHAT, message_id, f"ob:{step}:{value}")


def run_wizard(ctx, sent, *, interval="ten_days", last="two_three_days", material="plastic"):
    commands.dispatch_message(ctx, CHAT, "/start")
    if ctx.vision is not None:
        assert "send a photo" in sent.last[1]
        tap(ctx, sent, "welcome", "skip")
    else:
        assert "photo" not in sent.texts[-2].lower()  # no key, no photo invitation (§3)
    assert "What is the pot made of" in sent.last[1]
    tap(ctx, sent, "pot_material", material)
    tap(ctx, sent, "pot_diameter", "20_30")
    tap(ctx, sent, "substrate", "potting_soil")
    tap(ctx, sent, "fit", "balanced")
    tap(ctx, sent, "light", "medium")
    tap(ctx, sent, "last_watered", last)
    tap(ctx, sent, "usual_interval", interval)


def test_wizard_without_xiaomi_skips_source_step_and_finishes(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]))
    run_wizard(ctx, sent, interval="unknown")
    # no Mi credentials -> straight to the city question
    assert "Which city" in sent.last[1]
    tap(ctx, sent, "city", "default")
    text = sent.last[1]
    assert text.startswith("Set up.")
    assert "I expect the soil to be dry around" in text
    assert "the date will move" in text
    user = ctx.state.get_user(CHAT)
    assert user["onboarding"] == {"step": "done", "draft": {}}
    assert user["env_source"]["type"] == "weather"
    p = user["plants"][0]
    assert p["B"] == pytest.approx(0.058, abs=1e-4)
    assert p["last_watered"] == (ctx.today() - timedelta(days=3)).isoformat()
    assert p["last_tick_date"] == ctx.today().isoformat()
    D = model.daily_depletion(0.058, 29, 45, 15.3)
    assert p["S"] == pytest.approx(1.0 - 3 * D, abs=0.01)


def test_wizard_with_xiaomi_probe(tmp_path):
    cfg = make_config(STATE_PATH=str(tmp_path / "s.json"), XIAOMI_USERNAME="u", XIAOMI_PASSWORD="p")
    probe = lambda: ("998877", Reading(24.3, 47, "xiaomi_cloud"))
    primary = FakeSource("xiaomi_cloud", [reading(24.3, 47)])
    ctx, sent, _ = make_ctx(tmp_path, config=cfg, primary=primary, probe=probe)
    run_wizard(ctx, sent)
    assert "Where should the room temperature" in sent.last[1]
    tap(ctx, sent, "env_source", "xiaomi")
    assert "Found it - 24.3 °C, 47%" in sent.last[1]
    tap(ctx, sent, "xiaomi_confirm", "use")
    assert primary.calls == 0  # the confirmed probe reading is used; no second cloud read
    user = ctx.state.get_user(CHAT)
    assert user["env_source"] == {"type": "xiaomi_cloud", "device_id": "998877", "offset_c": 0.0, "city": None,
                                  "last_reading": {"temp_c": 24.3, "rh": 47, "source": "xiaomi_cloud",
                                                   "at": "2026-07-15T09:00:00+02:00"}}
    p = user["plants"][0]
    # geometric blend of the pot estimate and the reported 10-day interval
    b_pot = 0.058
    b_rep = model.seed_B_from_interval(10, 24.3, 47, model.daylight_hours(196, 44.8))
    assert p["B"] == pytest.approx((b_pot * b_rep) ** 0.5, abs=1e-3)


def test_xiaomi_probe_failure_falls_through_to_weather(tmp_path):
    cfg = make_config(STATE_PATH=str(tmp_path / "s.json"), XIAOMI_USERNAME="u", XIAOMI_PASSWORD="p")
    ctx, sent, _ = make_ctx(tmp_path, config=cfg, primary=FakeSource("weather", [reading(29, 45, "weather")]),
                            probe=lambda: None)
    run_wizard(ctx, sent)
    tap(ctx, sent, "env_source", "xiaomi")
    assert "couldn't find or reach the purifier" in sent.texts[-2]
    assert "Which city" in sent.last[1]


def test_photo_proposal_collapses_facts(tmp_path):
    proposal = {"species_guess": "monstera_deliciosa", "pot_material": "terracotta", "pot_diameter_cm": 24,
                "substrate": "unclear", "fit": "root_bound", "mature_leaf_count": 6,
                "notes": "Top dressing hides the substrate."}
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]),
                            vision=lambda jpeg: proposal)
    commands.dispatch_message(ctx, CHAT, "/start")
    commands.dispatch_photo(ctx, CHAT, b"\xff\xd8fake")
    text = sent.last[1]
    assert "Top dressing hides the substrate." in text and "couldn't tell" in text
    tap(ctx, sent, "photo_review", "ok")
    # only the unclear field is asked
    assert "What is it planted in" in sent.last[1]
    tap(ctx, sent, "substrate", "aroid_mix")
    assert "How much light" in sent.last[1]
    tap(ctx, sent, "light", "bright")
    tap(ctx, sent, "last_watered", "today")
    tap(ctx, sent, "usual_interval", "unknown")
    tap(ctx, sent, "city", "default")
    p = ctx.state.get_user(CHAT)["plants"][0]
    assert p["setup"]["pot_material"] == "terracotta" and p["setup"]["fit"] == "root_bound"
    assert p["setup"]["substrate"] == "aroid_mix" and p["setup"]["pot_diameter_cm"] == 25
    assert p["B"] == pytest.approx(0.116, abs=1e-3)  # G clamped to 2.0
    assert p["photo_path"].endswith("/photos/42/monstera-1.jpg")


def test_photo_failure_falls_through_with_apology(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, vision=lambda jpeg: None)
    commands.dispatch_message(ctx, CHAT, "/start")
    commands.dispatch_photo(ctx, CHAT, b"x")
    assert "couldn't read anything useful" in sent.texts[-2]
    assert "What is the pot made of" in sent.last[1]


def test_wizard_survives_restart(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]))
    commands.dispatch_message(ctx, CHAT, "/start")
    tap(ctx, sent, "pot_material", "terracotta")
    tap(ctx, sent, "pot_diameter", "20_30")
    # "restart": a fresh context on the same state file
    ctx2, sent2, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]))
    assert ctx2.state.get_user(CHAT)["onboarding"]["step"] == "substrate"
    commands.dispatch_message(ctx2, CHAT, "/start")  # resumes, does not restart
    assert "What is it planted in" in sent2.last[1]
    # a stale tap on an old button re-asks the live step instead of acting
    tap(ctx2, sent2, "pot_material", "plastic")
    assert "What is it planted in" in sent2.last[1]
    assert ctx2.state.get_user(CHAT)["onboarding"]["draft"]["pot_material"] == "terracotta"


def test_setup_rerun_keeps_history_and_reseeds(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")] * 3))
    user = seed_user(ctx, S=0.3, B=0.09, source_type="weather")
    user["plants"][0]["history"].append({"date": "2026-07-10", "event": "alert", "S": 0.24})
    commands.dispatch_message(ctx, CHAT, "/setup")
    tap(ctx, sent, "pot_material", "terracotta")
    tap(ctx, sent, "pot_diameter", "unknown")
    tap(ctx, sent, "substrate", "aroid_mix")
    tap(ctx, sent, "fit", "unknown")
    tap(ctx, sent, "light", "low")
    tap(ctx, sent, "last_watered", "today")
    tap(ctx, sent, "usual_interval", "unknown")
    tap(ctx, sent, "city", "default")
    p = ctx.state.get_user(CHAT)["plants"][0]
    assert len(ctx.state.get_user(CHAT)["plants"]) == 1
    assert p["B"] == pytest.approx(0.116, abs=1e-3)  # 1.6 * 1.3 = 2.08, G clamped to 2.0
    assert p["S"] == 1.0 and p["pending_alert"] is None
    assert any(h["event"] == "alert" for h in p["history"]) and p["history"][-1]["event"] == "setup"


# --- the three buttons -----------------------------------------------------------------------


def pending_user(tmp_path):
    ctx, sent, clock = make_ctx(tmp_path, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    today = ctx.today()
    user = seed_user(ctx, S=0.2, last_watered=today - timedelta(days=12),
                     last_reading={"temp_c": 27, "rh": 50, "source": "xiaomi_cloud", "at": clock().isoformat()})
    from tick import run_tick
    run_tick(ctx)
    assert user["plants"][0]["pending_alert"] is not None
    return ctx, sent, user


def alert_mid(user):
    return user["plants"][0]["pending_alert"]["message_id"]


def test_still_wet_button(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    p = user["plants"][0]
    S0, B0 = p["S"], p["B"]
    alert_mid_before = alert_mid(user)
    commands.dispatch_callback(ctx, CHAT, alert_mid(user), "ans:monstera-1:still_wet")
    assert p["B"] == pytest.approx(B0 * 0.85, abs=1e-4)
    assert p["S"] == pytest.approx(S0 + 0.10, abs=1e-4)
    assert p["pending_alert"] is None
    assert p["history"][-1]["event"] == "answer" and p["history"][-1]["answer"] == "still_wet"
    assert not any(h["event"] == "watered" and h["via"] == "alert" for h in p["history"])
    assert (CHAT, alert_mid_before) in sent.cleared
    assert "I was early" in sent.last[1]


def test_just_right_button(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    p = user["plants"][0]
    B0 = p["B"]
    commands.dispatch_callback(ctx, CHAT, alert_mid(user), "ans:monstera-1:just_right")
    assert p["B"] == B0 and p["S"] == 1.0
    assert p["last_watered"] == ctx.today().isoformat()
    assert p["history"][-1] == {"date": ctx.today().isoformat(), "event": "watered", "via": "alert"}
    assert p["history"][-2]["B_before"] == B0 and p["history"][-2]["B_after"] == B0
    assert "drainage holes" in sent.last[1]


def test_bone_dry_button(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    p = user["plants"][0]
    B0 = p["B"]
    commands.dispatch_callback(ctx, CHAT, alert_mid(user), "ans:monstera-1:bone_dry")
    assert p["B"] == pytest.approx(B0 * 1.2, abs=1e-4) and p["S"] == 1.0
    assert "drainage holes" in sent.last[1]


def test_answer_twice_is_rejected(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    mid = alert_mid(user)
    commands.dispatch_callback(ctx, CHAT, mid, "ans:monstera-1:just_right")
    B = user["plants"][0]["B"]
    commands.dispatch_callback(ctx, CHAT, mid, "ans:monstera-1:bone_dry")
    assert user["plants"][0]["B"] == B
    assert "already been answered" in sent.last[1]


def test_pending_alert_survives_restart(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    ctx2, sent2, _ = make_ctx(tmp_path)
    p = ctx2.state.get_user(CHAT)["plants"][0]
    assert 0 < p["pending_alert"]["S_at_alert"] <= 0.25
    commands.dispatch_callback(ctx2, CHAT, None, "ans:monstera-1:just_right")
    assert p["pending_alert"] is None and p["S"] == 1.0


# --- commands --------------------------------------------------------------------------------


def test_watered_command_does_not_touch_B(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    p = user["plants"][0]
    B0 = p["B"]
    commands.dispatch_message(ctx, CHAT, "/watered")
    assert p["B"] == B0 and p["S"] == 1.0 and p["pending_alert"] is None
    assert p["history"][-1]["via"] == "command"
    assert "Recorded" in sent.last[1] and "without a score" in sent.last[1]


def test_stats_reports_the_metric(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)
    user = seed_user(ctx, last_reading={"temp_c": 24, "rh": 47, "source": "xiaomi_cloud", "at": ctx.now().isoformat()})
    p = user["plants"][0]
    commands.dispatch_message(ctx, CHAT, "/stats")
    assert "No alerts yet" in sent.last[1]
    for ans in ["just_right", "just_right", "still_wet", "just_right", "just_right", "bone_dry"]:
        p["history"].append({"date": "2026-07-01", "event": "alert", "S": 0.24})
        p["history"].append({"date": "2026-07-01", "event": "answer", "answer": ans, "B_before": 0.058, "B_after": 0.058})
    # one alert closed by /watered, never scored - it stays in the denominator (§1: a share of alerts)
    p["history"].append({"date": "2026-07-02", "event": "alert", "S": 0.24})
    p["history"].append({"date": "2026-07-02", "event": "watered", "via": "command"})
    commands.dispatch_message(ctx, CHAT, "/stats")
    text = sent.last[1]
    assert "Last 7 alerts: 4 answered \"just barely dry\" - 57% agreement." in text
    assert "Too early (still wet): 1 · too late (bone dry): 1 · closed without a check: 1." in text
    assert "B = 0.0580" in text
    assert "Alerts sent in total: 7; answered: 6." in text


def test_status_and_help_and_unknown(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)
    seed_user(ctx, S=0.6, last_reading={"temp_c": 24, "rh": 47, "source": "xiaomi_cloud", "at": ctx.now().isoformat()})
    commands.dispatch_message(ctx, CHAT, "/status")
    text = sent.last[1]
    assert "drying down" in text and "Room: 24 °C, 47% (Xiaomi purifier)" in text and "Predicted dry around" in text
    commands.dispatch_message(ctx, CHAT, "/help")
    assert "/watered" in sent.last[1]
    commands.dispatch_message(ctx, CHAT, "/nope")
    assert "don't know that command" in sent.last[1]
    commands.dispatch_message(ctx, CHAT, "hello")
    assert "only answer commands" in sent.last[1]


def test_away_command(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)
    user = seed_user(ctx)
    commands.dispatch_message(ctx, CHAT, "/away")
    assert "No away window set" in sent.last[1]
    commands.dispatch_message(ctx, CHAT, "/away 2026-11-07 2026-11-17")
    assert user["away"] == {"from": "2026-11-07", "to": "2026-11-17", "prewarned": False}
    commands.dispatch_message(ctx, CHAT, "/away")
    assert sent.buttons() == ["away:clear"]
    commands.dispatch_callback(ctx, CHAT, 3, "away:clear")
    assert user["away"] is None
    commands.dispatch_message(ctx, CHAT, "/away 2026-11-17 2026-11-07")
    assert "Usage" in sent.last[1]
    commands.dispatch_message(ctx, CHAT, "/away 2026-01-01 2026-01-02")
    assert "already over" in sent.last[1]


def test_commands_before_setup(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)
    commands.dispatch_message(ctx, CHAT, "/status")
    assert "Nothing set up yet" in sent.last[1]


def test_start_when_onboarded_shows_status(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)
    seed_user(ctx, last_reading={"temp_c": 24, "rh": 47, "source": "xiaomi_cloud", "at": ctx.now().isoformat()})
    commands.dispatch_message(ctx, CHAT, "/start")
    assert "Soil:" in sent.last[1]


def test_russian_locale_renders(tmp_path):
    import locales.ru as ru
    cfg = make_config(STATE_PATH=str(tmp_path / "s.json"), BOT_LOCALE="ru")
    ctx, sent, _ = make_ctx(tmp_path, config=cfg, primary=FakeSource("xiaomi_cloud", [reading(27, 50)]))
    seed_user(ctx, S=0.2, last_watered=ctx.today() - timedelta(days=12))
    from tick import run_tick
    run_tick(ctx)
    text, keyboard = sent.last[1], sent.last[2]
    assert ru.plural_days(12) in text and "27" in text
    assert keyboard[0][0][0] == ru.STRINGS["btn_still_wet"]
    assert ctx.strings.date(ctx.today()) == f"15 {ru.MONTHS[6]}"
    # the ru plural rule: 1 / 2-4 / 5+ take different endings; 21 behaves like 1
    assert ru.plural_days(1)[2:] == ru.plural_days(21)[3:]
    assert ru.plural_days(3)[2:] != ru.plural_days(5)[2:] != ru.plural_days(1)[2:]


# --- review fixes (Codex pass, 2026-09-13) ---------------------------------------------------


def test_no_vision_means_no_photo_invitation_and_photos_are_declined(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path)  # vision=None
    commands.dispatch_message(ctx, CHAT, "/start")
    assert "photo" not in sent.texts[-2].lower() and "What is the pot made of" in sent.last[1]
    assert ctx.state.get_user(CHAT)["onboarding"]["step"] == "pot_material"
    commands.dispatch_photo(ctx, CHAT, b"x")
    assert "only use one during setup" in sent.last[1]
    assert "photo_path" not in ctx.state.get_user(CHAT)["onboarding"]["draft"]


def test_restart_at_photo_review_resumes_the_confirmation(tmp_path):
    proposal = {"species_guess": "monstera_deliciosa", "pot_material": "plastic", "pot_diameter_cm": None,
                "substrate": "potting_soil", "fit": "balanced", "mature_leaf_count": None, "notes": "Clear view."}
    ctx, sent, _ = make_ctx(tmp_path, vision=lambda jpeg: proposal)
    commands.dispatch_message(ctx, CHAT, "/start")
    commands.dispatch_photo(ctx, CHAT, b"x")
    ctx2, sent2, _ = make_ctx(tmp_path, vision=lambda jpeg: proposal)
    assert ctx2.state.get_user(CHAT)["onboarding"]["step"] == "photo_review"
    commands.dispatch_message(ctx2, CHAT, "/start")
    assert "Clear view." in sent2.last[1] and "ob:photo_review:ok" in sent2.buttons()
    tap(ctx2, sent2, "photo_review", "ok")
    assert "Roughly how wide" in sent2.last[1]  # the one unclear fact


def test_restart_at_xiaomi_confirm_resumes_with_the_saved_reading(tmp_path):
    cfg = make_config(STATE_PATH=str(tmp_path / "s.json"), XIAOMI_USERNAME="u", XIAOMI_PASSWORD="p")
    probe = lambda: ("998877", Reading(24.3, 47, "xiaomi_cloud"))
    ctx, sent, _ = make_ctx(tmp_path, config=cfg, probe=probe)
    run_wizard(ctx, sent)
    tap(ctx, sent, "env_source", "xiaomi")
    ctx2, sent2, _ = make_ctx(tmp_path, config=cfg, probe=lambda: None)  # cloud down after restart
    commands.dispatch_message(ctx2, CHAT, "/start")
    assert "Found it - 24.3 °C, 47%" in sent2.last[1] and "ob:xiaomi_confirm:use" in sent2.buttons()


def test_setup_without_any_reading_seeds_from_pot_only_and_does_not_advance(tmp_path):
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", []), fallback=None)
    run_wizard(ctx, sent, interval="ten_days", last="week")
    tap(ctx, sent, "city", "default")
    text = sent.last[1]
    assert "couldn't get a room reading" in text and "I expect the soil to be dry around" not in text
    p = ctx.state.get_user(CHAT)["plants"][0]
    week_ago = (ctx.today() - timedelta(days=7)).isoformat()
    assert p["B"] == pytest.approx(0.058) and p["S"] == 1.0
    assert p["last_watered"] == week_ago and p["last_tick_date"] == week_ago  # first tick catches up
    assert ctx.state.get_user(CHAT)["env_source"]["last_reading"] is None


def test_buttons_on_an_older_alert_do_not_score_the_open_one(tmp_path):
    ctx, sent, user = pending_user(tmp_path)
    p = user["plants"][0]
    old_mid = alert_mid(user)
    commands.dispatch_message(ctx, CHAT, "/watered")  # closes the alert, clears its buttons
    assert (CHAT, old_mid) in sent.cleared
    # a new alert some days later
    ctx.now.advance(days=12)
    p["S"] = 0.2
    user["env_source"]["last_reading"]["at"] = ctx.now().isoformat()
    from tick import run_tick
    run_tick(ctx)
    new_mid = alert_mid(user)
    assert new_mid != old_mid
    B = p["B"]
    commands.dispatch_callback(ctx, CHAT, old_mid, "ans:monstera-1:bone_dry")
    assert p["pending_alert"] is not None and p["B"] == B and "older alert" in sent.last[1]
    commands.dispatch_callback(ctx, CHAT, new_mid, "ans:monstera-1:bone_dry")
    assert p["pending_alert"] is None and p["B"] == pytest.approx(B * 1.2, abs=1e-4)


def test_group_chat_skips_photo_step(tmp_path):
    # a group (negative chat_id): the photo step is skipped even with vision configured
    ctx, sent, _ = make_ctx(tmp_path, primary=FakeSource("weather", [reading(29, 45, "weather")]),
                            vision=lambda jpeg: {"species_guess": "monstera_deliciosa"})
    GROUP = -1001234567890
    from state import is_onboarded
    user = ctx.state.ensure_user(GROUP, "en", ctx.now())
    import onboarding
    onboarding.start_wizard(ctx, GROUP, user)
    assert "photo" not in sent.texts[-2].lower()  # no photo invitation
    assert "What is the pot made of" in sent.last[1]
    # a photo sent into the group is ignored, not treated as onboarding input
    assert onboarding.handle_photo(ctx, GROUP, user, b"x") is False
