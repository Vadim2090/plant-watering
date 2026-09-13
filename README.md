# repo-plant-watering

A watering scheduler for a single Monstera deliciosa in a Belgrade apartment — built as a small
**water-demand model**, not a calendar reminder.

A fixed interval ("every 7 days") is wrong roughly half the year: indoor water demand swings about
2.5× between July and January. Too little water is recoverable; too much is root rot, which is the
usual way this plant dies. So this predicts the pot's remaining water day by day from temperature,
daylight and humidity, fires only when the substrate is predicted to be dry, then asks whether it
was right and recalibrates itself from the answer.

Environment readings come from a **Xiaomi Smart Air Purifier 4 Pro** sitting in the same room — a
real thermometer in the actual apartment, rather than a weather API and a guess about the indoor
offset. Alerts and the feedback buttons run over a **Telegram bot**.

**Status: spec approved, implementation not started.**

| Document | What it is |
|---|---|
| [`SPEC.md`](SPEC.md) | The build document — architecture, data model, the wizard, the tick, the tests. **Start here to implement.** |
| [`PRODUCT-BRIEF.md`](PRODUCT-BRIEF.md) | The problem, how the model was derived, and the Monstera facts it encodes. **Start here to understand.** |

## Design principles

1. **Predict, then verify.** The app never claims to know the soil moisture. Every alert is a
   prediction to check with a finger, and the answer feeds back into the model.
2. **Safety rules beat the model.** Hard floors on the watering interval — 7 days always, 10 days
   in winter — override any computed date.
3. **One measurable success metric.** The share of alerts where the finger test agrees with the
   prediction. Target ≥ 80% after three watering cycles.

## License

MIT — see [LICENSE](LICENSE).
