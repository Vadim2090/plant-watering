# plant-watering

A Telegram bot that predicts when a Monstera deliciosa needs water, asks you to check with a
finger before you do, and learns from your answer.

It is a small **water-demand model with a reminder attached**, not a calendar. Indoor water demand
in a Belgrade flat swings roughly 2.5x between July and January, so a fixed interval is wrong for
half the year. Too little water is recoverable; too much is root rot, which is how this plant
usually dies.

**Self-hosted, single-household.** You run it on your own machine or VPS with your own bot token
and your own state file. There is no shared instance, and none is planned: running other people's
home telemetry is a different project with different obligations.

## What it does

1. Every morning it reads the room temperature and humidity, from a **Xiaomi Smart Air Purifier
   4 Pro** via the Xiaomi cloud, or, without one, from the outdoor weather with a crude indoor
   estimate that it labels as such.
2. It computes the day's daylight for your latitude and subtracts one day of water use from a
   running estimate of what is left in the pot.
3. When the estimate says the top few centimetres should be dry, it sends **a question, not an
   instruction**: push a finger in and answer *still wet* / *just barely dry* / *bone dry*.
4. The answer refits the one parameter the model learns, how fast this particular pot dries.
5. `/stats` reports how often the prediction agreed with your finger.

Setup is a Telegram wizard, optionally seeded by a photo of the plant. Hard safety rules override
the model: never sooner than 4 days after a watering, never sooner than 10 days in winter, and no
watering advice at all below 12 °C.

## The model, briefly

```
S(0)   = 1.0                         full pot, after watering to runoff
S(t+1) = S(t) - B * T(t) * L(t) * H(t)
alert when S <= 0.25
```

`T` doubles per +10 °C, `L` follows day length with a 1.5 exponent, `H` rises as the air dries.
`B` is the base daily depletion, seeded from the pot material, substrate and fit at setup, then
fitted from your answers: *still wet* lowers it 15%, *bone dry* raises it 20%, *just barely dry*
leaves it alone. The derivation, the constants and the Monstera facts they encode are in
[`PRODUCT-BRIEF.md`](PRODUCT-BRIEF.md); the build document is [`SPEC.md`](SPEC.md).

**What it does not claim.** The model does not measure soil moisture; it estimates it and asks you
to verify. It reaches its reference intervals on a synthetic year (`python backtest.py`: 7 days in
July, 17 in January for a plastic pot in potting soil), and it has **no measured hit rate yet**.
The share of alerts answered "just barely dry" is the only success metric, and `/stats` prints it
with its denominator. Until that number exists for your plant, treat the dates as a first guess.

## Setup on a clean VPS

Python 3.11 or newer.

```bash
git clone https://github.com/<you>/plant-watering.git /opt/plant-watering
cd /opt/plant-watering
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env
$EDITOR .env          # at minimum TELEGRAM_BOT_TOKEN and ALLOWED_CHAT_IDS
.venv/bin/python backtest.py        # must print PASS before you trust an alert
.venv/bin/python bot.py
```

Then open the bot in Telegram and send `/start`.

For a service that survives reboots, `deploy/plant-watering.service` is a systemd unit; adjust the
paths and user, then `systemctl enable --now plant-watering`.

### Xiaomi login when the account has two-factor auth

Xiaomi demands a captcha, and then a 2FA code, for password logins from a new client. A headless
bot cannot answer either. Log in **once, interactively, on a machine you control** to obtain a
long-lived token, then run the bot with the token instead of the password:

1. Set `XIAOMI_USERNAME` / `XIAOMI_PASSWORD` in `.env`.
2. Obtain a `userId` + token with a standard interactive extractor such as
   [Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor),
   which walks the captcha and the 2FA code prompt for you.
3. Put them in `.env` as `XIAOMI_USER_ID` and `XIAOMI_PASS_TOKEN`. With these set the bot logs in
   with the token and never sends the password, so neither the captcha nor 2FA can block it.
4. `python probe.py` should now print the purifier's live temperature and humidity.

`python probe.py --login` handles the captcha for accounts **without** 2FA. When 2FA is on it
tells you so and stops; use the extractor above.

### Configuration

Everything is in `.env`. Only the token is required.

| Key | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From @BotFather. **Required** |
| `ALLOWED_CHAT_IDS` | Comma-separated chat ids allowed to use the bot. Empty means anyone. Set it |
| `BOT_LOCALE` | `en` (default) or `ru` |
| `XIAOMI_USERNAME`, `XIAOMI_PASSWORD` | Mi account. Absent: the purifier is not offered, the weather is used |
| `XIAOMI_REGION` | `de` (default, EU) · `cn` · `ru` · `sg` · `us` · `i2`. A wrong region returns an empty device list, not an error |
| `XIAOMI_USER_ID`, `XIAOMI_PASS_TOKEN` | Optional but recommended on a server. Xiaomi demands a captcha for password logins from a new client after a few attempts, which a headless bot cannot answer. Log in once interactively (`python probe.py` guides you), store the resulting token here, and the bot never sends the password again |
| `PERSONAL_OPENAI_API_KEY` | Optional. A personal OpenAI key. Enables the plant-photo step in onboarding (model `gpt-5.4-mini`). Absent: the step is skipped |
| `LATITUDE`, `LONGITUDE` | Default Belgrade, `44.8` / `20.5` |
| `TIMEZONE`, `ALERT_HOUR` | Default `Europe/Belgrade`, `9` |
| `STATE_PATH` | Default `data/state.json` |

The whole thing is one process: Telegram is long-polled, so there is no webhook, no inbound port
and no certificate. State is one JSON file under `data/`, written atomically. Photos, if you send
one, are stored under `data/photos/` and never leave the machine except for the single vision call.

## Commands

| | |
|---|---|
| `/start` | Setup wizard, or the current status once set up |
| `/status` | Estimated water left, the room reading, the predicted dry date |
| `/watered` | Record a watering the bot did not ask about. Does not touch the learned parameter |
| `/stats` | The metric: share of alerts answered "just barely dry", with the count |
| `/away FROM TO` | Mute alerts while travelling; a warning the day before if the pot will run dry |
| `/setup` | Re-run the wizard, also after repotting |
| `/help` | Commands and a one-paragraph explanation of the model |

## Development

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest        # model, gate, ladder, wizard, commands - no network needed
.venv/bin/python backtest.py      # the synthetic year
```

`model.py` is pure, imports nothing else from the project, and is where every number lives.
Species profiles and the seeding tables are in `profiles.py`; only Monstera deliciosa ships,
because those are the only constants anyone here can stand behind.

## License

MIT, see [LICENSE](LICENSE).
Backup executor smoke test (Builder-G).
