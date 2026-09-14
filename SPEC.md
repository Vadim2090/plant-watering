# Plant Watering — technical spec v1

> **This is the build document.** It is written to be implemented cold, by a session that has not
> seen the conversation behind it. The *why* lives in [`PRODUCT-BRIEF.md`](PRODUCT-BRIEF.md); this
> file is the *what* and the *how*, and where the two disagree, this one is newer.
> Date: 2026-09-13 · Owner: Vadim Smirnov · Status: **approved for build**

---

## 1 · What is being built, in one paragraph

A Telegram bot that predicts, day by day, how much water is left in a Monstera's pot — from the room
temperature and humidity reported by a Xiaomi Smart Air Purifier 4 Pro, plus the Belgrade daylight
curve — and alerts once the substrate is predicted to be dry. The alert is a *question*, not an
instruction: the user checks with a finger and answers one of three buttons, and that answer refits
the model's single parameter. Setup happens entirely inside a Telegram wizard, optionally seeded by a
photo of the plant. Everything runs as one process on a VPS.

**The success metric is the share of alerts answered "just barely dry" — target ≥ 80% after three
watering cycles.** It is reported by `/stats`. A build that cannot report this number is not done.

---

## 2 · Architecture

One Python process, one systemd unit, one JSON state file. All network traffic is outbound.

```
   Xiaomi cloud (micloud)  ──HTTPS out, 1/day──┐
   Open-Meteo (fallback)   ──HTTPS out────────►│
                                               ▼
   Telegram  ◄──long-poll getUpdates, HTTPS out──►  bot process
                                               │        │
                                               ▼        ▼
                                     data/state.json   data/photos/
```

**Two loops in one process:**

| Loop | Trigger | Work |
|---|---|---|
| **Conversation** | `getUpdates` long-poll, 30 s timeout | Onboarding wizard, command handling, button callbacks |
| **Daily tick** | A background thread; fires at **09:00 Europe/Belgrade** | Read the sensor, advance `S` for every plant, send alerts |

**No webhook, no inbound port, no TLS certificate, no reverse proxy.** Long-polling is a deliberate
choice: it removes the entire public-surface problem, and the bot serves one household.

**Missed ticks.** The tick thread persists `last_tick_date` per plant. On start-up, and on every
tick, it advances the model once per *calendar day* elapsed since `last_tick_date`, using the best
reading available for each of those days (in practice: the current reading). A process that was down
for three days catches up on restart rather than losing three days of depletion.

### Library choices

| Need | Choice | Why |
|---|---|---|
| Telegram | **`pyTelegramBotAPI`** (`telebot`) | Synchronous. No async colouring through the whole codebase for a bot that handles a handful of messages a day |
| Xiaomi cloud | **`micloud`** | ~40 lines to a reading. See §5.1 |
| Weather fallback | **`requests`** against Open-Meteo | No key, no account, one GET |
| Vision | **`anthropic`** | §8 |
| Scheduling | **`threading.Thread` + a sleep loop** | A cron dependency for one daily job is not worth a second deployment artefact |

**Do not reach for a conversation framework.** The wizard is a explicit state machine over inline
buttons (§7); every callback carries its step, and the step lives in the state file. That is ~40
lines and it survives a restart mid-onboarding, which a framework's in-memory handler chain does not.

---

## 3 · Configuration

`.env`, loaded at start-up, validated loudly — a missing required key aborts start-up with a message
naming the key. Ship `.env.example` with these names and no values.

| Key | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | **yes** | From @BotFather |
| `ALLOWED_CHAT_IDS` | no | Comma-separated. Empty = anyone can use this instance. **Set it.** |
| `BOT_LOCALE` | no | `en` (default) or `ru` |
| `XIAOMI_USERNAME` · `XIAOMI_PASSWORD` | no | Mi account. Absent → the Xiaomi source is not offered |
| `XIAOMI_REGION` | no | Default `de` (the EU server). Others: `cn`, `ru`, `sg`, `us`, `i2` |
| `XIAOMI_DEVICE_ID` | no | The `did` from `get_devices()`. Resolved once during onboarding and written back to `.env` is **not** done — it is stored in the state file |
| `ANTHROPIC_API_KEY` | no | Absent → the onboarding photo step is skipped entirely |
| `LATITUDE` · `LONGITUDE` | no | Default `44.8` / `20.5` (Belgrade) |
| `TIMEZONE` | no | Default `Europe/Belgrade` |
| `ALERT_HOUR` | no | Default `9` |
| `STATE_PATH` | no | Default `data/state.json` |

**Secrets never leave `.env`.** The file is gitignored; the repo is public. `.env` should be
`chmod 600`. Nothing in the log lines may contain a token, a password, or a device id.

---

## 4 · Data model

One JSON file, written atomically (`write temp → os.replace`). Every write goes through
`state.save()`; nothing else touches the file. A `schema_version` integer sits at the top so a later
migration has something to branch on.

```jsonc
{
  "schema_version": 1,
  "users": {
    "<chat_id>": {
      "locale": "en",
      "created_at": "2026-09-13T09:00:00+02:00",
      "onboarding": { "step": "done", "draft": {} },
      "env_source": {
        "type": "xiaomi_cloud",          // or "weather"
        "device_id": "123456789",
        "offset_c": 0.0,                  // see PRODUCT-BRIEF §6 — stays 0.0 unless /stats says otherwise
        "city": null,                     // only for type "weather"
        "last_reading": {
          "temp_c": 24.3, "rh": 47, "at": "2026-09-13T09:00:02+02:00", "source": "xiaomi_cloud"
        }
      },
      "away": { "from": "2026-11-07", "to": "2026-11-17", "prewarned": false },
      "plants": [
        {
          "id": "monstera-1",
          "name": "Monstera",
          "species": "monstera_deliciosa",
          "photo_path": "data/photos/<chat_id>/monstera-1.jpg",
          "setup": {
            "pot_material": "plastic",     // terracotta | plastic | unknown
            "pot_diameter_cm": 24,
            "substrate": "aroid_mix",      // aroid_mix | potting_soil | peat_heavy | unknown
            "fit": "balanced",             // root_bound | balanced | small_in_big | unknown
            "light": "bright",             // bright | medium | low
            "reported_interval_days": 10   // or null
          },
          "B": 0.0602,
          "S": 0.63,
          "last_watered": "2026-09-10",
          "last_tick_date": "2026-09-13",
          "pending_alert": { "sent_at": "...", "S_at_alert": 0.24 },   // or null
          "history": [
            { "date": "2026-09-10", "event": "watered", "via": "command" },
            { "date": "2026-09-22", "event": "alert", "S": 0.24 },
            { "date": "2026-09-22", "event": "answer", "answer": "just_right",
              "B_before": 0.0602, "B_after": 0.0602 }
          ]
        }
      ]
    }
  }
}
```

**`history` is append-only and is the evidence base** for `/stats` and for any later question about
whether a factor earns its place. Do not trim it; a decade of one plant is a few hundred KB.

---

## 5 · Environment readings

```python
class EnvSource(ABC):
    def read(self) -> Reading | None: ...   # Reading = (temp_c: float, rh: int, source: str)
```

Two implementations. Nothing above this interface knows which one is live — that is what makes the
LAN version, or Xiaomi's OAuth cloud, a one-class change later.

### 5.1 · `XiaomiCloudSource`

Uses [`micloud`](https://github.com/Squachen/micloud). Login with the Mi account, then read MIoT
properties for the device. Property addresses for **`zhimi.airp.vb4`** (Smart Air Purifier 4 Pro),
from [the MIoT spec](https://home.miot-spec.com/spec/zhimi.airp.vb4):

| Reading | siid | piid |
|---|---|---|
| `temperature` (float, °C) | **3** | **7** |
| `relative-humidity` (uint8, %) | **3** | **1** |
| `on` (bool — liveness) | 2 | 1 |

`XIAOMI_REGION` defaults to `de`, the EU server — a wrong region returns an empty device list, not an
error, so **treat "device not found" as a region problem first**. The device id is resolved once
during onboarding via `get_devices()` and stored in state.

Log in once and keep the session; re-login on auth failure with a single retry and a backoff. Do not
poll more than a handful of times a day — this is an unofficial path and there is no reason to lean
on it.

### 5.2 · `WeatherSource` (fallback, and the path for anyone without a purifier)

Open-Meteo, no key: `GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&daily=temperature_2m_mean,relative_humidity_2m_mean&timezone=auto&past_days=1`.

Outdoor readings are converted to an indoor *estimate* — crude, and labelled as such everywhere it
surfaces:

```
if outdoor_mean_c >= 18:  indoor_c = outdoor_mean_c + 2      # warm flat, windows open
else:                     indoor_c = 22                       # heating season, thermostat wins
if outdoor_mean_c < 12:   indoor_rh = 35                      # central heating dries the air
else:                     indoor_rh = clamp(outdoor_rh, 35, 65)
```

### 5.3 · The ladder

Applied on every tick, in order:

1. Call the configured source. If it returns a reading, **validate**: `5 ≤ temp_c ≤ 40` and
   `10 ≤ rh ≤ 95`. Out of range → discard as a sensor fault, fall through.
2. A valid reading → apply `offset_c`, store as `last_reading`, use it. `degraded = false`.
3. No valid reading, `last_reading` **younger than 7 days** → reuse it unchanged. `degraded = false`.
   Indoor temperature in a heated flat moves slowly; this genuinely costs nothing.
4. No valid reading, `last_reading` **older than 7 days or absent** → `WeatherSource`.
   **`degraded = true`**, and every alert sent that day carries a line saying the sensor has been
   unreachable since `<date>`.
5. Even the fallback fails → skip the tick entirely. Do not advance `S` on invented data, and do not
   alert. Log it.

---

## 6 · The model

Pure functions in `model.py`. No I/O, no state mutation, no clock reads — every input is an argument.
This is the part that gets unit-tested, and it is the reason the module boundary is strict.

### 6.1 · Daylight

CBM model (Forsythe et al., 1995), accurate to about a minute — no ephemeris dependency:

```python
def daylight_hours(day_of_year: int, lat_deg: float) -> float:
    P = asin(0.39795 * cos(0.2163108 + 2*atan(0.9671396*tan(0.00860*(day_of_year - 186)))))
    lat = radians(lat_deg)
    x = (sin(radians(0.8333)) + sin(lat)*sin(P)) / (cos(lat)*cos(P))
    return 24 - (24/pi) * acos(clamp(x, -1.0, 1.0))
```

At 44.8 °N this gives **15.592 h** on 21 June, **8.787 h** on 21 December, and an annual mean of
**12.228 h** — which is where the `12.2` normaliser below comes from.

### 6.2 · The factors

```python
T = clamp(2 ** ((temp_c - 22) / 10), 0.35, 2.20)
if temp_c < 15: T *= 0.6                                   # dormancy, a safety rule not a curve
L = clamp((daylight_hours / 12.2) ** 1.5 * window_factor, 0.55, 1.25)
H = clamp(1 + (60 - rh) / 100, 0.85, 1.30)

D = B * T * L * H
S_next = S - D
```

`window_factor`: `bright` → 1.10, `medium` → 1.00, `low` → 0.85.

### 6.3 · Seeding `B`

```python
G = clamp(material_f * substrate_f * fit_f, 0.55, 2.00)
B_from_pot = 0.058 * G
```

| Component | Value | Factor |
|---|---|---|
| `pot_material` | `terracotta` | 1.6 |
| | `plastic`, `unknown` | 1.0 |
| `substrate` | `aroid_mix` | 1.3 |
| | `potting_soil`, `unknown` | 1.0 |
| | `peat_heavy` | 0.8 |
| `fit` | `root_bound` | 1.3 |
| | `balanced`, `unknown` | 1.0 |
| | `small_in_big` | 0.7 |

If the user also reported a usual watering interval, that is a second, independent estimate of the
same quantity — blend them geometrically rather than picking one:

```python
if reported_interval_days:
    B_from_report = 0.75 / (reported_interval_days * T_today * L_today * H_today)
    B_init = sqrt(B_from_pot * B_from_report)
else:
    B_init = B_from_pot
B_init = clamp(B_init, 0.015, 0.25)
```

**Initial `S`**, from the reported last watering: start at `1.0` on `last_watered` and run the tick
forward to today with today's conditions. "Don't remember" → `last_watered = today - 7` and `S`
computed from that.

### 6.4 · Alert gate

Fire an alert only when **all** of these hold:

| Condition | |
|---|---|
| `S <= 0.25` | The model says dry |
| `days_since_last_watered >= 4` | Growing-season floor |
| `days_since_last_watered >= 10` **if month in {11, 12, 1, 2}** | Winter floor. Overwatering a dormant Monstera is the classic way to kill it |
| `temp_c >= 12` | Below this, send a **cold warning instead** and suppress the watering alert |
| `not in away window` | §9.3 |
| `pending_alert is None` | Never stack two unanswered alerts |

### 6.5 · Learning

On the answer to a pending alert:

| Answer | `B` | `S` | Watering recorded |
|---|---|---|---|
| `still_wet` | `× 0.85` | `min(S + 0.10, 0.5)` | no |
| `just_right` | unchanged | `1.0` | **yes** |
| `bone_dry` | `× 1.20` | `1.0` | **yes** |

`B` clamped to `[0.015, 0.25]` after every update. `pending_alert` cleared. Both the answer and the
`B` transition are appended to `history`.

There is no separate snooze state. `still_wet` nudges `S` back up by about two days' worth, and the
next alert arrives on its own when it falls again — which is both simpler and more honest than a
fixed timer.

### 6.6 · Reference intervals — the numbers the build must reproduce

With `B = 0.058` and a threshold of `S ≤ 0.25` (a depletion of 0.75):

| Conditions | `T` | `L` | `H` | `D`/day | Interval |
|---|---|---|---|---|---|
| **July** — 27 °C, 50% RH, 15.4 h | 1.414 | 1.250 | 1.100 | 0.1128 | **6.6 d** |
| **April** — 22 °C, 45% RH, 12.9 h | 1.000 | 1.155 | 1.150 | 0.0771 | **9.7 d** |
| **October** — 23 °C, 50% RH, 11.4 h | 1.072 | 0.863 | 1.100 | 0.0590 | **12.7 d** |
| **January** — 22 °C, 33% RH, 9.1 h | 1.000 | 0.649 | 1.270 | 0.0478 | **15.7 d** |

Seeded extremes, same reference conditions:

| Setup | `G` | `B_init` | July | January |
|---|---|---|---|---|
| Terracotta + aroid mix + root-bound | 2.70 → clamped **2.00** | 0.116 | 3.3 d → **floored to 4** | 7.8 d → **floored to 10** |
| Plastic + potting soil + balanced | 1.00 | 0.058 | 6.6 d | 15.7 d |
| Plastic + peat + small plant in a big pot | 0.56 | 0.033 | 11.9 d | **28.0 d** |

That last row is not a bug. A small Monstera in an oversized peat-heavy pot in January genuinely
should go about a month, and it is the exact configuration that dies of root rot when a calendar app
says "day 7".

---

## 7 · Onboarding

`/start` on an unknown `chat_id` (or `/setup` on a known one) opens the wizard. **Every step is
inline buttons except the city**, and every step writes `onboarding.draft` + `onboarding.step` to
state before waiting — so a restart mid-wizard resumes where it left off rather than starting over.

Every question carries a **`Don't know`** option that maps to the neutral factor. Guessing is what
the feedback loop is for; making the user guess at setup is not.

| # | Step key | Prompt | Options |
|---|---|---|---|
| 0 | `welcome` | What this bot does, in three lines. Then: *send a photo of your plant in its pot, or skip* | `[Skip the photo]` |
| 1 | `photo_review` | Only if a photo arrived and `ANTHROPIC_API_KEY` is set. §8 proposes the facts; show them as a summary | `[That's right]` `[Let me correct it]` |
| 2 | `pot_material` | What is the pot made of? | `Terracotta / unglazed` · `Plastic or glazed` · `Don't know` |
| 3 | `pot_diameter` | Roughly how wide is the pot at the top? | `Under 20 cm` · `20–30` · `30–40` · `Over 40` · `Don't know` |
| 4 | `substrate` | What is it planted in? | `Chunky mix — bark, perlite` · `Regular potting soil` · `Dense / peat-heavy` · `Don't know` |
| 5 | `fit` | How does the plant sit in the pot? | `Roots fill it / it's tight` · `About right` · `Small plant, big pot` · `Don't know` |
| 6 | `light` | How much light does it get? | `Bright — right by a window` · `Medium` · `Dim — far from a window` |
| 7 | `last_watered` | When did you last water it? | `Today` · `Yesterday` · `2–3 days ago` · `About a week ago` · `Don't remember` |
| 8 | `usual_interval` | How often have you been watering it? | `About weekly` · `Every 10 days or so` · `Every 2 weeks` · `Less often` · `Don't know` |
| 9 | `env_source` | Where should the room temperature come from? | `My Xiaomi air purifier` · `My city's weather` |
| 9a | `xiaomi_confirm` | Resolve the device, read it live, show the value: *"Found it — 24.3 °C, 47% right now. Use this?"* | `[Use it]` `[Use weather instead]` |
| 9b | `city` | Free text. Geocode via Open-Meteo's geocoding endpoint, confirm the match | `[Yes, that's it]` `[Try again]` |
| 10 | `done` | Summary of everything, the seeded `B` translated into plain language, and the first predicted date | — |

**Step 9 is skipped** and `weather` is chosen automatically when no Mi credentials are configured.

**The closing summary must state the prediction as a prediction:**

> *Set up. Based on what you told me, I expect the soil to be dry around **22 September**. I'll check
> the room every morning and adjust — the date will move. When I do alert you, I'll ask you to check
> with a finger before you water, and I'll use your answer to get this right.*

---

## 8 · The photo step

> **Deviation, 2026-09-14:** implemented against **OpenAI** (`gpt-4o-mini`, structured
> outputs), not Anthropic, because that is the key available (`PERSONAL_OPENAI_API_KEY`). The
> field list, `unclear`-first behaviour and graceful fall-through are exactly as below; only the
> provider and call shape differ. See `vision.py`.

**Purpose: collapse steps 2–5 into one confirmation tap.** Nothing more. Every extracted field is a
*proposal* the user confirms or overrides, and `unclear` is a first-class answer that routes straight
to the corresponding question.

Download the largest `photo` size via `getFile`, store under `data/photos/<chat_id>/`, base64 it into
one Claude call:

```python
client.messages.create(
    model="claude-opus-5",
    max_tokens=1024,
    output_config={
        "effort": "low",
        "format": {"type": "json_schema", "schema": PLANT_PHOTO_SCHEMA},
    },
    messages=[{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64",
                                     "media_type": "image/jpeg", "data": b64}},
        {"type": "text", "text": PHOTO_PROMPT},
    ]}],
)
```

`PLANT_PHOTO_SCHEMA` — `additionalProperties: false`, everything required:

| Field | Type |
|---|---|
| `species_guess` | `monstera_deliciosa` · `other` · `unclear` |
| `pot_material` | `terracotta` · `plastic` · `unclear` |
| `pot_diameter_cm` | integer or null |
| `substrate` | `aroid_mix` · `potting_soil` · `peat_heavy` · `unclear` |
| `fit` | `root_bound` · `balanced` · `small_in_big` · `unclear` |
| `mature_leaf_count` | integer or null |
| `notes` | string, one sentence, shown to the user verbatim |

**The prompt must instruct the model to answer `unclear` rather than guess**, and to say so in
`notes`. Honest limits, stated in the prompt: substrate under a top dressing is invisible, and pot
diameter without a reference object is an estimate. Those two are the ones most likely to come back
`unclear`, and that is the correct behaviour.

`species_guess != monstera_deliciosa` → say so plainly and offer to continue with the Monstera
profile anyway, since it is the only one shipped.

**Cost and failure.** One image is roughly 1.6K input tokens; at Opus 5 rates ($5 / $25 per MTok) a
call lands near **$0.015**, once per plant. Any failure — no API key, network, a refusal, a schema
violation — falls through to steps 2–5 with a one-line apology. **The photo path is never required.**

---

## 9 · Daily tick

At `ALERT_HOUR` local, for each user, for each plant:

### 9.1 · Sequence

1. Resolve a reading through the §5.3 ladder. No reading at all → log and stop; do not advance `S`.
2. For each calendar day from `last_tick_date` to today: compute `D` (§6.2) and decrement `S`.
   `S` floors at `0.0`.
3. Set `last_tick_date = today`.
4. Evaluate the §6.4 gate. If it passes, send the alert, set `pending_alert`, append to `history`.
5. Save state. **Once, at the end** — not per plant, not per step.

### 9.2 · The alert

> 🪴 **Monstera** — I think the soil is dry now.
>
> Push a finger 3–5 cm in and tell me what you find. It's 24 °C and 47% in the room; last watered 12
> days ago.
>
> `[Still wet]` `[Just barely dry]` `[Bone dry / drooping]`

On `degraded = true`, one extra line: *"⚠️ I haven't been able to reach the sensor since 4 September —
this is a guess from the weather."*

On `just_right` / `bone_dry`, the confirmation restates the method, because it is the part people get
wrong: *"Water thoroughly until it runs out of the drainage holes, then empty the saucer within half
an hour."*

### 9.3 · Away windows

`/away 2026-11-07 2026-11-17` stores the window.

- Inside the window: no alerts at all. `S` still advances — the plant does not stop drinking.
- **On the last tick before it starts**: if `S` is predicted to fall below the threshold at any point
  during the window, send a one-off *"you're away from the 7th — water it thoroughly before you go"*
  and set `prewarned`.
- The first tick after the window ends resumes normally, with `S` reflecting the whole gap.

### 9.4 · Cold suppression

`temp_c < 12` → no watering alert. Send instead, at most once a week:

> ❄️ It's 11 °C where the sensor is. Monstera takes damage below about 12 °C, and wet roots in the
> cold are worse than dry ones. I'm holding off on watering advice until it warms up.

---

## 10 · Commands

| Command | Behaviour |
|---|---|
| `/start` | Onboarding wizard, or a status summary if already set up |
| `/setup` | Re-run the wizard for an existing plant — also the answer to "I repotted it" |
| `/status` | Current `S` as plain language, the reading, the predicted date, days since watering |
| `/watered` | Record a watering outside an alert. `S = 1.0`, `last_watered = today`. **Does not touch `B`** — there was no prediction to score |
| `/stats` | The §1 metric: last 10 alerts, how many were "just barely dry", current `B`, and the current interval it implies |
| `/away FROM TO` | Set the window. No arguments → show or clear it |
| `/help` | Commands, plus the one-paragraph explanation of what the model is doing |

**Copy lives in `locales/en.py` and `locales/ru.py`**, keyed by string id, selected by `BOT_LOCALE`.
English is the default and the one the repo documents. `locales/ru.py` is the single file in the repo
containing non-English text — it is UI data, not documentation, and the English-only rule for authored
files does not reach it.

---

## 11 · Module layout

```
bot.py             entry point — telebot polling, tick thread, wiring
config.py          .env load + loud validation
state.py           load/save, atomic write, schema_version
model.py           daylight, factors, tick step, seeding, learning  ← pure, no I/O
profiles.py        species profiles + the seeding factor tables
env_source.py      EnvSource ABC · XiaomiCloudSource · WeatherSource · the ladder
onboarding.py      the wizard state machine
vision.py          the photo call, schema, graceful degradation
commands.py        command + callback handlers
locales/en.py      strings (default)
locales/ru.py      strings
backtest.py        synthetic Belgrade year → the §6.6 interval table
tests/             pytest
```

**`model.py` imports nothing from the rest of the project.** That is the one boundary worth being
strict about: it is what makes §12 possible without mocks.

---

## 12 · Tests

### 12.1 · Unit — `model.py`

| Case | Expectation |
|---|---|
| `daylight_hours(172, 44.8)` | 15.59 ± 0.02 h |
| `daylight_hours(355, 44.8)` | 8.79 ± 0.02 h |
| Annual mean over 365 days | 12.23 ± 0.02 h |
| July reference (27 °C, 50%, `B`=0.058) | interval 6–8 days |
| January reference (22 °C, 33%, `B`=0.058) | interval 14–18 days |
| `T` at 5 °C | clamped to 0.35, then × 0.6 dormancy |
| `H` at 95% RH | clamped to 0.85 |
| `still_wet` answer | `B` × 0.85, `S` up by 0.10, **no** watering in history |
| `bone_dry` answer | `B` × 1.20, `S` = 1.0, watering recorded |
| 20 consecutive `still_wet` | `B` stops at 0.015, never below |
| 20 consecutive `bone_dry` | `B` stops at 0.25, never above |
| Seeding, terracotta + aroid + root-bound | `G` clamped to 2.00, `B_init` = 0.116 |
| Seeding with a reported 10-day interval | geometric blend, result inside `[0.015, 0.25]` |

### 12.2 · Gate and ladder

| Case | Expectation |
|---|---|
| `S` = 0.2, watered 3 days ago, July | **no alert** — 4-day floor |
| `S` = 0.2, watered 8 days ago, January | **no alert** — 10-day winter floor |
| `S` = 0.2, 11 °C | **no alert**; cold warning instead |
| `S` = 0.2, inside an away window | no alert |
| `S` = 0.2, `pending_alert` set | no second alert |
| Reading 55 °C | discarded; `last_reading` reused |
| `last_reading` 8 days old | weather fallback, `degraded = true`, notice in the alert |
| Both sources fail | tick skipped, `S` unchanged, `last_tick_date` unchanged |
| Process down 3 days | catch-up advances `S` by 3 days on restart |

### 12.3 · Backtest — run before the bot ever sends anything

`backtest.py` runs a synthetic Belgrade year: indoor temperature 26–28 °C in summer and 21–23 °C in
winter, RH 50% summer and 33% winter, daylight computed. It prints the predicted interval for each
month for each of the three seeded setups in §6.6.

**Acceptance: July 6–8 days and January 14–18 days for the balanced setup.** If the backtest
disagrees with that, the coefficients are wrong and the plant never finds out.

---

## 13 · Definition of done

1. `pytest` green, including every case in §12.1 and §12.2.
2. `python backtest.py` prints a monthly interval table that satisfies §12.3.
3. Onboarding completes end-to-end in a real Telegram chat, with and without a photo.
4. A forced tick produces a real alert; all three buttons produce the §6.5 transitions in the state file.
5. The bot survives a restart mid-onboarding and mid-`pending_alert`.
6. `/stats` reports the §1 metric.
7. `.env.example` lists every key in §3 with no values. `git grep` finds no token, password, device id
   or personal photo in tracked files.
8. `README.md` is rewritten for a public audience: what it is, the model in one short section, setup
   from a clean VPS, and an explicit statement that it is self-hosted and single-household.

---

## 14 · Not in v1, and why

| | Why not |
|---|---|
| Fertilizer and repotting reminders | Pure calendar features. They dilute the one thing this is testing — whether the water model is right |
| The symptom decoder | Needs photos and judgement; a wrong answer here is worse than no answer |
| The `F` airflow factor | §7.4 of the brief — add it only if the accuracy log asks for it |
| Growth log, charts, web UI | No decision depends on them yet |
| A second species | The data model is ready. The horticultural constants are not, and inventing them would be the one dishonest thing in this project |
| A hosted multi-tenant instance | Running other people's home telemetry is a different project with different obligations. Self-hosting is the answer |
