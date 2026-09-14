"""SPEC.md §12.1 - unit tests for model.py. No mocks: the module is pure."""

import math

import pytest

import model
from model import (
    ANSWER_BONE_DRY,
    ANSWER_JUST_RIGHT,
    ANSWER_STILL_WET,
    DEFAULT_PARAMS,
    DayConditions,
    advance,
    alert_gate,
    apply_answer,
    daylight_hours,
    humidity_factor,
    light_factor,
    pot_factor,
    predicted_interval_days,
    seed_B,
    seed_B_from_pot,
    temperature_factor,
)

LAT = 44.8
B_REF = 0.058


# --- daylight ---------------------------------------------------------------------------------


def test_daylight_june_solstice():
    assert daylight_hours(172, LAT) == pytest.approx(15.59, abs=0.02)


def test_daylight_december_solstice():
    assert daylight_hours(355, LAT) == pytest.approx(8.79, abs=0.02)


def test_daylight_annual_mean():
    mean = sum(daylight_hours(d, LAT) for d in range(1, 366)) / 365
    assert mean == pytest.approx(12.23, abs=0.02)


def test_daylight_is_bounded_at_polar_latitudes():
    assert 0.0 <= daylight_hours(172, 89.0) <= 24.0
    assert 0.0 <= daylight_hours(355, 89.0) <= 24.0


# --- reference intervals ----------------------------------------------------------------------


def test_july_reference_interval():
    days = predicted_interval_days(B_REF, temp_c=27, rh=50, daylight_h=15.4)
    assert 6 <= days <= 8


def test_january_reference_interval():
    days = predicted_interval_days(B_REF, temp_c=22, rh=33, daylight_h=9.1)
    assert 14 <= days <= 18


def test_reference_table_july_and_january_exact():
    # SPEC §6.6: 6.6 d and 15.7 d.
    assert predicted_interval_days(B_REF, 27, 50, 15.4) == pytest.approx(6.6, abs=0.1)
    assert predicted_interval_days(B_REF, 22, 33, 9.1) == pytest.approx(15.7, abs=0.2)


def test_day_by_day_simulation_agrees_with_analytic_interval():
    conditions = DayConditions(temp_c=27, rh=50, daylight_h=15.4)
    S, n = 1.0, 0
    while S > DEFAULT_PARAMS.alert_threshold:
        S = advance(S, B_REF, [conditions])
        n += 1
    assert n == math.ceil(predicted_interval_days(B_REF, 27, 50, 15.4))


# --- factors ----------------------------------------------------------------------------------


def test_temperature_factor_at_5c_is_clamped_then_dormancy_scaled():
    assert temperature_factor(5) == pytest.approx(0.35 * 0.6)


def test_temperature_factor_reference_and_q10():
    assert temperature_factor(22) == pytest.approx(1.0)
    assert temperature_factor(32) == pytest.approx(2.0)
    assert temperature_factor(45) == pytest.approx(2.20)  # upper clamp


def test_temperature_dormancy_boundary():
    assert temperature_factor(15) == pytest.approx(2 ** (-0.7))
    assert temperature_factor(14.9) == pytest.approx(clamped(2 ** (-0.71)) * 0.6)


def clamped(x):
    return max(0.35, min(2.2, x))


def test_humidity_factor_at_95_is_clamped_low():
    assert humidity_factor(95) == pytest.approx(0.85)


def test_humidity_factor_at_20_is_clamped_high():
    assert humidity_factor(20) == pytest.approx(1.30)


def test_humidity_factor_reference():
    assert humidity_factor(60) == pytest.approx(1.0)
    assert humidity_factor(33) == pytest.approx(1.27)


def test_light_factor_clamps_and_window():
    assert light_factor(15.6) == pytest.approx(1.25)  # summer clamps at the top
    assert light_factor(8.8) == pytest.approx((8.8 / 12.2) ** 1.5)
    assert light_factor(12.2, window_factor=1.10) == pytest.approx(1.10)
    assert light_factor(12.2, window_factor=0.85) == pytest.approx(0.85)
    assert light_factor(5.0) == pytest.approx(0.55)


def test_step_floors_at_zero():
    assert model.step(0.05, 0.10) == 0.0


# --- learning ---------------------------------------------------------------------------------


def test_still_wet_answer():
    r = apply_answer(B=0.0602, S=0.24, answer=ANSWER_STILL_WET)
    assert r.B_after == pytest.approx(0.0602 * 0.85)
    assert r.S_after == pytest.approx(0.34)
    assert r.watered is False


def test_still_wet_s_is_capped():
    r = apply_answer(B=0.06, S=0.48, answer=ANSWER_STILL_WET)
    assert r.S_after == pytest.approx(0.5)


def test_just_right_answer():
    r = apply_answer(B=0.0602, S=0.24, answer=ANSWER_JUST_RIGHT)
    assert r.B_after == pytest.approx(0.0602)
    assert r.S_after == 1.0
    assert r.watered is True


def test_bone_dry_answer():
    r = apply_answer(B=0.0602, S=0.24, answer=ANSWER_BONE_DRY)
    assert r.B_after == pytest.approx(0.0602 * 1.20)
    assert r.S_after == 1.0
    assert r.watered is True


def test_twenty_still_wet_answers_floor_B():
    B = B_REF
    for _ in range(20):
        B = apply_answer(B, 0.2, ANSWER_STILL_WET).B_after
        assert B >= 0.015
    assert B == pytest.approx(0.015)


def test_twenty_bone_dry_answers_cap_B():
    B = B_REF
    for _ in range(20):
        B = apply_answer(B, 0.2, ANSWER_BONE_DRY).B_after
        assert B <= 0.25
    assert B == pytest.approx(0.25)


def test_unknown_answer_raises():
    with pytest.raises(ValueError):
        apply_answer(0.05, 0.2, "maybe")


def test_hit_rate():
    assert model.hit_rate([]) is None
    assert model.hit_rate([ANSWER_JUST_RIGHT, ANSWER_STILL_WET, ANSWER_JUST_RIGHT, ANSWER_BONE_DRY]) == 0.5


# --- seeding ----------------------------------------------------------------------------------


def test_seed_terracotta_aroid_root_bound_clamps_G():
    assert pot_factor(1.6, 1.3, 1.3) == pytest.approx(2.00)
    assert seed_B_from_pot(1.6, 1.3, 1.3) == pytest.approx(0.116)


def test_seed_balanced_is_reference():
    assert seed_B(1.0, 1.0, 1.0) == pytest.approx(B_REF)


def test_seed_small_in_big_peat():
    assert pot_factor(1.0, 0.8, 0.7) == pytest.approx(0.56)
    assert seed_B_from_pot(1.0, 0.8, 0.7) == pytest.approx(0.058 * 0.56)


def test_seed_with_reported_interval_is_geometric_blend_within_bounds():
    b_pot = seed_B_from_pot(1.0, 1.0, 1.0)
    b_report = model.seed_B_from_interval(10, temp_c=24, rh=47, daylight_h=12.7)
    b = seed_B(1.0, 1.0, 1.0, reported_interval_days=10, temp_c=24, rh=47, daylight_h=12.7)
    assert b == pytest.approx(math.sqrt(b_pot * b_report))
    assert 0.015 <= b <= 0.25
    assert b != pytest.approx(b_pot)  # the report actually moved it


def test_seed_extreme_report_is_clamped():
    b = seed_B(1.6, 1.3, 1.3, reported_interval_days=0.1, temp_c=30, rh=30, daylight_h=15.5)
    assert b == 0.25
    b = seed_B(1.0, 0.8, 0.7, reported_interval_days=2000, temp_c=10, rh=90, daylight_h=8.8)
    assert b == 0.015


def test_seeded_extremes_reproduce_spec_table():
    # SPEC §6.6 seeded extremes, July and January reference conditions.
    fast = seed_B_from_pot(1.6, 1.3, 1.3)
    slow = seed_B_from_pot(1.0, 0.8, 0.7)
    assert predicted_interval_days(fast, 27, 50, 15.4) == pytest.approx(3.3, abs=0.1)
    assert predicted_interval_days(fast, 22, 33, 9.1) == pytest.approx(7.8, abs=0.2)
    assert predicted_interval_days(slow, 27, 50, 15.4) == pytest.approx(11.9, abs=0.2)
    assert predicted_interval_days(slow, 22, 33, 9.1) == pytest.approx(28.0, abs=0.5)


# --- days until threshold ---------------------------------------------------------------------


def test_days_until_threshold_summer():
    n = model.days_until_threshold(1.0, B_REF, temp_c=27, rh=50, start_day_of_year=196, lat_deg=LAT)
    assert 6 <= n <= 8


def test_days_until_threshold_already_dry():
    assert model.days_until_threshold(0.2, B_REF, 22, 50, 100, LAT) == 0


# --- gate (pure part; the wiring is covered in test_tick.py) ----------------------------------


def test_gate_fires_when_everything_holds():
    r = alert_gate(S=0.2, days_since_watered=8, month=7, temp_c=24, in_away_window=False, has_pending_alert=False)
    assert r.alert and not r.cold_warning


def test_gate_min_days_floor():
    r = alert_gate(0.2, 3, 7, 24, False, False)
    assert not r.alert and r.reason == "min_days"


def test_gate_winter_floor():
    r = alert_gate(0.2, 8, 1, 22, False, False)
    assert not r.alert and r.reason == "winter_min_days"
    assert alert_gate(0.2, 10, 1, 22, False, False).alert


def test_gate_cold():
    r = alert_gate(0.2, 12, 1, 11, False, False)
    assert not r.alert and r.cold_warning


def test_gate_away_and_pending():
    assert not alert_gate(0.2, 12, 7, 24, True, False).alert
    assert not alert_gate(0.2, 12, 7, 24, False, True).alert


def test_gate_not_dry():
    assert not alert_gate(0.26, 12, 7, 24, False, False).alert
