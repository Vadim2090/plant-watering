"""The water-balance model. Pure functions only.

This module imports nothing else from the project, reads no clock, does no I/O and mutates no
state. Every input is an argument. That boundary is what lets the test suite run without mocks.

The model (SPEC.md §6):

    S(0)   = 1.0                      full pot, right after watering to runoff
    S(t+1) = S(t) - D(t)              today's depletion
    D(t)   = B * T(t) * L(t) * H(t)
    alert when S(t) <= 0.25

`S` is the fraction of plant-available water remaining - an estimate, never a measurement.
`B` is the base daily depletion for this pot: the only parameter, and the only learned one.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import acos, asin, atan, cos, pi, radians, sin, sqrt, tan
from typing import Iterable, Sequence

# ---------------------------------------------------------------------------------------------
# Constants (SPEC.md §6). Anything species-specific lives in `ModelParams`, so a second species is
# a new params instance, not a new module.
# ---------------------------------------------------------------------------------------------

DAYLIGHT_NORMALISER_H = 12.2  # annual mean daylight at 44.8 N, see `daylight_hours`
REFERENCE_TEMP_C = 22.0
REFERENCE_RH = 60.0

WINDOW_FACTOR = {"bright": 1.10, "medium": 1.00, "low": 0.85}

ANSWER_STILL_WET = "still_wet"
ANSWER_JUST_RIGHT = "just_right"
ANSWER_BONE_DRY = "bone_dry"
ANSWERS = (ANSWER_STILL_WET, ANSWER_JUST_RIGHT, ANSWER_BONE_DRY)


@dataclass(frozen=True)
class ModelParams:
    """Species-level constants. Defaults are the Monstera deliciosa values from SPEC.md §6."""

    b_reference: float = 0.058  # base daily depletion of the reference pot
    b_min: float = 0.015
    b_max: float = 0.25
    alert_threshold: float = 0.25  # S at which the top 3-5 cm are predicted dry
    min_days_between_waterings: int = 4  # growing-season floor
    winter_min_days: int = 10  # dormancy floor
    winter_months: tuple[int, ...] = (11, 12, 1, 2)
    cold_temp_c: float = 12.0  # below this: cold warning, no watering alert
    dormancy_temp_c: float = 15.0  # below this: T is scaled by `dormancy_factor`
    dormancy_factor: float = 0.6
    t_min: float = 0.35
    t_max: float = 2.20
    l_min: float = 0.55
    l_max: float = 1.25
    h_min: float = 0.85
    h_max: float = 1.30
    g_min: float = 0.55  # combined pot factor floor
    g_max: float = 2.00  # combined pot factor ceiling
    still_wet_b_mult: float = 0.85
    still_wet_s_bump: float = 0.10
    still_wet_s_cap: float = 0.50
    bone_dry_b_mult: float = 1.20
    reported_interval_depletion: float = 0.75  # 1.0 - alert_threshold, the depletion an interval spans


DEFAULT_PARAMS = ModelParams()


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------------------------
# §6.1 Daylight
# ---------------------------------------------------------------------------------------------


def daylight_hours(day_of_year: int, lat_deg: float) -> float:
    """Day length in hours from the CBM model (Forsythe et al., 1995). Accurate to ~1 minute.

    At 44.8 N: 15.59 h on 21 June, 8.79 h on 21 December, annual mean 12.23 h.
    """
    P = asin(0.39795 * cos(0.2163108 + 2 * atan(0.9671396 * tan(0.00860 * (day_of_year - 186)))))
    lat = radians(lat_deg)
    x = (sin(radians(0.8333)) + sin(lat) * sin(P)) / (cos(lat) * cos(P))
    return 24 - (24 / pi) * acos(clamp(x, -1.0, 1.0))


# ---------------------------------------------------------------------------------------------
# §6.2 The factors
# ---------------------------------------------------------------------------------------------


def temperature_factor(temp_c: float, params: ModelParams = DEFAULT_PARAMS) -> float:
    """Evapotranspiration roughly doubles per +10 C (Q10 ~ 2), referenced to 22 C.

    Below `dormancy_temp_c` the result is scaled down further - a safety rule, not a curve:
    growth stalls, and wet roots in the cold are how a Monstera rots.
    """
    T = clamp(2 ** ((temp_c - REFERENCE_TEMP_C) / 10), params.t_min, params.t_max)
    if temp_c < params.dormancy_temp_c:
        T *= params.dormancy_factor
    return T


def light_factor(
    daylight_h: float, window_factor: float = 1.0, params: ModelParams = DEFAULT_PARAMS
) -> float:
    """Season through day length. The exponent is above 1 because winter costs sun angle and
    intensity as well as hours."""
    return clamp((daylight_h / DAYLIGHT_NORMALISER_H) ** 1.5 * window_factor, params.l_min, params.l_max)


def humidity_factor(rh: float, params: ModelParams = DEFAULT_PARAMS) -> float:
    """Drier air pulls water faster. Central heating drops a Belgrade flat to 30-35% RH."""
    return clamp(1 + (REFERENCE_RH - rh) / 100, params.h_min, params.h_max)


def daily_depletion(
    B: float,
    temp_c: float,
    rh: float,
    daylight_h: float,
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
) -> float:
    """D = B * T * L * H - today's loss as a fraction of the reservoir."""
    return (
        B
        * temperature_factor(temp_c, params)
        * light_factor(daylight_h, window_factor, params)
        * humidity_factor(rh, params)
    )


@dataclass(frozen=True)
class DayConditions:
    temp_c: float
    rh: float
    daylight_h: float


def step(S: float, D: float) -> float:
    """One day of depletion. `S` floors at 0.0."""
    return max(0.0, S - D)


def advance(
    S: float,
    B: float,
    days: Iterable[DayConditions],
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
) -> float:
    """Run the model forward one step per entry in `days`."""
    for day in days:
        S = step(S, daily_depletion(B, day.temp_c, day.rh, day.daylight_h, window_factor, params))
    return S


def predicted_interval_days(
    B: float,
    temp_c: float,
    rh: float,
    daylight_h: float,
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
) -> float:
    """Days from a full pot to the alert threshold if today's conditions held. The §6.6 number."""
    D = daily_depletion(B, temp_c, rh, daylight_h, window_factor, params)
    if D <= 0:
        return float("inf")
    return (1.0 - params.alert_threshold) / D


def days_until_threshold(
    S: float,
    B: float,
    temp_c: float,
    rh: float,
    start_day_of_year: int,
    lat_deg: float,
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
    max_days: int = 180,
) -> int:
    """Whole days from now until `S` is predicted to reach the threshold, holding today's
    temperature and humidity and letting daylight follow the calendar. 0 if already there."""
    if S <= params.alert_threshold:
        return 0
    doy = start_day_of_year
    for n in range(1, max_days + 1):
        doy = doy % 365 + 1
        S = step(S, daily_depletion(B, temp_c, rh, daylight_hours(doy, lat_deg), window_factor, params))
        if S <= params.alert_threshold:
            return n
    return max_days


# ---------------------------------------------------------------------------------------------
# §6.3 Seeding B
# ---------------------------------------------------------------------------------------------


def pot_factor(
    material_f: float, substrate_f: float, fit_f: float, params: ModelParams = DEFAULT_PARAMS
) -> float:
    """G - the combined pot factor, clamped."""
    return clamp(material_f * substrate_f * fit_f, params.g_min, params.g_max)


def seed_B_from_pot(
    material_f: float, substrate_f: float, fit_f: float, params: ModelParams = DEFAULT_PARAMS
) -> float:
    return params.b_reference * pot_factor(material_f, substrate_f, fit_f, params)


def seed_B_from_interval(
    reported_interval_days: float,
    temp_c: float,
    rh: float,
    daylight_h: float,
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
) -> float:
    """The user's usual interval, read as an independent estimate of B under today's factors."""
    TLH = (
        temperature_factor(temp_c, params)
        * light_factor(daylight_h, window_factor, params)
        * humidity_factor(rh, params)
    )
    return params.reported_interval_depletion / (reported_interval_days * TLH)


def seed_B(
    material_f: float,
    substrate_f: float,
    fit_f: float,
    reported_interval_days: float | None = None,
    temp_c: float | None = None,
    rh: float | None = None,
    daylight_h: float | None = None,
    window_factor: float = 1.0,
    params: ModelParams = DEFAULT_PARAMS,
) -> float:
    """B_init. Pot facts alone, or a geometric blend with the reported interval when there is one."""
    b_pot = seed_B_from_pot(material_f, substrate_f, fit_f, params)
    if reported_interval_days and temp_c is not None and rh is not None and daylight_h is not None:
        b_report = seed_B_from_interval(reported_interval_days, temp_c, rh, daylight_h, window_factor, params)
        b = sqrt(b_pot * b_report)
    else:
        b = b_pot
    return clamp(b, params.b_min, params.b_max)


# ---------------------------------------------------------------------------------------------
# §6.4 Alert gate
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    alert: bool
    cold_warning: bool
    reason: str  # why no alert fired; "" when it did


def alert_gate(
    S: float,
    days_since_watered: int,
    month: int,
    temp_c: float,
    in_away_window: bool,
    has_pending_alert: bool,
    params: ModelParams = DEFAULT_PARAMS,
) -> GateResult:
    """Fire only when every condition holds. Order matters only for the reason string."""
    if has_pending_alert:
        return GateResult(False, False, "pending_alert")
    if temp_c < params.cold_temp_c:
        return GateResult(False, True, "cold")
    if in_away_window:
        return GateResult(False, False, "away")
    if S > params.alert_threshold:
        return GateResult(False, False, "not_dry")
    if days_since_watered < params.min_days_between_waterings:
        return GateResult(False, False, "min_days")
    if month in params.winter_months and days_since_watered < params.winter_min_days:
        return GateResult(False, False, "winter_min_days")
    return GateResult(True, False, "")


# ---------------------------------------------------------------------------------------------
# §6.5 Learning
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AnswerResult:
    B_after: float
    S_after: float
    watered: bool


def apply_answer(B: float, S: float, answer: str, params: ModelParams = DEFAULT_PARAMS) -> AnswerResult:
    """The finger-test answer refits B. `B` is clamped after every update so one mis-tap cannot
    break the model."""
    if answer == ANSWER_STILL_WET:
        return AnswerResult(
            clamp(B * params.still_wet_b_mult, params.b_min, params.b_max),
            min(S + params.still_wet_s_bump, params.still_wet_s_cap),
            False,
        )
    if answer == ANSWER_JUST_RIGHT:
        return AnswerResult(clamp(B, params.b_min, params.b_max), 1.0, True)
    if answer == ANSWER_BONE_DRY:
        return AnswerResult(clamp(B * params.bone_dry_b_mult, params.b_min, params.b_max), 1.0, True)
    raise ValueError(f"unknown answer: {answer!r}")


def hit_rate(answers: Sequence[str]) -> float | None:
    """Share of answers that were `just_right` - the §1 metric. None when there is nothing to score."""
    if not answers:
        return None
    return sum(1 for a in answers if a == ANSWER_JUST_RIGHT) / len(answers)
