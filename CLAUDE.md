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

**Spec approved 2026-09-13. Implementation not started.** No code exists yet — `SPEC.md §11` names
the module layout to create.

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
