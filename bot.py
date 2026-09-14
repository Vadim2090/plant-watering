"""Entry point: telebot long-polling, the daily tick thread, and the wiring between them.

Run with `python bot.py`. Everything configurable comes from `.env` (SPEC.md §3).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import telebot
from telebot import types

import commands
import tick as tick_mod
import vision
from config import Config, ConfigError, load_config
from context import AppContext
from env_source import (
    SOURCE_XIAOMI,
    EnvSource,
    WeatherSource,
    XiaomiCloudSource,
    list_xiaomi_devices,
    pick_purifier,
)
from locales import get_strings
from state import State

log = logging.getLogger("plant")


# ---------------------------------------------------------------------------------------------
# Wiring helpers
# ---------------------------------------------------------------------------------------------


def make_keyboard(rows) -> types.InlineKeyboardMarkup | None:
    if not rows:
        return None
    kb = types.InlineKeyboardMarkup()
    for row in rows:
        kb.row(*[types.InlineKeyboardButton(label, callback_data=data) for label, data in row])
    return kb


def source_factory(config: Config):
    """Build the user's configured `EnvSource` from their `env_source` dict."""
    cache: dict[str, EnvSource] = {}

    def make(env: dict) -> EnvSource | None:
        if not env:
            return None
        if env.get("type") == SOURCE_XIAOMI:
            did = env.get("device_id") or config.xiaomi_device_id
            if not (config.has_xiaomi and did):
                return None
            key = f"x:{did}"
            if key not in cache:  # keep one logged-in session per device
                cache[key] = XiaomiCloudSource(config.xiaomi_username, config.xiaomi_password, config.xiaomi_region, did,
                                               config.xiaomi_user_id, config.xiaomi_pass_token)
            return cache[key]
        city = env.get("city") or {}
        lat = float(city.get("latitude", config.latitude))
        lon = float(city.get("longitude", config.longitude))
        return WeatherSource(lat, lon)

    return make


def xiaomi_prober(config: Config):
    def probe():
        did = config.xiaomi_device_id
        if not did:
            devices = list_xiaomi_devices(config.xiaomi_username, config.xiaomi_password, config.xiaomi_region,
                                          config.xiaomi_user_id, config.xiaomi_pass_token)
            device = pick_purifier(devices)
            if device is None:
                log.warning("xiaomi: %d device(s) on the account, none looked like a purifier", len(devices))
                return None
            did = device["did"]
        reading = XiaomiCloudSource(config.xiaomi_username, config.xiaomi_password, config.xiaomi_region, did,
                                    config.xiaomi_user_id, config.xiaomi_pass_token).read()
        if reading is None:
            return None
        return did, reading

    return probe


def photo_saver(config: Config):
    def save(chat_id: int, plant_id: str, jpeg: bytes) -> str:
        folder = config.photo_dir / str(chat_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{plant_id}.jpg"
        path.write_bytes(jpeg)
        return str(path)

    return save


# ---------------------------------------------------------------------------------------------
# The tick thread
# ---------------------------------------------------------------------------------------------


def next_fire(now: datetime, hour: int) -> datetime:
    fire = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if fire <= now:
        fire += timedelta(days=1)
    return fire


def tick_loop(ctx: AppContext, stop: threading.Event) -> None:
    # catch up on a tick the process was down for
    try:
        if tick_mod.catch_up_if_missed(ctx):
            log.info("missed tick caught up")
    except Exception:
        log.exception("start-up catch-up failed")
    while not stop.is_set():
        fire = next_fire(ctx.now(), ctx.config.alert_hour)
        log.info("next tick at %s", fire.isoformat(timespec="minutes"))
        while not stop.is_set() and ctx.now() < fire:
            time.sleep(min(60, max(1, (fire - ctx.now()).total_seconds())))
        if stop.is_set():
            break
        try:
            tick_mod.run_tick(ctx)
        except Exception:
            log.exception("tick failed")


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------


def build_context(config: Config, bot: telebot.TeleBot) -> AppContext:
    tz = ZoneInfo(config.timezone)
    state = State.load(config.state_path)

    def send(chat_id: int, text: str, keyboard=None):
        try:
            msg = bot.send_message(chat_id, text, reply_markup=make_keyboard(keyboard))
            return msg.message_id
        except Exception:
            log.exception("send failed for chat %s", chat_id)
            return None

    def clear_buttons(chat_id: int, message_id: int) -> None:
        try:
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except Exception:
            pass  # the message may be too old to edit; nothing depends on it

    return AppContext(
        config=config,
        state=state,
        strings=get_strings(config.bot_locale),
        send=send,
        now=lambda: datetime.now(tz),
        make_primary_source=source_factory(config),
        fallback_source=WeatherSource(config.latitude, config.longitude),
        clear_buttons=clear_buttons,
        vision=(lambda jpeg: vision.analyze_photo(config.openai_api_key, jpeg)) if config.has_vision else None,
        save_photo=photo_saver(config),
        probe_xiaomi=xiaomi_prober(config) if config.has_xiaomi else None,
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config()
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    bot = telebot.TeleBot(config.telegram_bot_token, parse_mode=None, threaded=False)
    ctx = build_context(config, bot)
    log.info("state: %s (%d user(s)); locale %s; tick at %02d:00 %s; xiaomi %s; vision %s",
             config.state_path, len(ctx.state.users), config.bot_locale, config.alert_hour, config.timezone,
             "on" if config.has_xiaomi else "off", "on" if config.has_vision else "off")
    if not config.allowed_chat_ids:
        log.warning("ALLOWED_CHAT_IDS is empty - anyone who finds this bot can use it. Set it.")

    def allowed(chat_id: int) -> bool:
        if config.is_allowed(chat_id):
            return True
        log.info("ignoring chat not in ALLOWED_CHAT_IDS")
        return False

    @bot.message_handler(content_types=["photo"])
    def on_photo(message):
        if not allowed(message.chat.id):
            return
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            jpeg = bot.download_file(file_info.file_path)
        except Exception:
            log.exception("photo download failed")
            return
        commands.dispatch_photo(ctx, message.chat.id, jpeg)

    @bot.message_handler(func=lambda m: True, content_types=["text"])
    def on_text(message):
        if not allowed(message.chat.id):
            return
        commands.dispatch_message(ctx, message.chat.id, message.text or "")

    @bot.callback_query_handler(func=lambda c: True)
    def on_callback(call):
        chat_id = call.message.chat.id
        if not allowed(chat_id):
            return
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass
        commands.dispatch_callback(ctx, chat_id, call.message.message_id, call.data or "")

    stop = threading.Event()
    thread = threading.Thread(target=tick_loop, args=(ctx, stop), name="tick", daemon=True)
    thread.start()

    log.info("polling")
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=30, skip_pending=True)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
