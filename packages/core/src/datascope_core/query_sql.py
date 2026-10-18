"""Private, conservative candidate selection for the legacy custom-query path."""
from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from datascope_core.query import _filter_float


@dataclass(frozen=True)
class CustomQueryPlan:
    conditions: tuple[str, ...] = ()
    parameters: tuple[Any, ...] = ()
    needs_python_filter: bool = True
    needs_unicode_lower: bool = False
    metadata_conditions: tuple[str, ...] = ()
    metadata_parameters: tuple[Any, ...] = ()
    time_bounds: tuple[tuple[str, float], ...] = ()

    def sql_limit(self, limit: int) -> int | None:
        # Core historically accepts nonpositive/noninteger limits; leave those
        # to run_custom_query rather than changing its behavior through SQL.
        if not self.needs_python_filter and isinstance(limit, int) and limit > 0:
            return limit
        return None


def compile_custom_query(filters: dict[str, Any] | None) -> CustomQueryPlan:
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        return CustomQueryPlan()
    conditions: list[str] = []
    parameters: list[Any] = []
    residual = False
    unicode_lower = False
    metadata_conditions: list[str] = []
    metadata_parameters: list[Any] = []
    time_bounds: list[tuple[str, float]] = []
    try:
        for name, operator in (("time_start", ">="), ("time_end", "<=")):
            bound = _filter_float(filters.get(name))
            if bound is None:
                continue
            if not math.isfinite(bound):
                residual = True
                continue
            conditions.append(f"qr.time {operator} ?")
            parameters.append(bound)
            time_bounds.append((operator, bound))
        for name in ("entity_path", "key"):
            needle = str(filters.get(name) or "").strip().lower()
            if needle:
                conditions.append(f"instr(datascope_lower(qr.{name}), ?) > 0")
                parameters.append(needle)
                metadata_conditions.append(f"instr(datascope_lower(qr.{name}), ?) > 0")
                metadata_parameters.append(needle)
                unicode_lower = True
        text = str(filters.get("text") or "").strip().lower()
        operator = str(filters.get("operator") or "any")
        expected = filters.get("value")
        residual |= bool(text) or (operator != "any" and expected not in (None, ""))
    except (TypeError, ValueError, OverflowError):
        # Preserve the original filter's lazy validation (including empty input).
        return CustomQueryPlan()
    return CustomQueryPlan(tuple(conditions), tuple(parameters), residual, unicode_lower,
                           tuple(metadata_conditions), tuple(metadata_parameters), tuple(time_bounds))


def register_custom_query_functions(conn: sqlite3.Connection, plan: CustomQueryPlan) -> None:
    if plan.needs_unicode_lower:
        # SQLite lower() only handles ASCII. Cache repeated field/path strings,
        # with a bound so high-cardinality paths cannot retain the whole index.
        @lru_cache(maxsize=4096)
        def lower(value: str | None) -> str:
            return str(value or "").lower()

        conn.create_function("datascope_lower", 1, lower, deterministic=True)
