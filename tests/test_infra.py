"""config, state, locale coverage."""

import json
import re
from pathlib import Path

import pytest

import locales.en as en
import locales.ru as ru
from config import ConfigError, build_config, parse_env_file
from state import SCHEMA_VERSION, State

ROOT = Path(__file__).resolve().parent.parent


def test_missing_token_aborts_loudly():
    with pytest.raises(ConfigError) as e:
        build_config({})
    assert "TELEGRAM_BOT_TOKEN" in str(e.value)


def test_defaults():
    c = build_config({"TELEGRAM_BOT_TOKEN": "x"})
    assert (c.latitude, c.longitude, c.timezone, c.alert_hour, c.bot_locale) == (44.8, 20.5, "Europe/Belgrade", 9, "en")
    assert c.xiaomi_region == "de" and not c.has_xiaomi and not c.has_vision
    assert c.is_allowed(123)  # empty allowlist = anyone


def test_validation():
    with pytest.raises(ConfigError):
        build_config({"TELEGRAM_BOT_TOKEN": "x", "ALERT_HOUR": "24"})
    with pytest.raises(ConfigError):
        build_config({"TELEGRAM_BOT_TOKEN": "x", "XIAOMI_USERNAME": "u"})
    with pytest.raises(ConfigError):
        build_config({"TELEGRAM_BOT_TOKEN": "x", "TIMEZONE": "Mars/Olympus"})
    with pytest.raises(ConfigError):
        build_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1,abc"})
    c = build_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1, 2"})
    assert c.allowed_chat_ids == frozenset({1, 2}) and not c.is_allowed(3)


def test_parse_env_file(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# c\nexport A="x y"\nB=\'q\'\nC=plain # note\n\nD=\n')
    assert parse_env_file(p) == {"A": "x y", "B": "q", "C": "plain", "D": ""}


def test_env_example_lists_every_key_with_no_values():
    values = parse_env_file(ROOT / ".env.example")
    from config import KEYS
    assert set(values) == set(KEYS)
    assert all(v == "" for v in values.values())


def test_state_roundtrip_is_atomic(tmp_path):
    path = tmp_path / "data" / "state.json"
    s = State.load(path)
    assert s.data == {"schema_version": SCHEMA_VERSION, "users": {}}
    from datetime import datetime
    s.ensure_user(1, "en", datetime(2026, 9, 13, 9))
    s.save()
    assert not path.with_suffix(".json.tmp").exists()
    again = State.load(path)
    assert "1" in again.users and again.data["schema_version"] == SCHEMA_VERSION
    json.loads(path.read_text())


def test_future_schema_is_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION + 1, "users": {}}))
    with pytest.raises(RuntimeError):
        State.load(path)


def test_every_string_id_exists_in_both_locales():
    ids = set()
    for f in ("tick.py", "onboarding.py", "commands.py"):
        src = (ROOT / f).read_text()
        ids |= set(re.findall(r'\bt\("([a-z_0-9]+)"', src))
        ids |= set(re.findall(r'\("(opt_[a-z_0-9]+)"', src))
    for prefix, values in (("val_pot_material_", ["terracotta", "plastic", "unknown"]),
                           ("val_substrate_", ["aroid_mix", "potting_soil", "peat_heavy", "unknown"]),
                           ("val_fit_", ["root_bound", "balanced", "small_in_big", "unknown"]),
                           ("val_light_", ["bright", "medium", "low"])):
        ids |= {prefix + v for v in values}
    assert ids - set(en.STRINGS) == set()
    assert ids - set(ru.STRINGS) == set()
    assert set(en.STRINGS) == set(ru.STRINGS)


def test_only_ru_locale_contains_cyrillic():
    cyr = re.compile("[%s-%s]" % (chr(0x0400), chr(0x04FF)))
    offenders = []
    for p in ROOT.rglob("*"):
        if p.is_dir() or ".venv" in p.parts or ".git" in p.parts or "__pycache__" in p.parts or p.name.endswith(".pyc"):
            continue
        if p.suffix not in (".py", ".md", ".txt", ".ini", ".service", ".example", "") or p.name == "LICENSE":
            continue
        if p == ROOT / "locales" / "ru.py":
            continue
        try:
            if cyr.search(p.read_text(encoding="utf-8")):
                offenders.append(str(p.relative_to(ROOT)))
        except (UnicodeDecodeError, OSError):
            continue
    assert offenders == []
