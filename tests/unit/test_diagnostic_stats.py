from __future__ import annotations

import math
from contextlib import closing

import numpy as np
import pytest

from benchmarks.c2c_diagnostics_reference import WorkspaceDiagnosticsMixin as ReferenceDiagnostics
from datascope_core.diagnostic_stats import ExactSeries, SpillBudget
from datascope_core.robot_diagnostics import _iqr_outliers
from datascope_core.workspace import Workspace
from tests.unit.test_custom_query_pushdown import assert_same
from tests.unit.test_typed_query_storage import add_recording, make_catalog, to_typed


class OldWorkspace(ReferenceDiagnostics, Workspace):
    pass


def old(workspace):
    result = object.__new__(OldWorkspace)
    result.__dict__.update(workspace.__dict__)
    return result


@pytest.mark.parametrize('budget', [1024, 64*1024*1024])
def test_exact_ranks_and_spilling(tmp_path, budget):
    rng = np.random.default_rng(123)
    for n in [1,2,3,4,5,6,7,8,31,32,33,127,128,129,2049]:
        values = rng.integers(-20, 100, n).astype(float).tolist()
        series = ExactSeries(SpillBudget(tmp_path, budget))
        for start in range(0,n,17):
            series.append(values[start:start+17], (start,))
        assert series.iqr(1.5) == _iqr_outliers(values,1.5)
        from statistics import median
        assert series.median() == median(values)
    # Multi-pass external merges and early rank completion release run handles.
    assert all(p.name.startswith('values-') for p in tmp_path.iterdir())


@pytest.mark.parametrize('layout', ['legacy','typed','mixed'])
@pytest.mark.parametrize('budget,limit,preset', [(2048,1,'balanced'),(64*1024*1024,1000,'strict'),(2048,0,'lenient')])
def test_complete_report_contract(tmp_path, layout, budget, limit, preset):
    catalog = make_catalog(tmp_path)
    workspace, project, source, spec = catalog
    add_recording(workspace, project, source, 'r_b', spec)
    if layout in {'typed','mixed'}:
        to_typed(catalog)
    if layout == 'typed':
        workspace._index_recording('r_b',workspace.get_source(source),spec,query_storage='typed_sqlite')
    workspace._diagnostic_work_bytes = budget
    expected = old(workspace).run_diagnostics(project, [], preset=preset, limit=limit)
    workspace._diagnostic_read_stats = {}
    actual = workspace.run_diagnostics(project, [], preset=preset, limit=limit)
    assert_same(actual,expected)
    assert workspace._diagnostic_read_stats['logical_rows'] == actual['checks'][0]['evidence']['query_row_count']
    assert not list((workspace.root/'cache/diagnostics').iterdir())


@pytest.mark.parametrize('values', [
    ['1','1','1'],['-0.0','0.0','-0.0'],['True','False','True'],
    ['inf','1','-inf','2','inf'],[str(2**53),str(2**53+1),str(2**53+2)],
    ['1','2','3','4','5','100'],['word','word','word'],
])
def test_special_values_and_same_path_times(tmp_path,values):
    text='time,a,b\n'+'\n'.join(f'{i//2},{v},{i}' for i,v in enumerate(values))
    catalog=make_catalog(tmp_path,text,[{'semantic_type':'state','entity_path':'/same','source_fields':['a','b']}])
    workspace,project,_,_=catalog
    expected=old(workspace).run_diagnostics(project)
    to_typed(catalog)
    workspace._diagnostic_read_stats={}
    assert_same(workspace.run_diagnostics(project),expected)


def test_snapshot_and_cleanup_on_failure(tmp_path,monkeypatch):
    catalog=make_catalog(tmp_path)
    workspace,project,_,_=catalog
    to_typed(catalog)
    import datascope_core.diagnostic_reader as reader
    original=reader._typed_stats
    def fail(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('injected diagnostic failure')
    monkeypatch.setattr(reader,'_typed_stats',fail)
    with pytest.raises(RuntimeError,match='injected'):
        workspace.run_diagnostics(project)
    assert not list((workspace.root/'cache/diagnostics').iterdir())


def test_one_snapshot_even_when_writer_commits_mid_read(tmp_path, monkeypatch):
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    workspace.get_schema_profile(catalog[2])
    with closing(workspace._connect()) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
    expected = old(workspace).run_diagnostics(project)
    import datascope_core.diagnostic_reader as reader
    original = reader._typed_stats
    def concurrent(*args):
        original(*args)
        with closing(workspace._connect()) as writer, writer:
            writer.execute("UPDATE query_rows SET value_json='\"fault\"' WHERE semantic_type='text_log'")
    monkeypatch.setattr(reader, '_typed_stats', concurrent)
    assert_same(workspace.run_diagnostics(project), expected)


def test_corrupt_typed_values_propagate_and_cleanup(tmp_path):
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    with closing(workspace._connect()) as conn, conn:
        table, column = conn.execute("SELECT d.schema_id,b.column_no FROM typed_bindings b "
            "JOIN typed_datasets d ON d.id=b.dataset_id WHERE b.kind='float' LIMIT 1").fetchone()
        from datascope_core.query_typed import sample_table
        conn.execute(f'UPDATE {sample_table(table)} SET c{column}=?', (b'invalid',))
    import sqlite3
    with pytest.raises(sqlite3.OperationalError, match='user-defined function'):
        workspace.run_diagnostics(project)
    assert not list((workspace.root/'cache/diagnostics').iterdir())


@pytest.mark.parametrize('fmt', ['json','csv','html'])
def test_typed_exports_keep_complete_report_contract(tmp_path, fmt):
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    reference_path, result_path = tmp_path/('old.'+fmt), tmp_path/('new.'+fmt)
    old(workspace).export_diagnostics(project, fmt=fmt, output_path=str(reference_path), limit=2)
    workspace.export_diagnostics(project, fmt=fmt, output_path=str(result_path), limit=2)
    assert reference_path.read_bytes() == result_path.read_bytes()


def test_signed_zero_first_value_and_group_fallback_reason(tmp_path):
    catalog = make_catalog(tmp_path, 'time,a,b\n2,0.0,inf\n0,-0.0,1\n1,0.0,2\n',
        [{'semantic_type':'scalar_group','entity_path':'/g','source_fields':['a','b']}])
    workspace, project, _, _ = catalog
    expected = old(workspace).run_diagnostics(project)
    to_typed(catalog)
    workspace._diagnostic_read_stats = {}
    actual = workspace.run_diagnostics(project)
    assert_same(actual, expected)
    zero = next(f for f in actual['findings'] if f.get('key') == 'a')
    assert math.copysign(1., zero['evidence']['value']) == -1
    assert workspace._diagnostic_read_stats['fallbacks'][0]['reason'] == 'nonfinite numeric values'


def test_fractional_state_code_is_corruption_not_a_truncated_dictionary_id(tmp_path):
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    from datascope_core.query_typed import sample_table
    with closing(workspace._connect()) as conn, conn:
        schema = conn.execute("SELECT id FROM typed_schemas WHERE family='state'").fetchone()[0]
        conn.execute(f'UPDATE {sample_table(schema)} SET c0=1.5')
    with pytest.raises(RuntimeError, match='Invalid typed state dictionary code'):
        workspace.run_diagnostics(project)

@pytest.mark.parametrize('cached', [False, True])
def test_every_diagnostic_connection_closes_without_gc(tmp_path, monkeypatch, cached):
    import sqlite3
    catalog = make_catalog(tmp_path)
    workspace, project, source, _ = catalog
    to_typed(catalog)
    if cached:
        workspace.get_schema_profile(source)
    opened = []
    class Tracked(sqlite3.Connection):
        was_closed = False
        def close(self):
            self.was_closed = True
            return super().close()
    def connect():
        conn = sqlite3.connect(workspace.db_path, factory=Tracked)
        conn.row_factory = sqlite3.Row
        opened.append(conn)
        return conn
    monkeypatch.setattr(workspace, '_connect', connect)
    workspace.run_diagnostics(project)
    assert opened and all(conn.was_closed for conn in opened)
    if cached:
        assert len(opened) == 1


def test_validation_order_and_failure_connection_release(tmp_path, monkeypatch):
    import sqlite3
    catalog = make_catalog(tmp_path)
    workspace, project, source, _ = catalog
    to_typed(catalog)
    workspace.get_schema_profile(source)
    with pytest.raises(KeyError, match='Project not found'):
        workspace.run_diagnostics('missing', preset='bad')
    with pytest.raises(ValueError, match='Unsupported diagnostics preset'):
        workspace.run_diagnostics(project, ['missing'], preset='bad')
    opened = []
    class Tracked(sqlite3.Connection):
        was_closed = False
        def close(self):
            self.was_closed = True
            return super().close()
    def connect():
        conn = sqlite3.connect(workspace.db_path, factory=Tracked)
        conn.row_factory = sqlite3.Row
        opened.append(conn)
        return conn
    monkeypatch.setattr(workspace, '_connect', connect)
    import datascope_core.diagnostic_reader as reader
    def fail(*args):
        raise RuntimeError('injected read failure')
    monkeypatch.setattr(reader, '_typed_stats', fail)
    with pytest.raises(RuntimeError, match='injected read failure'):
        workspace.run_diagnostics(project)
    assert len(opened) == 1 and opened[0].was_closed


def test_long_state_dictionary_uses_bounded_cache_and_exact_counts(tmp_path):
    values = ['长状态_'+('x'*4096)+str(i) for i in range(600)]
    text = 'time,state\n'+''.join(f'{i},{value}\n' for i,value in enumerate(values))
    catalog = make_catalog(tmp_path, text, [
        {'semantic_type':'state','entity_path':'/State/K%_','source_fields':['state']},
        {'semantic_type':'state','entity_path':'/State/K%_','source_fields':['state']},
    ])
    workspace, project, _, _ = catalog
    expected = old(workspace).run_diagnostics(project, limit=2)
    to_typed(catalog)
    workspace._diagnostic_work_bytes = 64*1024
    workspace._diagnostic_read_stats = {}
    assert_same(workspace.run_diagnostics(project, limit=2), expected)
    assert workspace._diagnostic_read_stats['dictionary_cache_peak_bytes'] <= 8*1024
    assert workspace._diagnostic_read_stats['logical_rows'] == 1200
