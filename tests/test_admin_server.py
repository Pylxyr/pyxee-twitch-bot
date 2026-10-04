"""End-to-end checks of the admin server's public and gated routes, run against a
real listener on an ephemeral port."""

from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager

import aiohttp
from conftest import run

from twitch_radio.admin.app import run_admin_server
from twitch_radio.admin.security import ConnectionLimiter
from twitch_radio.chatfeed import ChatFeed
from twitch_radio.netutil import host_without_port, parse_networks, rate_limit_key
from twitch_radio.runtime import RuntimeStatus
from twitch_radio.store import JsonStore


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager
async def _server(tmp_path, make_db, *, password=None):
    db = await make_db()
    port = _free_port()
    runner = await run_admin_server(
        chat_feed=ChatFeed(),
        status=RuntimeStatus(),
        tunables_store=JsonStore(tmp_path / "tunables.json"),
        specs_store=JsonStore(tmp_path / "specs.json"),
        toggles_store=JsonStore(tmp_path / "toggles.json"),
        db=db,
        settings_password=password,
        broadcast_info={},
        host="127.0.0.1",
        port=port,
        trusted_proxies=parse_networks("127.0.0.1/32")[0],
        session_hours=12,
        session_remember_days=30,
    )
    try:
        yield f"http://127.0.0.1:{port}", runner
    finally:
        await runner.cleanup()


def test_chat_json_and_healthz_are_rate_limited(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            statuses = [(await http.get(f"{base}/chat.json")).status for _ in range(125)]
            assert statuses[:120] == [200] * 120 and set(statuses[120:]) == {429}
            health = [(await http.get(f"{base}/healthz")).status for _ in range(32)]
            assert health[:30] == [200] * 30 and set(health[30:]) == {429}

    run(go())


def test_healthz_reuses_its_answer_for_a_few_seconds(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, runner), aiohttp.ClientSession() as http:
            ctx = next(iter(runner.app.values()))
            first = await (await http.get(f"{base}/healthz")).json()
            assert ctx.health_cache is not None
            second = await (await http.get(f"{base}/healthz")).json()
            assert first["uptime_seconds"] == second["uptime_seconds"]  # served from the cache

    run(go())


def test_websocket_connections_are_capped_per_client(tmp_path, make_db):
    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            sockets = [await http.ws_connect(f"{base}/ws/chat") for _ in range(8)]
            try:
                async with http.get(f"{base}/ws/chat") as refused:
                    assert refused.status == 429
                await sockets[0].close()
                await asyncio.sleep(0.2)  # the slot is released once the handler notices
                extra = await http.ws_connect(f"{base}/ws/chat")
                await extra.close()
            finally:
                for s in sockets:
                    await s.close()

    run(go())


def test_passwordless_settings_requires_a_loopback_host_header(tmp_path, make_db):
    """DNS rebinding: the attacker's page reaches us with Host: attacker.example, and an
    Origin that matches it, so only the Host itself can give it away."""

    async def go():
        async with _server(tmp_path, make_db) as (base, _), aiohttp.ClientSession() as http:
            ok = await http.get(f"{base}/settings", headers={"Accept": "text/html"})
            assert ok.status == 200
            rebound = await http.get(f"{base}/settings", headers={"Host": "attacker.example:8098"})
            assert rebound.status == 403
            origin = "http://attacker.example:8098"
            post = await http.post(
                f"{base}/settings",
                data={"action": "toggles"},
                headers={"Host": "attacker.example:8098", "Origin": origin},
            )
            assert post.status == 403

    run(go())


def test_login_turns_away_extra_concurrent_verifications(tmp_path, make_db, monkeypatch):
    import threading

    from twitch_radio.admin.handlers import login as login_mod

    release = threading.Event()
    seen = []

    def slow_verify(password, stored):
        seen.append(password)
        release.wait(5)
        return False

    monkeypatch.setattr(login_mod, "verify_password", slow_verify)

    async def go():
        async with _server(tmp_path, make_db, password="secret") as (base, _), aiohttp.ClientSession() as http:
            headers = {"Origin": base}

            async def attempt(i):
                resp = await http.post(f"{base}/login", data={"password": f"p{i}"}, headers=headers)
                return resp.status

            tasks = [asyncio.create_task(attempt(i)) for i in range(2)]
            await asyncio.sleep(0.3)  # both verifications are now running
            assert await attempt(99) == 429  # the third is refused, not queued
            release.set()
            assert sorted(await asyncio.gather(*tasks)) == [401, 401]
            assert "p99" not in seen

    run(go())


def test_rate_limit_key_groups_ipv6_by_64_and_leaves_ipv4_alone():
    assert rate_limit_key("203.0.113.9") == "203.0.113.9"
    a = rate_limit_key("2001:db8:1:2:aaaa:bbbb:cccc:dddd")
    b = rate_limit_key("2001:db8:1:2:1111:2222:3333:4444")
    assert a == b == "2001:db8:1:2::/64"
    assert rate_limit_key("2001:db8:1:3::1") != a
    assert rate_limit_key("::ffff:203.0.113.9") == "203.0.113.9"


def test_host_without_port():
    assert host_without_port("localhost:8098") == "localhost"
    assert host_without_port("[::1]:8098") == "::1"
    assert host_without_port("127.0.0.1") == "127.0.0.1"
    assert host_without_port(None) == ""


def test_connection_limiter_counts_and_releases():
    lim = ConnectionLimiter(max_per_key=2, max_total=3)
    assert lim.acquire("a") and lim.acquire("a") and not lim.acquire("a")
    assert lim.acquire("b") and not lim.acquire("c")  # total cap
    lim.release("a")
    assert lim.acquire("c") and lim.total == 3
    lim.release("zzz")  # releasing something never acquired is a no-op
    assert lim.total == 3
