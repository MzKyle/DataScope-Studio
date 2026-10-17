from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

import pytest

from datascope_core.query import run_custom_query
from datascope_core.query_sql import compile_custom_query
from datascope_core.workspace import Workspace
import datascope_core.workspace_query as workspace_query


@pytest.fixture
def catalog(tmp_path):
    workspace = Workspace(tmp_path / "workspace")
    source_path = tmp_path / "data.csv"
    source_path.write_text("time,value\n0,1\n", encoding="utf-8")
    projects = [workspace.create_project(name)["id"] for name in ("one", "two")]
    for project, ids in zip(projects, (("r_a", "r_b"), ("r_foreign",))):
        source = workspace.add_source(project, str(source_path), storage_mode="reference")["id"]
        with workspace._connect() as conn:
            for recording in ids:
                conn.execute("INSERT INTO recordings (id, project_id, source_id, app_id, path, run_name, created_at) "
                             "VALUES (?, ?, ?, 'test', 'unused.rrd', ?, 'test')", (recording, project, source, recording))
                values = [0.9, "0.10", True, False, None, "bad", 0.05, 2**53 + 1,
                          float("nan"), float("inf"), -float("inf"), {"code": 42}, [1, 2]]
                rows = [(recording, source, float(i), "/Robot/K%_/Battery", "scalar", "Battery%_",
                         json.dumps(value)) for i, value in enumerate(values)]
                rows += [(recording, source, None, "/null", "scalar", "temperature", "2"),
                         (recording, source, 0., "/robot/state", "state", "state", '"WARNING"'),
                         (recording, source, 0., "/robot/temperature", "scalar", "temperature", "20"),
                         (recording, source, 1., "/robot/İ", "scalar", "İ", "3"),
                         (recording, source, 1., "/robot/nul", "scalar", "a\x00b", "4")]
                conn.executemany("INSERT INTO query_rows VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return workspace, projects[0], projects[1]


def legacy(workspace, project, filters=None, recording_ids=None, semantic_types=None, limit=1000):
    workspace.get_project(project)
    return run_custom_query(workspace._iter_query_rows(project, recording_ids=recording_ids,
                            semantic_types=semantic_types), filters, limit)


def assert_same(left, right):
    assert type(left) is type(right)
    if isinstance(left, dict):
        assert left.keys() == right.keys()
        for key in left:
            assert_same(left[key], right[key])
    elif isinstance(left, list):
        assert len(left) == len(right)
        for a, b in zip(left, right):
            assert_same(a, b)
    elif isinstance(left, float) and math.isnan(left):
        assert math.isnan(right)
    else:
        assert left == right


@pytest.mark.parametrize("filters", [
    None, {}, {"key": "  bAtTeRy%_  "}, {"entity_path": "k%_"},
    {"key": "i\u0307"}, {"key": "%"}, {"key": "_"}, {"key": "a\x00b"},
    {"key": "x' OR 1=1 --"}, {"time_start": 0., "time_end": 1.},
    {"time_start": "1", "time_end": "1"}, {"time_start": 5., "time_end": 1.},
    {"time_start": True}, {"time_start": "bad"}, {"time_start": float("nan")},
    {"time_start": float("inf")}, {"time_end": -float("inf")},
    {"key": "battery", "operator": "lt", "value": 0.2},
    {"key": "battery", "operator": "gte", "value": "0.1"},
    {"operator": "gt", "value": 0}, {"operator": "lte", "value": 0.1},
    {"operator": "lt", "value": True}, {"operator": "lt", "value": "bad"},
    {"operator": "gt", "value": float("nan")}, {"operator": "eq", "value": 2**53 + 1},
    {"operator": "contains", "value": "WARN"}, {"text": "BATTERY%_ 0.1"},
    {"key": "battery", "text": "BAD", "time_start": 1.},
    {"operator": "unsupported", "value": ""},
])
@pytest.mark.parametrize("limit", [1, 1000])
def test_custom_query_matches_legacy(catalog, filters, limit):
    workspace, project, _ = catalog
    expected = legacy(workspace, project, filters, limit=limit)
    actual = workspace.custom_query(project, filters, limit=limit)
    assert_same(actual, expected)


@pytest.mark.parametrize("recordings,semantics", [(None, None), ([], []), (["r_b", "r_a"], None),
    (["r_a"], ["scalar"]), (["r_a", "r_a"], ["state"]), (["r_foreign"], None)])
def test_recording_and_project_scope(catalog, recordings, semantics):
    workspace, project, _ = catalog
    filters = {"time_start": 0, "time_end": 1}
    assert_same(workspace.custom_query(project, filters, recordings, semantics),
                legacy(workspace, project, filters, recordings, semantics))


@pytest.mark.parametrize("limit", [0, -1, 1.5, True])
def test_core_limit_compatibility(catalog, limit):
    workspace, project, _ = catalog
    assert_same(workspace.custom_query(project, {"key": "battery"}, limit=limit),
                legacy(workspace, project, {"key": "battery"}, limit=limit))


def test_lazy_validation_and_database_errors(catalog):
    workspace, project, _ = catalog
    for method in (workspace.custom_query, lambda *a, **k: legacy(workspace, *a, **k)):
        assert method(project, {"key": "absent", "operator": "invalid", "value": 1})["rows"] == []
        assert method(project, {"time_start": 10**400}, recording_ids=["absent"])["rows"] == []
        with pytest.raises(ValueError, match="Unsupported custom query operator"):
            method(project, {"key": "temperature", "operator": "invalid", "value": 1})
        with pytest.raises(OverflowError):
            method(project, {"time_start": 10**400})
        with pytest.raises(KeyError):
            method("missing", {})
    with workspace._connect() as conn:
        conn.execute("DROP TABLE query_rows")
    with pytest.raises(sqlite3.OperationalError):
        workspace.custom_query(project, {"key": "battery"})


def test_sql_limit_and_residual_filter_read_counts(catalog, monkeypatch):
    workspace, project, _ = catalog
    captured, count = [], 0
    connect, convert = workspace._connect, workspace_query.row_to_dict
    def traced_connect():
        conn = connect()
        conn.set_trace_callback(captured.append)
        return conn
    def counted(row):
        nonlocal count
        count += 1
        return convert(row)
    monkeypatch.setattr(workspace, "_connect", traced_connect)
    monkeypatch.setattr(workspace_query, "row_to_dict", counted)
    result = workspace.custom_query(project, {"key": "battery", "operator": "lt", "value": 0.08},
                                    ["r_a"], limit=1)
    assert result["rows"][0]["time"] == 6.
    assert count == 7  # The initial rows fail, including a numeric string and booleans.
    sql = next(sql for sql in reversed(captured) if "select qr.*" in sql)
    assert "limit" not in sql.lower()
    count = 0
    workspace.custom_query(project, {"key": "battery"}, ["r_a"], limit=1)
    assert count == 1
    assert "limit 1" in next(sql for sql in reversed(captured) if "select qr.*" in sql).lower()
    count = 0
    result = workspace.custom_query(project, {"time_start": 10., "time_end": 12.}, ["r_a"])
    assert count == len(result["rows"]) == 3


def test_query_is_read_only_and_plan_parameters_are_bound(catalog):
    workspace, project, _ = catalog
    def schema():
        with workspace._connect() as conn:
            return conn.execute("pragma user_version").fetchone()[0], [tuple(row) for row in
                conn.execute("select type,name,sql from sqlite_master order by type,name")]
    before = schema()
    filters = {"key": "' OR 1=1 --", "entity_path": "k%_", "time_start": 1, "time_end": 2}
    plan = compile_custom_query(filters)
    assert "' OR 1=1 --" not in " ".join(plan.conditions)
    assert filters["key"].lower() in plan.parameters
    assert not plan.needs_python_filter
    workspace.custom_query(project, filters)
    assert schema() == before
