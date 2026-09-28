"""
jev_stats.py
------------
The statistics the Jev evaluation harness reports, and nothing that can call
anything. Pure: the standard library alone.

Phase C4 lands the two the forward clock's report needs, a proportion and its
Wilson interval; the harness (C9) adds the rest here. One rule runs through
every function, because the research UI is a machine for fooling yourself:
**a figure computed over nothing is ``None``, never 0.** A coverage of "0 of 0
sessions" is not a coverage of zero, and printed as 0.00 it is the most
flattering lie a report about a model that never answered could tell.
``tests/unit/test_jev_stats.py`` feeds every function empty input.
"""

from __future__ import annotations

import math
from statistics import NormalDist


def proportion(k: int, n: int) -> float | None:
    """``k / n``, or ``None`` when ``n`` is 0: nothing was measured."""
    _check_counts(k, n)
    return k / n if n else None


def wilson(
    k: int, n: int, level: float = 0.95, *, one_sided: bool = False
) -> tuple[float, float] | None:
    """
    The Wilson score interval for ``k`` successes in ``n`` trials, or ``None``
    when ``n`` is 0.

    Wilson rather than the normal approximation, which gives an interval of
    zero width at 0 of n and n of n and one reaching below 0 near them: exactly
    where a small forward sample sits. ``level`` is two-sided by default, so
    0.95 leaves 2.5% outside each bound. With ``one_sided``, each bound is a
    one-sided bound at ``level`` — the lower is the figure a gate compares with
    a target at, say, 0.995 — and the pair is not an interval at ``level``.

    At 0 of ``n`` the lower bound is exactly 0, and at ``n`` of ``n`` the upper
    exactly 1, as they are in exact arithmetic: the floating-point formula
    leaves a residue near 1e-17 there, which put the bound on the wrong side of
    the estimate itself (``tests/unit/test_jev_stats.py``).
    """
    _check_counts(k, n)
    if not 0.0 < level < 1.0:
        raise ValueError(
            f"level is a probability strictly between 0 and 1, got {level}"
        )
    if n == 0:
        return None
    tail = 1.0 - level if one_sided else (1.0 - level) / 2.0
    z = NormalDist().inv_cdf(1.0 - tail)
    p = k / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denominator
    lower = 0.0 if k == 0 else max(0.0, centre - half)
    upper = 1.0 if k == n else min(1.0, centre + half)
    return lower, upper


def _check_counts(k: int, n: int) -> None:
    for name, value in (("k", k), ("n", n)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} is a count, got {value!r}")
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"k and n are counts with 0 <= k <= n, got k={k}, n={n}")


__all__ = ["proportion", "wilson"]
