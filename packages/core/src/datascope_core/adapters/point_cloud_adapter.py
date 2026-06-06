from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from datascope_core.inference import safe_slug
from datascope_core.models import (
    ConvertRequest,
    MappingSpec,
    POINT_CLOUD_EXTENSIONS,
    SourceInfo,
    StreamInfo,
)


@dataclass(slots=True)
class PointCloudStats:
    path: Path
    file_format: str
    point_count: int
    bounds: dict[str, list[float]] | None = None
    warning: str | None = None


class PointCloudAdapter:
    adapter_id = "point_cloud"
    display_name = "3D Point Cloud"
    supported_extensions = sorted(POINT_CLOUD_EXTENSIONS)

    def inspect(self, path: str, source_id: str | None = None) -> SourceInfo:
        source_path = Path(path)
        clouds = supported_point_cloud_paths(source_path)
        if not clouds:
            raise ValueError(f"No supported point cloud files found: {path}")

        sampled = [_read_point_cloud_stats(item, include_bounds=True) for item in clouds[: min(10, len(clouds))]]
        point_counts = [item.point_count for item in sampled if item.point_count >= 0]
        times = [_cloud_time(index, item) for index, item in enumerate(clouds)]
        return SourceInfo(
            source_id=source_id or f"source_{safe_slug(source_path.stem or source_path.name)}",
            source_type="point_cloud",
            path=str(source_path),
            metadata={
                "point_cloud_count": len(clouds),
                "files": [_relative_or_name(source_path, item) for item in clouds],
                "formats": sorted({item.suffix.lower().lstrip(".") for item in clouds}),
                "sampled": [
                    {
                        **asdict(item),
                        "path": _relative_or_name(source_path, item.path),
                    }
                    for item in sampled
                ],
                "sampled_point_count_min": min(point_counts) if point_counts else 0,
                "sampled_point_count_max": max(point_counts) if point_counts else 0,
                "sampled_point_count_mean": (
                    sum(point_counts) / len(point_counts) if point_counts else 0
                ),
                "start_time": min(times) if times else None,
                "end_time": max(times) if times else None,
                "size_bytes": sum(item.stat().st_size for item in clouds),
            },
        )

    def infer_streams(self, source: SourceInfo) -> list[StreamInfo]:
        return [
            StreamInfo(
                stream_id="stream_point_cloud",
                name="point_cloud",
                semantic_type="points3d",
                fields=["points"],
                time_key="time",
                confidence=0.96,
                metadata={
                    "role": "point_cloud",
                    "file_count": source.metadata.get("point_cloud_count", 0),
                    "formats": source.metadata.get("formats", []),
                },
            )
        ]

    def preview(self, source: SourceInfo, stream_id: str, limit: int = 100) -> dict[str, Any]:
        source_path = Path(source.path)
        clouds = supported_point_cloud_paths(source_path)
        rows = []
        for index, cloud in enumerate(clouds[:limit]):
            stats = _read_point_cloud_stats(cloud, include_bounds=True)
            rows.append(
                {
                    "file": _relative_or_name(source_path, cloud),
                    "format": stats.file_format,
                    "point_count": stats.point_count,
                    "time": _cloud_time(index, cloud),
                    "bounds": stats.bounds,
                    "warning": stats.warning or "",
                }
            )
        return {
            "source_id": source.source_id,
            "stream_id": stream_id,
            "columns": ["file", "format", "point_count", "time", "bounds", "warning"],
            "rows": rows,
        }

    def convert(self, request: ConvertRequest) -> None:
        import rerun as rr

        source_path = Path(request.source.path)
        clouds = supported_point_cloud_paths(source_path)
        if not clouds:
            raise ValueError(f"No supported point cloud files found: {request.source.path}")

        entity_path = _entity_path(request.mappings, "/sensors/lidar/points")
        Path(request.output_rrd).parent.mkdir(parents=True, exist_ok=True)
        with rr.RecordingStream(
            request.app_id,
            recording_id=request.recording_id,
            send_properties=False,
        ) as rec:
            rec.save(request.output_rrd)
            rec.send_recording_name(request.recording_id)
            for index, cloud in enumerate(clouds):
                points = read_point_cloud_points(cloud)
                if not points:
                    continue
                rec.set_time("time", duration=_cloud_time(index, cloud))
                rec.log(entity_path, rr.Points3D(points))

    def validate_mapping(
        self,
        source: SourceInfo,
        spec: MappingSpec,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        sampled = source.metadata.get("sampled", [])
        issues = [
            {
                "severity": "warning",
                "code": "point_cloud_sample_warning",
                "message": str(item["warning"]),
                "stream_id": "stream_point_cloud",
                "rule_key": None,
                "field": item.get("path"),
            }
            for item in sampled
            if item.get("warning")
        ]
        if sampled and not any(int(item.get("point_count") or 0) > 0 for item in sampled):
            issues.append(
                {
                    "severity": "error",
                    "code": "point_cloud_coordinates_missing",
                    "message": "Sampled point clouds do not contain readable x/y/z coordinates.",
                    "stream_id": "stream_point_cloud",
                    "rule_key": None,
                    "field": "points",
                }
            )
        return issues


def supported_point_cloud_paths(root: str | Path) -> list[Path]:
    root_path = Path(root)
    if root_path.is_file():
        return [root_path] if root_path.suffix.lower() in POINT_CLOUD_EXTENSIONS else []
    if not root_path.is_dir():
        return []
    return sorted(
        child
        for child in root_path.rglob("*")
        if child.is_file() and child.suffix.lower() in POINT_CLOUD_EXTENSIONS
    )


def read_point_cloud_points(path: str | Path) -> list[list[float]]:
    cloud_path = Path(path)
    suffix = cloud_path.suffix.lower()
    if suffix == ".ply":
        return _read_ply_points(cloud_path)
    if suffix == ".pcd":
        return _read_pcd_points(cloud_path)
    if suffix in {".npy", ".npz"}:
        return _read_numpy_points(cloud_path)
    raise ValueError(f"Unsupported point cloud file: {path}")


def _read_point_cloud_stats(path: Path, include_bounds: bool = False) -> PointCloudStats:
    try:
        point_count = _point_count(path)
        bounds = _bounds(read_point_cloud_points(path)) if include_bounds else None
        return PointCloudStats(path=path, file_format=path.suffix.lower().lstrip("."), point_count=point_count, bounds=bounds)
    except Exception as exc:
        return PointCloudStats(
            path=path,
            file_format=path.suffix.lower().lstrip("."),
            point_count=0,
            bounds=None,
            warning=str(exc),
        )


def _point_count(path: Path) -> int:
    suffix = path.suffix.lower()
    if suffix == ".ply":
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("element vertex "):
                    return int(line.split()[-1])
                if line == "end_header":
                    break
        return len(_read_ply_points(path))
    if suffix == ".pcd":
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            width = height = None
            for line in handle:
                parts = line.strip().split()
                if not parts:
                    continue
                key = parts[0].upper()
                if key == "POINTS" and len(parts) > 1:
                    return int(parts[1])
                if key == "WIDTH" and len(parts) > 1:
                    width = int(parts[1])
                elif key == "HEIGHT" and len(parts) > 1:
                    height = int(parts[1])
                elif key == "DATA":
                    break
            if width is not None and height is not None:
                return width * height
        return len(_read_pcd_points(path))
    if suffix in {".npy", ".npz"}:
        return len(_read_numpy_points(path))
    return 0


def _read_ply_points(path: Path) -> list[list[float]]:
    header: list[str] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            header.append(stripped)
            if stripped == "end_header":
                break
        if not any(line == "format ascii 1.0" for line in header):
            raise ValueError(f"Only ASCII PLY is supported: {path.name}")
        vertex_count = _ply_vertex_count(header)
        xyz_indices = _ply_xyz_indices(header)
        points: list[list[float]] = []
        for _ in range(vertex_count):
            line = handle.readline()
            if not line:
                break
            values = line.strip().split()
            if len(values) <= max(xyz_indices):
                continue
            point = _finite_xyz(values[index] for index in xyz_indices)
            if point is not None:
                points.append(point)
    return points


def _ply_vertex_count(header: list[str]) -> int:
    for line in header:
        if line.startswith("element vertex "):
            return int(line.split()[-1])
    raise ValueError("PLY header missing element vertex")


def _ply_xyz_indices(header: list[str]) -> tuple[int, int, int]:
    in_vertex = False
    properties: list[str] = []
    for line in header:
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "element":
            if parts[1] == "vertex":
                in_vertex = True
                continue
            if in_vertex:
                break
        if in_vertex and len(parts) >= 3 and parts[0] == "property":
            properties.append(parts[-1])
    try:
        return (properties.index("x"), properties.index("y"), properties.index("z"))
    except ValueError as exc:
        raise ValueError("PLY vertex properties must include x, y, z") from exc


def _read_pcd_points(path: Path) -> list[list[float]]:
    fields: list[str] = []
    data = ""
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            parts = stripped.split()
            if not parts:
                continue
            key = parts[0].upper()
            if key == "FIELDS":
                fields = parts[1:]
            elif key == "DATA":
                data = parts[1].lower() if len(parts) > 1 else ""
                break
        if data != "ascii":
            raise ValueError(f"Only ASCII PCD is supported: {path.name}")
        try:
            xyz_indices = (fields.index("x"), fields.index("y"), fields.index("z"))
        except ValueError as exc:
            raise ValueError("PCD fields must include x, y, z") from exc
        points = []
        for line in handle:
            values = line.strip().split()
            if len(values) <= max(xyz_indices):
                continue
            point = _finite_xyz(values[index] for index in xyz_indices)
            if point is not None:
                points.append(point)
    return points


def _read_numpy_points(path: Path) -> list[list[float]]:
    import numpy as np

    if path.suffix.lower() == ".npy":
        array = np.load(path)
    else:
        with np.load(path) as data:
            array = _npz_points_array(data)
    array = np.asarray(array)
    if array.ndim > 2:
        array = array.reshape(-1, array.shape[-1])
    if array.ndim != 2 or array.shape[1] < 3:
        raise ValueError(f"Point cloud array must have shape Nx3 or NxM: {path.name}")
    array = array[:, :3]
    array = array[np.isfinite(array).all(axis=1)]
    return array.astype(float).tolist()


def _npz_points_array(data) -> Any:
    for key in ("points", "point_cloud", "xyz", "positions"):
        if key in data:
            return data[key]
    for key in data.files:
        array = data[key]
        if getattr(array, "ndim", 0) >= 2 and array.shape[-1] >= 3:
            return array
    raise ValueError("NPZ file must contain a point cloud array")


def _finite_xyz(values) -> list[float] | None:
    coordinates = []
    for value in values:
        coordinate = float(value)
        if coordinate != coordinate or coordinate in (float("inf"), float("-inf")):
            return None
        coordinates.append(coordinate)
    return coordinates


def _bounds(points: list[list[float]]) -> dict[str, list[float]] | None:
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    zs = [point[2] for point in points]
    return {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
    }


def _cloud_time(index: int, path: Path) -> float:
    stem = path.stem
    try:
        value = float(stem)
    except ValueError:
        return float(index)
    if len(stem) >= 16:
        return value / 1_000_000_000.0
    if len(stem) >= 13:
        return value / 1000.0
    return value


def _relative_or_name(root: Path, path: Path) -> str:
    if root.is_file():
        return path.name
    try:
        return str(path.relative_to(root))
    except ValueError:
        return path.name


def _entity_path(mappings: list[dict[str, Any]], fallback: str) -> str:
    for mapping in mappings:
        if mapping.get("semantic_type") == "points3d" or mapping.get("role") == "point_cloud":
            return str(mapping.get("entity_path") or fallback)
    return fallback
