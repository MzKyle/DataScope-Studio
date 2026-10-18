from __future__ import annotations

import json
import math
import sqlite3

import pytest

from benchmarks.c2b_query_reference import C2bQueryReference
from datascope_core.query import QUERY_TEMPLATES
from datascope_core.query_typed import sample_table
from datascope_core.workspace import Workspace
from tests.unit.test_custom_query_pushdown import assert_same
from tests.unit.test_typed_query_storage import add_recording, make_catalog, to_typed


class ReferenceWorkspace(C2bQueryReference, Workspace):
    pass


def reference(workspace):
    result = object.__new__(ReferenceWorkspace)
    result.__dict__.update(workspace.__dict__)
    return result


@pytest.fixture
def mixed(tmp_path):
    catalog = make_catalog(tmp_path)
    workspace, project, source, spec = catalog
    add_recording(workspace, project, source, "r_0", spec)
    to_typed(catalog)
    return catalog


@pytest.mark.parametrize("filters", [
    {}, {"key": " bAtTeRy%_ "}, {"entity_path": "k%_", "time_end": 0},
    {"key": "battery", "operator": "lt", "value": "0.2"},
    {"operator": "gte", "value": 0.1}, {"operator": "lt", "value": True},
    {"operator": "lt", "value": "word"}, {"operator": "eq", "value": 9007199254740993},
    {"operator": "contains", "value": "WARN"}, {"text": "-0.0", "operator": "lte", "value": 0},
    {"time_start": math.nan, "operator": "lt", "value": 0.2},
    {"time_start": -math.inf, "operator": "lt", "value": 0.2},
    {"operator": "gt", "value": math.inf},
])
@pytest.mark.parametrize("ids,limit", [(None, 1), (["r_a"], 1000), ([], 0), (["r_0", "r_a"], -1)])
def test_mixed_matches_frozen_c2b(mixed, filters, ids, limit):
    workspace, project, _, _ = mixed
    assert_same(workspace.custom_query(project, filters, ids, limit=limit),
                reference(workspace).custom_query(project, filters, ids, limit=limit))


def test_routes_templates_complete_inputs_and_export(mixed, tmp_path):
    workspace, project, _, _ = mixed
    old = reference(workspace)
    for item in QUERY_TEMPLATES:
        template = item["template_id"]
        workspace._query_read_stats = {}
        assert_same(workspace.run_query(project, template), old.run_query(project, template))
        routes = workspace._query_read_stats.get("routes", [])
        if template in {"low_battery", "find_errors"}:
            assert any(row["source"] == "typed_sql" for row in routes)
        else:
            assert all(row["source"] == "typed_compat" for row in routes)
    for mode in ("summary", "series"):
        assert_same(workspace.compare(project, ["r_a", "r_0"], mode=mode),
                    old.compare(project, ["r_a", "r_0"], mode=mode))
    reports = [w.run_diagnostics(project, thresholds={"battery_low": 0.8}) for w in (workspace, old)]
    for report in reports:
        report.pop("created_at", None)
    assert_same(*reports)
    for w, name in ((workspace, "new.csv"), (old, "old.csv")):
        w.export_query(project, "find_errors", output_path=str(tmp_path / name))
    assert (tmp_path / "new.csv").read_bytes() == (tmp_path / "old.csv").read_bytes()


@pytest.mark.parametrize("operator", ["gt", "gte", "lt", "lte"])
def test_exact_int64_custom_float_vs_native_template(tmp_path, operator):
    numbers = [-(2**63), -(2**53 + 1), -1, 0, 2**53 - 1, 2**53, 2**53 + 1, 2**63 - 1]
    catalog = make_catalog(tmp_path, "time,battery\n" + "\n".join(
        f"{i},{n}" for i, n in enumerate(numbers)),
        [{"semantic_type": "scalar", "entity_path": "/battery", "source_fields": ["battery"]}])
    workspace, project, _, _ = catalog
    to_typed(catalog)
    old = reference(workspace)
    for target in (float(-(2**63)), float(-(2**53)), 0., float(2**53), float(2**63)):
        filters = {"operator": operator, "value": target}
        assert_same(workspace.custom_query(project, filters), old.custom_query(project, filters))
        assert_same(workspace.run_query(project, "low_battery", params={"threshold": target}),
                    old.run_query(project, "low_battery", params={"threshold": target}))


def test_bool_and_negative_zero_semantics(tmp_path):
    catalog = make_catalog(tmp_path, "time,battery,zero\n0,False,-0.0\n1,True,0.0\n", [
        {"semantic_type": "scalar_group", "entity_path": "/battery", "source_fields": ["battery", "zero"]}])
    workspace, project, _, _ = catalog
    to_typed(catalog)
    assert workspace.custom_query(project, {"key": "battery", "operator": "lt", "value": 2})["rows"] == []
    assert len(workspace.run_query(project, "low_battery", params={"threshold": 2})["rows"]) == 4
    result = workspace.custom_query(project, {"key": "zero", "operator": "lte", "value": 0})
    assert [math.copysign(1, r["value"]) for r in result["rows"]] == [-1, 1]


def test_sql_predicates_residual_limit_and_raw_diagnostics(mixed):
    workspace, project, _, _ = mixed
    captured = []
    connect = workspace._connect
    def traced():
        conn = connect()
        conn.set_trace_callback(captured.append)
        return conn
    workspace._connect = traced
    workspace._query_read_stats = {}
    filters = {"key": "battery", "operator": "lt", "value": 0.2}
    assert_same(workspace.custom_query(project, filters, ["r_a"], limit=1),
                reference(workspace).custom_query(project, filters, ["r_a"], limit=1))
    sample_sql = [s for s in captured if "FROM typed_samples_" in s]
    assert any("CAST" in s and "LIMIT 1" in s for s in sample_sql)
    assert any(r["source"] == "typed_sql" for r in workspace._query_read_stats["routes"])
    captured.clear()
    workspace.custom_query(project, {**filters, "text": "absent"}, ["r_a"], limit=1)
    assert all("LIMIT" not in s for s in captured if "FROM typed_samples_" in s)
    workspace._query_read_stats = {}
    workspace._query_rows(project, template_id="low_battery")
    assert all(r["source"] == "typed_compat" for r in workspace._query_read_stats["routes"])


@pytest.mark.parametrize("oversized", ["dictionary", "matches"])
def test_dictionary_caps_fall_back_without_losing_values(mixed, oversized):
    workspace, project, _, _ = mixed
    with workspace._connect() as conn:
        dataset = conn.execute("SELECT id FROM typed_datasets WHERE recording_id='r_a' "
                               "AND schema_id IN (SELECT id FROM typed_schemas WHERE family='state')").fetchone()[0]
        count = 4097 if oversized == "dictionary" else 501
        conn.executemany("INSERT INTO typed_states(dataset_id,value_json) VALUES (?,?)",
                         [(dataset, json.dumps(f"error_{i}")) for i in range(count)])
    workspace._query_read_stats = {}
    assert_same(workspace.run_query(project, "find_errors"), reference(workspace).run_query(project, "find_errors"))
    assert all(r["source"] == "typed_compat" for r in workspace._query_read_stats["routes"])


def test_lazy_errors_and_corruption_propagate(mixed):
    workspace, project, _, _ = mixed
    for w in (workspace, reference(workspace)):
        assert w.custom_query(project, {"operator": "invalid", "value": 1, "key": "absent"})["rows"] == []
        with pytest.raises(ValueError, match="Unsupported custom query operator"):
            w.custom_query(project, {"operator": "invalid", "value": 1, "key": "temperature"})
        with pytest.raises(OverflowError):
            w.custom_query(project, {"time_start": 10**400, "operator": "lt", "value": -1000}, ["r_a"])
    with workspace._connect() as conn:
        b = conn.execute("SELECT b.*, d.schema_id FROM typed_bindings b JOIN typed_datasets d "
                         "ON b.dataset_id=d.id WHERE b.key='temperature' AND b.recording_id='r_a'").fetchone()
        conn.execute(f"UPDATE {sample_table(b['schema_id'])} SET c{b['column_no']}=? WHERE dataset_id=?",
                     (b'corrupt', b['dataset_id']))
    with pytest.raises(sqlite3.DatabaseError):
        workspace.custom_query(project, {"key": "temperature", "operator": "lt", "value": -1}, ["r_a"])


def test_missing_state_dictionary_is_not_filtered_away(mixed):
    workspace, project, _, _ = mixed
    with workspace._connect() as conn:
        conn.execute("DELETE FROM typed_states WHERE value_json='\"running\"'")
    with pytest.raises(RuntimeError, match="Missing typed state"):
        workspace.run_query(project, "find_errors", ["r_a"])


def test_python_residual_reads_past_initial_numeric_matches(tmp_path):
    catalog = make_catalog(tmp_path, "time,value\n" + "\n".join(f"{i},{i}" for i in range(200)),
        [{"semantic_type": "scalar", "entity_path": "/v", "source_fields": ["value"]}])
    workspace, project, _, _ = catalog
    to_typed(catalog)
    workspace._query_read_stats = {}
    result = workspace.custom_query(project, {"operator": "lt", "value": 200, "text": "199"}, limit=1)
    assert result["rows"][0]["value"] == 199
    assert workspace._query_read_stats["typed_fetched"] == 200
