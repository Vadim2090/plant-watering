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
D(t)   = B × T(t) × L(t) × H(t)

alert when S(t) <= 0.25           # top 3–5 cm dry — the Monstera "water now" point
```

- **`S`** — fraction of plant-available water remaining. Not a soil-moisture reading. An estimate.
- **`B`** — base daily depletion for this pot. **The only parameter, and the only learned one.**
  Reference value **0.058**, seeded from the pot facts at setup (§3.2) and fitted from there.
- **`D`** — today's loss, as a fraction of the reservoir.

**One parameter, on purpose.** An earlier draft carried a separate pot constant `G` alongside `B`.
They multiply, and `B` is fitted against the finger test — so after calibration the two are
indistinguishable and one of them is decoration. The pot facts now seed `B` and then step out of the
way.

### 3.2 · The factors

| Factor | Formula | Range | Rationale |
|---|---|---|---|
| **`T` temperature** | `2^((temp_C − 22) / 10)` | 0.35 – 2.2 | Evapotranspiration roughly doubles per +10 °C (Q10 ≈ 2). Reference 22 °C |
| **`T` cold override** | `× 0.6` when temp < 15 °C | — | Growth stalls. Wet + cold roots = rot. This is a safety rule, not a curve |
| **`L` light / season** | `(daylight_h / 12.2)^1.5 × window_factor` | 0.55 – 1.25 | Belgrade: **15h 35m** daylight in late June vs **8h 47m** in late December. The exponent is above 1 because winter costs intensity and sun angle as well as hours. Computed from date + latitude — no sensor, no API |
| **`H` humidity** | `1 + (60 − RH%) / 100` | 0.85 – 1.30 | Drier air pulls water faster. Central heating in winter drops a Belgrade flat to 30–35% RH |

**Seeding `B` at setup** — the pot facts multiply into a single starting value,
`B_init = 0.058 × (material × substrate × fit)`, clamped to a combined factor of 0.55–2.0:

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

**Where 0.058 comes from.** It is solved backwards from the two intervals the model has to get
right. Belgrade July (27 °C, 50% RH, 15.4 h daylight) gives `T·L·H = 1.94`; January (22 °C indoors,
33% RH, 8.8 h) gives `0.78`. Requiring a 0.75 depletion to reach the alert threshold:
**7 days in July and ~16 in January both solve to B ≈ 0.058.** The same constant reproduces both
ends of the year, which is the only evidence available before the first real watering.

### 3.3 · The learning loop — this is the part that matters

When the alert fires, the app does **not** say "water now". It says:

> *Predicted dry. Push a finger 3–5 cm into the soil — what do you find?*
> `[still wet]` · `[just barely dry]` · `[bone dry / drooping]`

| Answer | Action | Effect on `B` |
|---|---|---|
| Still wet | No watering recorded. `S += 0.10` — the pot had more left than modelled, so the next alert arrives on its own in a day or two | `B × 0.85` — model was too fast |
| Just barely dry | Water now, `S = 1.0`. Perfect hit | unchanged ✅ |
| Bone dry / drooping | Water now, `S = 1.0` | `B × 1.20` — model was too slow |

`B` is clamped to [0.015, 0.25] so a single mis-tap cannot break the model. **Convergence: 2–3
cycles.** Logged every time, so the hit rate from §1 is measurable rather than felt.

### 3.4 · Hard safety rules that override the model

The model is a guess; these are not. They win over any computed date.

| Rule | Why |
|---|---|
| **Never alert sooner than 4 days after the last watering** | Terracotta plus a chunky aroid mix in a hot July genuinely can dry in 4–5 days, so this floor sits low. Anything under it means the model is broken, not the plant thirsty |
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
## 6 · Decisions — closed 2026-09-13

| # | Decision | Answer |
|---|---|---|
| **D1** | Alert channel | **Telegram bot.** The three feedback buttons are native inline keyboards — no UI to build |
| **D2** | Environment data | **Xiaomi Smart Air Purifier 4 Pro**, read from **Xiaomi's cloud**, not the LAN. See §7 |
| **D3** | Scope | **Multi-plant, multi-user data model; one profile shipped (Monstera).** Adding a species later is a config entry |
| **D4** | Feedback | **Full loop.** Finger test on every alert, three-button answer, `B` recalibrates |
| **D5** | Setup | **Everything is collected in a Telegram onboarding wizard**, including an optional photo. No config file for plant facts |
| **D6** | Repo | **Public.** MIT, self-hosted — anyone running it uses their own bot token |

**D2 turned out better than the hybrid originally proposed.** A weather API plus a guessed indoor
offset is a model of the apartment; the purifier is a thermometer *in* it. It removes the model's
largest error source, which was winter: outdoor −2 °C while the room sits at 23 °C on radiators.

**The sensor is 2 m away in the adjacent room, and is deliberately not calibrated.** That is the
right call and costs almost nothing: a *constant* offset — whether from the sensor sitting inside a
running appliance or from the room next door — is fully absorbed by `B` within two or three cycles,
because `B` is fitted against the finger test, not against the thermometer. `sensor_offset_c` stays
in the config, defaulting to `0.0`, in case `/stats` later shows a seasonal pattern rather than a
constant one. Only a *varying* difference would hurt, and a 2 m gap through a doorway does not
produce one.

---

## 7 · The sensor — Xiaomi Smart Air Purifier 4 Pro, via the cloud

### 7.1 · Why the cloud, not the LAN

`python-miio` speaks the MIoT protocol over the local network, which a VPS cannot reach. But the
device also reports to Xiaomi's cloud, and the cloud is reachable from anywhere. That single fact
removes the Mac from the architecture entirely — see §8.

| Path | How | Verdict |
|---|---|---|
| **Xiaomi cloud** via [`micloud`](https://github.com/Squachen/micloud) | Mi account login → `get_devices()` → MIoT property read. EU region is the `de` server | **Chosen.** ~40 lines, works from anywhere |
| Xiaomi's own [OAuth2 MIoT cloud](https://github.com/XiaoMi/ha_xiaomi_home) | The official integration's `miot_cloud` module — OAuth, no stored password, MQTT push | Better auth story, heavier to lift out of a Home Assistant integration. The upgrade path if `micloud` breaks |
| WireGuard/Tailscale tunnel into the flat | VPS joins the home network | Needs an always-on device or a capable router at home. More setup than the cloud for no gain |
| Local LAN (`python-miio`) | Direct, fastest, no account | Only if the bot ever moves back onto a machine at home |

The `EnvSource` interface in §9 exists precisely so this is a one-class swap.

### 7.2 · The exact properties

From the [MIoT spec for `zhimi.airp.vb4`](https://home.miot-spec.com/spec/zhimi.airp.vb4):

| Reading | siid | piid | Type | Used for |
|---|---|---|---|---|
| `temperature` | **3** | **7** | float, −30…100 °C | the `T` factor |
| `relative-humidity` | **3** | **1** | uint8, 0–100 % | the `H` factor |
| `pm2.5-density` | 3 | 4 | float | not used |
| `on` | 2 | 1 | bool | liveness check |
| `fan-level` | 2 | 5 | uint8 | candidate `F` factor, §7.4. Not in v1 |

> ⚠️ **Vadim supplies the Mi account credentials himself**, into `.env` on the VPS. They are never
> committed, never pasted into a chat, and the repo ships `.env.example` only. The device id comes
> from one `get_devices()` call at setup.

### 7.3 · Failure handling — three rungs

The purifier gets switched off, unplugged, or Xiaomi rotates something. The model degrades, never stops:

| Condition | Behaviour |
|---|---|
| Cloud read succeeds, values plausible | Use it |
| Read fails, or device offline, last good reading < 7 days old | Use the last good reading unchanged. Indoor temperature in a heated flat moves slowly; this costs almost nothing |
| Last good reading > 7 days old | Fall back to an Open-Meteo outdoor reading plus an explicit indoor model, and **say so in the alert** |
| Any reading outside 5–40 °C or 10–95 % RH | Discard as a fault. A broken sensor must never become a watering decision |

### 7.4 · A free extra — deliberately not in v1

`fan_level` comes back in the same call. A purifier on high moves air across the leaves and raises
transpiration — physically real, probably 5–15%, and swamped by `B` recalibration if the fan setting
is steady. It earns a place only if the accuracy log later shows worse hit rates in high-fan weeks.
That is a question the log can answer on its own, which is the right reason to add a factor rather
than a plausible story about airflow.

---

## 8 · Architecture — resolved

**One Python process on the existing VPS. No Mac, no webhook, no public HTTPS, no inbound ports.**

```
          Xiaomi cloud  ──(1/day, HTTPS out)──┐
                                              ▼
Telegram  ──(long-poll getUpdates, HTTPS out)──►  bot process (systemd)
                                              │      │
          Open-Meteo ──(fallback only)────────┘      ▼
                                                  state.json
```

Three things make this smaller than it looks:

1. **Telegram long-polling** (`getUpdates`) means the bot reaches out, so there is no webhook, no TLS
   certificate, and nothing listening on a public port.
2. **The sensor comes over the cloud**, so the process does not need to be on the home network.
3. **A once-daily tick** is all the model needs. The conversational half is event-driven and cheap.

**What this buys over the earlier Mac plan:** alerts keep arriving during the **7–17 November** trip
to Germany and Austria, so the away-window handling in §9 is a convenience rather than a patch over
a gap.

---

## 9 · Scope

### In v1
- Telegram bot: an onboarding wizard, a daily check, the alert with three inline buttons, `/watered`, `/stats`, `/away`
- Optional **photo in onboarding** → a vision call proposes the pot and plant facts → user confirms or corrects
- The §3 water-balance model, one tick a day at 09:00 Europe/Belgrade
- Daylight from date + latitude — pure arithmetic, no dependency
- Temperature and humidity from the Air Purifier 4 Pro via Xiaomi cloud, with the §7.3 ladder
- `EnvSource` interface with a **weather fallback**, which doubles as the path for anyone without a Xiaomi purifier
- Plant profiles as data; **Monstera deliciosa is the only profile shipped**
- The §3.3 feedback loop and `B` recalibration
- The §3.4 safety overrides
- A local JSON store: every reading, alert, answer and `B` change
- An away-window so a trip does not silently break the record

### Explicitly not in v1
Fertilizer track · repotting reminders · the §5 symptom decoder · the `F` airflow factor · growth
log and charts · any web UI · any second species profile · a hosted multi-tenant instance

### Non-functional
- **Python 3.11+**, venv, systemd unit. Dependencies: a Telegram client, `micloud`, `anthropic`, `requests`
- Secrets in `.env` — Telegram token, Mi account, device id, Anthropic key. Never in a tracked file
- **Public, MIT, self-hosted.** Anyone running it brings their own bot token and their own state file.
  No shared instance — that would make the operator a data processor for other people's home telemetry
- The bot runs without an Anthropic key; the photo step simply disappears

---

## 10 · Implementation

Everything above is the *what* and the *why*. The *how* — data model, module boundaries, the exact
wizard steps and copy, config schema, the seeded `B` arithmetic, and the test cases — is in
[`SPEC.md`](SPEC.md).
