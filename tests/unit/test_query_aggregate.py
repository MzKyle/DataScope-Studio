from contextlib import closing
import json
import math

import pytest

from datascope_core.query import compare_recordings, run_query_template
from datascope_core.workspace import Workspace
from tests.unit.test_typed_query_storage import make_catalog, to_typed
from tests.unit.test_custom_query_pushdown import assert_same


@pytest.mark.parametrize('sort', ['source', 'ascending'])
def test_exact_summary_complete_order_and_spill(tmp_path, monkeypatch, sort):
    import datascope_core.query_typed as typed
    import datascope_core.query_aggregate as aggregates
    monkeypatch.setattr(typed, 'CSV_CHUNK_SIZE', 3)
    monkeypatch.setattr(aggregates, 'WORK_BYTES', 1024)
    streams = [
        {'semantic_type': 'scalar', 'entity_path': '/v', 'source_fields': ['value']},
        {'semantic_type': 'scalar', 'entity_path': '/v', 'source_fields': ['value']},
        {'semantic_type': 'state', 'entity_path': '/state', 'source_fields': ['state']},
    ]
    catalog = make_catalog(tmp_path, 'time,value,state\n3,1e16,idle\n1,1,run\n'
        '2,-1e16,idle\n0,-0.0,run\n,1,done\n4,2,done\n', streams)
    workspace, project, _, spec = catalog
    spec.timeline_sort = sort
    workspace._index_recording('r_a', workspace.get_source(catalog[2]), spec)
    rows = workspace._query_rows(project)
    expected = compare_recordings(rows, ['r_a'])
    to_typed(catalog)
    actual = workspace.compare(project, ['r_a'])
    assert_same(actual, expected)
    with workspace._connect() as conn:
        assert conn.execute('SELECT count(*) FROM typed_summaries').fetchone()[0] == 2
    # The summary is genuinely used, including all input for a small output limit.
    monkeypatch.setattr(aggregates, 'iter_group', lambda *a, **k: pytest.fail('summary missed'))
    assert_same(workspace.compare(project, ['r_a'], limit=1),
                {'columns': expected['columns'], 'rows': expected['rows'][:1]})


def test_mixed_overlap_runtime_fallback_and_state_lookahead(tmp_path):
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    expected = workspace._query_rows(project)
    to_typed(catalog)
    with workspace._connect() as conn:
        conn.execute("UPDATE typed_summaries SET algorithm='different-runtime'")
    assert_same(workspace.compare(project, ['r_a']), compare_recordings(expected, ['r_a']))
    for limit in (1, 2, 4, 1000):
        assert_same(workspace.run_query(project, 'state_duration', limit=limit),
                    run_query_template(expected, 'state_duration', None, None, limit))
        assert_same(workspace.compare(project, ['r_a'], mode='series', limit=limit),
                    compare_recordings(expected, ['r_a'], mode='series', limit=limit))


def test_v4_migration_is_additive_and_summaries_clean_up(tmp_path):
    catalog = make_catalog(tmp_path)
    workspace, project, source, spec = catalog
    to_typed(catalog)
    expected = workspace.custom_query(project)
    with closing(workspace._connect()) as conn, conn:
        before = conn.execute('SELECT * FROM typed_indexes').fetchall()
        conn.execute('DROP TABLE typed_summaries')
        conn.execute('PRAGMA user_version=4')
    reopened = Workspace(workspace.root)
    assert_same(reopened.custom_query(project), expected)
    with reopened._connect() as conn:
        assert list(map(tuple, conn.execute('SELECT * FROM typed_indexes'))) == list(map(tuple, before))
        assert conn.execute('SELECT count(*) FROM typed_summaries').fetchone()[0] == 0
    reopened._index_recording('r_a', reopened.get_source(source), spec, query_storage='typed_sqlite')
    reopened._index_recording('r_a', reopened.get_source(source), spec, query_storage='legacy')
    with reopened._connect() as conn:
        assert conn.execute('SELECT count(*) FROM typed_summaries').fetchone()[0] == 0


@pytest.mark.parametrize('source_type,expected', [('csv', 'typed_sqlite'), ('jsonl', 'legacy')])
def test_auto_is_resolved_before_job_persistence(tmp_path, source_type, expected):
    workspace = Workspace(tmp_path / 'workspace')
    project = workspace.create_project('Auto')
    path = tmp_path / ('input.' + source_type)
    path.write_text('time,value\n0,1\n' if source_type == 'csv' else '{"time":0,"value":1}\n')
    source = workspace.add_source(project['id'], str(path), storage_mode='reference')
    job = workspace.enqueue_build_recording(project['id'], source['id'], query_storage='auto')
    assert job['payload']['query_storage'] == expected


def test_summary_failure_rolls_back_previous_index_and_closes_spools(tmp_path, monkeypatch):
    import datascope_core.query_aggregate as aggregates
    catalog = make_catalog(tmp_path)
    workspace, project, source, spec = catalog
    to_typed(catalog)
    expected = workspace.compare(project, ['r_a'])
    cache = tmp_path / 'owned-cache'
    def fail(*args):
        raise RuntimeError('summary interrupted')
    monkeypatch.setattr(aggregates, '_spooled_numbers', fail)
    with pytest.raises(RuntimeError, match='summary interrupted'):
        workspace._index_recording('r_a', workspace.get_source(source), spec,
                                   query_storage='typed_sqlite', cache_dir=cache)
    assert list(cache.iterdir()) == []
    assert_same(workspace.compare(project, ['r_a']), expected)
    with workspace._connect() as conn:
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_interrupted_batch_only_removes_its_incomplete_recording(tmp_path, monkeypatch):
    from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers, _mapped_csv_workspace
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b'rrd', blueprint_payload=b'rbl')
    good = workspace.build_recording(project['id'], source['id'], mapping['id'], output_name='good',
                                    query_storage='typed_sqlite')
    batch = workspace.enqueue_batch_import(project['id'], [source['uri']], query_storage='auto')
    partial = workspace.build_recording(project['id'], source['id'], mapping['id'], output_name='partial',
        query_storage='auto', _job_id=batch['id'], _manage_job=False)
    with workspace._connect() as conn:
        conn.execute("UPDATE jobs SET status='interrupted' WHERE id=?", (batch['id'],))
    workspace.cleanup_job_resources(batch['id'])
    assert workspace.get_recording(good['recording_id'])
    with pytest.raises(KeyError):
        workspace.get_recording(partial['recording_id'])
    from pathlib import Path
    assert not Path(partial['recording_path']).exists()
    with workspace._connect() as conn:
        assert not conn.execute('SELECT 1 FROM typed_summaries WHERE recording_id=?',
                                (partial['recording_id'],)).fetchone()


def test_old_job_without_strategy_stays_legacy(tmp_path, monkeypatch):
    from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers, _mapped_csv_workspace
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b'rrd', blueprint_payload=b'rbl')
    job = workspace.enqueue_build_recording(project['id'], source['id'], mapping['id'], query_storage='auto')
    payload = job['payload']
    del payload['query_storage']
    with workspace._connect() as conn:
        conn.execute('UPDATE jobs SET payload_json=? WHERE id=?', (json.dumps(payload), job['id']))
    assert workspace.claim_job(job['id'], 'test-worker')
    workspace.execute_job(job['id'], 'test-worker')
    with workspace._connect() as conn:
        assert conn.execute('SELECT count(*) FROM typed_indexes').fetchone()[0] == 0


def test_auto_batch_retry_preserves_typed_strategy(tmp_path, monkeypatch):
    from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers
    _install_fake_artifact_writers(monkeypatch, recording_payload=b'rrd', blueprint_payload=b'rbl')
    workspace = Workspace(tmp_path / 'workspace')
    project = workspace.create_project('Batch retry')
    path = tmp_path / 'sample.csv'
    path.write_text('time,battery,state\n0,0.9,idle\n1,0.1,error\n')
    original = workspace._index_recording
    def fail_once(*args, **kwargs):
        monkeypatch.setattr(workspace, '_index_recording', original)
        raise RuntimeError('temporary writer failure')
    monkeypatch.setattr(workspace, '_index_recording', fail_once)
    batch = workspace.batch_import(project['id'], [str(path)], query_storage='auto')
    item = batch['items'][0]
    assert item['status'] == 'failed'
    retry = workspace.enqueue_batch_item_retry(project['id'], batch['id'], item['id'])
    assert retry['payload']['query_storage'] == 'auto'
    assert workspace.claim_job(retry['id'], 'retry-worker')
    workspace.execute_job(retry['id'], 'retry-worker')
    retried = workspace.get_batch(batch['id'])['items'][0]
    assert retried['status'] == 'succeeded'
    with workspace._connect() as conn:
        assert conn.execute('SELECT count(*) FROM typed_indexes').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM typed_summaries').fetchone()[0] == 2


def test_value_index_does_not_hide_invalid_blob(tmp_path):
    from datascope_core.query_typed import sample_table
    import sqlite3
    catalog = make_catalog(tmp_path)
    workspace, project, _, _ = catalog
    to_typed(catalog)
    with workspace._connect() as conn:
        binding = conn.execute("SELECT b.column_no,d.schema_id,b.dataset_id FROM typed_bindings b "
            "JOIN typed_datasets d ON d.id=b.dataset_id WHERE b.key='Battery%_' AND b.semantic_type='scalar'").fetchone()
        conn.execute(f'UPDATE {sample_table(binding[1])} SET c{binding[0]}=? WHERE dataset_id=?',
                     (b'invalid', binding[2]))
    with pytest.raises((RuntimeError, sqlite3.OperationalError)):
        workspace.custom_query(project, {'key': 'Battery%_', 'operator': 'lt', 'value': 0.2})


def test_batch_item_cancel_interrupts_long_sql_transaction(tmp_path, monkeypatch):
    import threading
    import datascope_core.workspace_query as queries
    from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers
    _install_fake_artifact_writers(monkeypatch, recording_payload=b'rrd', blueprint_payload=b'rbl')
    workspace = Workspace(tmp_path / 'workspace')
    project = workspace.create_project('Batch cancellation')
    path = tmp_path / 'sample.csv'
    path.write_text('time,battery,state\n0,0.9,idle\n1,0.1,error\n')
    entered = threading.Event()
    original = queries.build_typed_index
    def slow(conn, *args, **kwargs):
        entered.set()
        conn.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<10000000) '
                     'SELECT sum(x) FROM n').fetchone()
        return original(conn, *args, **kwargs)
    monkeypatch.setattr(queries, 'build_typed_index', slow)
    result = []
    worker = threading.Thread(target=lambda: result.append(workspace.batch_import(
        project['id'], [str(path)], query_storage='auto')))
    worker.start()
    assert entered.wait(10)
    batch = workspace.list_batches(project['id'])[0]
    item = workspace.get_batch(batch['id'])['items'][0]
    workspace.cancel_batch_item(batch['id'], item['id'])
    worker.join(10)
    assert not worker.is_alive()
    assert result[0]['items'][0]['status'] == 'cancelled'
    with workspace._connect() as conn:
        assert conn.execute('SELECT count(*) FROM typed_indexes').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM typed_summaries').fetchone()[0] == 0


@pytest.mark.parametrize('values', [['0.0', '-0.0', '-0.0'], ['-0.0', '0.0', '0.0']])
def test_summary_preserves_first_zero_extrema_and_latest_sign(tmp_path, monkeypatch, values):
    import datascope_core.query_typed as typed
    monkeypatch.setattr(typed, 'CSV_CHUNK_SIZE', 1)
    catalog = make_catalog(tmp_path, 'time,value\n' + '\n'.join(f'{i},{v}' for i, v in enumerate(values)),
        [{'semantic_type': 'scalar', 'entity_path': '/v', 'source_fields': ['value']}])
    workspace, project, _, _ = catalog
    expected = workspace.compare(project, ['r_a'])['rows'][0]['value']
    to_typed(catalog)
    actual = workspace.compare(project, ['r_a'])['rows'][0]['value']
    assert_same(actual, expected)
    for key in ('min', 'max', 'mean', 'latest'):
        assert math.copysign(1, actual[key]) == math.copysign(1, expected[key])


def test_overlapping_eav_group_bypasses_summary_without_merging_partial_means(tmp_path):
    streams = [
        {'semantic_type': 'scalar', 'entity_path': '/v', 'source_fields': ['value']},
        {'semantic_type': 'scalar', 'entity_path': '/v', 'source_fields': ['value', 'mixed']},
    ]
    catalog = make_catalog(tmp_path, 'time,value,mixed\n0,1e16,word\n1,1,x\n2,-1e16,y\n3,1,z\n', streams)
    workspace, project, _, _ = catalog
    expected = workspace.compare(project, ['r_a'])
    to_typed(catalog)
    with workspace._connect() as conn:
        assert not conn.execute("SELECT 1 FROM typed_summaries WHERE entity_path='/v' AND key='value'").fetchone()
    assert_same(workspace.compare(project, ['r_a']), expected)


def test_typed_cancel_marker_is_immediate_without_per_sample_database_reads(tmp_path, monkeypatch):
    from tests.unit.test_rerun_artifacts import _install_fake_artifact_writers, _mapped_csv_workspace
    workspace, project, source, mapping = _mapped_csv_workspace(tmp_path)
    _install_fake_artifact_writers(monkeypatch, recording_payload=b'rrd', blueprint_payload=b'rbl')
    factory = workspace._adapter_for_path
    original_check = workspace._check_job_cancelled
    counts = []
    def checked(job_id):
        counts.append(job_id)
        return original_check(job_id)
    monkeypatch.setattr(workspace, '_check_job_cancelled', checked)
    class Adapter:
        def __init__(self, delegate):
            self.delegate = delegate
        def convert(self, request):
            before = len(counts)
            for _ in range(1000):
                request.cancel_check()
            assert len(counts) - before < 10
            self.delegate.convert(request)
    monkeypatch.setattr(workspace, '_adapter_for_path', lambda *a, **k: Adapter(factory(*a, **k)))
    built = workspace.build_recording(project['id'], source['id'], mapping['id'], query_storage='auto')
    assert built['query_index']['storage'] == 'typed_sqlite'
