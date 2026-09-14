"""User-facing copy, keyed by string id, selected by `BOT_LOCALE` (SPEC.md §10).

English is the default and the fallback for any key a locale lacks. `ru.py` is the only file in
the repo allowed to hold non-English text: it is UI data, not documentation.
"""

from __future__ import annotations

from datetime import date
from importlib import import_module

DEFAULT_LOCALE = "en"


class Strings:
    def __init__(self, locale: str):
        self.locale = locale
        self._primary = import_module(f"locales.{locale}")
        self._fallback = import_module(f"locales.{DEFAULT_LOCALE}")

    def raw(self, key: str) -> str:
        table = getattr(self._primary, "STRINGS", {})
        if key in table:
            return table[key]
        fallback = getattr(self._fallback, "STRINGS", {})
        if key in fallback:
            return fallback[key]
        raise KeyError(f"missing string id: {key}")

    def t(self, key: str, **kwargs) -> str:
        text = self.raw(key)
        return text.format(**kwargs) if kwargs else text

    def date(self, d: date) -> str:
        """'22 September' - day and month name, no year."""
        months = getattr(self._primary, "MONTHS", None) or getattr(self._fallback, "MONTHS")
        return f"{d.day} {months[d.month - 1]}"

    def days(self, n: int) -> str:
        """'1 day' / '12 days' with the locale's plural rule."""
        plural = getattr(self._primary, "plural_days", None) or getattr(self._fallback, "plural_days")
        return plural(n)


def get_strings(locale: str | None) -> Strings:
    try:
        return Strings(locale or DEFAULT_LOCALE)
    except ModuleNotFoundError:
        return Strings(DEFAULT_LOCALE)
