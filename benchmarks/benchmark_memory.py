from __future__ import annotations

import threading
from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

import psutil


class MemorySampler:
    """Sample the real process RSS, including native Rerun/Arrow allocations."""

    def __init__(self, interval_seconds: float = 0.01) -> None:
        self.interval = interval_seconds
        self.process = psutil.Process()
        self.stages: dict[str, dict] = {}
        self.peak = 0
        self._stage_peak = 0
        self._stop = threading.Event()

    def sample(self) -> int:
        rss = self.process.memory_info().rss
        self.peak = max(self.peak, rss)
        self._stage_peak = max(self._stage_peak, rss)
        return rss

    def _poll(self) -> None:
        while not self._stop.wait(self.interval):
            self.sample()

    def __enter__(self) -> MemorySampler:
        self.before = self.sample()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        self._thread.join()
        self.after = self.sample()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        before = self.sample()
        self._stage_peak = before
        started = perf_counter()
        try:
            yield
        finally:
            after = self.sample()
            self.stages[name] = {
                "elapsed_ms": (perf_counter() - started) * 1000,
                "rss_before_mb": before / 1_000_000,
                "rss_after_mb": after / 1_000_000,
                "peak_rss_mb": self._stage_peak / 1_000_000,
            }

    def report(self) -> dict:
        info = self.process.memory_info()
        # Windows exposes the OS working-set high water mark; sampled peak is portable.
        os_peak = getattr(info, "peak_wset", None)
        return {
            "method": "psutil process RSS polling; includes native allocations",
            "sample_interval_ms": self.interval * 1000,
            "peak_rss_mb": self.peak / 1_000_000,
            "os_peak_rss_mb": os_peak / 1_000_000 if os_peak is not None else None,
            "rss_before_mb": self.before / 1_000_000,
            "rss_after_mb": getattr(self, "after", self.sample()) / 1_000_000,
            "stages": self.stages,
            "scope": "this process; child processes and system page cache are excluded",
        }
