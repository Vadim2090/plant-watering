# Plant Watering — product brief v0

> **Status: draft for review, rev. 1.** Nothing here is built yet. This document exists to be
> edited and approved before a spec is written. The four framing decisions were answered on
> 2026-09-13 (§6); what is still open is in §10.
> Author: Claude · Date: 2026-09-13 · Owner: Vadim Smirnov

---

## 1 · The answer first

**This is not a reminder app. It is a small water-demand model with a reminder attached.**

A calendar reminder ("water every 7 days") is the thing that kills Monstera. Water demand in a
Belgrade apartment swings roughly **2.5× between July and January** — same plant, same pot. A fixed
interval is either too wet in winter or too dry in summer, and the too-wet failure mode is fatal.

So the product predicts, day by day, how much water is left in the pot, and fires **only** when the
substrate is predicted to be dry. Then it asks one question — *was it actually dry?* — and uses the
answer to recalibrate itself. After two or three watering cycles it is fitted to this specific pot,
this specific window, this specific apartment.

**Success = a single number: the share of alerts where the finger test agrees with the prediction.**
Target ≥ 80% after three cycles. Everything else in this document serves that number.

---

## 2 · The problem, stated honestly

| | |
|---|---|
| **Who** | One person, one Monstera deliciosa, one apartment in Belgrade |
| **Job** | "Tell me the day I should water, and be right about it" |
| **Failure mode today** | Watering on feel → irregular. Long gaps, then a corrective over-water |
| **Why it matters** | Root rot from overwatering is the #1 killer of Monstera deliciosa. Underwatering is recoverable; a rotted root ball usually is not |

### Why existing apps do not solve it

Every consumer plant app (Planta, Vera, Blossom) does one of two things: a fixed interval per
species, or a fixed interval with a crude season toggle. Neither reads the actual conditions in
*this* room, and none of them close the loop — they never ask whether they were right, so they never
get better. **The loop is the product.**

---

## 3 · The model

### 3.1 · Core idea — a water balance, not a countdown

The pot holds a reservoir of plant-available water. It starts full after a thorough watering and
depletes a little every day. The rate of depletion is what the conditions change.

```
S(0)   = 1.0                      # full pot, right after watering to runoff
S(t+1) = S(t) − D(t)              # today's depletion
D(t)   = B × T(t) × L(t) × H(t) × G

alert when S(t) <= 0.25           # top 3–5 cm dry — the Monstera "water now" point
```

- **`S`** — fraction of plant-available water remaining. Not a soil-moisture reading. An estimate.
- **`B`** — base daily depletion for this pot. **The only learned parameter.** Typical starting
  value 0.10–0.14 (a 7–10 day dry-down at reference conditions).
- **`D`** — today's loss, as a fraction of the reservoir.

### 3.2 · The factors

| Factor | Formula | Range | Rationale |
|---|---|---|---|
| **`T` temperature** | `2^((temp_C − 22) / 10)` | 0.35 – 2.2 | Evapotranspiration roughly doubles per +10 °C (Q10 ≈ 2). Reference 22 °C |
| **`T` cold override** | `× 0.6` when temp < 15 °C | — | Growth stalls. Wet + cold roots = rot. This is a safety rule, not a curve |
| **`L` light / season** | daylight hours at 44.8 °N, normalised, × window-brightness level | 0.55 – 1.25 | Belgrade: **15h 22m** daylight in late June vs **8h 47m** in late December. Computed from date + latitude — no sensor, no API |
| **`H` humidity** | `1 + (60 − RH%) / 100` | 0.85 – 1.30 | Drier air pulls water faster. Central heating in winter drops a Belgrade flat to 30–35% RH |
| **`G` pot & plant** | product of the constants below | ~0.6 – 2.5 | Fixed per setup, re-entered only after repotting |

**`G` components** — set once at setup:

| Component | Options | Multiplier |
|---|---|---|
| Pot material | Terracotta / unglazed | **1.6** |
| | Plastic, glazed ceramic, cachepot | **1.0** |
| Substrate | Chunky aroid mix (bark, perlite, coco) | **1.3** |
| | Standard potting soil | **1.0** |
| | Peat-heavy / water-retaining | **0.8** |
| Plant vs pot | Root-bound, many large leaves | **1.3** |
| | Balanced | **1.0** |
| | Small plant in an oversized pot | **0.7** ⚠️ highest rot risk |

### 3.3 · The learning loop — this is the part that matters

When the alert fires, the app does **not** say "water now". It says:

> *Predicted dry. Push a finger 3–5 cm into the soil — what do you find?*
> `[still wet]` · `[just barely dry]` · `[bone dry / drooping]`

| Answer | Action | Effect on `B` |
|---|---|---|
| Still wet | Snooze 2 days, ask again | `B × 0.85` — model was too fast |
| Just barely dry | Water now. Perfect hit | unchanged ✅ |
| Bone dry / drooping | Water now | `B × 1.20` — model was too slow |

`B` is clamped to [0.04, 0.30] so a single mis-tap cannot break the model. **Convergence: 2–3
cycles.** Logged every time, so the hit rate from §1 is measurable rather than felt.

### 3.4 · Hard safety rules that override the model

The model is a guess; these are not. They win over any computed date.

| Rule | Why |
|---|---|
| **Never alert sooner than 7 days after the last watering** | No plausible indoor condition dries a Monstera pot faster. A shorter interval means the model is broken, not the plant thirsty |
| **Never alert sooner than 10 days between 1 Nov and 28 Feb** | Dormancy + low light. Winter overwatering is the classic way to kill this plant |
| **If temp < 12 °C, suppress alerts entirely and warn** | Cold damage risk. Watering is not the problem to solve that week |
| **Alerts fire in the morning** | Watering in the evening leaves a cold wet root ball overnight |

---

## 4 · What the app must never pretend

Credibility is the whole asset here. Three explicit boundaries:

1. **It does not know the soil moisture.** It predicts it. Every alert is phrased as a prediction to
   verify, never as an instruction to obey.
2. **Low humidity is not thirst.** Brown crispy leaf edges in January mean dry *air*. Watering more
   at the roots in response is precisely how a healthy plant gets root rot. The app must say this out
   loud when it sees low RH plus a watering question.
3. **It does not diagnose disease.** Pests, fungus and rot get a "this is beyond what I can tell you
   from a watering schedule — here is what to look at" answer, not a confident verdict.

---

## 5 · Monstera deliciosa — the facts the app encodes

| Parameter | Value | Note |
|---|---|---|
| **Watering method** | Thoroughly, until water runs out of the drainage holes | Never a fixed small dose — that salts up the substrate and leaves dry pockets |
| **Dry-down target** | Top 3–5 cm dry before the next watering | Epiphytic aroid roots need air between waterings |
| **Saucer** | Empty within 30 minutes, always | Standing water = root rot. The single most important habit |
| **Temperature** | 18–30 °C ideal · below 12 °C causes damage | Tropical |
| **Light** | Bright indirect. No direct midday sun | Too dark → new leaves come out without fenestration (no splits) |
| **Humidity** | 50–60%+ preferred; tolerates 40% | Winter heating drops a flat to 30–35% |
| **Fertilizer** | Mar–Sep, every 2–4 weeks, balanced NPK at **half** strength | **None Oct–Feb.** Feeding a dormant plant burns roots |
| **Repotting** | Every 18–24 months, in spring, one pot size up | Fresh chunky aroid mix |
| **Support** | Moss pole / coir pole once mature | Aerial roots attach and leaves get larger |
| **Toxicity** | Calcium oxalate — irritant to cats, dogs and children | Worth one line in the app |

### Symptom decoder — proposed as a second screen, not v1

| Symptom | Most likely cause | ⚠️ Not this |
|---|---|---|
| Lower leaves yellow, soft | **Overwatering** | Not fertilizer deficiency |
| Brown crispy tips and edges | Low humidity, or chronic underwatering | Not overwatering |
| Black mushy stem base, sour smell | **Root rot — urgent** | Stop watering, unpot, cut rot |
| Whole plant drooping, soil dry | Underwatering | Recovers within hours of a thorough soak |
| New leaves solid, no splits | **Too little light** | Not a watering problem at all |
| Sticky residue, fine webbing | Pests (scale / spider mites) | Outside this app's scope |

---

## 6 · Decisions — answered 2026-09-13

| # | Decision | Answer |
|---|---|---|
| **D1** | Alert channel | **Telegram bot.** Already wired into the AI OS, pushes to the phone, and the three feedback buttons are native inline keyboards — no UI to build |
| **D2** | Environment data | **Xiaomi Smart Air Purifier 4 Pro**, read directly. See §7 — this is now the most interesting part of the build, and it opens one sub-question |
| **D3** | Scope | **Multi-plant data model, one profile shipped (Monstera).** Adding a ficus later is a config entry, not a refactor |
| **D4** | Feedback | **Full loop.** Finger test on every alert, three-button answer, `B` recalibrates |

**D2 is a genuinely better answer than the hybrid I proposed.** A weather API plus a guessed indoor
offset is a model of the apartment; the purifier is a thermometer *in* the apartment. It removes the
single largest source of error in §3, which was the winter case: outdoor −2 °C while the room sits at
23 °C on radiators.

---

## 7 · The sensor — Xiaomi Smart Air Purifier 4 Pro

### 7.1 · What it gives, and that it is reachable

The Air Purifier 4 Pro is model **`zhimi.airp.vb4`**, and it is supported by
[python-miio](https://python-miio.readthedocs.io/en/latest/api/miio.integrations.zhimi.airpurifier.airpurifier_miot.html)
via the `AirPurifierMiot` class over Xiaomi's MIoT protocol. It exposes, among other properties:

| Property | Used for |
|---|---|
| `temperature` | **`T` factor** — replaces the weather API entirely |
| `humidity` | **`H` factor** — replaces the estimate entirely |
| `fan_level` / `mode` | Candidate **`F` factor**, see §7.4. Not in v1 |
| `aqi` (PM2.5), PM10 | Not used. Interesting, irrelevant to watering |

This is a **local network** protocol, not a cloud API. It needs two things: the device's **LAN IP**
and its **32-character device token**. That has one consequence that shapes the whole architecture —
§8.

> ⚠️ **Vadim does the token extraction himself.** It is pulled from the Xiaomi account with the
> standard `Xiaomi-cloud-tokens-extractor` tool, which wants the Mi account login. I do not touch
> those credentials at any point. The token goes into `.env`, which is already gitignored.

### 7.2 · Two things to verify before writing a line of code

1. **Is the purifier in the same room as the Monstera?** If it is in the bedroom and the plant is in
   the living room, the reading is precise and wrong. Same room, and ideally not blowing directly at
   the plant.
2. **Does its temperature reading match reality?** Sensors mounted inside a running appliance sit
   near their own electronics and in their own airflow, and typically read warm. Before trusting it:
   put any independent thermometer next to the purifier for an hour and compare. Whatever the gap
   is, it becomes a fixed `sensor_offset_c` in the config.

   This matters more than it sounds. `T` doubles per +10 °C, so a **+2 °C** sensor bias inflates
   every daily depletion estimate by about **15%** — which is the difference between a 12-day and a
   14-day winter interval, in exactly the season where erring wet is how the plant dies.

   Mitigating detail: the §3.3 feedback loop absorbs a constant bias anyway, because `B` moves to
   compensate. So a wrong offset costs accuracy for two or three cycles, not forever. Calibrate
   anyway — it makes the first month right instead of the second.

### 7.3 · Failure handling — the sensor will be unreachable sometimes

Purifier off, unplugged, moved, Wi-Fi rebooted, token rotated. The model must degrade, not stop:

| Reading age | Behaviour |
|---|---|
| < 36 h | Use it. Normal operation |
| 36 h – 7 days | Use the last known value, unchanged. Indoor temperature in a heated flat moves slowly; this costs almost nothing |
| > 7 days | Fall back to a seasonal default for Belgrade, and **say so in the alert**: "running without a sensor reading since \<date\>" |
| Reading out of plausible range (< 5 °C or > 40 °C, RH < 10% or > 95%) | Discard, treat as missing. A sensor fault must never become a watering decision |

### 7.4 · A free extra the purifier makes possible — not v1

We are already reading the device state, so `fan_level` is available at no cost. A purifier running
on high moves air across the leaves, which raises transpiration. Physically real, probably a
5–15% effect, and entirely swamped by `B` recalibration if the fan setting is steady.

**Deliberately excluded from v1.** It is only worth adding if the logged data later shows that alert
accuracy is worse in weeks when the fan ran hard. That is a question the accuracy log can answer on
its own, which is the right reason to add a factor rather than a plausible story about airflow.

---

## 8 · Architecture — the one thing still open

**The conflict:** D1 wants alerts that arrive whether or not the laptop is open. D2's sensor is on
the home LAN and cannot be read from a VPS. Those pull in opposite directions.

| | **A · Mac only** *(recommended for v1)* | **B · Split: Mac collects, VPS alerts** |
|---|---|---|
| Where the model runs | Mac, `launchd`, once a day | Existing VPS, cron |
| How the reading arrives | Direct LAN poll of the purifier | Mac polls the purifier, POSTs the reading to the VPS |
| Telegram button taps | Collected by `getUpdates` polling on the next run — **no webhook, no always-on listener** | Webhook or long-poll on the VPS |
| Moving parts | One script, one plist, one JSON file | Two services, one endpoint, one shared secret |
| Fails when | The Mac is closed for days | Almost never |
| Effort | ~1 evening | ~2–3× that |

**Recommendation: A.** It is the whole product in one script, with direct access to the sensor and
no infrastructure. `launchd` runs a missed daily job at the next wake, so a morning alert lands when
the laptop opens — which is when he would water anyway.

**The known hole in A, stated plainly:** **7–17 November**, ten days in Germany and Austria with the
laptop presumably closed at least part of it. That is one missed watering window. Two honest ways to
handle it without building B: the model can fire an early "you are about to travel, water it
thoroughly before you go" alert from a manually entered away-window, and can suppress alerts during
it. That is ten lines of code instead of a second service.

**B is a clean upgrade, not a rewrite** — the collector/model split is in the design from day one,
so promoting it later means changing where two functions run, not restructuring anything.

---

## 9 · Scope

### In v1
- Telegram bot: one daily check, alert + three inline buttons, plus a `/watered` command
- The §3 water-balance model, evaluated once daily
- Daylight from date + Belgrade latitude — pure arithmetic, no dependency
- Temperature and humidity from the Air Purifier 4 Pro, with `sensor_offset_c` and the §7.3 fallback ladder
- Plant profiles as data (multi-plant capable); **Monstera deliciosa is the only profile shipped**
- The §3.3 feedback loop and `B` recalibration
- The four §3.4 safety overrides
- A local JSON log: every reading, every alert, every answer, every `B` change
- `/stats` — the accuracy counter from §1, so the model can be judged instead of trusted
- An away-window (§8) so the November trip does not silently break the record

### Explicitly not in v1
Fertilizer track · repotting reminders · the §5 symptom decoder · the `F` airflow factor · photos
and growth log · charts · any web UI · any second plant profile · any cloud account beyond Telegram

### Non-functional
- **Python 3.11+** in a venv — `python-miio` needs it, and the system Python here is 3.9.6
- Dependencies kept to `python-miio` and one Telegram client. The model itself is stdlib arithmetic
- Secrets in `.env` — Telegram token, device token, device IP. Never in a tracked file
- **Repo is English-only and safe to publish.** A calibrated water-demand model with a documented
  accuracy metric is a decent small public artifact; there is nothing confidential in it

---

## 10 · Open questions for Vadim

1. **Architecture A or B?** §8. Recommendation is A.
2. **Is the purifier in the same room as the Monstera?** §7.2. If not, the whole D2 answer weakens
   and the hybrid from the original D2 comes back.
3. **Pot facts, for `G` in §3.2** — material (terracotta or plastic/glazed), rough diameter,
   substrate (chunky aroid mix or normal potting soil), and how the plant sits in it (root-bound,
   balanced, or small plant in a big pot). Guessing these costs two or three extra calibration
   cycles; a 30-second answer removes that.
4. **When was it last watered, and roughly how often have you been watering it?** Seeds `B` near the
   truth instead of at a generic default, and starts the log with a real state instead of an empty one.
5. **Public repo or private?** Affects the README's register, nothing else. Default: build it
   publishable, decide at push time.

---

## 11 · What happens after approval

1. Vadim edits this file / answers §10 → approves
2. `SPEC.md` — data model, module boundaries, the exact Telegram copy, config schema, and test cases
   with expected intervals
3. Build, then a **backtest before it ever sends an alert**: run the model over a synthetic Belgrade
   year and confirm the predicted intervals are sane — roughly **6–8 days in July, 14–18 in January**.
   If the backtest disagrees with that, the coefficients are wrong and the plant never finds out
