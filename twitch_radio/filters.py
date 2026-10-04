"""Chat-filter rules. Pure logic (no Twitch, no I/O) so every rule is unit
testable; `automod.py` wires the verdicts to warnings, deletes and timeouts."""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

REASON_LINK = "link"
REASON_CAPS = "caps"
REASON_TERM = "term"

# Deliberately not every TLD: short ambiguous ones (.in .it .to .me .us) would
# flag ordinary typos like "yeah.it was". These are the ones spam actually uses.
_TLDS = (
    "com", "net", "org", "io", "gg", "tv", "ly", "xyz", "info", "gl", "cc", "ws", "fm", "app", "dev",
    "ai", "sh", "biz", "online", "site", "store", "club", "shop", "link", "click", "top", "vip", "icu",
    "pw", "live", "ru", "cn", "tk", "ml", "ga", "cf", "gq", "buzz", "fun", "life", "world", "today",
    "cloud", "pro", "tech", "space", "website", "page", "art", "one", "lol", "wtf", "gift", "gifts",
    "bet", "casino", "win", "bid", "stream", "tube", "video", "chat", "games", "game", "work", "rest",
)
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_BARE_RE = re.compile(
    r"(?<![\w@./-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:" + "|".join(_TLDS) + r")(?![\w-])"
    r"(?:[/:?#][^\s<>\"']*)?",
    re.IGNORECASE,
)


# Lookalike letters people substitute to slip past a word list. Deliberately
# small: Unicode compatibility decomposition (below) already folds fullwidth
# letters, ligatures, circled/mathematical alphabets and accents; this covers
# the common Cyrillic and Greek homoglyphs it doesn't.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
        "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
        "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
        "υ": "u", "χ": "x", "ɡ": "g", "ɑ": "a", "ı": "i", "ӏ": "l",
    }
)


def normalize_for_matching(text: str) -> str:
    """The form of `text` that filters compare against: compatibility-decomposed,
    with combining marks (zalgo, accents) and invisible format characters
    (zero-width spaces/joiners, soft hyphens, bidi controls) removed, common
    homoglyphs mapped to Latin, and case folded. Used for *matching only* —
    the original text is what's shown, logged and deleted."""
    decomposed = unicodedata.normalize("NFKD", text)
    kept = "".join(c for c in decomposed if unicodedata.category(c) not in ("Mn", "Cf"))
    return kept.casefold().translate(_CONFUSABLES)


_DEOBFUSCATE_BRACKETED_DOT = re.compile(r"\s*[\[\(\{<]\s*(?:\.|dot)\s*[\]\)\}>]\s*", re.IGNORECASE)


def deobfuscate_links(text: str) -> str:
    """'example[.]com' and 'example(dot)com' -> 'example.com'. A bare spoken
    "dot" is deliberately not treated as a dot: "the dot com bubble" is
    ordinary speech, and flagging it would cost more than it catches."""
    return _DEOBFUSCATE_BRACKETED_DOT.sub(".", text)


@dataclass(frozen=True, slots=True)
class Violation:
    reason: str
    detail: str = ""


def visible_text(fragments: Sequence[dict[str, object]], fallback: str) -> str:
    """The message with emotes and cheermotes removed. Falls back to the raw
    text when no fragments are available."""
    if not fragments:
        return fallback
    return "".join(str(f.get("text", "")) for f in fragments if f.get("type") == "text")


def is_shouting(text: str, threshold_percent: int, min_letters: int = 10) -> bool:
    letters = [c for c in text if c.isalpha()]
    if len(letters) < min_letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper * 100 > threshold_percent * len(letters)


def normalize_domain(value: str) -> str:
    """'https://www.Example.com/x' -> 'example.com' (also accepts a bare host)."""
    host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip(), flags=re.IGNORECASE)
    host = re.split(r"[/?#]", host, maxsplit=1)[0].rsplit("@", 1)[-1]
    host = host.split(":", 1)[0].strip(".").lower()
    return host[4:] if host.startswith("www.") else host


def _allowed(host: str, allowed: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed)


def find_link(text: str, allowed_domains: Iterable[str] = ()) -> str | None:
    """First link in `text` whose host isn't allow-listed, else None. Catches
    scheme/www links and bare domains like `discord.gg/x`."""
    allowed = tuple(normalize_domain(d) for d in allowed_domains)
    text = deobfuscate_links(normalize_for_matching(text))
    for pattern in (_URL_RE, _BARE_RE):
        for match in pattern.finditer(text):
            host = normalize_domain(match.group(0))
            if host and not _allowed(host, allowed):
                return host
    return None


class TermMatcher:
    """Whole-word matching against a blocklist, after both sides go through
    normalize_for_matching (case, accents, zero-width characters, homoglyphs)."""

    def __init__(self, terms: Iterable[str] = ()) -> None:
        self._terms: tuple[str, ...] = ()
        self._re: re.Pattern[str] | None = None
        self.set_terms(terms)

    @property
    def terms(self) -> tuple[str, ...]:
        return self._terms

    def set_terms(self, terms: Iterable[str]) -> None:
        cleaned = sorted({normalize_for_matching(t).strip() for t in terms if t.strip()} - {""})
        self._terms = tuple(cleaned)
        self._re = (
            re.compile("|".join(rf"(?<!\w){re.escape(t)}(?!\w)" for t in cleaned), re.IGNORECASE) if cleaned else None
        )

    def find(self, text: str) -> str | None:
        match = self._re.search(normalize_for_matching(text)) if self._re else None
        return match.group(0) if match else None


def evaluate(
    text: str,
    *,
    fragments: Sequence[dict[str, object]] = (),
    link_on: bool = False,
    caps_on: bool = False,
    term_on: bool = False,
    caps_threshold_percent: int = 70,
    allowed_domains: Iterable[str] = (),
    matcher: TermMatcher | None = None,
    may_post_links: bool = False,
) -> Violation | None:
    """The first rule the message breaks (terms, then links, then caps)."""
    if term_on and matcher is not None:
        hit = matcher.find(text)
        if hit:
            return Violation(REASON_TERM, hit)
    if link_on and not may_post_links:
        host = find_link(text, allowed_domains)
        if host:
            return Violation(REASON_LINK, host)
    if caps_on and is_shouting(visible_text(fragments, text), caps_threshold_percent):
        return Violation(REASON_CAPS)
    return None


class StrikeTracker:
    """Counts violations per chatter inside a sliding window."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_users: int = 2000) -> None:
        self._clock = clock
        self._max_users = max_users
        self._hits: dict[str, list[float]] = {}

    def record(self, key: str, window_seconds: float) -> int:
        now = self._clock()
        hits = [t for t in self._hits.pop(key, []) if now - t <= window_seconds]
        hits.append(now)
        self._hits[key] = hits
        while len(self._hits) > self._max_users:
            del self._hits[next(iter(self._hits))]
        return len(hits)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)


class PermitBook:
    """Time-limited "may post links" grants, keyed by lowercase login."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until: dict[str, float] = {}

    def grant(self, login: str, seconds: float) -> None:
        now = self._clock()
        self._until = {k: v for k, v in self._until.items() if v > now}
        self._until[login.lower()] = now + seconds

    def active(self, login: str) -> bool:
        return self._until.get(login.lower(), 0.0) > self._clock()
