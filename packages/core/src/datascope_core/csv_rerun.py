"""Private replayable CSV execution; business timelines retain SDK scalar rounding."""
from __future__ import annotations

import math
import re
from contextlib import closing
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from datascope_core import rerun_writer as writer, time_utils

WORK_BYTES = 64*1024*1024


def _stamp(path):
    stat=Path(path).stat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns


def normalize_time_value(value, unit='auto'):
    # CSV numeric scalars have already been parsed by the same pandas reader.
    # Reuse the original epoch/unit functions, skipping a one-element Series.
    if isinstance(value,(int,float,bool,np.integer,np.floating,np.bool_)) and unit!='datetime':
        number=float(value)
        if not math.isfinite(number):
            return None
        if unit in ('relative_s','seconds'):
            return time_utils.NormalizedTime('duration',number,unit='relative_s')
        if unit=='auto':
            return time_utils._normalize_numeric_time(number)
        if unit in ('unix_s','unix_ms','unix_us','unix_ns'):
            divisor={'unix_s':1,'unix_ms':1000,'unix_us':1_000_000,'unix_ns':1_000_000_000}[unit]
            return time_utils._epoch_time(number/divisor,unit)
    return time_utils.normalize_time_value(value,unit)


def _nanos(value):
    from rerun.time import to_nanos,to_nanos_since_epoch
    return int(to_nanos_since_epoch(value.timestamp) if value.kind=='timestamp' else to_nanos(value.seconds))


def _capable():
    import rerun as rr
    return (bool(re.match(r'^0\.33\.',str(getattr(rr,'__version__',''))))
        and callable(getattr(getattr(rr,'RecordingStream',None),'send_columns',None))
        and callable(getattr(getattr(rr,'Scalars',None),'columns',None)) and callable(getattr(rr,'TimeColumn',None)))


def _outputs(mapping, columns):
    if not mapping.get('enabled',True) or not mapping.get('entity_path') or not mapping.get('source_fields'):
        return []
    path,fields=mapping['entity_path'],mapping['source_fields']
    if mapping.get('semantic_type')=='scalar_group':
        return [(f'{path}/{field}',field) for field in fields if field in columns]
    return [(path,next((f for f in fields if f in columns),None))]


def _canonical(path):
    return (path.startswith('/') and not path.endswith('/') and path==path.strip()
            and '//' not in path and '\\' not in path
            and all(part not in ('.','..') for part in path.split('/')))


def _kind(series):
    values=series.dropna()
    if not len(values):
        return None
    if (pd.api.types.is_integer_dtype(values.dtype) or pd.api.types.is_float_dtype(values.dtype)
            or pd.api.types.is_bool_dtype(values.dtype)):
        return str(values.dtype) if np.isfinite(values.to_numpy(dtype=np.float64)).all() else 'unsupported'
    return 'unsupported'


@dataclass(frozen=True)
class CsvBuildPlan:
    stamp: tuple
    rows: int
    columns: tuple
    ordered: bool
    numeric: tuple
    reasons: dict
    time_kind: str | None
    batch_rows: int
    preflight_ms: float


def preflight(factory, request, *, batch_numeric=True):
    started=perf_counter()
    stamp=_stamp(request.source.path)
    columns,kinds,previous=None,{},None
    ordered,rows=True,0
    time_kinds,unsafe_time=set(),False
    can_batch=batch_numeric and _capable()
    actual_time=request.primary_timeline or writer._primary_time_key(request.mappings)
    iterator=iter(factory())
    try:
        for frame in iterator:
            writer._check_cancel(request)
            current=tuple(frame.columns)
            if columns is None:
                columns=current
            elif columns!=current:
                raise RuntimeError('CSV columns changed during replay preflight')
            rows+=len(frame)
            if batch_numeric:
                fields={field for mapping in request.mappings
                    if mapping.get('semantic_type') in ('scalar','scalar_group')
                    for _,field in _outputs(mapping,columns) if field is not None}
                for field in fields:
                    kind=_kind(frame[field])
                    if kind is not None:
                        prior=kinds.get(field)
                        kinds[field]=kind if prior in (None,kind) else 'unsupported'
            sort_values=(frame[request.primary_timeline].tolist()
                if request.primary_timeline and request.primary_timeline in frame else [None]*len(frame))
            time_values=sort_values if actual_time==request.primary_timeline else (
                frame[actual_time].tolist() if actual_time in frame else [None]*len(frame))
            for sort_value,time_value in zip(sort_values,time_values):
                normalized=normalize_time_value(sort_value,request.timeline_unit) if pd.notna(sort_value) else None
                key=(normalized is None,normalized.seconds if normalized is not None else 0.)
                if previous is not None and key<previous:
                    ordered=False
                previous=key
                actual=normalized if actual_time==request.primary_timeline else (
                    normalize_time_value(time_value,request.timeline_unit) if pd.notna(time_value) else None)
                if actual is not None:
                    time_kinds.add(actual.kind)
                    if can_batch:
                        try:
                            ns=_nanos(actual)
                            # NumPy reserves int64's minimum for NaT; retain
                            # the scalar SDK path for that encoding as well.
                            unsafe_time |= not -(2**63)<ns<2**63
                        except (OverflowError,ValueError,TypeError):
                            unsafe_time=True
            writer._report_progress(request,'sorting' if request.timeline_sort=='ascending' else 'converting',0.)
    finally:
        close=getattr(iterator,'close',None)
        if close:
            close()
    if _stamp(request.source.path)!=stamp:
        raise RuntimeError('CSV changed during Rerun preflight')
    columns=columns or ()
    eligible,reasons,seen=[],{},set()
    collision=False
    for index,mapping in enumerate(request.mappings):
        outputs=_outputs(mapping,columns)
        if not outputs:
            continue
        if mapping.get('semantic_type') not in ('scalar','scalar_group','state','text_log'):
            collision=True  # Other archetypes can create descendants; retain row order.
        for entity,_ in outputs:
            if not _canonical(entity) or entity in seen:
                collision=True
            seen.add(entity)
        if mapping.get('semantic_type') in ('scalar','scalar_group'):
            if any(kinds.get(field)=='unsupported' for _,field in outputs if field is not None):
                reasons[index]='non-numeric, nonfinite or changing field type'
            else:
                eligible.append(index)
    if collision or len(time_kinds)>1 or unsafe_time or not can_batch:
        reason=('entity collision or unmodeled descendants' if collision else 'mixed/unsafe time' if len(time_kinds)>1 or unsafe_time
                else 'numeric batching disabled' if not batch_numeric else 'SDK capability/version')
        reasons.update({index:reason for index in eligible})
        eligible=[]
    batch_rows=max(1,min(50_000,WORK_BYTES//max(1024,len(columns)*256+len(request.mappings)*96)))
    return CsvBuildPlan(stamp,rows,columns,ordered,tuple(eligible),reasons,
                        next(iter(time_kinds)) if len(time_kinds)==1 else None,batch_rows,(perf_counter()-started)*1000)


def _batch(rec, data, start, request, plan, *, external, stats):
    import rerun as rr
    frame=isinstance(data,pd.DataFrame)
    count=len(data)
    rows=np.arange(start,start+count,dtype=np.int64)
    time_key=request.primary_timeline or writer._primary_time_key(request.mappings)
    raw_times=(data[time_key].tolist() if time_key in data else [None]*count) if frame else [r.get(time_key) for r in data]
    normalized=[normalize_time_value(v,request.timeline_unit) if pd.notna(v) else None for v in raw_times]
    timed=np.fromiter((v is not None for v in normalized),dtype=bool,count=count)
    nanos=np.fromiter((_nanos(v) if v is not None else 0 for v in normalized),dtype=np.int64,count=count)
    indexes={}
    for index in plan.numeric:
        for entity,field in _outputs(request.mappings[index],plan.columns):
            if field is None:
                continue
            if frame:
                values=data[field].to_numpy(dtype=np.float64,na_value=np.nan)
            else:
                values=np.asarray([np.nan if r[field] is None or r[field] is pd.NA else r[field] for r in data],dtype=np.float64)
            present=~np.isnan(values)
            for is_timed in (True,False):
                mask=present & (timed if is_timed else ~timed)
                if not mask.any():
                    continue
                key=mask.tobytes()
                axis=indexes.get(key)
                if axis is None:
                    axis=[rr.TimeColumn('row',sequence=rows[mask])]
                    if is_timed:
                        temporal=nanos[mask].view('datetime64[ns]' if plan.time_kind=='timestamp' else 'timedelta64[ns]')
                        axis.append(rr.TimeColumn('time',**({'timestamp':temporal} if plan.time_kind=='timestamp' else {'duration':temporal})))
                    indexes[key]=axis
                rec.send_columns(entity,indexes=axis,columns=rr.Scalars.columns(scalars=values[mask]))
                if stats is not None:
                    stats['column_calls']=stats.get('column_calls',0)+1
    remaining=[mapping for i,mapping in enumerate(request.mappings) if i not in plan.numeric
               and mapping.get('enabled',True) and mapping.get('entity_path') and mapping.get('source_fields')]
    if remaining:
        records=writer._frame_records(data) if frame else iter(data)
        for i,row in enumerate(records):
            rec.set_time('row',sequence=int(rows[i]))
            value=normalized[i]
            if value is None:
                rec.disable_timeline('time')
            elif value.kind=='timestamp':
                rec.set_time('time',timestamp=value.timestamp)
            else:
                rec.set_time('time',duration=value.seconds)
            for mapping in remaining:
                writer._log_mapping(rec,row,mapping)
            if (start+i)%1000==0:
                fraction=writer._fraction(start+i,request)
                writer._report_progress(request,'converting',.5+.5*fraction if external else fraction)
    fraction=writer._fraction(start+count,request)
    writer._report_progress(request,'converting',.5+.5*fraction if external else fraction)


def write_replayable_csv(request, factory, *, fast_sort=True,batch_numeric=True,stats=None):
    plan=preflight(factory,request,batch_numeric=batch_numeric)
    writer._check_cancel(request)
    if _stamp(request.source.path)!=plan.stamp:
        raise RuntimeError('CSV changed before Rerun writing')
    ordered=request.timeline_sort!='ascending' or (fast_sort and plan.ordered)
    if stats is not None:
        stats.update(preflight_ms=plan.preflight_ms,source_rows=plan.rows,source_columns=len(plan.columns),
            fast_sort=bool(request.timeline_sort=='ascending' and ordered),numeric_mappings=list(plan.numeric),
            fallback_reasons=plan.reasons,batch_rows=plan.batch_rows,work_budget_bytes=WORK_BYTES)
    if not plan.numeric:
        # No partial-write fallback: the route is fixed before opening the sink.
        legacy=replace(request,timeline_sort='source') if ordered else request
        processed=0
        def replay():
            nonlocal processed
            iterator=iter(factory())
            try:
                for frame in iterator:
                    processed+=len(frame)
                    yield frame
            finally:
                close=getattr(iterator,'close',None)
                if close:
                    close()
        writer.write_tabular_chunks(replay(),legacy,_sort_work_bytes=WORK_BYTES)
        if processed!=plan.rows:
            raise RuntimeError('CSV sample count changed during Rerun writing')
    else:
        Path(request.output_rrd).parent.mkdir(parents=True,exist_ok=True)
        with writer.recording_stream(request.app_id,request.recording_id) as rec:
            rec.save(request.output_rrd)
            rec.send_recording_name(request.recording_id)
            processed=0
            if ordered:
                iterator=iter(factory())
                try:
                    for frame in iterator:
                        for start in range(0,len(frame),plan.batch_rows):
                            writer._check_cancel(request)
                            section=frame.iloc[start:start+plan.batch_rows]
                            _batch(rec,section,processed,request,plan,external=False,stats=stats)
                            processed+=len(section)
                finally:
                    close=getattr(iterator,'close',None)
                    if close:
                        close()
            else:
                with closing(writer._externally_sorted_rows(factory(),request,_work_bytes=WORK_BYTES)) as iterator:
                    while rows:=list(islice(iterator,plan.batch_rows)):
                        writer._check_cancel(request)
                        _batch(rec,rows,processed,request,plan,external=True,stats=stats)
                        processed+=len(rows)
            if processed!=plan.rows:
                raise RuntimeError('CSV sample count changed during Rerun writing')
    if _stamp(request.source.path)!=plan.stamp:
        raise RuntimeError('CSV changed during Rerun writing')
