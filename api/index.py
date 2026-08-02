"""
api/index.py
------------
Vercel's entry point for the FastAPI control plane.

Vercel's Python runtime looks for files under ``api/`` and expects an ASGI
callable named ``app``. That is all this file provides: the application is
built by ``src/api/main.py`` exactly as it is for uvicorn, docker-compose and
the test suite, so what deploys is the object those exercise rather than a
parallel one assembled for the platform.

The two lines of ceremony below are not decoration:

``sys.path`` — the handler lives in ``api/`` and imports from ``src/`` at the
repository root. Whether a platform puts the project root on the path is a
detail of its invoker, and getting it wrong surfaces as ``ModuleNotFoundError:
src`` at runtime, on a build that succeeded. Adding the parent directory
explicitly costs nothing and removes the question.

``includeFiles`` in ``vercel.json`` is the other half. Python dependency
tracing cannot see through ``from src.api.main import app`` reliably, so the
package has to be named as an asset or it is simply absent from the bundle.

There is deliberately **no catch-all rewrite** in ``vercel.json``. There was
one — ``{"source": "/(.*)", "destination": "/api/index"}`` — and it made every
route in this application unreachable. A Vercel rewrite rewrites the *path*:
the function is invoked with ``/api/index``, not with the path the client
asked for, so FastAPI received ``/api/index`` for every request and answered
its own 404 to all of them. The runtime routes a detected ASGI ``app`` on the
full path already, which is why Vercel's own FastAPI example declares real
paths like ``/api/items/{item_id}`` inside the application and configures no
rewrite at all.

The bug was invisible for as long as it existed, because the module raised at
import and every request returned ``FUNCTION_INVOCATION_FAILED`` before
routing happened. It became visible in the same deploy that stopped the app
crashing — a 404 in the runtime log naming ``/api/index`` on a request for
``/api/v1/health``.
"""

from __future__ import annotations

import pathlib
import sys

# The repository root, one level up from api/.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.main import app  # noqa: E402

__all__ = ["app"]
