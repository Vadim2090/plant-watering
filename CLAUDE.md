# repo-plant-watering — agent instructions

A Telegram bot that predicts when a Monstera needs water from room temperature, humidity and the
Belgrade daylight curve, and refits itself from the user's answer to a finger test.

**Read in this order before touching anything:**

1. [`SPEC.md`](SPEC.md) — the build document. Written to be implemented cold. Authoritative.
2. [`PRODUCT-BRIEF.md`](PRODUCT-BRIEF.md) — the *why*: the problem, the model's derivation, the
   Monstera facts it encodes, and the decisions already closed. Read it to understand a choice in the
   spec; do not re-open a decision it records without saying so.

Where the two disagree, **`SPEC.md` is newer.**

---

## Status

**Built 2026-09-13 against SPEC v1.** `pytest` covers §12.1 and §12.2; `python backtest.py` passes
§12.3 (July 7 d, January 17 d). Not yet done from §13: a live end-to-end run in a real Telegram
chat (items 3–5) — the Telegram, Xiaomi cloud and vision paths are wired but have only been
exercised with fakes.

**Codex review 2026-09-13, 13 findings, all fixed** (94 tests). Two of them settled a spec reading —
do not re-open without saying so: the `/stats` metric is a share of *alerts* (an alert closed by
`/watered` stays in the denominator as "closed without a check"), and when setup gets no reading
from any source the plant is seeded from the pot facts alone with `last_tick_date` left on the
watering day, so the first real tick catches up instead of advancing `S` on invented data (§5.3
step 5).

**Photo step uses OpenAI, not Anthropic (2026-09-14).** `vision.py` calls OpenAI
(`gpt-4o-mini`, structured outputs) and the key is `PERSONAL_OPENAI_API_KEY`; SPEC §8 carries a
dated note. The step stays optional - absent key, it is skipped.

**Layout deviates from `SPEC.md §11` in two files:** `tick.py` holds the daily tick and the plant
operations shared by the wizard and the commands (so the §12.2 cases run without telebot), and
`context.py` holds `AppContext`, the object through which every side effect enters (clock, send,
sources, vision). `bot.py` is wiring only.

---

## Rules

1. **This repo is public.** MIT, self-hosted, single-household. Nothing personal goes in a tracked
   file: no tokens, no Mi account, no device ids, no home IP, no photos. `data/` and `.env` are
   gitignored and must stay that way.
2. **English only**, per the workspace rule — every `.md`, every code comment, every commit message.
   Verify with `grep -nP '[\x{0400}-\x{04FF}]' <file>` before saving.
   **One exception:** `locales/ru.py` holds Russian user-facing strings. That is UI data, not authored
   documentation, and it is the only file in the repo allowed to contain Cyrillic.
3. **`model.py` imports nothing else from this project.** Pure functions, every input an argument, no
   clock reads, no I/O. That boundary is what makes the test suite work without mocks — keep it.
4. **The backtest runs before the bot ever sends an alert.** `SPEC.md §12.3`. Coefficients that fail
   it are wrong, and the plant is the one that finds out.
5. **Never present a prediction as a fact.** The whole product rests on the alert being a question the
   user verifies. Copy that says "water now" instead of "check, then tell me" is a bug, not a style
   preference.
6. **Claim discipline in the README.** It is a public artefact. The model is a calibrated estimate
   with a measured hit rate — say exactly that, with the denominator, and no more.
