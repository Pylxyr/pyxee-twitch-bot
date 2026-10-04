"""Access control for the gated /settings route."""

from __future__ import annotations

import logging
from urllib.parse import quote

from aiohttp import web

from twitch_radio.admin.context import AdminContext, forwarded_host, is_https
from twitch_radio.admin.security import fetch_site_ok, origin_matches_host, safe_next_path
from twitch_radio.netutil import host_without_port, is_loopback_host, looks_proxied

log = logging.getLogger(__name__)

PROTECTED_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

SECURE_COOKIE = "__Host-radio_session"
PLAIN_COOKIE = "radio_session"

_LOCKED_MESSAGE = (
    "This page is disabled: no password is set, and this request either came through a reverse "
    "proxy or the server listens beyond localhost. Set TWITCH_SETTINGS_PASSWORD and restart. "
    "(Only on a network you fully trust, TWITCH_SETTINGS_ALLOW_OPEN=true restores password-less access.)"
)


def protect(response: web.Response) -> web.Response:
    for name, value in PROTECTED_HEADERS.items():
        response.headers[name] = value
    return response


def redirect(location: str) -> web.Response:
    return protect(web.Response(status=303, headers={"Location": location}))


def locked_response() -> web.Response:
    return protect(web.Response(status=403, text=_LOCKED_MESSAGE))


_BAD_HOST_MESSAGE = (
    "Refusing this request: with no password set, /settings only answers to localhost, 127.0.0.1 or [::1] "
    "(this stops a malicious web page from reaching it through a DNS-rebinding trick). Open it at "
    "http://localhost:<port>/settings, or set TWITCH_SETTINGS_PASSWORD."
)


def session_token(request: web.Request) -> str | None:
    return request.cookies.get(SECURE_COOKIE) or request.cookies.get(PLAIN_COOKIE)


def is_signed_in(ctx: AdminContext, request: web.Request) -> bool:
    return ctx.sessions.is_valid(session_token(request))


def set_session_cookie(
    response: web.Response, request: web.Request, token: str, *, max_age: int | None
) -> None:
    secure = is_https(request)
    response.set_cookie(
        SECURE_COOKIE if secure else PLAIN_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="Lax",
    )


def clear_session_cookie(response: web.Response) -> None:
    response.del_cookie(SECURE_COOKIE, path="/", secure=True, httponly=True, samesite="Lax")
    response.del_cookie(PLAIN_COOKIE, path="/", httponly=True, samesite="Lax")


def _is_local(ctx: AdminContext, request: web.Request) -> bool:
    return not ctx.exposed and not looks_proxied(request.headers)


def _login_required(request: web.Request) -> web.Response:
    if "text/html" in request.headers.get("Accept", ""):
        target = request.path_qs if request.method in ("GET", "HEAD") else request.path
        return redirect(f"/login?next={quote(safe_next_path(target), safe='')}")
    return protect(
        web.json_response({"error": "authentication required", "login": "/login"}, status=401)
    )


def authorize(ctx: AdminContext, request: web.Request) -> web.Response | None:
    """None to proceed; otherwise the response to return as-is."""
    if ctx.settings_password is None:
        if ctx.allow_open:
            return None
        if _is_local(ctx, request):
            # The Origin check compares against the Host header, which a
            # DNS-rebinding page controls, so password-less access additionally
            # insists the Host actually names this machine.
            if not is_loopback_host(host_without_port(request.headers.get("Host"))):
                log.warning("Refused password-less /settings request with Host %r.", request.headers.get("Host"))
                return protect(web.Response(status=403, text=_BAD_HOST_MESSAGE))
            return None
        return locked_response()
    if is_signed_in(ctx, request):
        return None
    return _login_required(request)


def origin_ok(request: web.Request) -> bool:
    ok = origin_matches_host(
        request.headers.get("Origin"),
        request.headers.get("Referer"),
        (request.headers.get("Host"), forwarded_host(request)),
    ) and fetch_site_ok(request.headers.get("Sec-Fetch-Site"))
    if not ok:
        log.warning(
            "Rejected %s %s from %s — Origin/Referer/Sec-Fetch-Site didn't match Host (possible CSRF, "
            "or a proxy that rewrites Host; nginx needs `proxy_set_header Host $host;`).",
            request.method,
            request.path,
            request.remote,
        )
    return ok
