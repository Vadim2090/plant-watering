"""One JSON state file, written atomically (SPEC.md §4).

Every write goes through `State.save()`; nothing else touches the file. The data stays a plain
dict shaped exactly like the JSON, with small helpers around it - no ORM, no dataclass tree.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1


def empty_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "users": {}}


def new_user(locale: str, created_at: datetime) -> dict:
    return {
        "locale": locale,
        "created_at": created_at.isoformat(timespec="seconds"),
        "onboarding": {"step": "welcome", "draft": {}},
        "env_source": None,
        "away": None,
        "last_cold_warning": None,
        "plants": [],
    }


def new_plant(plant_id: str, name: str, species: str, setup: dict, B: float, S: float,
              last_watered: str, last_tick_date: str, photo_path: str | None) -> dict:
    return {
        "id": plant_id,
        "name": name,
        "species": species,
        "photo_path": photo_path,
        "setup": setup,
        "B": B,
        "S": S,
        "last_watered": last_watered,
        "last_tick_date": last_tick_date,
        "pending_alert": None,
        "history": [],
    }


def migrate(data: dict) -> dict:
    """Branch on `schema_version` here when the shape changes. v1 has nothing to migrate."""
    version = data.get("schema_version", 0)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"state file is schema v{version}; this build understands v{SCHEMA_VERSION}")
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("users", {})
    return data


class State:
    def __init__(self, path: str | os.PathLike, data: dict):
        self.path = Path(path)
        self.data = data
        self.lock = threading.RLock()  # the poll thread and the tick thread both write

    @classmethod
    def load(cls, path: str | os.PathLike) -> "State":
        p = Path(path)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = empty_state()
        return cls(p, migrate(data))

    def save(self) -> None:
        """write temp -> os.replace, so a crash mid-write leaves the old file intact."""
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False, sort_keys=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)

    # --- users -------------------------------------------------------------------------------

    @property
    def users(self) -> dict:
        return self.data["users"]

    def get_user(self, chat_id: int | str) -> dict | None:
        return self.users.get(str(chat_id))

    def ensure_user(self, chat_id: int | str, locale: str, now: datetime) -> dict:
        key = str(chat_id)
        if key not in self.users:
            self.users[key] = new_user(locale, now)
        return self.users[key]

    def iter_plants(self) -> Iterator[tuple[str, dict, dict]]:
        for chat_id, user in self.users.items():
            for plant in user.get("plants", []):
                yield chat_id, user, plant


def find_plant(user: dict, plant_id: str) -> dict | None:
    for plant in user.get("plants", []):
        if plant["id"] == plant_id:
            return plant
    return None


def is_onboarded(user: dict | None) -> bool:
    return bool(user) and user.get("onboarding", {}).get("step") == "done" and bool(user.get("plants"))
