from pathlib import Path

from datascope_core.adapters.point_cloud_adapter import PointCloudAdapter, read_point_cloud_points
from datascope_core.mapping import suggest_mapping
from datascope_core.models import detect_source_type
from datascope_core.query import build_query_rows
from datascope_core.templates import match_templates


def test_point_cloud_adapter_inspects_ply_directory(tmp_path: Path) -> None:
    cloud_dir = _make_point_cloud_fixture(tmp_path)
    adapter = PointCloudAdapter()

    source = adapter.inspect(str(cloud_dir), source_id="source_cloud")
    streams = adapter.infer_streams(source)
    preview = adapter.preview(source, "stream_point_cloud")
    spec = suggest_mapping(source, streams)
    matches = match_templates(streams)

    assert detect_source_type(cloud_dir) == "point_cloud"
    assert source.source_type == "point_cloud"
    assert source.metadata["point_cloud_count"] == 2
    assert source.metadata["formats"] == ["ply"]
    assert streams[0].semantic_type == "points3d"
    assert streams[0].metadata["role"] == "point_cloud"
    assert preview["rows"][0]["point_count"] == 3
    assert spec.app_id == "datascope.robotics_debug.v1"
    assert spec.streams[0]["entity_path"] == "/sensors/lidar/points"
    assert matches[0]["template_id"] == "robotics_debug"


def test_point_cloud_query_rows(tmp_path: Path) -> None:
    cloud_dir = _make_point_cloud_fixture(tmp_path)
    adapter = PointCloudAdapter()
    source = adapter.inspect(str(cloud_dir), source_id="source_cloud")
    streams = adapter.infer_streams(source)
    spec = suggest_mapping(source, streams, template_id="robotics_debug")

    rows = build_query_rows("recording_cloud", source, spec)

    assert any(row.key == "point_count" and row.value == 3 for row in rows)
    assert any(row.semantic_type == "points3d" for row in rows)


def test_read_point_cloud_points_filters_nan(tmp_path: Path) -> None:
    path = tmp_path / "cloud.ply"
    _write_ply(path, [[0, 1, 2], [float("nan"), 1, 2], [3, 4, 5]])

    assert read_point_cloud_points(path) == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]


def _make_point_cloud_fixture(tmp_path: Path) -> Path:
    cloud_dir = tmp_path / "clouds"
    cloud_dir.mkdir()
    _write_ply(cloud_dir / "1780166165355.ply", [[0, 0, 0], [1, 0, 0], [0, 1, 0]])
    _write_ply(cloud_dir / "1780166166355.ply", [[0, 0, 1], [1, 1, 1], [2, 2, 2]])
    return cloud_dir


def _write_ply(path: Path, points: list[list[float]]) -> None:
    lines = [
        "ply",
        "format ascii 1.0",
        f"element vertex {len(points)}",
        "property float x",
        "property float y",
        "property float z",
        "end_header",
    ]
    lines.extend(" ".join(str(value) for value in point) for point in points)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
