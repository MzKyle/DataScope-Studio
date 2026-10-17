from __future__ import annotations

import json
from pathlib import Path

from mcap.writer import Writer

from benchmarks.benchmark_memory import MemorySampler
from benchmarks.benchmark_pipeline import BenchmarkWorkspace
from benchmarks.benchmark_query import measure_query


def benchmark_time_sync(workspace: BenchmarkWorkspace, project_id: str, root: Path,
                        memory: MemorySampler, *, runs: int, warmups: int, limit: int) -> dict:
    """Actual MCAP inspection/indexing; a catalog fixture, not a Rerun artifact build."""
    path = root / "topic_ranges.mcap"
    base = 1_800_000_000_000_000_000
    with path.open("xb") as handle:
        writer = Writer(handle)
        writer.start(library="datascope-benchmark")
        schema = writer.register_schema("Telemetry", "jsonschema", b'{"type":"object"}')
        for topic, offset in (("/sensor/a", 0), ("/sensor/b", 20_000_000)):
            channel = writer.register_channel(topic, "json", schema)
            for elapsed in (0, 1_000_000_000):
                timestamp = base + offset + elapsed
                writer.add_message(channel, log_time=timestamp, publish_time=timestamp,
                                   data=json.dumps({"value": elapsed}).encode())
        writer.finish()
    with memory.stage("time_sync_fixture/build"):
        source = workspace.add_source(project_id, str(path))
        inspection = workspace.inspect_source(source["id"])
        spec = workspace.suggest_mapping(source["id"], template_id="robotics_debug")
        recording_id = spec.recording_id
        conn = workspace._connect()
        try:
            with conn:
                conn.execute(
                    """insert into recordings
                    (id, project_id, source_id, app_id, path, run_name, created_at)
                    values (?, ?, ?, ?, '', 'time_sync_metadata_fixture', 'benchmark-index-only')""",
                    (recording_id, project_id, source["id"], spec.app_id),
                )
        finally:
            conn.close()
        workspace._index_recording(recording_id, workspace.get_source(source["id"]), spec)

    def validate(result: dict) -> None:
        if len(result["rows"]) != 1:
            raise AssertionError("Two MCAP topics must produce one time-sync delta")
        row = result["rows"][0]
        # Current MCAP inspect exposes file-wide ranges, not per-topic ranges.
        # Query Index copies that shared range to both topics, hence zero deltas.
        if row["key"] != "time_delta" or row["value"]["start_delta"] != 0:
            raise AssertionError("Incorrect MCAP start-time delta")
        if row["value"]["end_delta"] != 0:
            raise AssertionError("Incorrect MCAP end-time delta")

    query = measure_query(lambda: workspace.run_query(
        project_id, "time_sync", [recording_id], limit=limit), validate,
        runs=runs, warmups=warmups, memory=memory, name="time_sync_topics")
    query["coverage"] = "two real inspected MCAP topics; four metadata index rows; no RRD build"
    query["coverage_limitation"] = (
        "MCAP inspect exposes a shared file-wide range; current index/template returns zero "
        "delta despite the generated 20 ms topic offset. This measures metadata query execution, "
        "not correctness of sensor synchronization; per-topic range support is a follow-up.")
    return {"query": query, "source_size_bytes": path.stat().st_size,
            "topics": len(inspection["source"]["metadata"]["topics"]),
            "messages": 4, "query_rows": 4, "known_topic_offset_ms": 20,
            "current_reported_delta": 0,
            "artifact_build": "not performed; metadata fixture"}
