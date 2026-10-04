"""Small, strict parsers for numbers typed into chat.

`str.isdigit()` is not a safe pre-check for `int()`: it is true for characters
such as "²" and "①" (which `int()` rejects) and for non-ASCII decimal digits
such as Arabic-Indic "٣" (which `int()` accepts, so the same amount can be
spelled several ways). It also says nothing about size, and a number beyond
SQLite's 64-bit INTEGER raises OverflowError at the database. Everything that
turns chat text into an integer goes through here instead.
"""

from __future__ import annotations

# 12 digits is far beyond any bet, cooldown or count this bot accepts, and
# comfortably inside SQLite's INTEGER range.
MAX_DIGITS = 12


def parse_uint(text: str, *, max_digits: int = MAX_DIGITS) -> int | None:
    """A non-negative integer from plain ASCII digits, else None."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) > max_digits or not (cleaned.isascii() and cleaned.isdigit()):
        return None
    return int(cleaned)


def parse_int(text: str, *, max_digits: int = MAX_DIGITS) -> int | None:
    """Like parse_uint, but accepts one leading '-'."""
    cleaned = text.strip()
    if cleaned.startswith("-"):
        value = parse_uint(cleaned[1:], max_digits=max_digits)
        return None if value is None else -value
    return parse_uint(cleaned, max_digits=max_digits)
