from __future__ import annotations

import time
import threading

from datascope_api.services import AppServices


def test_workspace_warmup_does_not_block_startup(monkeypatch) -> None:
    services = AppServices()
    started = threading.Event()
    release = threading.Event()

    def slow_workspace() -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(services, "workspace", slow_workspace)

    start = time.monotonic()
    services.warm_workspace()

    assert started.wait(timeout=1)
    assert time.monotonic() - start < 0.5
    release.set()
