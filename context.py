"""The application context handed to handlers and the tick.

Everything with a side effect - the clock, Telegram, the sensor, the vision call - enters through
this object, so the handlers can be exercised in tests with fakes and no network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Optional, Sequence

from config import Config
from env_source import EnvSource, Reading
from locales import Strings
from state import State

# One row of inline buttons is a list of (label, callback_data); a keyboard is a list of rows.
Keyboard = Sequence[Sequence[tuple[str, str]]]
SendFn = Callable[[int, str, Optional[Keyboard]], Optional[int]]  # returns message_id when known
ClearButtonsFn = Callable[[int, int], None]
SourceFactory = Callable[[dict], Optional[EnvSource]]
VisionFn = Callable[[bytes], Optional[dict]]
PhotoSaver = Callable[[int, str, bytes], str]  # (chat_id, plant_id, jpeg) -> stored path
XiaomiProbe = Callable[[], Optional[tuple[str, "Reading"]]]  # resolve the device, read it live


@dataclass
class AppContext:
    config: Config
    state: State
    strings: Strings
    send: SendFn
    now: Callable[[], datetime]
    make_primary_source: SourceFactory
    fallback_source: Optional[EnvSource]
    clear_buttons: Optional[ClearButtonsFn] = None
    vision: Optional[VisionFn] = None
    save_photo: Optional[PhotoSaver] = None
    probe_xiaomi: Optional[XiaomiProbe] = None
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("plant"))

    @property
    def t(self):
        return self.strings.t

    def today(self) -> date:
        return self.now().date()
