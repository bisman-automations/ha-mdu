"""A fake MDU portal on a local aiohttp test server.

The client talks to it over real HTTP, so cookies, redirects and headers
behave as they do against the real portal, with no response mocking library.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

Responder = Callable[[web.Request, bytes], web.StreamResponse]

# A base64 value with "=" padding, like the portal's real session cookie.
SESSION_COOKIE = ("SESSION", "YmFkZjAwZA==")


def html(body: str, status: int = 200, **headers: str) -> Responder:
    return lambda request, raw: web.Response(text=body, status=status, content_type="text/html", headers=headers)


def as_json(obj: Any, status: int = 200) -> Responder:
    return lambda request, raw: web.Response(text=json.dumps(obj), status=status, content_type="application/json")


def redirect(location: str) -> Responder:
    return lambda request, raw: web.Response(status=302, headers={"Location": location})


def empty(status: int = 200, **headers: str) -> Responder:
    return lambda request, raw: web.Response(status=status, headers=headers)


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes

    @property
    def form(self) -> dict[str, str]:
        from urllib.parse import parse_qsl

        return dict(parse_qsl(self.body.decode()))

    @property
    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class FakePortal:
    """Routes are (METHOD, path) → responder, or a list used in turn (the last one repeats)."""

    routes: dict[tuple[str, str], Responder | list[Responder]] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)
    server: TestServer | None = None

    def on(self, method: str, path: str, *responders: Responder) -> None:
        self.routes[(method.upper(), path)] = list(responders) if len(responders) > 1 else responders[0]

    def sent(self, method: str, path: str) -> list[Recorded]:
        return [r for r in self.requests if r.method == method.upper() and r.path == path]

    @property
    def url(self) -> str:
        assert self.server is not None
        return str(self.server.make_url("")).rstrip("/")

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        raw = await request.read()
        self.requests.append(Recorded(request.method, request.path, dict(request.headers), raw))
        key = (request.method, request.path)
        if key not in self.routes:
            return web.Response(status=404, text=f"no route for {key}")
        route = self.routes[key]
        if isinstance(route, list):
            responder = route.pop(0) if len(route) > 1 else route[0]
        else:
            responder = route
        response = responder(request, raw)
        # The real portal starts a session on its sign-in page.
        if request.method == "GET" and request.path == "/login":
            response.headers.add("Set-Cookie", f"{SESSION_COOKIE[0]}={SESSION_COOKIE[1]}; Path=/; HttpOnly")
        return response

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self.server = TestServer(app)
        await self.server.start_server()

    async def close(self) -> None:
        if self.server is not None:
            await self.server.close()
