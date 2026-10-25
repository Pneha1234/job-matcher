"""Protection for an API that only listens on localhost.

Binding to 127.0.0.1 keeps other machines out, but not web pages open in the user's own
browser: any site can send requests to localhost. Two checks close that gap:

- DNS rebinding: a hostile domain that resolves to 127.0.0.1 makes the browser treat the
  API as same-origin. Such requests carry that domain in ``Host`` (or, through the
  Next.js proxy, ``X-Forwarded-Host``), so only local host names are accepted.
- Cross-site requests: a page on another site can still *send* a POST to localhost even
  though it can't read the reply. Browsers mark those with ``Origin`` and
  ``Sec-Fetch-Site``, so any request that changes data must come from a local origin.

Requests without these headers come from local tools (curl, scripts), not a browser,
and are allowed.
"""

from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1", "testserver"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _host_name(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:3000
        return value.split("]")[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _origin_is_local(origin: str) -> bool:
    if origin == "null":  # sandboxed iframes and file:// pages
        return False
    host = urlsplit(origin).hostname or ""
    return host in LOCAL_HOSTS or f"[{host}]" in LOCAL_HOSTS


class LocalOnlyMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        for name in ("host", "x-forwarded-host"):
            if name in headers and _host_name(headers[name].split(",")[0]) not in LOCAL_HOSTS:
                await _reject(send, "Requests must be addressed to localhost.")
                return
        if scope["method"] not in SAFE_METHODS:
            origin = headers.get("origin")
            if origin is not None and not _origin_is_local(origin):
                await _reject(send, "Cross-site requests are not allowed.")
                return
            if headers.get("sec-fetch-site") == "cross-site":
                await _reject(send, "Cross-site requests are not allowed.")
                return
        await self.app(scope, receive, send)


async def _reject(send: Send, message: str) -> None:
    body = ('{"detail": "' + message + '"}').encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
