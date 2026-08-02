"""
api/index.py
------------
Vercel's entry point for the FastAPI control plane.

Vercel's Python runtime looks for files under ``api/`` and expects an ASGI
callable named ``app``. That is the whole of this file: the application is
built in ``src/api/main.py`` exactly as it is for uvicorn, docker-compose and
the test suite, so the deployed app is the same object those exercise rather
than a parallel one assembled for the platform.

What runs the jobs here
~~~~~~~~~~~~~~~~~~~~~~~
Nothing long-lived can exist on this host, so there is no worker. Set
``SERVERLESS_DRAIN_ENABLED=true`` and queued research jobs are executed by
``POST /api/v1/system/drain``, which the frontend calls after submitting a
backtest and which ``vercel.json`` also schedules. Research only — trading
jobs are not drainable, and ``test_drain_boundary.py`` holds that line.

This deployment therefore runs the **research lab**. The live path needs a
process that outlives a request, which is what ``render.yaml`` is for.
"""

from src.api.main import app

__all__ = ["app"]
