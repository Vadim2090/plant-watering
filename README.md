# repo-plant-watering

A watering scheduler for a single Monstera deliciosa in a Belgrade apartment — built as a small
**water-demand model**, not a calendar reminder.

A fixed interval ("every 7 days") is wrong roughly half the year: indoor water demand swings about
2.5× between July and January. Too little water is recoverable; too much is root rot, which is the
usual way this plant dies. So this predicts the pot's remaining water day by day from temperature,
daylight and humidity, fires only when the substrate is predicted to be dry, then asks whether it
was right and recalibrates itself from the answer.

**Status: v0 brief, pending review.** Nothing is implemented yet.

| Document | What it is |
|---|---|
| [`PRODUCT-BRIEF.md`](PRODUCT-BRIEF.md) | The problem, the model, the Monstera facts it encodes, and the open decisions. **Read this first.** |
| `SPEC.md` | Not written yet — comes after the brief is approved |

## Design principles

1. **Predict, then verify.** The app never claims to know the soil moisture. Every alert is a
   prediction to check with a finger, and the answer feeds back into the model.
2. **Safety rules beat the model.** Hard floors on the watering interval — 7 days always, 10 days
   in winter — override any computed date.
3. **One measurable success metric.** The share of alerts where the finger test agrees with the
   prediction. Target ≥ 80% after three watering cycles.

## License

MIT — see [LICENSE](LICENSE).
