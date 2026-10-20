"""Untimed attribution pass only; native SDK serialization stays inside SDK calls."""
from __future__ import annotations

from collections import Counter
from contextlib import ExitStack, contextmanager
from time import perf_counter
from unittest.mock import patch
from pathlib import Path


@contextmanager
def legacy_sort_cleanup():
    """Resource-only adapter for the frozen writer's Windows open-file unlink.

    The original source and its rows, ordering, pickle and SDK calls stay intact.
    """
    import sqlite3
    connect=sqlite3.connect
    class ClosingSortConnection(sqlite3.Connection):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.readers=[]
        def execute(self,*args,**kwargs):
            cursor=super().execute(*args,**kwargs)
            if cursor.description:
                self.readers.append(cursor)
            return cursor
        def __exit__(self,*args):
            try:
                return super().__exit__(*args)
            finally:
                for cursor in self.readers:
                    cursor.close()
                self.readers.clear()
                self.close()
    def opened(*args,**kwargs):
        if args and Path(str(args[0])).name=='tabular-sort.sqlite':
            kwargs={**kwargs,'factory':ClosingSortConnection}
        return connect(*args,**kwargs)
    with patch.object(sqlite3,'connect',opened):
        yield


class Attribution:
    def __init__(self):
        self.seconds, self.inclusive, self.calls = Counter(), Counter(), Counter()
        self.active = []

    @contextmanager
    def stage(self, name):
        frame = [name, 0.]
        self.active.append(frame)
        start = perf_counter()
        try:
            yield
        finally:
            elapsed = perf_counter()-start
            self.active.pop()
            self.calls[name] += 1
            self.seconds[name] += elapsed-frame[1]
            self.inclusive[name] += elapsed
            if self.active:
                self.active[-1][1] += elapsed

    def wrap(self, name, function):
        def measured(*args, **kwargs):
            with self.stage(name):
                return function(*args, **kwargs)
        return measured

    def factory(self, factory):
        def frames():
            with self.stage('csv_read'):
                iterator = iter(factory())
            try:
                while True:
                    with self.stage('csv_read'):
                        frame = next(iterator, None)
                    if frame is None:
                        break
                    yield frame
            finally:
                close = getattr(iterator, 'close', None)
                if close:
                    close()
        return frames

    def report(self):
        return {'milliseconds': {key: value*1000 for key, value in self.seconds.items()},
                'inclusive_milliseconds': {key: value*1000 for key, value in self.inclusive.items()},
                'calls': dict(self.calls),
                'scope': 'separate instrumented build; milliseconds are exclusive intervals, inclusive_milliseconds must not be summed; uninstrumented overhead remains; SDK native serialization is included in sdk_calls'}


@contextmanager
def instrument(writer, attribution, *, helpers=()):
    import rerun as rr
    import pickle
    import sqlite3
    import pandas as pd
    metrics = attribution
    original_stream, connect = writer.recording_stream, sqlite3.connect

    class Recording:
        def __init__(self, raw):
            self.raw = raw
        def __getattr__(self, name):
            value = getattr(self.raw, name)
            if name in {'log','send_columns','set_time','disable_timeline','save','send_recording_name'}:
                return metrics.wrap('sdk_calls', value)
            return value

    @contextmanager
    def stream(*args, **kwargs):
        manager = original_stream(*args, **kwargs)
        with metrics.stage('sdk_setup'):
            recording = manager.__enter__()
        try:
            yield Recording(recording)
        except BaseException:
            import sys
            with metrics.stage('flush_disconnect'):
                manager.__exit__(*sys.exc_info())
            raise
        else:
            with metrics.stage('flush_disconnect'):
                manager.__exit__(None, None, None)

    class Cursor:
        def __init__(self, raw, stage):
            self.raw, self.stage = raw, stage
        def __iter__(self):
            return self
        def __next__(self):
            with metrics.stage(self.stage):
                return next(self.raw)
        def __getattr__(self, name):
            return getattr(self.raw, name)

    class Connection:
        def __init__(self, raw):
            self.raw = raw
        def __enter__(self):
            self.raw.__enter__()
            return self
        def __exit__(self, *args):
            with metrics.stage('sqlite_load'):
                return self.raw.__exit__(*args)
        def execute(self, sql, *args):
            stage = 'sqlite_sort_fetch' if sql.lstrip().lower().startswith('select') else 'sqlite_load'
            with metrics.stage(stage):
                return Cursor(self.raw.execute(sql, *args), stage)
        def executemany(self, *args):
            with metrics.stage('sqlite_load'):
                return self.raw.executemany(*args)
        def commit(self):
            with metrics.stage('sqlite_load'):
                return self.raw.commit()
        def __getattr__(self, name):
            return getattr(self.raw, name)

    class Archetype:
        def __init__(self, raw):
            self.raw = raw
        def __call__(self, *args, **kwargs):
            with metrics.stage('archetype_arrow'):
                return self.raw(*args, **kwargs)
        def __getattr__(self, name):
            value = getattr(self.raw, name)
            return metrics.wrap('archetype_arrow', value) if name == 'columns' else value

    class CsvReader:
        def __init__(self, raw):
            self.raw = raw
        def __iter__(self):
            return self
        def __next__(self):
            with metrics.stage('csv_read'):
                return next(self.raw)
        def __enter__(self):
            self.raw.__enter__()
            return self
        def __exit__(self, *args):
            with metrics.stage('csv_read'):
                return self.raw.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.raw,name)
    read_csv = pd.read_csv
    def read(*args, **kwargs):
        with metrics.stage('csv_read'):
            result = read_csv(*args, **kwargs)
        return CsvReader(result) if hasattr(result,'__next__') else result

    with ExitStack() as stack:
        stack.enter_context(patch.object(writer, 'recording_stream', stream))
        stack.enter_context(patch.object(pd,'read_csv',read))
        def sort_connection(*args, **kwargs):
            result = connect(*args, **kwargs)
            return Connection(result) if args and Path(str(args[0])).name == 'tabular-sort.sqlite' else result
        stack.enter_context(patch.object(sqlite3, 'connect', sort_connection))
        for name in ('dumps','loads'):
            stack.enter_context(patch.object(pickle, name, metrics.wrap('pickle_'+name, getattr(pickle,name))))
        for module in (writer, *helpers):
            for name in ('normalize_time_value','time_seconds_or_none','_nanos'):
                if hasattr(module,name):
                    stack.enter_context(patch.object(module,name,metrics.wrap('time_conversion',getattr(module,name))))
            if hasattr(module,'preflight'):
                stack.enter_context(patch.object(module,'preflight',metrics.wrap('csv_preflight',module.preflight)))
        for name in ('Scalars','StateChange','TextLog','TimeColumn'):
            if hasattr(rr,name):
                stack.enter_context(patch.object(rr,name,Archetype(getattr(rr,name))))
        yield
