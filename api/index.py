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
