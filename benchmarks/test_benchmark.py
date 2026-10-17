"""Opt-in harness verification: python -m pytest -q benchmarks/test_benchmark.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.benchmark_models import DatasetConfig
from benchmarks.generate_dataset import generate_dataset
from benchmarks.run_benchmark import parser, run_one


def test_generator_seed_and_size_modes(tmp_path: Path) -> None:
    first, second, changed = (tmp_path / name for name in ("a.csv", "b.csv", "c.csv"))
    config = DatasetConfig(rows=12, frequency_hz=50, scalar_fields=30, state_fields=3)
    generate_dataset(config, first)
    generate_dataset(config, second)
    generate_dataset(DatasetConfig(rows=12, frequency_hz=50, seed=42), changed)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes() != changed.read_bytes()
    with pytest.raises(FileExistsError):
        generate_dataset(config, first)
    command = [sys.executable, "benchmarks/generate_dataset.py", "--frequency", "50",
               "--duration", "0.24", "--output", str(tmp_path / "duration.csv")]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout)["rows"] == 12


def test_c2a_read_only_workers_counts_and_parity(tmp_path: Path) -> None:
    from benchmarks.custom_query_pushdown import parser as c2a_parser, run, sha256

    baseline = run_one(parser().parse_args(["--rows", "24", "--query-runs", "1", "--warmups", "0",
        "--pipeline", "index-only", "--skip-diagnostics", "--skip-index-comparison",
        "--keep-dataset", "--keep-workspace", "--output-dir", str(tmp_path)]))
    before = {path: sha256(path) for path in tmp_path.rglob("*") if path.is_file()}
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    result_path = run(c2a_parser().parse_args(["--baseline", str(baseline), "--query-runs", "1",
        "--warmups", "0", "--output-dir", str(tmp_path)]))
    report = json.loads(result_path.read_text(encoding="utf-8"))
    assert report["status"] == "succeeded"
    assert report["read_only_verification"]
    assert all(row["exact_parity"] for row in report["comparison"].values())
    assert report["cleanup"]["status"] == "removed_owned_run_directory"
    for path, digest in before.items():
        assert sha256(path) == digest
    assert unrelated.read_text(encoding="utf-8") == "keep"
    for mode in ("legacy", "pushdown"):
        backend = report["backends"][mode]
        assert len(backend["queries"]) == 3
        assert all(data["samples_ms"] for data in backend["queries"].values())
        assert all(data["query_plan"] for data in backend["diagnostics"].values())
    assert report["backends"]["pushdown"]["diagnostics"]["custom_time_range"]["fetched_rows"] < (
        report["backends"]["legacy"]["diagnostics"]["custom_time_range"]["fetched_rows"])


def test_c2a_failure_preserves_inputs_and_unrelated_files(tmp_path: Path, monkeypatch) -> None:
    import benchmarks.custom_query_pushdown as c2a

    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")
    def fail(path):
        raise ValueError("invalid retained baseline")
    monkeypatch.setattr(c2a, "describe_input", fail)
    with pytest.raises(ValueError, match="invalid retained baseline"):
        c2a.run(c2a.parser().parse_args(["--baseline", "missing.json", "--output-dir", str(tmp_path)]))
    report = json.loads(next(tmp_path.glob("benchmark_c2a_*.json")).read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["cleanup"]["status"] == "removed_owned_run_directory"
    assert unrelated.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("mode", ["full", "index-only"])
def test_real_pipeline_and_default_cleanup(tmp_path: Path, mode: str) -> None:
    args = parser().parse_args(["--rows", "24", "--state-fields", "2", "--query-runs", "1",
                                "--pipeline", mode, "--output-dir", str(tmp_path)])
    result_path = run_one(args)
    report = json.loads(result_path.read_text(encoding="utf-8"))
    assert report["status"] == "succeeded"
    assert report["storage"]["query_rows"] == 24 * 33
    assert report["queries"]["low_battery"]["result_rows"] > 0
    assert report["pipeline"]["recording_build_ms"] is None if mode == "index-only" else (
        report["pipeline"]["recording_build_ms"] > 0)
    assert result_path.with_suffix(".md").is_file()
    assert not list((tmp_path / ".work").iterdir())
    assert len(report["index_comparison"]["variants"]) == 5


@pytest.mark.parametrize("keep_dataset,keep_workspace", [(True, False), (False, True), (True, True)])
def test_keep_flags_are_independent(tmp_path: Path, keep_dataset: bool, keep_workspace: bool) -> None:
    options = ["--rows", "8", "--query-runs", "1", "--pipeline", "index-only",
               "--skip-index-comparison", "--output-dir", str(tmp_path)]
    if keep_dataset:
        options.append("--keep-dataset")
    if keep_workspace:
        options.append("--keep-workspace")
    result_path = run_one(parser().parse_args(options))
    work = tmp_path / ".work" / result_path.stem
    assert (work / "robot.csv").exists() == keep_dataset
    assert (work / "workspace").exists() == keep_workspace


def test_failure_report_and_cleanup_preserve_unrelated_files(tmp_path: Path, monkeypatch) -> None:
    import benchmarks.benchmark_pipeline as pipeline
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("user content", encoding="utf-8")

    def fail(*args, **kwargs):
        raise RuntimeError("injected pipeline failure")

    monkeypatch.setattr(pipeline, "run_pipeline", fail)
    with pytest.raises(RuntimeError, match="injected pipeline failure"):
        run_one(parser().parse_args(["--rows", "8", "--output-dir", str(tmp_path)]))
    assert unrelated.read_text(encoding="utf-8") == "user content"
    assert not list((tmp_path / ".work").iterdir())
    result = json.loads(next(tmp_path.glob("benchmark_*.json")).read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert next(tmp_path.glob("benchmark_*.md")).is_file()


def test_timing_instrumentation_releases_completed_batches(monkeypatch) -> None:
    import gc
    import weakref
    import datascope_core.workspace_query as query_module
    from benchmarks.benchmark_pipeline import BenchmarkWorkspace
    from datascope_core.workspace import Workspace

    class BatchValue:
        pass

    def insert_without_storage(conn, batch):
        pass

    def production_loop(self, *args):
        for _ in range(3):
            value = BatchValue()
            reference = weakref.ref(value)
            query_module._insert_query_rows(None, [value])
            del value
            gc.collect()
            assert reference() is None, "Timing must not retain completed INSERT batches"

    monkeypatch.setattr(query_module, "_insert_query_rows", insert_without_storage)
    monkeypatch.setattr(Workspace, "_index_recording", production_loop)
    workspace = object.__new__(BenchmarkWorkspace)
    workspace.timings = {}
    workspace._index_recording("recording", {}, None)


def test_optional_poc_parity_and_source_checksum(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    from argparse import Namespace
    from benchmarks.duckdb_poc import run_poc

    baseline = run_one(parser().parse_args([
        "--rows", "24", "--state-fields", "2", "--query-runs", "1", "--pipeline", "index-only",
        "--skip-index-comparison", "--keep-dataset", "--keep-workspace", "--output-dir", str(tmp_path)]))
    options = Namespace(baseline=baseline, output_dir=tmp_path, query_runs=1, warmups=1,
                        threads=2, keep_artifacts=False)
    baseline_report = json.loads(baseline.read_text(encoding="utf-8"))
    db_path = Path(baseline_report["artifacts"]["workspace"]) / "metadata.sqlite"
    db_before = db_path.read_bytes()
    result_path = run_poc(options)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["status"] == "succeeded"
    assert result["normalized_sample_rows"] == [24, 24]
    assert len(result["queries"]) == 3
    assert not (tmp_path / ".work" / result_path.stem).exists()
    assert db_path.read_bytes() == db_before
    report = json.loads(baseline.read_text(encoding="utf-8"))
    data = Path(report["artifacts"]["dataset"])
    data.write_bytes(data.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="checksum"):
        run_poc(options)


@pytest.mark.parametrize('variant', ['none', 'time', 'minimal', 'covering'])
def test_phase_c_typed_sql_pushdown_and_integer_state_parity(tmp_path: Path, variant: str) -> None:
    pytest.importorskip('duckdb')
    from benchmarks.backend_common import assert_parity, csv_oracle, decode_typed, typed_queries, typed_select
    from benchmarks.backend_comparison import parser as comparison_parser, prepare_inputs
    from benchmarks.benchmark_memory import MemorySampler
    from benchmarks.sqlite_typed_poc import build_typed, sqlite_rows
    import sqlite3

    args = comparison_parser().parse_args(['--rows', '24', '--state-fields', '2', '--frequency', '50', '--query-limit', '4'])
    manifest, _ = prepare_inputs(args, tmp_path)
    golden = csv_oracle(manifest, 4)
    path = tmp_path / 'typed.sqlite'
    memory = MemorySampler()
    with memory:
        report = build_typed(path, manifest, variant, memory, batch_size=3)
    assert report['physical_sample_rows'] == 96
    assert len(report['secondary_indexes']) == {'none': 0, 'time': 2, 'minimal': 4, 'covering': 4}[variant]
    for name, sql in typed_queries(manifest, 4).items():
        assert_parity(decode_typed(sqlite_rows(path, sql), name, manifest), golden[name])
        assert 'value_json' not in sql and 'json_' not in sql.lower()
    if variant != 'none':
        # A value index must not turn a bounded scalar lookup into a full sort.
        sql = typed_queries(manifest, 4)['custom_scalar_key']
        with sqlite3.connect(path) as conn:
            plan = [row[-1] for row in conn.execute('EXPLAIN QUERY PLAN ' + sql)]
        assert not any('TEMP B-TREE' in step for step in plan), plan
    battery = next(field for field in manifest['fields'] if field['recording_key'] == 1 and field['key'] == 'battery')
    filters = {'semantic_types': ['scalar', 'scalar_group'], 'key': 'battery',
               'entity_path_exact': battery['entity_path'], 'entity_path_prefix': battery['entity_path'].rsplit('/', 1)[0],
               'time_start': .4, 'time_end': .46, 'operator': 'lt', 'value': .2}
    sql = typed_select(manifest, filters, 4)
    rows = decode_typed(sqlite_rows(path, sql), 'custom_numeric_threshold', manifest)['rows']
    assert rows and all(.4 <= row['time'] <= .46 and row['value'] < .2 for row in rows)
    assert all(row['recording_id'] == manifest['recordings'][0]['recording_id'] for row in rows)
    assert not sqlite_rows(path, typed_select(manifest, {**filters, 'entity_path_exact': '/wrong'}, 4))
    assert not sqlite_rows(path, typed_select(manifest, {}, 4, []))
    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute('PRAGMA table_info(numeric_samples)')]
        assert 'value_json' not in columns and 'battery' in columns and 'error_code' in columns
        assert conn.execute('SELECT typeof(error_code) FROM numeric_samples LIMIT 1').fetchone()[0] == 'integer'
    with pytest.raises(FileExistsError):
        build_typed(path, manifest, variant, memory)


def test_phase_c_all_backends_canonical_parity_and_cleanup(tmp_path: Path) -> None:
    pytest.importorskip('duckdb')
    from benchmarks.backend_comparison import BACKENDS, parser as comparison_parser, run_comparison

    unrelated = tmp_path / 'keep.txt'
    unrelated.write_text('user content', encoding='utf-8')
    result_path = run_comparison(comparison_parser().parse_args([
        '--rows', '24', '--state-fields', '2', '--frequency', '50', '--query-limit', '4',
        '--query-runs', '1', '--warmups', '1', '--production-control', '--output-dir', str(tmp_path)]))
    report = json.loads(result_path.read_text(encoding='utf-8'))
    assert report['status'] == 'succeeded'
    assert set(report['backends']) == set(BACKENDS)
    for backend in report['backends'].values():
        assert backend['status'] == 'succeeded'
        assert len(backend['queries']) == 7
        assert backend['source_checksums'] == [row['checksum'] for row in report['recordings']]
        assert backend['queries']['compare']['result_rows'] == 4
        assert backend['preparation']['physical_sample_rows'] == (48 * 33 if backend['backend'] == 'legacy_sqlite_eav' else 96)
    assert report['legacy_analysis']['returned_rows'] == 4
    assert report['cleanup']['status'] == 'removed_owned_run_directory'
    assert not list((tmp_path / '.work').iterdir())
    assert unrelated.read_text(encoding='utf-8') == 'user content'
    assert result_path.with_suffix('.md').is_file()


def test_phase_c_worker_failure_reports_and_cleans_owned_data(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip('duckdb')
    import benchmarks.backend_comparison as comparison
    original_run = comparison.subprocess.run

    def fail(command, *args, **kwargs):
        if '--worker' in command:
            raise RuntimeError('injected comparison worker failure')
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(comparison.subprocess, 'run', fail)
    with pytest.raises(RuntimeError, match='injected comparison'):
        comparison.run_comparison(comparison.parser().parse_args(['--rows', '8', '--output-dir', str(tmp_path)]))
    result = json.loads(next(tmp_path.glob('benchmark_phase_c_*.json')).read_text(encoding='utf-8'))
    assert result['status'] == 'failed'
    assert result['cleanup']['status'] == 'removed_owned_run_directory'
    assert not list((tmp_path / '.work').iterdir())


def test_phase_c_integer_transport_preserves_values_above_double_precision(tmp_path: Path) -> None:
    pytest.importorskip('duckdb')
    import csv
    from benchmarks.backend_common import assert_parity, csv_oracle, decode_typed, typed_queries
    from benchmarks.backend_comparison import parser as comparison_parser, prepare_inputs
    from benchmarks.benchmark_memory import MemorySampler
    from benchmarks.comparison_backends import build_duck
    from benchmarks.sqlite_typed_poc import build_typed, sqlite_rows

    manifest, _ = prepare_inputs(comparison_parser().parse_args(['--rows', '24']), tmp_path)
    source = Path(manifest['recordings'][0]['csv_path'])
    with source.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))
    value = 2**53 + 1
    rows[-1][rows[0].index('error_code')] = str(value)
    with source.open('w', encoding='utf-8', newline='') as handle:
        csv.writer(handle).writerows(rows)
    golden = csv_oracle(manifest, 1000)
    sql = typed_queries(manifest, 1000)['custom_time_range']
    memory = MemorySampler()
    with memory:
        path = tmp_path / 'integer.sqlite'
        build_typed(path, manifest, 'minimal', memory)
        actual = decode_typed(sqlite_rows(path, sql), 'custom_time_range', manifest)
        assert_parity(actual, golden['custom_time_range'])
        for parquet in (False, True):
            work = tmp_path / str(parquet)
            work.mkdir()
            conn, _ = build_duck(work, manifest, memory, parquet=parquet, threads=2)
            try:
                actual = decode_typed(conn.execute(sql).fetchall(), 'custom_time_range', manifest)
                assert_parity(actual, golden['custom_time_range'])
                assert any(row['key'] == 'error_code' and row['value'] == value and type(row['value']) is int for row in actual['rows'])
            finally:
                conn.close()


def test_phase_c_resume_remeasures_queries_without_mutating_retained_preparations(tmp_path: Path) -> None:
    pytest.importorskip('duckdb')
    from benchmarks.backend_common import checksum
    from benchmarks.backend_comparison import parser as comparison_parser, run_comparison

    first = run_comparison(comparison_parser().parse_args([
        '--rows', '24', '--query-runs', '1', '--keep-artifacts', '--backends',
        'legacy_sqlite_eav', 'sqlite_typed_none', 'sqlite_typed_time', '--output-dir', str(tmp_path)]))
    original = first.read_bytes()
    old_work = tmp_path / '.work' / first.stem
    database = old_work / 'sqlite_typed_time/samples.sqlite'
    before = checksum(database)
    second = run_comparison(comparison_parser().parse_args([
        '--resume-from', str(first), '--query-runs', '1', '--backends',
        'legacy_sqlite_eav', 'sqlite_typed_none', 'sqlite_typed_time', '--output-dir', str(tmp_path)]))
    report = json.loads(second.read_text(encoding='utf-8'))
    assert report['status'] == 'succeeded'
    assert report['resumed_from']['json'] == str(first)
    assert checksum(database) == before and first.read_bytes() == original
    for backend in report['backends'].values():
        assert backend['preparation']['reuse_provenance']['original_run_id'] == first.stem
        assert backend['memory']['workflow_peak_rss_mb'] >= backend['memory']['peak_rss_mb']
        assert len(backend['queries']) == 7
    assert old_work.exists() and not (tmp_path / '.work' / second.stem).exists()
    third = run_comparison(comparison_parser().parse_args([
        '--resume-from', str(second), '--reuse-legacy-control', str(second), '--query-runs', '1', '--backends',
        'legacy_sqlite_eav', 'sqlite_typed_time', '--output-dir', str(tmp_path)]))
    third_report = json.loads(third.read_text(encoding='utf-8'))
    assert third_report['status'] == 'succeeded'
    assert third_report['backends']['legacy_sqlite_eav']['query_control_reuse']['sha256'] == checksum(second)
    assert third_report['backends']['legacy_sqlite_eav']['queries'] == report['backends']['legacy_sqlite_eav']['queries']
    assert checksum(database) == before and first.read_bytes() == original
    source = Path(report['recordings'][0]['csv_path'])
    source.write_bytes(source.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='Resume source checksum'):
        run_comparison(comparison_parser().parse_args([
            '--resume-from', str(first), '--query-runs', '1', '--output-dir', str(tmp_path)]))
