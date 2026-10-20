from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import pandas as pd
import pytest
from benchmarks import c2c_rerun_writer as old
from benchmarks.rerun_profile import legacy_sort_cleanup
from benchmarks.rrd_contract import semantic_summary
from datascope_core.models import ConvertRequest,SourceInfo

from datascope_core import csv_rerun as fast
rr = pytest.importorskip("rerun")
pytestmark = pytest.mark.skipif(not str(rr.__version__).startswith("0.33."), reason="Real SDK 0.33 column contract")


def compare(tmp_path,text,mappings=None,unit='relative_s',order='ascending'):
    path=tmp_path/'input.csv'
    path.write_text(text,encoding='utf8')
    mappings=mappings or [
        {'semantic_type':'scalar','entity_path':'/value','source_fields':['a','b']},
        {'semantic_type':'scalar_group','entity_path':'/group','source_fields':['b']},
        {'semantic_type':'state','entity_path':'/state','source_fields':['state']},
    ]
    request=ConvertRequest(SourceInfo('source','csv',str(path),{'rows':len(text.splitlines())-1}),
        mappings,str(tmp_path/'new.rrd'),'test','test',primary_timeline='time',timeline_unit=unit,
        timeline_sort=order,cache_dir=str(tmp_path/'cache'))
    def factory():
        with pd.read_csv(path,chunksize=50_000) as frames:
            yield from frames
    with legacy_sort_cleanup():
        old.write_tabular_chunks(factory(),replace(request,output_rrd=str(tmp_path/'old.rrd')))
        old.cleanup_recording_streams()
    stats={}
    fast.write_replayable_csv(request,factory,stats=stats)
    old.cleanup_recording_streams()
    left=semantic_summary(tmp_path/'old.rrd',tmp_path/'verify')
    right=semantic_summary(tmp_path/'new.rrd',tmp_path/'verify')
    assert left['sha256']==right['sha256'],(left,right)
    return stats,left


@pytest.mark.parametrize('times,ordered', [
    (['0','1','1','2',''],True),(['2','1','0'],False),(['0','','1'],False),
    (['','',''],True),(['0','0.0000000015','0.0000000025'],True),
])
def test_time_order_missing_and_nanosecond_rounding(tmp_path,times,ordered):
    text='time,a,b,state\n'+'\n'.join(f'{t},{i},{i+1},run' for i,t in enumerate(times))+'\n'
    stats,_=compare(tmp_path,text)
    assert stats['fast_sort'] is ordered
    assert stats['numeric_mappings']==[0,1]


def test_source_order_and_first_present_missing(tmp_path):
    stats,result=compare(tmp_path,'time,a,b,state\n2,,99,run\n0,1,2,error\n1,3,4,run\n',order='source')
    assert not stats['fast_sort']
    assert next(g for g in result['groups'] if g['entity']=='/value')['rows']==2


@pytest.mark.parametrize('unit,times', [
    ('unix_s',['1700000000.000001','1700000000.000002']),
    ('unix_ns',['1700000000000000001','1700000000000001025']),
    ('datetime',['2026-01-01T00:00:00.123456789Z','2026-01-01T00:00:00.123457001Z']),
])
def test_absolute_time_precision(tmp_path,unit,times):
    stats,_=compare(tmp_path,'time,a,b,state\n'+''.join(f'{t},{i},-0.0,run\n' for i,t in enumerate(times)),unit=unit)
    assert stats['numeric_mappings']==[0,1]


def test_large_integer_bool_and_negative_zero(tmp_path):
    compare(tmp_path,'time,a,b,state\n0,9007199254740993,-0.0,True\n1,9223372036854775807,0.0,False\n2,-9223372036854775808,-0.0,True\n')
    nested=tmp_path/'bool'
    nested.mkdir()
    compare(nested,'time,a,b,state\n0,True,False,ok\n1,False,True,error\n')


def test_collision_and_mixed_time_use_rows(tmp_path):
    mappings=[{'semantic_type':'scalar','entity_path':'/same','source_fields':['a']},
              {'semantic_type':'scalar','entity_path':'/same','source_fields':['b']}]
    stats,_=compare(tmp_path,'time,a,b,state\n0,1,2,x\n0,3,4,y\n',mappings)
    assert not stats['numeric_mappings']
    other=tmp_path/'mixed'
    other.mkdir()
    stats,_=compare(other,'time,a,b,state\n1,1,2,x\n1700000000,3,4,y\n',unit='auto')
    assert not stats['numeric_mappings']


def test_older_sdk_keeps_row_writing(tmp_path,monkeypatch):
    import rerun as rr
    monkeypatch.setattr(rr,'__version__','0.26.2')
    stats,_=compare(tmp_path,'time,a,b,state\n0,1,2,x\n1,3,4,y\n')
    assert not stats['numeric_mappings']


def test_source_change_before_sink_and_cancel(tmp_path):
    path=tmp_path/'input.csv'
    path.write_text('time,a\n0,1\n1,2\n',encoding='utf8')
    req=ConvertRequest(SourceInfo('s','csv',str(path)),[{'semantic_type':'scalar','entity_path':'/a','source_fields':['a']}],
        str(tmp_path/'out.rrd'),'t','t',primary_timeline='time',timeline_sort='ascending')
    def factory():
        with pd.read_csv(path,chunksize=50_000) as reader:
            yield from reader
    def changed(*args):
        path.write_text('time,a\n0,1\n1,3\n2,4\n',encoding='utf8')
    req.progress_callback=changed
    with pytest.raises(RuntimeError,match='CSV changed during Rerun preflight'):
        fast.write_replayable_csv(req,factory)
    assert not Path(req.output_rrd).exists()
    req.progress_callback=None
    def cancel():
        raise RuntimeError('cancelled')
    req.cancel_check=cancel
    with pytest.raises(RuntimeError,match='cancelled'):
        fast.write_replayable_csv(req,factory)
    assert not Path(req.output_rrd).exists()


def test_full_preflight_cross_chunk_change_and_stable_sort(tmp_path):
    text='time,a,b,state\n'+''.join(f'{i},1,2,run\n' for i in range(50_000))+'50000,1.5,2,error\n'
    stats,_=compare(tmp_path,text)
    assert stats['fast_sort']
    assert 0 not in stats['numeric_mappings']
    assert 1 in stats['numeric_mappings']


def test_cross_chunk_disorder_uses_external_sort(tmp_path):
    text='time,a,b,state\n'+''.join(f'{i},1,2,run\n' for i in range(50_000))+'-1,3,4,error\n'
    stats,_=compare(tmp_path,text)
    assert not stats['fast_sort']



def test_adapter_uses_replay_and_skips_sort_database(tmp_path, monkeypatch):
    from datascope_core.adapters.csv_adapter import CsvAdapter
    from datascope_core import rerun_writer
    path = tmp_path/'input.csv'
    path.write_text('time,a\n0,1\n1,2\n', encoding='utf8')
    source = CsvAdapter().inspect(str(path), options={'header_mode':'header'})
    req = ConvertRequest(source, [{'semantic_type':'scalar','entity_path':'/a','source_fields':['a']}],
                         str(tmp_path/'output.rrd'), 'test', 'test', primary_timeline='time',
                         timeline_unit='relative_s', timeline_sort='ascending')
    calls = []
    original = fast._batch
    def batch(*args, **kwargs):
        calls.append(len(args[1]))
        return original(*args, **kwargs)
    def unexpected(*args, **kwargs):
        raise AssertionError('Sorted CSV must not use SQLite or pickle sorting')
    monkeypatch.setattr(fast, '_batch', batch)
    monkeypatch.setattr(rerun_writer, '_externally_sorted_rows', unexpected)
    CsvAdapter().convert(req)
    rerun_writer.cleanup_recording_streams()
    assert calls == [2]
    assert semantic_summary(req.output_rrd, tmp_path/'decode')['logical_component_rows'] == 2


def test_nonfinite_mapping_really_uses_row_path(tmp_path):
    stats, _ = compare(tmp_path, 'time,a,b,state\n0,1,2,x\n1,inf,3,y\n')
    assert 0 not in stats['numeric_mappings']


def test_object_field_preserves_original_float_conversion_error(tmp_path):
    path = tmp_path/'input.csv'
    path.write_text('time,a\n0,1\n1,word\n', encoding='utf8')
    req = ConvertRequest(SourceInfo('s','csv',str(path)),
        [{'semantic_type':'scalar','entity_path':'/a','source_fields':['a']}],
        str(tmp_path/'new.rrd'),'test','test',primary_timeline='time',
        timeline_unit='relative_s',timeline_sort='ascending',cache_dir=str(tmp_path/'cache'))
    def frames():
        with pd.read_csv(path, chunksize=50_000) as reader:
            yield from reader
    plan = fast.preflight(frames, req)
    assert not plan.numeric
    with legacy_sort_cleanup(), pytest.raises(ValueError) as before:
        old.write_tabular_chunks(frames(), replace(req, output_rrd=str(tmp_path/'old.rrd')))
    with pytest.raises(ValueError) as after:
        fast.write_replayable_csv(req, frames)
    old.cleanup_recording_streams()
    assert str(after.value) == str(before.value)


def test_missing_sdk_columns_capability_uses_rows(tmp_path, monkeypatch):
    import rerun as rr
    monkeypatch.setattr(rr.Scalars, 'columns', None)
    stats, _ = compare(tmp_path, 'time,a,b,state\n0,1,2,x\n1,3,4,y\n')
    assert not stats['numeric_mappings']


def test_numpy_nat_sentinel_keeps_scalar_time_conversion(tmp_path):
    path = tmp_path/'input.csv'
    path.write_text('time,a\n-9223372036.854776,1\n0,2\n', encoding='utf8')
    req = ConvertRequest(SourceInfo('s','csv',str(path)),
        [{'semantic_type':'scalar','entity_path':'/a','source_fields':['a']}],
        str(tmp_path/'out.rrd'),'test','test',primary_timeline='time',
        timeline_unit='relative_s',timeline_sort='ascending')
    def frames():
        with pd.read_csv(path, chunksize=50_000) as reader:
            yield from reader
    assert not fast.preflight(frames, req).numeric


def test_nonreplayable_writer_preserves_legacy_route(tmp_path, monkeypatch):
    from datascope_core import rerun_writer
    req = ConvertRequest(SourceInfo('s','csv',str(tmp_path/'not-needed.csv')),
        [{'semantic_type':'scalar','entity_path':'/a','source_fields':['a']}],
        str(tmp_path/'old-route.rrd'),'test','test',timeline_sort='source')
    def unexpected(*args, **kwargs):
        raise AssertionError('Nonreplayable input must use the existing writer')
    monkeypatch.setattr(fast, 'preflight', unexpected)
    rerun_writer.write_tabular_chunks(iter([pd.DataFrame({'a':[1.,2.]})]), req)
    rerun_writer.cleanup_recording_streams()
    assert semantic_summary(req.output_rrd, tmp_path/'decode')['logical_component_rows'] == 2


def test_external_sort_closes_source_and_database_on_early_stop(tmp_path):
    from datascope_core import rerun_writer
    closed = []
    def frames():
        try:
            yield pd.DataFrame({'time':[2,1,0], 'a':[1,2,3]})
        finally:
            closed.append(True)
    req = ConvertRequest(SourceInfo('s','csv','unused'), [], str(tmp_path/'out.rrd'),
        'test','test',primary_timeline='time',timeline_unit='relative_s',
        timeline_sort='ascending',cache_dir=str(tmp_path/'cache'))
    rows = iter(rerun_writer._externally_sorted_rows(frames(), req, _work_bytes=1024))
    assert next(rows)['time'] == 0
    rows.close()
    assert closed == [True]
    assert not (tmp_path/'cache/tabular-sort.sqlite').exists()


@pytest.mark.parametrize('failure', ['cancel', 'source-change'])
def test_workspace_cleans_partial_fast_csv_build(tmp_path, monkeypatch, failure):
    from datascope_core.workspace import Workspace
    from datascope_core.workspace_jobs import JobCancelled
    path = tmp_path/'input.csv'
    path.write_text('time,battery,temperature\n0,0.9,20\n1,0.8,21\n2,0.7,22\n', encoding='utf8')
    workspace = Workspace(tmp_path/'workspace')
    project = workspace.create_project('Cleanup')
    source = workspace.add_source(project['id'], str(path), storage_mode='reference')
    workspace.inspect_source(source['id'])
    changed = []
    original = fast._batch
    def batch(*args, **kwargs):
        result = original(*args, **kwargs)
        if not changed:
            changed.append(True)
            if failure == 'source-change':
                with path.open('a', encoding='utf8') as stream:
                    stream.write('3,0.6,23\n')
        return result
    def cancel():
        if changed and failure == 'cancel':
            raise JobCancelled('test cancellation after batch')
    monkeypatch.setattr(fast, '_batch', batch)
    monkeypatch.setattr(fast, 'WORK_BYTES', 1024)
    with pytest.raises(RuntimeError, match='cancellation|CSV changed'):
        workspace.build_recording(project['id'], source['id'],
            output_dir=str(tmp_path/'output'), _cache_dir=tmp_path/'cache', _cancel_check=cancel)
    assert changed
    assert workspace.list_recordings(project['id']) == []
    assert list((tmp_path/'output').rglob('*.rrd')) == []
    assert list((tmp_path/'output').rglob('*.rbl')) == []
