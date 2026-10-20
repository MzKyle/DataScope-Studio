"""Exact business-row RRD fingerprints using the real 0.33 SDK and disk sorting.

Only automatic clocks, generated IDs and chunk organization are excluded. Row
IDs are used to recover ingestion order for ties, then removed from the digest.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from contextlib import ExitStack, closing
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc


def semantic_summary(path, scratch):
    from rerun.experimental import RrdReader
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    groups, written = {}, 0
    with tempfile.TemporaryDirectory(prefix='rrd-contract-', dir=scratch) as directory, ExitStack() as stack:
        assert Path(directory).resolve().parent == scratch.resolve()
        reader = RrdReader(path)
        with closing(iter(reader.stream())) as chunks:
            for chunk in chunks:
                batch = chunk.to_record_batch()
                if 'row' not in batch.schema.names:
                    continue  # SDK store metadata has no business row timeline.
                row_column = batch.column('row')
                assert pa.types.is_int64(row_column.type), 'Business row must remain an int64 sequence'
                rows = row_column.to_numpy(zero_copy_only=False)
                ids = batch.column('rerun.controls.RowId')
                raw_ids = np.frombuffer(ids.buffers()[1], dtype='V16', count=len(ids), offset=ids.offset*16)
                time_tag, time_values = np.zeros(len(rows), dtype='u1'), np.zeros(len(rows), dtype='<i8')
                if 'time' in batch.schema.names:
                    timeline = batch.column('time')
                    assert pa.types.is_duration(timeline.type) or pa.types.is_timestamp(timeline.type)
                    assert timeline.type.unit == 'ns', 'Business time must preserve nanoseconds'
                    valid = timeline.is_valid().to_numpy(zero_copy_only=False)
                    time_tag[valid] = 1 if pa.types.is_duration(timeline.type) else 2
                    time_values[valid] = pc.fill_null(pc.cast(timeline,pa.int64()),0).to_numpy()[valid]
                for field in batch.schema:
                    if (field.metadata or {}).get(b'rerun:kind') != b'data':
                        continue
                    column = batch.column(field.name)
                    valid = column.is_valid().to_numpy(zero_copy_only=False) & row_column.is_valid().to_numpy(zero_copy_only=False)
                    if not valid.any():
                        continue
                    single_float = (pa.types.is_list(column.type) and pa.types.is_float64(column.type.value_type)
                                    and pc.all(pc.equal(pc.list_value_length(column).filter(pa.array(valid)),1)).as_py())
                    kind = 'float64' if single_float else str(column.type)
                    key = (chunk.entity_path, field.name, kind)
                    group = groups.get(key)
                    if group is None:
                        dtype = np.dtype([('row','<i8'),('id','V16'),('tag','u1'),('time','<i8'),
                                          ('value','<u8',(1 if single_float else 4,))])
                        target = Path(directory)/f'group-{len(groups)}.bin'
                        group = groups[key] = {'path':target, 'dtype':dtype, 'count':0,
                            'stream':stack.enter_context(target.open('wb'))}
                    values = np.zeros(int(valid.sum()), dtype=group['dtype'])
                    values['row'],values['id'] = rows[valid],raw_ids[valid]
                    values['tag'],values['time'] = time_tag[valid],time_values[valid]
                    filtered = column.filter(pa.array(valid))
                    if single_float:
                        native = pc.list_flatten(filtered).to_numpy(zero_copy_only=False)
                        values['value'][:,0] = native.astype('<f8',copy=False).view('<u8')
                    else:
                        # Dictionary encoding avoids repeated JSON conversion of states.
                        cache = {}
                        for i,value in enumerate(filtered.to_pylist()):
                            encoded = json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=True)
                            if encoded not in cache:
                                cache[encoded] = np.frombuffer(hashlib.sha256(encoded.encode('utf-8')).digest(),dtype='<u8')
                            values['value'][i] = cache[encoded]
                    group['stream'].write(values.tobytes())
                    group['count'] += len(values)
                    written += values.nbytes
        # Writers close before mmap sorting, including on Windows.
        stack.close()
        result = []
        for (entity, component, kind),group in sorted(groups.items()):
            data = np.memmap(group['path'],dtype=group['dtype'],mode='r+',shape=(group['count'],))
            try:
                data.sort(order=['row','id'],kind='quicksort')
                digest = hashlib.sha256()
                payload_dtype = np.dtype([('row','<i8'),('tag','u1'),('time','<i8'),
                    ('value','<u8',group['dtype']['value'].shape)])
                for start in range(0,len(data),50_000):
                    block = data[start:start+50_000]
                    payload = np.empty(len(block),dtype=payload_dtype)
                    for name in payload_dtype.names:
                        payload[name] = block[name]
                    digest.update(payload.tobytes())
                result.append({'entity':entity,'component':component,'type':kind,'rows':len(data),
                               'sha256':digest.hexdigest()})
                del block
            finally:
                data.flush()
                data._mmap.close()
                del data
        encoded = json.dumps(result,sort_keys=True,ensure_ascii=False).encode('utf-8')
        return {'sha256':hashlib.sha256(encoded).hexdigest(),'groups':result,
                'logical_component_rows':sum(g['rows'] for g in result),'temporary_bytes':written,
                'scope':'all business components, row sequence, exact ns time type/value and duplicate ingestion order; ignores SDK clocks/IDs and chunk boundaries'}
