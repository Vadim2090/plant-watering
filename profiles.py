"""Species profiles and the seeding factor tables (SPEC.md §6.3).

One profile ships: Monstera deliciosa. The data model is ready for more; the horticultural
constants are not, and inventing them would be the one dishonest thing in this project.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from model import DEFAULT_PARAMS, WINDOW_FACTOR, ModelParams

# Setup answer -> multiplier. "unknown" always maps to the neutral factor.
MATERIAL_FACTOR = {"terracotta": 1.6, "plastic": 1.0, "unknown": 1.0}
SUBSTRATE_FACTOR = {"aroid_mix": 1.3, "potting_soil": 1.0, "peat_heavy": 0.8, "unknown": 1.0}
FIT_FACTOR = {"root_bound": 1.3, "balanced": 1.0, "small_in_big": 0.7, "unknown": 1.0}
LIGHT_FACTOR = dict(WINDOW_FACTOR)

# Wizard option -> reported interval in days. None = "don't know".
INTERVAL_DAYS = {"weekly": 7, "ten_days": 10, "two_weeks": 14, "less_often": 21, "unknown": None}

# Wizard option -> days ago. None = "don't remember" (SPEC §6.3: treated as 7 days).
LAST_WATERED_DAYS_AGO = {"today": 0, "yesterday": 1, "two_three_days": 3, "week": 7, "unknown": None}
UNKNOWN_LAST_WATERED_DAYS = 7


@dataclass(frozen=True)
class SpeciesProfile:
    key: str
    display_name: str
    params: ModelParams = field(default_factory=lambda: DEFAULT_PARAMS)


MONSTERA = SpeciesProfile(key="monstera_deliciosa", display_name="Monstera", params=DEFAULT_PARAMS)

PROFILES = {MONSTERA.key: MONSTERA}
DEFAULT_SPECIES = MONSTERA.key


def get_profile(species: str | None) -> SpeciesProfile:
    return PROFILES.get(species or "", MONSTERA)


def factors_for_setup(setup: dict) -> tuple[float, float, float]:
    """(material_f, substrate_f, fit_f) for a plant's `setup` dict. Unknown keys read as neutral."""
    return (
        MATERIAL_FACTOR.get(setup.get("pot_material") or "unknown", 1.0),
        SUBSTRATE_FACTOR.get(setup.get("substrate") or "unknown", 1.0),
        FIT_FACTOR.get(setup.get("fit") or "unknown", 1.0),
    )


def window_factor_for_setup(setup: dict) -> float:
    return LIGHT_FACTOR.get(setup.get("light") or "medium", 1.0)
