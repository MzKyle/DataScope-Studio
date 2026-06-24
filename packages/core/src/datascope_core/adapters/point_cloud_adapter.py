from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO

from datascope_core.inference import safe_slug
from datascope_core.models import (
    ConvertRequest,
    MappingSpec,
    POINT_CLOUD_EXTENSIONS,
    SourceInfo,
    StreamInfo,
)


TEXT_POINT_CLOUD_EXTENSIONS = {".xyz", ".xyzn", ".xyzrgb", ".pts", ".asc"}


@dataclass(slots=True)
class PointCloudStats:
    path: Path
    file_format: str
    point_count: int
    bounds: dict[str, list[float]] | None = None
    warning: str | None = None


@dataclass(slots=True)
class PcdHeader:
    fields: list[str]
    sizes: list[int]
    types: list[str]
    counts: list[int]
    point_count: int | None
    data: str


@dataclass(slots=True)
class PlyProperty:
    name: str
    data_type: str
    is_list: bool = False


@dataclass(slots=True)
class PlyHeader:
    encoding: str
    vertex_count: int
    vertex_properties: list[PlyProperty]


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
                if request.cancel_check is not None:
                    request.cancel_check()
                points = read_point_cloud_points(cloud)
                if not points:
                    continue
                rec.set_time("time", duration=_cloud_time(index, cloud))
                rec.log(entity_path, rr.Points3D(points))
                if request.progress_callback is not None:
                    request.progress_callback(
                        "converting",
                        (index + 1) / max(len(clouds), 1),
                    )

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
    if suffix in TEXT_POINT_CLOUD_EXTENSIONS:
        return _read_text_point_cloud_points(cloud_path)
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
        with open(path, "rb") as handle:
            return _read_ply_header(handle, path.name).vertex_count
    if suffix == ".pcd":
        with open(path, "rb") as handle:
            header = _read_pcd_header(handle)
            if header.point_count is not None:
                return header.point_count
        return len(_read_pcd_points(path))
    if suffix in {".npy", ".npz"}:
        return len(_read_numpy_points(path))
    if suffix in TEXT_POINT_CLOUD_EXTENSIONS:
        return len(_read_text_point_cloud_points(path))
    return 0


def _read_ply_points(path: Path) -> list[list[float]]:
    with open(path, "rb") as handle:
        header = _read_ply_header(handle, path.name)
        if header.encoding == "ascii":
            return _read_ascii_ply_points(handle, header)
        if header.encoding == "binary_little_endian":
            return _read_binary_little_endian_ply_points(handle, header, path.name)
        raise ValueError(f"Unsupported PLY encoding '{header.encoding}': {path.name}")


def _read_ply_header(handle: BinaryIO, filename: str) -> PlyHeader:
    if handle.readline().strip() != b"ply":
        raise ValueError(f"Invalid PLY header: {filename}")

    encoding = ""
    vertex_count: int | None = None
    vertex_properties: list[PlyProperty] = []
    current_element: str | None = None
    nonempty_element_before_vertex = False
    while True:
        raw_line = handle.readline()
        if not raw_line:
            raise ValueError(f"PLY header missing end_header: {filename}")
        try:
            parts = raw_line.decode("ascii").strip().split()
        except UnicodeDecodeError as exc:
            raise ValueError(f"PLY header must be ASCII: {filename}") from exc
        if not parts or parts[0] in {"comment", "obj_info"}:
            continue
        if parts[0] == "end_header":
            break
        if parts[0] == "format":
            if len(parts) != 3 or parts[2] != "1.0":
                raise ValueError(f"Unsupported PLY format declaration: {filename}")
            encoding = parts[1].lower()
            continue
        if parts[0] == "element":
            if len(parts) != 3:
                raise ValueError(f"Invalid PLY element declaration: {filename}")
            try:
                element_count = int(parts[2])
            except ValueError as exc:
                raise ValueError(f"PLY element count must be an integer: {filename}") from exc
            if element_count < 0:
                raise ValueError(f"PLY element count must not be negative: {filename}")
            current_element = parts[1].lower()
            if current_element == "vertex":
                vertex_count = element_count
            elif vertex_count is None and element_count:
                nonempty_element_before_vertex = True
            continue
        if parts[0] == "property" and current_element == "vertex":
            if len(parts) == 3:
                vertex_properties.append(
                    PlyProperty(name=parts[2].lower(), data_type=parts[1].lower())
                )
            elif len(parts) == 5 and parts[1].lower() == "list":
                vertex_properties.append(
                    PlyProperty(name=parts[4].lower(), data_type=parts[3].lower(), is_list=True)
                )
            else:
                raise ValueError(f"Invalid PLY vertex property declaration: {filename}")

    if not encoding:
        raise ValueError(f"PLY header missing format: {filename}")
    if encoding not in {"ascii", "binary_little_endian", "binary_big_endian"}:
        raise ValueError(f"Unsupported PLY encoding '{encoding}': {filename}")
    if vertex_count is None:
        raise ValueError("PLY header missing element vertex")
    if nonempty_element_before_vertex:
        raise ValueError(f"PLY vertex element must be the first non-empty element: {filename}")
    if any(prop.is_list for prop in vertex_properties):
        raise ValueError(f"PLY list properties on vertices are not supported: {filename}")
    _ply_xyz_property_indices(vertex_properties)
    return PlyHeader(
        encoding=encoding,
        vertex_count=vertex_count,
        vertex_properties=vertex_properties,
    )


def _ply_xyz_property_indices(properties: list[PlyProperty]) -> tuple[int, int, int]:
    names = [prop.name for prop in properties]
    try:
        return (names.index("x"), names.index("y"), names.index("z"))
    except ValueError as exc:
        raise ValueError("PLY vertex properties must include x, y, z") from exc


def _read_ascii_ply_points(handle: BinaryIO, header: PlyHeader) -> list[list[float]]:
    xyz_indices = _ply_xyz_property_indices(header.vertex_properties)
    points: list[list[float]] = []
    for _ in range(header.vertex_count):
        raw_line = handle.readline()
        if not raw_line:
            break
        values = raw_line.split()
        if len(values) <= max(xyz_indices):
            continue
        point = _finite_xyz(values[index] for index in xyz_indices)
        if point is not None:
            points.append(point)
    return points


def _read_binary_little_endian_ply_points(
    handle: BinaryIO,
    header: PlyHeader,
    filename: str,
) -> list[list[float]]:
    import numpy as np

    property_dtypes = [_ply_numpy_dtype(prop.data_type) for prop in header.vertex_properties]
    property_offsets: list[int] = []
    stride = 0
    for dtype in property_dtypes:
        property_offsets.append(stride)
        stride += dtype.itemsize
    if stride <= 0:
        raise ValueError(f"PLY binary vertex stride must be positive: {filename}")

    expected_size = header.vertex_count * stride
    payload = handle.read(expected_size)
    if len(payload) < expected_size:
        raise ValueError(
            f"PLY binary payload is truncated: expected {expected_size} bytes, "
            f"found {len(payload)} in {filename}"
        )

    xyz_indices = _ply_xyz_property_indices(header.vertex_properties)
    coordinates = np.column_stack(
        [
            np.ndarray(
                shape=(header.vertex_count,),
                dtype=property_dtypes[index],
                buffer=payload,
                offset=property_offsets[index],
                strides=(stride,),
            )
            for index in xyz_indices
        ]
    )
    coordinates = coordinates[np.isfinite(coordinates).all(axis=1)]
    return coordinates.astype(float, copy=False).tolist()


def _ply_numpy_dtype(data_type: str):
    import numpy as np

    dtypes = {
        "char": "<i1",
        "int8": "<i1",
        "uchar": "<u1",
        "uint8": "<u1",
        "short": "<i2",
        "int16": "<i2",
        "ushort": "<u2",
        "uint16": "<u2",
        "int": "<i4",
        "int32": "<i4",
        "uint": "<u4",
        "uint32": "<u4",
        "float": "<f4",
        "float32": "<f4",
        "double": "<f8",
        "float64": "<f8",
    }
    try:
        return np.dtype(dtypes[data_type])
    except KeyError as exc:
        raise ValueError(f"Unsupported PLY property type: {data_type}") from exc


def _read_pcd_points(path: Path) -> list[list[float]]:
    with open(path, "rb") as handle:
        header = _read_pcd_header(handle)
        if header.data == "ascii":
            return _read_ascii_pcd_points(handle, header)
        if header.data == "binary":
            return _read_binary_pcd_points(handle, header, path.name)
        raise ValueError(f"Unsupported PCD DATA encoding '{header.data}': {path.name}")


def _read_pcd_header(handle: BinaryIO) -> PcdHeader:
    values: dict[str, list[str]] = {}
    while True:
        raw_line = handle.readline()
        if not raw_line:
            raise ValueError("PCD header missing DATA")
        try:
            parts = raw_line.decode("ascii").strip().split()
        except UnicodeDecodeError as exc:
            raise ValueError("PCD header must be ASCII") from exc
        if not parts or parts[0].startswith("#"):
            continue
        key = parts[0].upper()
        values[key] = parts[1:]
        if key == "DATA":
            break

    fields = values.get("FIELDS", [])
    if not fields:
        raise ValueError("PCD header missing FIELDS")
    try:
        sizes = [int(value) for value in values["SIZE"]]
        types = [value.upper() for value in values["TYPE"]]
        counts = [int(value) for value in values.get("COUNT", ["1"] * len(fields))]
    except KeyError as exc:
        raise ValueError(f"PCD header missing {exc.args[0]}") from exc
    except ValueError as exc:
        raise ValueError("PCD SIZE and COUNT values must be integers") from exc

    if not (len(fields) == len(sizes) == len(types) == len(counts)):
        raise ValueError("PCD FIELDS, SIZE, TYPE, and COUNT lengths must match")
    if any(size <= 0 for size in sizes) or any(count <= 0 for count in counts):
        raise ValueError("PCD SIZE and COUNT values must be positive")

    point_count = _pcd_header_point_count(values)
    data_values = values.get("DATA", [])
    data = data_values[0].lower() if data_values else ""
    if not data:
        raise ValueError("PCD header DATA encoding is missing")
    return PcdHeader(
        fields=fields,
        sizes=sizes,
        types=types,
        counts=counts,
        point_count=point_count,
        data=data,
    )


def _pcd_header_point_count(values: dict[str, list[str]]) -> int | None:
    try:
        if values.get("POINTS"):
            return int(values["POINTS"][0])
        if values.get("WIDTH") and values.get("HEIGHT"):
            return int(values["WIDTH"][0]) * int(values["HEIGHT"][0])
    except ValueError as exc:
        raise ValueError("PCD POINTS, WIDTH, and HEIGHT values must be integers") from exc
    return None


def _pcd_xyz_field_indices(header: PcdHeader) -> tuple[int, int, int]:
    normalized_fields = [field.lower() for field in header.fields]
    try:
        return (
            normalized_fields.index("x"),
            normalized_fields.index("y"),
            normalized_fields.index("z"),
        )
    except ValueError as exc:
        raise ValueError("PCD fields must include x, y, z") from exc


def _read_ascii_pcd_points(handle: BinaryIO, header: PcdHeader) -> list[list[float]]:
    xyz_fields = _pcd_xyz_field_indices(header)
    scalar_offsets: list[int] = []
    offset = 0
    for count in header.counts:
        scalar_offsets.append(offset)
        offset += count
    xyz_indices = tuple(scalar_offsets[index] for index in xyz_fields)

    points: list[list[float]] = []
    for raw_line in handle:
        values = raw_line.split()
        if len(values) <= max(xyz_indices):
            continue
        point = _finite_xyz(values[index] for index in xyz_indices)
        if point is not None:
            points.append(point)
    return points


def _read_binary_pcd_points(
    handle: BinaryIO,
    header: PcdHeader,
    filename: str,
) -> list[list[float]]:
    xyz_fields = _pcd_xyz_field_indices(header)
    byte_offsets: list[int] = []
    stride = 0
    for size, count in zip(header.sizes, header.counts):
        byte_offsets.append(stride)
        stride += size * count
    if stride <= 0:
        raise ValueError("PCD binary point stride must be positive")

    coordinate_formats = [
        _pcd_struct_format(header.types[index], header.sizes[index]) for index in xyz_fields
    ]
    coordinate_offsets = [byte_offsets[index] for index in xyz_fields]
    payload = handle.read()
    point_count = header.point_count
    if point_count is None:
        point_count, remainder = divmod(len(payload), stride)
        if remainder:
            raise ValueError(f"PCD binary payload is not aligned to point size: {filename}")
    expected_size = point_count * stride
    if len(payload) < expected_size:
        raise ValueError(
            f"PCD binary payload is truncated: expected {expected_size} bytes, "
            f"found {len(payload)} in {filename}"
        )

    points: list[list[float]] = []
    for point_index in range(point_count):
        base_offset = point_index * stride
        coordinates = [
            struct.unpack_from(f"<{format_code}", payload, base_offset + coordinate_offset)[0]
            for format_code, coordinate_offset in zip(coordinate_formats, coordinate_offsets)
        ]
        point = _finite_xyz(coordinates)
        if point is not None:
            points.append(point)
    return points


def _pcd_struct_format(field_type: str, size: int) -> str:
    formats = {
        ("F", 4): "f",
        ("F", 8): "d",
        ("I", 1): "b",
        ("I", 2): "h",
        ("I", 4): "i",
        ("I", 8): "q",
        ("U", 1): "B",
        ("U", 2): "H",
        ("U", 4): "I",
        ("U", 8): "Q",
    }
    try:
        return formats[(field_type, size)]
    except KeyError as exc:
        raise ValueError(f"Unsupported PCD field type/size: {field_type}{size}") from exc


def _read_text_point_cloud_points(path: Path) -> list[list[float]]:
    points: list[list[float]] = []
    saw_data_line = False
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(("#", "//", ";")):
                continue
            values = line.replace(",", " ").split()
            if path.suffix.lower() == ".pts" and not saw_data_line and _is_point_count_header(values):
                saw_data_line = True
                continue
            saw_data_line = True
            if len(values) < 3:
                continue
            try:
                point = _finite_xyz(values[:3])
            except ValueError:
                continue
            if point is not None:
                points.append(point)
    return points


def _is_point_count_header(values: list[str]) -> bool:
    if len(values) != 1:
        return False
    try:
        return int(values[0]) >= 0
    except ValueError:
        return False


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
