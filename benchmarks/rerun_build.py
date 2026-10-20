"""Independent CSV Rerun build comparison; real SDK decoding and verification."""
from __future__ import annotations

import argparse
import gc
import json
import shutil
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, nullcontext
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

REPO = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0,str(REPO))

import pandas as pd
import psutil
import datascope_core.rerun_writer as production
import datascope_core.adapters.csv_adapter as csv_module
import datascope_core.workspace as workspace_module
from datascope_core.models import ConvertRequest, MappingSpec, SourceInfo
from datascope_core.workspace import Workspace
from benchmarks import c2c_rerun_writer as frozen
from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_models import DatasetConfig, PRESETS
from benchmarks.benchmark_query import latency_stats
from benchmarks.benchmark_report import environment
from benchmarks.custom_query_pushdown import sha256, write_json, describe_input
from benchmarks.rrd_contract import semantic_summary
from benchmarks.rerun_profile import Attribution, instrument, legacy_sort_cleanup
from benchmarks.typed_storage import fresh_inputs, retained_inputs

CODE = tuple('packages/core/src/datascope_core/'+p+'.py' for p in
             ('rerun_writer','csv_rerun','adapters/csv_adapter','time_utils','workspace')) + (
             'benchmarks/c2c_rerun_writer.py','benchmarks/rerun_build.py',
             'benchmarks/rerun_profile.py','benchmarks/rrd_contract.py')


class TemporaryUsage:
    """Sample only the task's sort cache during the separate instrumented pass."""
    def __init__(self, root):
        self.root = Path(root)
        self.peak = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self):
        while not self.stop.is_set():
            total = 0
            for path in self.root.rglob('*'):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                except FileNotFoundError:
                    pass
            self.peak = max(self.peak, total)
            self.stop.wait(.02)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()

    def report(self):
        return {'cache_peak_bytes_sampled': self.peak, 'sampling_interval_ms': 20,
                'scope': 'owned CSV sort cache; separate attribution pass; excludes RRD output and SDK validation scratch'}


def source_and_spec(manifest):
    item = manifest['records'][0]
    row = next(s for s in manifest['metadata']['sources'] if s['id']==item['source_id'])
    source = SourceInfo(row['id'],'csv',row['uri'],json.loads(row['metadata_json']))
    spec = MappingSpec(**item['spec'])
    spec.timeline_sort = 'ascending'
    spec.timeline_unit = spec.effective_timeline_unit = 'relative_s'
    return source,spec


def verify(path, scratch):
    checked = subprocess.run([sys.executable,'-m','rerun_cli','rrd','verify',str(path)],
                             capture_output=True,text=True,encoding='utf-8',errors='replace')
    assert checked.returncode == 0
    return {'rrd_verify': {'returncode':checked.returncode,'stdout':checked.stdout,'stderr':checked.stderr},
            'business':semantic_summary(path,scratch),'rrd_bytes':Path(path).stat().st_size}


def sort_storage_probe(manifest):
    """Load the same complete input without SDK writing, outside formal timing."""
    from datascope_core.csv_rerun import preflight
    source, spec = source_and_spec(manifest)
    root = Path(manifest['work'])/'temporary_probe'
    root.mkdir(parents=True, exist_ok=False)
    request = ConvertRequest(source, spec.streams, str(root/'unused.rrd'), 'probe', 'probe',
        primary_timeline=spec.primary_timeline, timeline_unit='relative_s',
        timeline_sort='ascending', cache_dir=str(root/'cache'))
    def frames():
        with pd.read_csv(source.path, chunksize=50_000,
                **csv_module._read_csv_kwargs(csv_module._source_csv_config(source))) as reader:
            yield from reader
    with legacy_sort_cleanup():
        rows = iter(frozen._externally_sorted_rows(frames(), request))
        try:
            next(rows, None)
            final_size = sum(p.stat().st_size for p in (root/'cache').rglob('*') if p.is_file())
        finally:
            rows.close()
    plan = preflight(frames, request)
    assert plan.rows == manifest['config']['rows'] and plan.ordered
    return {'old_final_sort_cache_bytes': final_size, 'new_sort_cache_bytes': 0,
            'source_rows': plan.rows, 'source_order_verified': True,
            'scope': 'separate untimed full-input load/sort and preflight; final owned SQLite sort cache bytes, not native temporary I/O or peak disk'}


def trial(manifest, scheme, root, memory, *, workspace_build=False, attribution=False):
    source,spec = source_and_spec(manifest)
    old = scheme=='old'
    metrics = Attribution()
    temporary = TemporaryUsage(root/'cache')
    stats = {}
    writer_elapsed = 0.
    last = time.monotonic()
    def progress(stage,fraction):
        nonlocal last
        if time.monotonic()-last>15:
            last=time.monotonic()
            print(f'{scheme}: {stage} {fraction:.1%}',flush=True)
    root.mkdir(parents=True,exist_ok=False)
    output = root/'recording.rrd'
    request = ConvertRequest(source,spec.streams,str(output),'benchmark','rerun-benchmark',
        primary_timeline=spec.primary_timeline,timeline_unit='relative_s',timeline_sort='ascending',
        cache_dir=str(root/'cache'),progress_callback=progress)
    active_writer = frozen if old else production
    def selected(frames, req, **kwargs):
        if old:
            return frozen.write_tabular_chunks(frames,req)
        return production.write_tabular_chunks(frames,req,**kwargs,
            _fast_sort=scheme!='batch_only',_batch_numeric=scheme!='sort_only',
            _stats=stats if attribution else None)
    original_convert = csv_module.CsvAdapter.convert
    def converted(adapter,req):
        nonlocal writer_elapsed
        started = time.perf_counter()
        with ExitStack() as stack:
            stack.enter_context(patch.object(csv_module,'write_tabular_chunks',selected))
            if old:
                stack.enter_context(legacy_sort_cleanup())
            original_cancel,original_progress = req.cancel_check,req.progress_callback
            if attribution:
                stack.enter_context(temporary)
                helpers=()
                if not old:
                    from datascope_core import csv_rerun
                    helpers=(csv_rerun,)
                stack.enter_context(instrument(active_writer,metrics,helpers=helpers))
                if original_cancel:
                    req.cancel_check=metrics.wrap('cancellation_progress',original_cancel)
                if original_progress:
                    req.progress_callback=metrics.wrap('cancellation_progress',original_progress)
            try:
                original_convert(adapter,req)
                with metrics.stage('flush_disconnect') if attribution else nullcontext():
                    production.cleanup_recording_streams()
            finally:
                req.cancel_check,req.progress_callback=original_cancel,original_progress
                writer_elapsed = (time.perf_counter()-started)*1000
    with memory.stage('workspace_prepare'):
        if workspace_build:
            workspace = Workspace(root/'workspace')
            project = workspace.create_project('Rerun build benchmark')
            entry = workspace.add_source(project['id'],source.path,storage_mode='reference')
            workspace.inspect_source(entry['id'])
            spec.source_id = entry['id']
            spec.mapping_id='rerun_benchmark_mapping'
            saved=workspace.save_mapping(project['id'],entry['id'],spec,confirmed=True)
    started=time.perf_counter()
    with memory.stage('recording_build'), patch.object(csv_module.CsvAdapter,'convert',converted), \
         patch.object(workspace_module,'cleanup_recording_streams',lambda:None):
        if workspace_build:
            built=workspace.build_recording(project['id'],entry['id'],mapping_id=saved['id'],
                                            output_name='rerun_benchmark',_cache_dir=root/'cache')
            output=Path(built['recording_path'])
            assert Path(built['blueprint_path']).stat().st_size>0
        else:
            csv_module.CsvAdapter().convert(request)
    elapsed=(time.perf_counter()-started)*1000
    # A checkpoint survives a Medium timeout during independent SDK validation.
    result={'rerun_ms':writer_elapsed,'workspace_ms':elapsed if workspace_build else None,
            'writer_complete':True,'rrd_bytes':output.stat().st_size,
            'scope':'Workspace build with default Job/legacy index/Blueprint' if workspace_build else 'standalone CsvAdapter writer; no Job, index or Blueprint',
            'writer_stats':stats,'attribution':metrics.report() if attribution else None,
            'temporary_usage':temporary.report() if attribution else None}
    write_json(root/'writer_complete.json',result)
    with memory.stage('independent_sdk_validation'):
        result['validation']=verify(output,root/'validation')
    assert result['validation']['business']['logical_component_rows']==manifest['config']['rows']*32
    return result


def worker(args):
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    memory=MemorySampler()
    results=[]
    if args.worker == 'temporary_probe':
        with memory:
            temporary = sort_storage_probe(manifest)
        write_json(args.worker_output, {'status':'succeeded', 'samples':[],
            'temporary_usage':temporary, 'memory':memory.report()})
        return
    with memory:
        if args.worker.startswith('profile_'):
            results.append(trial(manifest,args.worker[8:],Path(manifest['work'])/args.worker,
                                 memory,attribution=True))
        elif args.worker.startswith('workspace_'):
            results.append(trial(manifest,args.worker[10:],Path(manifest['work'])/args.worker,
                                 memory,workspace_build=True))
        else:
            warmups = manifest['warmups'] if args.worker in ('old','new') else 0
            runs = manifest['runs'] if args.worker in ('old','new') else 1
            for index in range(warmups+runs):
                root=Path(manifest['work'])/(args.worker+'_'+str(index))
                result=trial(manifest,args.worker,root,memory,
                    workspace_build=manifest['preset']=='small' and not manifest.get('development'))
                result['warmup']=index<warmups
                results.append(result)
                print(f"{args.worker} {'warm-up' if index<warmups else 'run'} {index}: Rerun {result['rerun_ms']:.2f} ms",flush=True)
                write_json(args.worker_output,{'status':'running','samples':results})
                assert root.resolve().parent==Path(manifest['work']).resolve()
                gc.collect()
                shutil.rmtree(root)
    result={'status':'succeeded','samples':results,'memory':memory.report()}
    samples=[item['rerun_ms'] for item in results if not item.get('warmup')]
    result['latency']=latency_stats(samples) if len(samples)>1 else {'elapsed_ms':samples[0]}
    write_json(args.worker_output,result)


def run(args):
    run_id=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid4().hex[:8]
    work=args.output_dir.resolve()/'.work'/('rerun_build_'+run_id)
    work.mkdir(parents=True,exist_ok=False)
    write_json(work/'owner.json',{'run_id':run_id})
    output=args.output_dir/('rerun_build_'+run_id+'.json')
    report={'format_version':1,'run_id':run_id,'preset':args.preset,'status':'running',
            'environment':environment(REPO),'schemes':{},
            'source_files_sha256':{p:sha256(REPO/p) for p in CODE if (REPO/p).exists()}}
    try:
        config=DatasetConfig(rows=args.rows or PRESETS[args.preset])
        if args.rows:
            inputs=fresh_inputs(work,config)
        elif args.preset=='medium':
            inputs=fresh_inputs(work,config,json.loads(args.phase_c_input.read_text(encoding='utf-8')))
        else:
            inputs=retained_inputs(args.preset,REPO/'benchmarks/results/baselines/2026-10-17-phase-c2a'/(args.preset+'.json'))
        runs,warmups=(3,1) if args.preset=='smoke' else (1,0)
        manifest={**inputs,'work':str(work),'preset':args.preset,'config':asdict(config),
            'runs':args.runs or runs,'warmups':warmups if args.warmups is None else args.warmups,'development':bool(args.rows)}
        write_json(work/'manifest.json',manifest)
        report['input']={**inputs,'config':asdict(config),'source_files':[
            {'path':s['uri'],'bytes':Path(s['uri']).stat().st_size,'sha256':sha256(Path(s['uri']))}
            for s in inputs['metadata']['sources']]}
        report['settings']={k:manifest[k] for k in ('runs','warmups','development')}
        if args.profile_only:
            schemes=['profile_old']
        elif args.preset=='medium' and not args.rows:
            schemes=['new']
        else:
            schemes=['old','new']
            if args.preset=='smoke' and not args.rows:
                schemes+=['sort_only','batch_only','workspace_old','workspace_new','profile_old','profile_new']
            elif args.preset=='small' and not args.rows:
                schemes+=['temporary_probe']
        for scheme in schemes:
            target=work/(scheme+'.json')
            process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--worker',scheme,
                '--manifest',str(work/'manifest.json'),'--worker-output',str(target)])
            started,peak,reason=time.monotonic(),0,None
            cache_peak = 0
            while process.poll() is None:
                try:
                    tree=[psutil.Process(process.pid),*psutil.Process(process.pid).children(recursive=True)]
                    peak=max(peak,sum(p.memory_info().rss for p in tree if p.is_running()))
                    if args.preset=='medium' and not args.rows:
                        if peak>2*1024**3 or time.monotonic()-started>1800:
                            reason='2 GiB RSS limit' if peak>2*1024**3 else '30 minute limit'
                            for child in reversed(tree):
                                child.kill()
                            break
                except psutil.NoSuchProcess:
                    pass
                cache_bytes = 0
                for path in work.rglob('tabular-sort.sqlite*'):
                    try:
                        cache_bytes += path.stat().st_size
                    except FileNotFoundError:
                        pass
                cache_peak = max(cache_peak, cache_bytes)
                time.sleep(.1)
            process.wait()
            value=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
            value.update(process_tree_peak_rss_bytes=peak,elapsed_process_ms=(time.monotonic()-started)*1000)
            value['resource_sampling'] = {'sort_cache_peak_bytes':cache_peak,
                'interval_ms':100, 'scope':'parent process resource sampling; owned tabular-sort.sqlite and journals; excludes RRD output, SDK validation files and SQLite native temporary I/O'}
            if reason:
                value.update(status='incomplete',reason=reason)
                checkpoints=[json.loads(p.read_text(encoding='utf-8')) for p in work.rglob('writer_complete.json')]
                value['writer_checkpoints']=checkpoints
            report['schemes'][scheme]=value
            write_json(output,report)
            if reason:
                report['status']='incomplete'
                break
            if process.returncode:
                raise RuntimeError(f'Worker failed: {scheme}, exit={process.returncode}')
        if report['status']!='incomplete':
            hashes={s['validation']['business']['sha256'] for r in report['schemes'].values() for s in r['samples']}
            assert len(hashes)==1,'SDK business row/type/time/value/order parity failed'
            paired = 'old' in report['schemes'] and 'new' in report['schemes']
            acceptance={'all_32_fields':True,'sdk_decode_complete':True,'rrd_verify':True,
                'sdk_parity':True if paired else None,
                'comparison_scope':'frozen old/new complete business fingerprints' if paired
                    else 'single path integrity/stress only; no paired parity claim'}
            if args.preset=='smoke' and not args.rows and not args.profile_only:
                speedup=report['schemes']['old']['latency']['median_ms']/report['schemes']['new']['latency']['median_ms']
                acceptance.update(rerun_median_speedup=speedup,rerun_speedup_ge_2=speedup>=2)
                assert speedup>=2,'Complete Rerun median speedup is below 2x'
            report.update(status='succeeded',acceptance=acceptance)
        if inputs.get('control'):
            assert describe_input(Path(inputs['control']['baseline']))==inputs['control']
        assert all(sha256(Path(s['path']))==s['sha256'] for s in report['input']['source_files'])
        assert report['source_files_sha256']=={p:sha256(REPO/p) for p in report['source_files_sha256']}
    except BaseException as error:
        report.update(status='failed',error=str(error))
        raise
    finally:
        if not args.keep_artifacts:
            assert work.resolve().parent==args.output_dir.resolve()/'.work'
            assert json.loads((work/'owner.json').read_text())['run_id']==run_id
            gc.collect()
            shutil.rmtree(work)
        write_json(output,report)
        output.with_suffix('.md').write_bytes(('# Phase D Rerun build\n\nStatus: '+report['status']+'\n\n'+
            json.dumps(report.get('acceptance',{}),ensure_ascii=False)+'\n\nRaw JSON contains all samples, SDK fingerprints, verify output, RSS, source hashes and scope.\n').encode('utf-8'))
        print('Report: '+str(output),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preset',choices=('smoke','small','medium'),default='smoke')
    parser.add_argument('--rows',type=int)
    parser.add_argument('--runs',type=int)
    parser.add_argument('--warmups',type=int)
    parser.add_argument('--profile-only',action='store_true')
    parser.add_argument('--keep-artifacts',action='store_true')
    parser.add_argument('--output-dir',type=Path,default=REPO/'benchmarks/results')
    parser.add_argument('--phase-c-input',type=Path,default=REPO/'benchmarks/results/baselines/2026-10-17-phase-c/medium.json')
    parser.add_argument('--worker',help=argparse.SUPPRESS)
    parser.add_argument('--manifest',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--worker-output',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not args.rows and (args.runs is not None or args.warmups is not None):
        parser.error('Standard presets use the fixed warm-up/run protocol')
    worker(args) if args.worker else run(args)


if __name__=='__main__':
    main()
