from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import datascope_core.query_typed as typed
from datascope_core.models import MappingSpec
from datascope_core.query import QUERY_TEMPLATES
from datascope_core.workspace import Workspace
from tests.unit.test_custom_query_pushdown import assert_same


def add_recording(workspace, project, source, recording, spec):
    with workspace._connect() as conn:
        conn.execute("""INSERT INTO recordings
            (id, project_id, source_id, app_id, path, run_name, created_at)
            VALUES (?, ?, ?, 'test', 'unused.rrd', ?, 'test')""",
            (recording, project, source, recording))
    workspace._index_recording(recording, workspace.get_source(source), spec)


def make_catalog(tmp_path, text=None, streams=None):
    path = tmp_path / "samples.csv"
    path.write_text(text or (
        "time,Battery%_,temperature,robot_state,big,flag,mixed,message,İ\n"
        "1,0.9,20,running,9007199254740993,True,word,ok,3\n"
        "0,0.1,-0.0,WARNING,9007199254740995,False,0.1,warn,4\n"
        "0,0.05,22,error,9007199254740997,True,other,fault,5\n"
        ",0.2,,idle,9007199254740999,False,word,ok,6\n"
        "3,,25,running,9007199254741001,True,word,ok,7\n"
    ), encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Typed")['id']
    source = workspace.add_source(project, str(path), storage_mode="reference")['id']
    if streams is None:
        streams = [
            {"stream_id": "battery", "semantic_type": "scalar", "entity_path": "/Robot/K%_", "source_fields": ["Battery%_"]},
            {"stream_id": "group", "semantic_type": "scalar_group", "entity_path": "/metrics", "source_fields": ["temperature", "big", "flag", "İ"]},
            {"stream_id": "state", "semantic_type": "state", "entity_path": "/robot", "source_fields": ["robot_state"]},
            {"stream_id": "mixed", "semantic_type": "scalar", "entity_path": "/mixed", "source_fields": ["mixed"]},
            {"stream_id": "log", "semantic_type": "text_log", "entity_path": "/logs", "source_fields": ["message"]},
            # Identical keys/paths and duplicate times must retain insertion order.
            {"stream_id": "duplicate", "semantic_type": "state", "entity_path": "/Robot/K%_", "source_fields": ["Battery%_"]},
        ]
    spec = MappingSpec("mapping", source, "test", "r_a", "time", streams,
                       timeline_unit="relative_s", effective_timeline_unit="relative_s")
    add_recording(workspace, project, source, "r_a", spec)
    return workspace, project, source, spec


@pytest.fixture
def catalog(tmp_path):
    return make_catalog(tmp_path)


def to_typed(catalog):
    workspace, _, source, spec = catalog
    return workspace._index_recording("r_a", workspace.get_source(source), spec,
                                      query_storage="typed_sqlite")


@pytest.mark.parametrize("filters", [
    None, {}, {"key": "  bAtTeRy%_  "}, {"entity_path": "k%_"},
    {"key": "i\u0307"}, {"key": "%"}, {"key": "_"}, {"key": "' OR 1=1 --"},
    {"time_start": 0, "time_end": 0}, {"time_start": "1", "time_end": "3"},
    {"time_start": 3, "time_end": 1}, {"time_start": "bad"},
    {"time_start": math.nan}, {"time_end": math.inf},
    {"key": "battery", "operator": "lt", "value": 0.2},
    {"operator": "gte", "value": "0.1"}, {"operator": "lt", "value": True},
    {"operator": "eq", "value": 9007199254740993},
    {"operator": "contains", "value": "WARN"}, {"text": "-0.0"},
    {"text": "battery%_ 0.1", "time_start": 0},
    {"key": "missing", "operator": "invalid", "value": 1},
])
@pytest.mark.parametrize("limit", [1, 1000, 0, -1, 1.5, True])
def test_custom_parity(catalog, filters, limit):
    workspace, project, _, _ = catalog
    expected = workspace.custom_query(project, filters, limit=limit)
    to_typed(catalog)
    assert_same(workspace.custom_query(project, filters, limit=limit), expected)


def test_full_reader_templates_compare_diagnostics_and_export(catalog, tmp_path):
    workspace, project, _, _ = catalog

    def results():
        return {
            "rows": workspace._query_rows(project),
            "templates": {t["template_id"]: workspace.run_query(project, t["template_id"])
                          for t in QUERY_TEMPLATES},
            "summary": workspace.compare(project, ["r_a"]),
            "series": workspace.compare(project, ["r_a"], mode="series"),
            "diagnostics": workspace.run_diagnostics(project),
        }

    expected = results()
    before = tmp_path / "before.csv"
    after = tmp_path / "after.csv"
    workspace.export_query(project, "find_errors", output_path=str(before))
    stats = to_typed(catalog)
    actual = results()
    # Diagnostic reports carry wall-clock creation timestamps.
    for report in (expected["diagnostics"], actual["diagnostics"]):
        report.pop("created_at", None)
    assert_same(actual, expected)
    workspace.export_query(project, "find_errors", output_path=str(after))
    assert before.read_bytes() == after.read_bytes()
    assert stats["eav_rows"] > 0
    with workspace._connect() as conn:
        assert {row[0] for row in conn.execute("SELECT DISTINCT key FROM query_rows")} == {"mixed", "message"}
        assert conn.execute("SELECT count(*) FROM typed_datasets").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    zero = workspace.custom_query(project, {"key": "temperature", "time_end": 0})["rows"][0]["value"]
    assert math.copysign(1, zero) == -1


def test_projects_recordings_empty_lists_and_shared_schemas(catalog):
    workspace, project, source, spec = catalog
    add_recording(workspace, project, source, "r_b", spec)
    other = workspace.create_project("Other")['id']
    other_source = workspace.add_source(other, workspace.get_source(source)["uri"])['id']
    add_recording(workspace, other, other_source, "r_foreign", spec)
    requests = [(None, None), ([], []), (["r_b", "r_a"], None), (["r_foreign"], None),
                (["r_a", "r_a"], ["state"]), (["r_b"], ["scalar_group"])]
    expected = [workspace.custom_query(project, recording_ids=ids, semantic_types=semantics)
                for ids, semantics in requests]
    to_typed(catalog)
    for (ids, semantics), result in zip(requests, expected):
        assert_same(workspace.custom_query(project, recording_ids=ids, semantic_types=semantics), result)
    workspace._index_recording("r_b", workspace.get_source(source), spec, query_storage="typed_sqlite")
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_schemas").fetchone()[0] == 2
    workspace._index_recording("r_a", workspace.get_source(source), spec)
    assert workspace.custom_query(project, recording_ids=["r_b"])["rows"]
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_schemas").fetchone()[0] == 2


@pytest.mark.parametrize("values", [
    [str(2**63 - 1), str(-(2**63))], [str(2**63), str(2**63 + 1)],
    ["inf", "-inf"], ["True", "False"], ["-0.0", "0.0"],
    ["12", "word"], ["1.0", "2.5"], ["", ""],
])
def test_numeric_codecs_and_fallback(tmp_path, values):
    streams = [{"semantic_type": "scalar", "entity_path": "/v", "source_fields": ["value"]}]
    catalog = make_catalog(tmp_path, "time,value\n" + "\n".join(f"{i},{v}" for i, v in enumerate(values)), streams)
    workspace, project, _, _ = catalog
    expected = workspace._query_rows(project)
    to_typed(catalog)
    assert_same(workspace._query_rows(project), expected)


def test_late_type_change_falls_back_whole_stream(tmp_path, monkeypatch):
    # The first chunk is integer; a later chunk is text. Earlier values must not
    # be coerced to text or left duplicated in a typed sample table.
    monkeypatch.setattr(typed, "CSV_CHUNK_SIZE", 2)
    import datascope_core.workspace_query as query_module
    original = query_module.iter_query_rows
    monkeypatch.setattr(query_module, "iter_query_rows", lambda *a, **k: original(*a, **k, chunk_size=2))
    streams = [{"semantic_type": "state", "entity_path": "/v", "source_fields": ["value"]}]
    catalog = make_catalog(tmp_path, "time,value\n0,1\n1,2\n2,word\n3,4\n", streams)
    expected = catalog[0]._query_rows(catalog[1])
    stats = to_typed(catalog)
    assert stats["physical_sample_rows"] == 0
    assert stats["eav_rows"] == 4
    assert_same(catalog[0]._query_rows(catalog[1]), expected)


def test_limit_residuals_late_window_and_closed_connections(tmp_path, monkeypatch):
    streams = [{"semantic_type": "scalar", "entity_path": "/v", "source_fields": ["value"]}]
    catalog = make_catalog(tmp_path, "time,value\n" + "\n".join(f"{i},{100 if i < 150 else 1}" for i in range(200)), streams)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    opened = []
    connect = workspace._connect

    def tracked():
        conn = connect()
        opened.append(conn)
        return conn

    monkeypatch.setattr(workspace, "_connect", tracked)
    workspace._query_read_stats = {}
    result = workspace.custom_query(project, {"operator": "lt", "value": 2}, limit=1)
    assert result["rows"][0]["time"] == 150
    assert workspace._query_read_stats["typed_fetched"] >= 151
    workspace._query_read_stats = {}
    result = workspace.custom_query(project, {"time_start": 190, "time_end": 192})
    assert len(result["rows"]) == workspace._query_read_stats["typed_fetched"] == 3
    # get_project still uses the legacy connection helper; inspect only reader
    # connections (the last one for each call), which must close even at limit.
    for conn in (opened[1], opened[-1]):
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def test_cancel_and_sql_failure_roll_back_entire_index(catalog, monkeypatch):
    workspace, project, source, spec = catalog
    expected = workspace._query_rows(project)
    original = typed.build_typed_index

    def fail_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("injected failure before commit")

    import datascope_core.workspace_query as query_module
    monkeypatch.setattr(query_module, "build_typed_index", fail_after_write)
    with pytest.raises(RuntimeError, match="injected"):
        to_typed(catalog)
    assert_same(workspace._query_rows(project), expected)
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM typed_schemas").fetchone()[0] == 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'typed_samples_%'").fetchall() == []
    monkeypatch.setattr(query_module, "build_typed_index", original)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise RuntimeError("cancelled during write")

    with pytest.raises(RuntimeError, match="cancelled"):
        workspace._index_recording("r_a", workspace.get_source(source), spec,
                                  query_storage="typed_sqlite", cancel_check=cancel)
    assert_same(workspace._query_rows(project), expected)
    to_typed(catalog)  # A retry must succeed with no duplicates.
    assert_same(workspace._query_rows(project), expected)


def test_crash_rollback_and_concurrent_snapshot(catalog):
    workspace, project, _, _ = catalog
    expected = workspace._query_rows(project)
    script = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]); c.execute('BEGIN IMMEDIATE')
c.execute('delete from query_rows'); c.execute('create table crash_partial(x)')
os._exit(17)
"""
    result = subprocess.run([sys.executable, "-c", script, str(workspace.db_path)])
    assert result.returncode == 17
    assert_same(workspace._query_rows(project), expected)
    with closing(workspace._connect()) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM query_rows").fetchone()
        to_typed(catalog)
        assert reader.execute("SELECT count(*) FROM query_rows").fetchone()[0] == len(expected)
    assert_same(workspace._query_rows(project), expected)


def test_errors_are_not_hidden(catalog):
    workspace, project, _, _ = catalog
    to_typed(catalog)
    with pytest.raises(ValueError, match="Unsupported custom query operator"):
        workspace.custom_query(project, {"operator": "invalid", "value": 1})
    with pytest.raises(OverflowError):
        workspace.custom_query(project, {"time_start": 10**400})
    with workspace._connect() as conn:
        conn.execute("UPDATE typed_indexes SET format_version = 99")
    with pytest.raises(RuntimeError, match="Unsupported typed"):
        workspace.custom_query(project)
    with workspace._connect() as conn:
        conn.execute("UPDATE typed_indexes SET format_version = 1")
        conn.execute("DROP TABLE typed_bindings")
    with pytest.raises(sqlite3.OperationalError):
        workspace.custom_query(project)


@pytest.mark.parametrize("version", [2, 3])
def test_additive_migration_preserves_old_eav(catalog, version):
    workspace, project, _, _ = catalog
    expected = workspace._query_rows(project)
    with closing(workspace._connect()) as conn, conn:
        for table in ("typed_bindings", "typed_states", "typed_datasets", "typed_schemas",
                      "typed_indexes", "typed_legacy_order"):
            conn.execute(f"DROP TABLE {table}")
        conn.execute(f"PRAGMA user_version = {version}")
    reopened = Workspace(workspace.root)
    assert_same(reopened._query_rows(project), expected)
    with reopened._connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4


def test_storage_option_validation_and_retry(catalog):
    workspace, project, source, _ = catalog
    with pytest.raises(ValueError, match="query storage"):
        workspace.enqueue_build_recording(project, source, query_storage="unknown")
    job = workspace.enqueue_build_recording(project, source, query_storage="typed_sqlite")
    workspace.cancel_job(job["id"])
    retry = workspace.retry_job(job["id"])
    assert retry["payload"]["query_storage"] == "typed_sqlite"


def test_wide_group_partition_and_mapping_order(tmp_path):
    fields = [f"field_{i}" for i in range(130)]
    streams = [{"semantic_type": "scalar", "entity_path": "/same", "source_fields": [field]}
               for field in fields]
    catalog = make_catalog(tmp_path, "time," + ",".join(fields) + "\n0," + ",".join(str(i) for i in range(130)) + "\n", streams)
    expected = catalog[0]._query_rows(catalog[1])
    stats = to_typed(catalog)
    assert stats["physical_sample_rows"] == 2
    assert stats["typed_logical_rows"] == 130
    assert_same(catalog[0]._query_rows(catalog[1]), expected)


def test_sort_and_disabled_missing_duplicate_fields(catalog):
    workspace, project, source, spec = catalog
    spec.timeline_sort = "ascending"
    spec.streams += [{"enabled": False, "semantic_type": "scalar", "source_fields": ["missing"]},
                     {"semantic_type": "scalar", "entity_path": "/dup", "source_fields": ["big", "big", "absent"]}]
    workspace._index_recording("r_a", workspace.get_source(source), spec)
    expected = workspace._query_rows(project)
    to_typed(catalog)
    assert_same(workspace._query_rows(project), expected)


def test_hard_kill_inside_production_typed_writer(catalog):
    workspace, project, source, spec = catalog
    expected = workspace._query_rows(project)
    script = """import json,os,sys
from datascope_core.workspace import Workspace
from datascope_core.models import MappingSpec
import datascope_core.query_typed as typed
typed.CSV_CHUNK_SIZE=2; typed.BATCH_SIZE=2
w=Workspace(sys.argv[1]); spec=MappingSpec(**json.loads(sys.argv[2])); calls=0
def kill():
    global calls
    calls+=1
    if calls==8: os._exit(23)
w._index_recording('r_a',w.get_source(spec.source_id),spec,query_storage='typed_sqlite',cancel_check=kill)
"""
    from dataclasses import asdict
    result = subprocess.run([sys.executable, "-c", script, str(workspace.root), json.dumps(asdict(spec))])
    assert result.returncode == 23
    assert_same(workspace._query_rows(project), expected)
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM typed_schemas").fetchone()[0] == 0


def test_non_csv_opt_in_retains_legacy_index(tmp_path):
    path = tmp_path / "values.jsonl"
    path.write_text('{"time":0,"value":1}\n', encoding="utf-8")
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("JSONL")['id']
    source = workspace.add_source(project, str(path))['id']
    spec = MappingSpec("mapping", source, "test", "r_a", "time", [
        {"semantic_type": "scalar", "entity_path": "/v", "source_fields": ["value"]}
    ], timeline_unit="relative_s")
    add_recording(workspace, project, source, "r_a", spec)
    expected = workspace._query_rows(project)
    assert workspace._index_recording("r_a", workspace.get_source(source), spec,
                                      query_storage="typed_sqlite") is None
    assert_same(workspace._query_rows(project), expected)
    with workspace._connect() as conn:
        assert conn.execute("SELECT count(*) FROM typed_indexes").fetchone()[0] == 0


def test_active_typed_reader_keeps_snapshot_during_schema_reuse(catalog):
    workspace, project, source, spec = catalog
    to_typed(catalog)
    expected = workspace._query_rows(project)
    with closing(workspace._iter_query_rows(project)) as reader:
        first = next(reader)
        add_recording(workspace, project, source, "r_b", spec)
        workspace._index_recording("r_b", workspace.get_source(source), spec, query_storage="typed_sqlite")
        assert_same([first, *reader], expected)
    assert len(workspace._query_rows(project)) == 2 * len(expected)


def test_source_change_during_second_pass_rolls_back(catalog, monkeypatch):
    workspace, project, source, _ = catalog
    expected = workspace._query_rows(project)
    original = typed._frames
    calls = 0

    def changed(*args):
        nonlocal calls
        calls += 1
        yield from original(*args)
        if calls == 2:
            with Path(workspace.get_source(source)["uri"]).open("a", encoding="utf-8") as handle:
                handle.write("\n")

    monkeypatch.setattr(typed, "_frames", changed)
    with pytest.raises(RuntimeError, match="CSV changed"):
        to_typed(catalog)
    assert_same(workspace._query_rows(project), expected)
