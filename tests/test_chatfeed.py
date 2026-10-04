from twitch_radio.chatfeed import ChatFeed


def test_remove_message_and_remove_user_take_entries_off_the_overlay():
    feed = ChatFeed()
    feed.append("A", "one", message_id="m1", user_id="u1")
    feed.append("B", "two", message_id="m2", user_id="u2")
    feed.append("A", "three", message_id="m3", user_id="u1")
    queue = feed.subscribe_state()

    assert feed.remove_message("m2") is True
    assert [m["text"] for m in feed.snapshot()] == ["one", "three"]
    assert queue.qsize() >= 1  # overlays are told to refresh

    assert feed.remove_message("m2") is False and feed.remove_message("") is False
    assert feed.remove_user("u1") == 2
    assert feed.snapshot() == []
    assert feed.remove_user("u1") == 0 and feed.remove_user("") == 0


def test_snapshot_never_exposes_twitch_ids():
    feed = ChatFeed()
    feed.append("A", "hi", message_id="secret-msg", user_id="secret-user")
    (entry,) = feed.snapshot()
    assert "secret-msg" not in str(entry) and "secret-user" not in str(entry)
