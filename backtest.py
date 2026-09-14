"""Backtest: a synthetic Belgrade year through the model (SPEC.md §12.3).

Runs before the bot ever sends anything. Indoor temperature follows a seasonal curve from 27 C in
mid-July to 22 C in mid-January (26-28 summer, 21-23 winter), relative humidity from 50% to 33%,
daylight computed from the date. For each month and each of the three seeded setups in §6.6 it
prints the predicted watering interval, and exits non-zero if the balanced setup misses the
acceptance window: July 6-8 days, January 14-18 days.

Usage: python backtest.py [--lat 44.8]
"""

from __future__ import annotations

import argparse
import calendar
import math
import sys
from datetime import date, timedelta

import model
from model import DEFAULT_PARAMS, DayConditions
from profiles import FIT_FACTOR, MATERIAL_FACTOR, SUBSTRATE_FACTOR

YEAR = 2026  # any non-leap year; only the day-of-year matters
PEAK_DOY = 196  # 15 July - the warm, humid end of the indoor curve; mid-January is the other end

SETUPS = [
    ("terracotta + aroid mix + root-bound", "terracotta", "aroid_mix", "root_bound"),
    ("plastic + potting soil + balanced", "plastic", "potting_soil", "balanced"),
    ("plastic + peat-heavy + small in big pot", "plastic", "peat_heavy", "small_in_big"),
]
BALANCED_INDEX = 1

ACCEPTANCE = {7: (6, 8), 1: (14, 18)}


def indoor_conditions(d: date, lat: float) -> DayConditions:
    """Synthetic indoor climate: a cosine between the July and January reference points."""
    doy = d.timetuple().tm_yday
    phase = math.cos(2 * math.pi * (doy - PEAK_DOY) / 365)
    temp_c = 24.5 + 2.5 * phase  # 27 in July, 22 in January
    rh = 41.5 + 8.5 * phase  # 50 in July, 33 in January
    return DayConditions(temp_c=temp_c, rh=rh, daylight_h=model.daylight_hours(doy, lat))


def simulate_interval(B: float, start: date, lat: float, max_days: int = 120) -> int:
    """Water on `start`, then count days until S is predicted to reach the threshold."""
    S, d = 1.0, start
    for n in range(1, max_days + 1):
        c = indoor_conditions(d, lat)
        S = model.step(S, model.daily_depletion(B, c.temp_c, c.rh, c.daylight_h))
        if S <= DEFAULT_PARAMS.alert_threshold:
            return n
        d += timedelta(days=1)
    return max_days


def floor_for_month(month: int) -> int:
    if month in DEFAULT_PARAMS.winter_months:
        return DEFAULT_PARAMS.winter_min_days
    return DEFAULT_PARAMS.min_days_between_waterings


def run(lat: float) -> bool:
    seeded = []
    for label, mat, sub, fit in SETUPS:
        G = model.pot_factor(MATERIAL_FACTOR[mat], SUBSTRATE_FACTOR[sub], FIT_FACTOR[fit])
        B = model.seed_B_from_pot(MATERIAL_FACTOR[mat], SUBSTRATE_FACTOR[sub], FIT_FACTOR[fit])
        seeded.append((label, G, B))

    print(f"Synthetic Belgrade year, lat {lat:.1f} N. Interval = days from a full pot to S <= "
          f"{DEFAULT_PARAMS.alert_threshold}, watered on the 1st, simulated day by day.")
    print("Values in [brackets] are floored by the §6.4 minimum-interval rule.\n")
    for label, G, B in seeded:
        print(f"  {label:<42} G = {G:.2f}  B_init = {B:.3f}")
    print()

    header = f"{'Month':<6}{'T °C':>6}{'RH %':>6}{'day h':>7}   " + "".join(
        f"{'setup ' + str(i + 1):>10}" for i in range(len(seeded))
    )
    print(header)
    print("-" * len(header))

    ok = True
    for month in range(1, 13):
        first = date(YEAR, month, 1)
        mid = date(YEAR, month, 15)
        c = indoor_conditions(mid, lat)
        cells = []
        for i, (_, _, B) in enumerate(seeded):
            raw = simulate_interval(B, first, lat)
            floor = floor_for_month(month)
            shown = f"[{floor}]" if raw < floor else str(raw)
            cells.append(f"{shown:>10}")
            if i == BALANCED_INDEX and month in ACCEPTANCE:
                lo, hi = ACCEPTANCE[month]
                if not (lo <= raw <= hi):
                    ok = False
                    cells[-1] += "  <-- FAIL"
        print(f"{calendar.month_abbr[month]:<6}{c.temp_c:>6.1f}{c.rh:>6.0f}{c.daylight_h:>7.2f}   " + "".join(cells))

    print()
    bal = seeded[BALANCED_INDEX]
    jul = simulate_interval(bal[2], date(YEAR, 7, 1), lat)
    jan = simulate_interval(bal[2], date(YEAR, 1, 1), lat)
    print(f"Acceptance (balanced setup): July {jul} d (need 6-8), January {jan} d (need 14-18) -> "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=44.8, help="latitude in degrees (default: Belgrade)")
    args = ap.parse_args()
    return 0 if run(args.lat) else 1


if __name__ == "__main__":
    sys.exit(main())
