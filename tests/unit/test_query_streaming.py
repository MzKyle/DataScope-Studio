from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from datascope_core.workspace import Workspace


def test_streamable_query_stops_after_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("Streaming query")
    consumed = 0

    def fail_full_fetch(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("streamable query should not fetch all rows")

    def stream_rows(*args: Any, **kwargs: Any):
        nonlocal consumed
        for index in range(1000):
            consumed += 1
            yield {
                "recording_id": "recording",
                "source_id": "source",
                "time": float(index),
                "entity_path": "/battery",
                "semantic_type": "scalar",
                "key": "battery",
                "value_json": json.dumps(0.1),
            }

    monkeypatch.setattr(workspace, "_query_rows", fail_full_fetch)
    monkeypatch.setattr(workspace, "_iter_query_rows", stream_rows)

    result = workspace.run_query(
        project["id"],
        "low_battery",
        params={"threshold": 0.5},
        limit=3,
    )

    assert len(result["rows"]) == 3
    assert consumed == 3
