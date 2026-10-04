from twitch_radio.cooldown import CooldownTracker


def test_per_chatter_keys_cannot_grow_without_bound():
    now = [0.0]
    tracker = CooldownTracker(lambda: now[0], max_keys=100)
    for i in range(1000):
        now[0] += 1
        tracker.mark(f"user:{i}")
    assert len(tracker._last_used_at) <= 100
    # the most recent users are the ones kept, so their cooldowns still apply
    assert tracker.remaining("user:999", 60) > 0
    assert tracker.remaining("user:0", 60) == 0


def test_remarking_a_key_refreshes_it_rather_than_duplicating():
    now = [0.0]
    tracker = CooldownTracker(lambda: now[0])
    tracker.mark("a")
    now[0] = 50
    tracker.mark("a")
    assert tracker.remaining("a", 60) == 60 - 0 and len(tracker._last_used_at) == 1
