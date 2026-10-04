from twitch_radio.filters import (
    PermitBook, StrikeTracker, TermMatcher, evaluate, find_link, is_shouting, normalize_domain, visible_text,
)


def test_emotes_are_not_counted_as_shouting():
    frags = [{"type": "emote", "name": "KEKWKEKW"}, {"type": "text", "text": " nice one"}]
    assert not is_shouting(visible_text(frags, "KEKWKEKW nice one"), 70)
    assert is_shouting("STOP SPAMMING ME NOW", 70)


def test_short_and_mixed_messages_are_not_shouting():
    assert not is_shouting("OK LOL", 70)  # fewer than 10 letters
    assert not is_shouting("This Is Fine Actually Really", 70)


def test_threshold_is_respected():
    text = "HELLO everyone"  # 5 of 13 letters upper
    assert not is_shouting(text, 50)
    assert is_shouting("HELLO EVERYone", 50)


def test_visible_text_falls_back_without_fragments():
    assert visible_text([], "raw text") == "raw text"


def test_link_detection():
    assert find_link("go to https://evil.example/x now") == "evil.example"
    assert find_link("join discord.gg/abc") == "discord.gg"
    assert find_link("see WWW.Spam.com") == "spam.com"
    assert find_link("just chatting") is None
    assert find_link("yeah.it was fine") is None  # ambiguous short TLDs are not treated as links
    assert find_link("mail me a@gmail.com") is None


def test_allowed_domains_cover_subdomains():
    assert find_link("clips.twitch.tv/x", ["twitch.tv"]) is None
    assert find_link("https://twitch.tv/x", ["https://www.twitch.tv/"]) is None
    assert find_link("nottwitch.tv/x", ["twitch.tv"]) == "nottwitch.tv"


def test_normalize_domain():
    assert normalize_domain("https://user@WWW.Example.com:8080/a?b#c") == "example.com"


def test_term_matcher_whole_words_only():
    matcher = TermMatcher(["Bad", "two words"])
    assert matcher.find("that is BAD") == "bad"
    assert matcher.find("badminton") is None
    assert matcher.find("say two words here") == "two words"
    matcher.set_terms([])
    assert matcher.find("bad") is None


def test_evaluate_priority_and_switches():
    matcher = TermMatcher(["heck"])
    text = "HECK VISIT spam.com NOW PLEASE STOP"
    assert evaluate(text, term_on=True, link_on=True, caps_on=True, matcher=matcher).reason == "term"
    assert evaluate(text, link_on=True, caps_on=True).reason == "link"
    assert evaluate(text, caps_on=True).reason == "caps"
    assert evaluate(text) is None
    assert evaluate("spam.com", link_on=True, may_post_links=True) is None


def test_strike_tracker_window():
    now = [0.0]
    tracker = StrikeTracker(clock=lambda: now[0])
    assert tracker.record("u", 60) == 1
    now[0] = 30
    assert tracker.record("u", 60) == 2
    now[0] = 70  # the first hit (age 70) has left the 60s window, the second (age 40) has not
    assert tracker.record("u", 60) == 2
    tracker.clear("u")
    assert tracker.record("u", 60) == 1


def test_permits_expire():
    now = [0.0]
    book = PermitBook(clock=lambda: now[0])
    book.grant("Alice", 60)
    assert book.active("alice")
    now[0] = 61
    assert not book.active("alice")


def test_term_matching_sees_through_invisible_characters_accents_and_homoglyphs():
    m = TermMatcher(["badword"])
    for sneaky in (
        "BADWORD",
        "b\u200badword",  # zero-width space
        "ba\u00addword",  # soft hyphen
        "b\u0430dword",  # Cyrillic a
        "\uff42\uff41\uff44\uff57\uff4f\uff52\uff44",  # fullwidth
        "bad\u0301word",  # combining accent
    ):
        assert m.find(sneaky) == "badword", sneaky
    assert m.find("badwords") is None  # still whole-word
    assert m.find("bad word") is None


def test_blocklist_entries_are_normalised_too():
    assert TermMatcher(["B\u0430dWord"]).find("badword") == "badword"


def test_link_detection_sees_through_obfuscation_but_not_ordinary_speech():
    assert find_link("go to discord[.]gg/x") == "discord.gg"
    assert find_link("evil(dot)com") == "evil.com"
    assert find_link("\uff45\uff56\uff49\uff4c.com") == "evil.com"  # fullwidth letters
    assert find_link("evil\u2024com") == "evil.com"  # one-dot leader
    assert find_link("this is evil.casino now") == "evil.casino"  # newer TLDs
    assert find_link("the dot com bubble") is None
    assert find_link("yeah.it was fine") is None
    assert find_link("see evil[.]com", allowed_domains=["evil.com"]) is None
