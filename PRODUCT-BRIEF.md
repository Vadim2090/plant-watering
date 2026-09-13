# Plant Watering — product brief v0

> **Status: draft for review.** Nothing here is built yet. This document exists to be edited and
> approved before a spec is written. Open decisions are in §7.
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

## 6 · Scope

### In v1
- One plant profile: **Monstera deliciosa**, with the setup constants from §3.2
- The water-balance model, evaluated once daily
- Daylight computed from date + Belgrade latitude (no dependency, pure arithmetic)
- Temperature and humidity input — **source is open decision D2**
- One alert channel — **channel is open decision D1**
- The three-button feedback loop and the `B` recalibration
- A watering log (date, answer given, model state) as a local JSON file
- The four safety overrides from §3.4
- A visible accuracy counter — "last 10 alerts: 8 correct"

### Explicitly not in v1
- Multiple plants (unless D3 says otherwise) · fertilizer track · repotting reminders ·
  symptom decoder · photos and growth log · physical sensors · any cloud service or account ·
  any UI beyond the alert channel itself

### Non-functional
- **Runs unattended.** One scheduled job per day; no laptop-open requirement if D1 allows it
- **No account, no server bill.** Local state file, free weather API at most
- **Repo is English-only** and safe to make public — a plant-watering model is a clean, small public
  artifact, unlike the rest of `Personal Projects/`

---

## 7 · Open decisions — need Vadim

| # | Decision | Why it blocks | Default if unanswered |
|---|---|---|---|
| **D1** | **Where does the alert land?** Telegram bot · web/PWA · macOS notification · iOS app | Determines the entire stack and whether the reminder reaches a phone | Telegram — already wired into the AI OS, pushes to phone, zero UI work |
| **D2** | **Where does temperature come from?** Manual seasonal estimate · Open-Meteo API for Belgrade + an indoor offset · a real sensor | Winter indoor temp is decoupled from outdoor. An API alone is wrong exactly when the risk is highest | Hybrid: API + a manual indoor offset he corrects when it feels off |
| **D3** | **One plant or many?** | Changes the data model. Cheap now, expensive later | Multi-plant data model, Monstera as the only profile shipped |
| **D4** | **How much input is he willing to give?** Full loop (tap "watered" + answer the finger test) · minimal (just "watered") · zero | The loop is what makes the model better than a calendar. Without it, §1's target is unreachable | Full loop — three taps a fortnight |

### Assumptions already made (correct them if wrong)

1. Location is **Belgrade, 44.8 °N** — hardcoded for the daylight curve.
2. The apartment has **central heating in winter** and no AC-driven summer cooling — i.e. indoor temp
   is high in summer and moderate-warm in winter.
3. He is willing to run a scheduled job (cron / launchd / a cheap VPS — one already exists per
   `vps-status-dashboard`).
4. This is a **personal tool first**, portfolio artifact second. If it is meant to be a public
   portfolio piece, the README and the model documentation get a different register — say so.

---

## 8 · Candidate stacks, once D1 is answered

| If D1 is… | Stack | Effort | Runs when laptop is closed |
|---|---|---|---|
| **Telegram** | Node or Python script + Telegram Bot API + cron on the existing VPS | **Lowest** | ✅ |
| **Web / PWA** | Static page + local storage, or a tiny Node server; web push | Medium | ⚠️ push is fiddly on iOS |
| **macOS only** | Python + launchd + `osascript` notification | Low | ❌ |
| **iOS native** | Swift + local notifications + a tiny model in-app | Highest | ✅ |

In all four cases the model itself is the same ~150 lines and is written once, separately from the
delivery channel.

---

## 9 · What happens after approval

1. Vadim edits this file / answers §7 → approves
2. `SPEC.md` — data model, module boundaries, alert copy, test cases with expected intervals
3. Build, plus a backtest: run the model over a synthetic Belgrade year and check the predicted
   intervals are sane (roughly 6–8 days in July, 14–18 in January) before it ever sends an alert
