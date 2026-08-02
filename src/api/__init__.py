"""
api
---
FastAPI control plane. Read queries, job enqueue, and the kill switch.

Never runs a backtest inline and never places an order — both belong to the
worker. See ``src/api/main.py``.
"""
