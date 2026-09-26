"""
test_metrics_contract.py
------------------------
A backtest figure the run did not record crosses the API as ``null``, and the
page is typed to receive one.

Two halves of one rule (CLAUDE.md: an unmeasured metric is never zero). The
API's ``BacktestMetrics`` used to fill a missing key from its own defaults —
252 sessions a year, no fills, a Sharpe of 0.0 ± 0.0, costs at 1x — so the
page's "not measured" branches could never fire. And ``lib/api.ts`` typed the
same fields as plain numbers, so once the API did send a ``null`` nothing made
a page handle it: ``fmtNum(null)`` throws, and ``String(null)`` prints "null".

So: no figure of the response model has a default other than ``None``, and
every field the model may send as ``None`` is ``| null`` in the TypeScript
interface the pages are checked against. The integration half, a stored row
with keys missing served through the real endpoint, is
``tests/integration/test_unmeasured_is_null.py``.

Standard library, pydantic and pytest: nothing here needs Node or a database.
"""

from __future__ import annotations

import re
import types
import typing
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from src.api.schemas import BacktestMetrics  # noqa: E402

API_TS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "api.ts"


def _ts_interface(source: str, name: str) -> dict[str, str]:
    """``{field: type}`` for one ``export interface`` in a TypeScript file."""
    match = re.search(
        rf"export interface {name} \{{(?P<body>.*?)^\}}", source, re.S | re.M
    )
    assert match, f"no `export interface {name}` in {API_TS}"
    body = re.sub(r"/\*.*?\*/", "", match["body"], flags=re.S)
    fields = {}
    for line in body.splitlines():
        field = re.match(r"\s*(\w+)\??:\s*(.+?);\s*(?://.*)?$", line)
        if field:
            fields[field[1]] = field[2]
    return fields


def _nullable(annotation) -> bool:
    return type(None) in typing.get_args(annotation) or annotation is types.NoneType


def test_no_figure_has_a_default_but_none() -> None:
    """
    Read off the model, so a field added later with a numeric default fails
    here rather than joining the defaults this replaced.
    """
    invented = {
        name: field.default
        for name, field in BacktestMetrics.model_fields.items()
        if field.default is not None
    }
    assert not invented, (
        "BacktestMetrics would report these for a run that never recorded them; "
        f"an unmeasured metric is never a number (CLAUDE.md): {invented}"
    )


def test_every_field_the_api_may_omit_is_nullable_in_the_page_types() -> None:
    ts = _ts_interface(API_TS.read_text(encoding="utf-8"), "BacktestMetrics")
    api = set(BacktestMetrics.model_fields)
    assert set(ts) == api, (
        "web/src/lib/api.ts and src/api/schemas.py disagree about the fields of "
        f"BacktestMetrics: only in TS {sorted(set(ts) - api)}, "
        f"only in the API {sorted(api - set(ts))}"
    )
    not_nullable = sorted(
        name
        for name, field in BacktestMetrics.model_fields.items()
        if _nullable(field.annotation) and "null" not in ts[name]
    )
    assert not not_nullable, (
        "the API may send these as null and the page is typed as if it never "
        f"would, so nothing makes a page render them through <Absent>: {not_nullable}"
    )


def test_the_interface_reader_reads_types() -> None:
    """Guards the guard: a reader that found no fields would pass everything."""
    source = """
export interface Sample {
  /** A comment with a colon: here. */
  plain: number;
  nullable: number | null;
  optional?: string; // trailing
}
"""
    assert _ts_interface(source, "Sample") == {
        "plain": "number",
        "nullable": "number | null",
        "optional": "string",
    }
