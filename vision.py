"""The onboarding photo step (SPEC.md §8): one vision call that proposes the pot facts.

Deviation from SPEC §8, chosen 2026-09-14: the call goes to OpenAI (structured outputs), not
Anthropic, because that is the API key available. The purpose is unchanged - collapse the pot
questions into one confirmation tap. Every extracted field is a proposal the user confirms or
overrides, and `unclear` is a first-class answer. Any failure returns None and the wizard falls
through to the manual questions.
"""

from __future__ import annotations

import base64
import json
import logging

log = logging.getLogger("plant.vision")

# Vision-capable and cheap: one image is a fraction of a cent, once per plant. Change here if you
# want a stronger model. Must support image input and json_schema structured outputs.
MODEL = "gpt-5.4-mini"

PLANT_PHOTO_SCHEMA = {
    "type": "object",
    "properties": {
        "species_guess": {"type": "string", "enum": ["monstera_deliciosa", "other", "unclear"]},
        "pot_material": {"type": "string", "enum": ["terracotta", "plastic", "unclear"]},
        "pot_diameter_cm": {"type": ["integer", "null"]},
        "substrate": {"type": "string", "enum": ["aroid_mix", "potting_soil", "peat_heavy", "unclear"]},
        "fit": {"type": "string", "enum": ["root_bound", "balanced", "small_in_big", "unclear"]},
        "mature_leaf_count": {"type": ["integer", "null"]},
        "notes": {"type": "string"},
    },
    "required": ["species_guess", "pot_material", "pot_diameter_cm", "substrate", "fit",
                 "mature_leaf_count", "notes"],
    "additionalProperties": False,
}

PHOTO_PROMPT = """You are helping set up a houseplant watering model. Look at this photo of a plant in
its pot and fill in the schema.

Rules:
- Answer "unclear" (or null for numbers) whenever you cannot actually see the evidence. Do not
  guess. A wrong confident answer is worse than "unclear"; the user will be asked the question
  directly.
- pot_material: "terracotta" only for unglazed clay. Glazed ceramic, plastic, metal and cachepots
  are all "plastic" for this purpose (they do not breathe).
- substrate: only judge from visible substrate. If the surface is covered by a top dressing
  (pebbles, moss, bark chips) or is not visible, answer "unclear". "aroid_mix" means a chunky mix
  with visible bark or perlite; "peat_heavy" means fine, dark, dense soil.
- pot_diameter_cm: an estimate is only possible with a reference object in frame (a hand, a
  window sill, a chair). Without one, answer null.
- fit: "root_bound" when the plant clearly fills or overflows the pot (large canopy, roots at the
  surface or out of the drainage holes); "small_in_big" when the plant is visibly small for the
  pot; otherwise "balanced"; "unclear" if you cannot see the pot in relation to the plant.
- mature_leaf_count: count only fully opened leaves; null if the plant is not fully visible.
- notes: one plain sentence for the user, saying what you could and could not tell. Mention
  explicitly any field you answered "unclear" and why."""


def analyze_photo(api_key: str, jpeg_bytes: bytes) -> dict | None:
    """Returns the proposal dict, or None on any failure (no key, network, refusal, bad JSON)."""
    if not api_key or not jpeg_bytes:
        return None
    try:
        import openai

        client = openai.OpenAI(api_key=api_key)
        b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
        response = client.chat.completions.create(
            model=MODEL,
            max_completion_tokens=1024,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PHOTO_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
            ]}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "plant_photo", "schema": PLANT_PHOTO_SCHEMA, "strict": True},
            },
        )
        message = response.choices[0].message
        if getattr(message, "refusal", None):
            log.warning("vision call refused")
            return None
        text = message.content
        if not text:
            return None
        data = json.loads(text)
        for key in PLANT_PHOTO_SCHEMA["required"]:
            if key not in data:
                return None
        return data
    except Exception as e:
        log.warning("vision call failed: %s", type(e).__name__)
        return None
