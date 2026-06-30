import struct
from pathlib import Path

from datascope_core.adapters.point_cloud_adapter import (
    PointCloudAdapter,
    read_point_cloud_frame,
    read_point_cloud_points,
)
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


def test_read_binary_little_endian_ply_with_extra_fields_and_nan(tmp_path: Path) -> None:
    path = tmp_path / "cloud_binary.ply"
    _write_binary_ply(
        path,
        [
            (7, 1.5, 2.5, 3.5, 10, 20, 30),
            (8, float("nan"), 4.0, 5.0, 40, 50, 60),
            (9, -1.0, -2.0, -3.0, 70, 80, 90),
        ],
    )

    assert read_point_cloud_points(path) == [
        [1.5, 2.5, 3.5],
        [-1.0, -2.0, -3.0],
    ]
    assert read_point_cloud_frame(path).colors == [[10, 20, 30], [70, 80, 90]]

    source = PointCloudAdapter().inspect(str(path))
    assert source.metadata["sampled"][0]["point_count"] == 3
    assert source.metadata["sampled"][0]["warning"] is None


def test_read_binary_pcd_points_with_extra_field_and_nan(tmp_path: Path) -> None:
    path = tmp_path / "cloud.pcd"
    _write_binary_pcd(
        path,
        [
            (7, 1.5, 2.5, 3.5),
            (8, float("nan"), 4.0, 5.0),
            (9, -1.0, -2.0, -3.0),
        ],
    )

    assert read_point_cloud_points(path) == [
        [1.5, 2.5, 3.5],
        [-1.0, -2.0, -3.0],
    ]

    source = PointCloudAdapter().inspect(str(path))
    assert source.metadata["sampled"][0]["point_count"] == 3
    assert source.metadata["sampled"][0]["warning"] is None


def test_read_ascii_pcd_frame_with_explicit_rgb_fields(tmp_path: Path) -> None:
    path = tmp_path / "cloud_rgb.pcd"
    path.write_text(
        "\n".join(
            [
                "# .PCD v0.7 - Point Cloud Data file format",
                "VERSION 0.7",
                "FIELDS x y z r g b",
                "SIZE 4 4 4 1 1 1",
                "TYPE F F F U U U",
                "COUNT 1 1 1 1 1 1",
                "WIDTH 3",
                "HEIGHT 1",
                "POINTS 3",
                "DATA ascii",
                "1 2 3 10 20 30",
                "nan 4 5 40 50 60",
                "-1 -2 -3 70 80 90",
            ]
        )
        + "\n",
        encoding="ascii",
    )

    frame = read_point_cloud_frame(path)

    assert frame.points == [[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]]
    assert frame.colors == [[10, 20, 30], [70, 80, 90]]


def test_read_text_point_cloud_formats(tmp_path: Path) -> None:
    xyz_path = tmp_path / "cloud.xyz"
    xyz_path.write_text(
        "# comment\n"
        "0 1 2 255 0 0\n"
        "nan 1 2\n"
        "3,4,5,0,255,0\n"
        "invalid row\n",
        encoding="utf-8",
    )
    pts_path = tmp_path / "cloud.pts"
    pts_path.write_text("3\n1 2 3 9\n4 5 6 8\ninf 1 2\n", encoding="utf-8")
    asc_path = tmp_path / "cloud.asc"
    asc_path.write_text("; comment\n-1 -2 -3\n7 8 9 intensity\n", encoding="utf-8")

    assert read_point_cloud_points(xyz_path) == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]
    assert read_point_cloud_points(pts_path) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    assert read_point_cloud_points(asc_path) == [[-1.0, -2.0, -3.0], [7.0, 8.0, 9.0]]

    source = PointCloudAdapter().inspect(str(xyz_path))
    preview = PointCloudAdapter().preview(source, "stream_point_cloud")
    assert detect_source_type(xyz_path) == "point_cloud"
    assert source.metadata["formats"] == ["xyz"]
    assert source.metadata["sampled"][0]["point_count"] == 2
    assert preview["rows"][0]["bounds"] == {"min": [0.0, 1.0, 2.0], "max": [3.0, 4.0, 5.0]}


def test_read_xyzrgb_frame_preserves_colors(tmp_path: Path) -> None:
    path = tmp_path / "cloud.xyzrgb"
    path.write_text(
        "0 1 2 255 0 0\n"
        "bad row\n"
        "3 4 5 0 255 0\n",
        encoding="utf-8",
    )

    frame = read_point_cloud_frame(path)

    assert frame.points == [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]]
    assert frame.colors == [[255, 0, 0], [0, 255, 0]]


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


def _write_binary_ply(
    path: Path,
    points: list[tuple[int, float, float, float, int, int, int]],
) -> None:
    header = "\n".join(
        [
            "ply",
            "format binary_little_endian 1.0",
            f"element vertex {len(points)}",
            "property ushort intensity",
            "property float x",
            "property float y",
            "property float z",
            "property uchar red",
            "property uchar green",
            "property uchar blue",
            "end_header",
            "",
        ]
    ).encode("ascii")
    payload = b"".join(struct.pack("<HfffBBB", *point) for point in points)
    path.write_bytes(header + payload)


def _write_binary_pcd(path: Path, points: list[tuple[int, float, float, float]]) -> None:
    header = "\n".join(
        [
            "# .PCD v0.7 - Point Cloud Data file format",
            "VERSION 0.7",
            "FIELDS intensity x y z",
            "SIZE 2 4 4 4",
            "TYPE U F F F",
            "COUNT 1 1 1 1",
            f"WIDTH {len(points)}",
            "HEIGHT 1",
            f"POINTS {len(points)}",
            "DATA binary",
            "",
        ]
    ).encode("ascii")
    payload = b"".join(struct.pack("<Hfff", *point) for point in points)
    path.write_bytes(header + payload)
