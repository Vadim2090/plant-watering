"""English strings - the default locale. Keys are shared with ru.py."""

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def plural_days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


STRINGS = {
    # --- onboarding -------------------------------------------------------------------------
    "welcome": (
        "Hi. I predict when your Monstera's soil will be dry, from the room temperature, the "
        "humidity and the season, and I ask you to check with a finger before you water. Your "
        "answer tunes the model to your pot.\n\n"
        "To start, send a photo of the plant in its pot, or skip the photo and answer a few "
        "questions instead."
    ),
    "welcome_no_photo": (
        "Hi. I predict when your Monstera's soil will be dry, from the room temperature, the "
        "humidity and the season, and I ask you to check with a finger before you water. Your "
        "answer tunes the model to your pot.\n\n"
        "A few questions to start."
    ),
    "btn_skip_photo": "Skip the photo",
    "photo_failed": "Sorry, I couldn't read anything useful from the photo. A few questions instead.",
    "photo_unexpected": "Thanks for the photo. I only use one during setup - run /setup to start over with it.",
    "photo_intro": "Here is what I think I see:",
    "photo_not_monstera": (
        "This doesn't look like a Monstera deliciosa to me. I only know the Monstera profile, "
        "so I'll carry on with that - the model will adjust from your answers."
    ),
    "photo_line": "  {field}: {value}",
    "photo_confirm_hint": "Everything I couldn't tell, I'll ask about.",
    "btn_photo_ok": "That's right",
    "btn_photo_fix": "Let me correct it",
    "field_pot_material": "Pot",
    "field_pot_diameter": "Pot width",
    "field_substrate": "Substrate",
    "field_fit": "Plant vs pot",
    "val_unclear": "couldn't tell",
    "val_pot_material_terracotta": "terracotta / unglazed",
    "val_pot_material_plastic": "plastic or glazed",
    "val_pot_material_unknown": "unknown",
    "val_substrate_aroid_mix": "chunky aroid mix",
    "val_substrate_potting_soil": "regular potting soil",
    "val_substrate_peat_heavy": "dense / peat-heavy",
    "val_substrate_unknown": "unknown",
    "val_fit_root_bound": "roots fill the pot",
    "val_fit_balanced": "about right",
    "val_fit_small_in_big": "small plant, big pot",
    "val_fit_unknown": "unknown",
    "val_light_bright": "bright",
    "val_light_medium": "medium",
    "val_light_low": "dim",

    "q_pot_material": "What is the pot made of?",
    "opt_terracotta": "Terracotta / unglazed",
    "opt_plastic": "Plastic or glazed",
    "opt_dont_know": "Don't know",
    "q_pot_diameter": "Roughly how wide is the pot at the top?",
    "opt_d_lt20": "Under 20 cm",
    "opt_d_20_30": "20-30 cm",
    "opt_d_30_40": "30-40 cm",
    "opt_d_gt40": "Over 40 cm",
    "q_substrate": "What is it planted in?",
    "opt_aroid": "Chunky mix - bark, perlite",
    "opt_soil": "Regular potting soil",
    "opt_peat": "Dense / peat-heavy",
    "q_fit": "How does the plant sit in the pot?",
    "opt_root_bound": "Roots fill it / it's tight",
    "opt_balanced": "About right",
    "opt_small_in_big": "Small plant, big pot",
    "q_light": "How much light does it get?",
    "opt_bright": "Bright - right by a window",
    "opt_medium": "Medium",
    "opt_low": "Dim - far from a window",
    "q_last_watered": "When did you last water it?",
    "opt_today": "Today",
    "opt_yesterday": "Yesterday",
    "opt_2_3_days": "2-3 days ago",
    "opt_week": "About a week ago",
    "opt_dont_remember": "Don't remember",
    "q_usual_interval": "How often have you been watering it?",
    "opt_weekly": "About weekly",
    "opt_ten_days": "Every 10 days or so",
    "opt_two_weeks": "Every 2 weeks",
    "opt_less_often": "Less often",
    "q_env_source": "Where should the room temperature come from?",
    "opt_src_xiaomi": "My Xiaomi air purifier",
    "opt_src_weather": "My city's weather",
    "xiaomi_found": "Found it - {temp} °C, {rh}% right now. Use this?",
    "btn_xiaomi_use": "Use it",
    "btn_xiaomi_weather": "Use weather instead",
    "xiaomi_not_found": (
        "I couldn't find or reach the purifier on the Mi account (region: {region}). A wrong "
        "region returns an empty device list rather than an error - check XIAOMI_REGION. I'll "
        "use the weather for now; run /setup again once it's fixed."
    ),
    "q_city": (
        "Which city are you in? Type its name and I'll look it up. Outdoor weather is only an "
        "estimate of your room, and I'll say so whenever I use it."
    ),
    "btn_city_default": "Use the configured location",
    "city_not_found": "I couldn't find that place. Try another spelling, or the nearest large city.",
    "city_confirm": "Is this it - {place}?",
    "btn_city_yes": "Yes, that's it",
    "btn_city_retry": "Try again",

    "done_title": "Set up.",
    "done_setup": "Pot: {material} · substrate: {substrate} · fit: {fit} · light: {light}.",
    "done_source_xiaomi": "Room readings come from your Xiaomi purifier.",
    "done_source_weather": "Room readings are estimated from the outdoor weather - a rough guide, not a thermometer.",
    "done_reading": "Right now: {temp} °C, {rh}%.",
    "done_no_reading": (
        "I couldn't get a room reading just now, so this starts from the pot facts alone. At the "
        "next morning check I'll read the room and catch up the days since your last watering; "
        "the first predicted date comes then."
    ),
    "done_interval": "Under today's conditions this pot should go about {days} between waterings.",
    "done_prediction": (
        "Based on what you told me, I expect the soil to be dry around {date}. I'll check the room "
        "every morning and adjust - the date will move. When I do alert you, I'll ask you to "
        "check with a finger before you water, and I'll use your answer to get this right."
    ),

    # --- alert and answers ------------------------------------------------------------------
    "alert": (
        "🪴 {name} - I think the soil is dry now.\n\n"
        "Push a finger 3-5 cm in and tell me what you find. It's {temp} °C and {rh}% in the "
        "room; last watered {days} ago."
    ),
    "alert_degraded": "⚠️ I haven't been able to reach the sensor since {since} - this is a guess from the weather.",
    "unknown_date": "a while",
    "btn_still_wet": "Still wet",
    "btn_just_right": "Just barely dry",
    "btn_bone_dry": "Bone dry / drooping",
    "answer_still_wet": "Noted - I was early. I've slowed the model down a little and I'll ask again around {date}.",
    "answer_just_right": "Good - that's the point to water.",
    "answer_bone_dry": "Noted - I was late. I've sped the model up; water it now.",
    "watering_method": (
        "Water thoroughly until it runs out of the drainage holes, then empty the saucer within "
        "half an hour."
    ),
    "low_humidity_note": (
        "The air is at {rh}%. If the leaf edges are going brown and crispy, that is dry air, not "
        "thirst - more water at the roots won't fix it and can cause rot."
    ),
    "answer_nothing_pending": "That alert has already been answered.",
    "answer_stale_alert": "That's an older alert - please answer the latest one.",
    "answer_unknown_plant": "I don't recognise that plant - run /status.",
    "soon": "the next day or two",
    "cold_warning": (
        "❄️ It's {temp} °C where the sensor is. Monstera takes damage below about 12 °C, and wet "
        "roots in the cold are worse than dry ones. I'm holding off on watering advice until it "
        "warms up."
    ),
    "away_prewarn": (
        "You're away from {date}, and I expect the {name}'s soil to run dry while you're gone. "
        "Water it thoroughly before you go."
    ),

    # --- commands ---------------------------------------------------------------------------
    "not_set_up": "Nothing set up yet - send /start.",
    "hint_commands": "I only answer commands - /status, /watered, /stats, /away, /help.",
    "unknown_command": "I don't know that command. /help lists the ones I do.",
    "status_title": "🪴 {name}",
    "status_s": "Soil: {words} (about {pct}% of the water left, by my estimate).",
    "s_full": "well watered",
    "s_drying": "drying down",
    "s_close": "getting close",
    "s_dry": "predicted dry",
    "status_reading": "Room: {temp} °C, {rh}% ({source}).",
    "source_xiaomi": "Xiaomi purifier",
    "source_weather": "estimated from weather",
    "source_cached": "last known reading",
    "status_no_reading": "No room reading available yet.",
    "status_prediction": "Predicted dry around {date}.",
    "status_predicted_dry": "Predicted dry now - I'll ask you to check at the next morning alert.",
    "status_watered": "Last watered {days} ago.",
    "status_pending": "There's an unanswered alert - tap one of its buttons when you've checked.",
    "status_away": "Away window: {frm} to {to}.",
    "watered_ok": "Recorded. Full pot from today; I expect it to be dry again around {date}.",
    "watered_ok_no_reading": "Recorded. Full pot from today.",
    "watered_unscored": "The open alert is closed without a score, since you didn't check first.",
    "stats_title": "📊 {name} - how well the prediction is doing",
    "stats_no_alerts": "No alerts yet. The first score arrives with the first finger test.",
    "stats_hit_rate": "Last {total} alerts: {just} answered \"just barely dry\" - {pct}% agreement.",
    "stats_breakdown": "Too early (still wet): {wet} · too late (bone dry): {dry} · closed without a check: {unanswered}.",
    "stats_target": "Target: at least 80% after three watering cycles.",
    "stats_target_met": "Target met: at least 80% after three cycles.",
    "stats_b": "Model constant B = {b}.",
    "stats_interval": "At {temp} °C and {rh}% that means about {days} between waterings.",
    "stats_alerts_total": "Alerts sent in total: {n}; answered: {answered}.",
    "away_none": "No away window set. Usage: /away 2026-11-07 2026-11-17",
    "away_usage": "Usage: /away FROM TO, dates as YYYY-MM-DD, e.g. /away 2026-11-07 2026-11-17",
    "away_in_past": "That window is already over.",
    "away_current": "Away window: {frm} to {to}. No alerts inside it.",
    "btn_away_clear": "Clear it",
    "away_cleared": "Away window cleared.",
    "away_set": (
        "Away from {frm} to {to}. No alerts in that window. If I expect the soil to run dry while "
        "you're gone, I'll tell you the day before you leave."
    ),
    "help": (
        "/status - where the model thinks the pot is, and when it expects it to be dry\n"
        "/watered - record a watering I didn't ask about\n"
        "/stats - how often my alerts were right\n"
        "/away FROM TO - mute alerts while you travel\n"
        "/setup - re-run the setup (also after repotting)\n"
        "/help - this\n\n"
        "What I do: I keep a running estimate of how much water is left in the pot. Every morning "
        "I read the room temperature and humidity, factor in the season's daylight, and subtract "
        "the day's use. When the estimate says the top few centimetres should be dry, I ask you "
        "to check with a finger. Your answer corrects the one number the model learns - how fast "
        "this pot dries - so after a few cycles it fits your plant, not an average one."
    ),
}
