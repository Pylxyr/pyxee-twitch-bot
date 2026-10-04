import pytest

from twitch_radio.economy import parse_bet
from twitch_radio.textutil import parse_int, parse_uint


@pytest.mark.parametrize("text", ["²", "①", "٣", "١٢", "9" * 13, "", " ", "-5", "1.5", "1e3", "0x10", "٣٤"])
def test_parse_uint_rejects_everything_but_plain_ascii_digits(text):
    assert parse_uint(text) is None


def test_parse_uint_accepts_plain_numbers():
    assert parse_uint("0") == 0 and parse_uint(" 42 ") == 42 and parse_uint("9" * 12) == 10**12 - 1


def test_parse_int_allows_one_leading_minus():
    assert parse_int("-7") == -7 and parse_int("7") == 7
    assert parse_int("--7") is None and parse_int("-") is None and parse_int("-²") is None


@pytest.mark.parametrize("text", ["²", "①", "٣", "9" * 5000, "9" * 40])
def test_gamble_amounts_that_used_to_raise_now_get_the_usage_message(text):
    bet, error = parse_bet(text, 100, 50)
    assert bet is None and error and error.startswith("Usage:")
