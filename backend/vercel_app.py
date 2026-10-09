"""
ASGI entrypoint for deploying the API as a Vercel Service.

Vercel routes `/api/(.*)` to this service but passes the **original** path
through -- `GET /api/health` arrives as `/api/health`, not `/health`. The app's
routes are defined without that prefix (and are served without it on Render and
locally), so rather than duplicate every route or hard-code a deployment detail
into the router, the prefix is stripped here at the ASGI boundary.

Mounting the app under a parent FastAPI instance would also work, but Starlette
does not propagate lifespan events into mounted sub-applications, so the
snapshot would never load. This wrapper forwards every scope type untouched,
including `lifespan`.

Vercel points at this module via `entrypoint` in vercel.json.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app as _api  # noqa: E402

PREFIX = os.getenv("API_PREFIX", "/api")


class StripPrefix:
    """Remove a fixed path prefix before handing the request to the app."""

    def __init__(self, app, prefix: str):
        self.app = app
        self.prefix = prefix.rstrip("/")

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket") and self.prefix:
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                scope = dict(scope)
                scope["path"] = path[len(self.prefix):] or "/"
                # raw_path is bytes and is what some routers prefer; keep the
                # two consistent or they disagree about which route matched.
                raw = scope.get("raw_path")
                if isinstance(raw, (bytes, bytearray)):
                    stripped = bytes(raw)[len(self.prefix.encode()):] or b"/"
                    scope["raw_path"] = stripped
        await self.app(scope, receive, send)


app = StripPrefix(_api, PREFIX)
