from __future__ import annotations

from pathlib import Path

from datascope_core.models import MappingSpec, StreamInfo


SENSOR_MONITOR_TEMPLATE = {
    "id": "sensor_monitor",
    "name": "Sensor Monitor",
    "version": "1.0.0",
    "app_id": "datascope.sensor_monitor.v1",
}

CV_DETECTION_TEMPLATE = {
    "id": "cv_detection",
    "name": "CV Detection",
    "version": "1.0.0",
    "app_id": "datascope.cv_detection.v1",
}

ROBOTICS_DEBUG_TEMPLATE = {
    "id": "robotics_debug",
    "name": "Robotics Debug",
    "version": "1.0.0",
    "app_id": "datascope.robotics_debug.v1",
}

EXPERIMENT_COMPARE_TEMPLATE = {
    "id": "experiment_compare",
    "name": "Experiment Compare",
    "version": "1.0.0",
    "app_id": "datascope.experiment_compare.v1",
}


def match_templates(streams: list[StreamInfo]) -> list[dict[str, float | str]]:
    semantic_types = {stream.semantic_type for stream in streams}
    matches: list[dict[str, float | str]] = []

    cv_score = 0.0
    if "image" in semantic_types:
        cv_score += 0.55
    if "boxes2d" in semantic_types:
        cv_score += 0.35
    if "points2d" in semantic_types or "segmentation" in semantic_types:
        cv_score += 0.15
    if any(stream.metadata.get("role") == "pred_scores" for stream in streams):
        cv_score += 0.1
    if cv_score:
        matches.append({"template_id": "cv_detection", "name": "CV Detection", "score": round(cv_score, 3)})

    robotics_score = 0.0
    if "mcap" in semantic_types:
        robotics_score += 0.45
    if "points3d" in semantic_types:
        robotics_score += 0.25
    if "transform3d" in semantic_types:
        robotics_score += 0.2
    if "trajectory3d" in semantic_types:
        robotics_score += 0.1
    if "asset3d" in semantic_types:
        robotics_score += 0.1
    if any(stream.metadata.get("message_encoding") for stream in streams):
        robotics_score += 0.6
    if robotics_score:
        matches.append(
            {
                "template_id": "robotics_debug",
                "name": "Robotics Debug",
                "score": round(min(robotics_score, 1.0), 3),
            }
        )

    sensor_score = 0.0
    if "scalar" in semantic_types or "scalar_group" in semantic_types:
        sensor_score += 0.45
    if "state" in semantic_types:
        sensor_score += 0.25
    if "text_log" in semantic_types:
        sensor_score += 0.2
    if streams:
        sensor_score += 0.1
    matches.append({"template_id": "sensor_monitor", "name": "Sensor Monitor", "score": round(sensor_score, 3)})
    return sorted(matches, key=lambda match: float(match["score"]), reverse=True)


def save_blueprint(spec: MappingSpec, template_id: str, path: str | Path) -> None:
    if template_id == "sensor_monitor":
        save_sensor_monitor_blueprint(spec, path)
        return
    if template_id == "cv_detection":
        save_cv_detection_blueprint(spec, path)
        return
    if template_id == "robotics_debug":
        save_robotics_debug_blueprint(spec, path)
        return
    if template_id == "experiment_compare":
        save_experiment_compare_blueprint(spec, path)
        return
    save_generic_blueprint(spec, path)


def save_sensor_monitor_blueprint(spec: MappingSpec, path: str | Path) -> None:
    import rerun.blueprint as rrb

    scalar_paths = [
        stream["entity_path"]
        for stream in spec.streams
        if stream.get("enabled", True)
        and stream.get("entity_path")
        and stream.get("semantic_type") in {"scalar", "scalar_group"}
    ]
    state_paths = [
        stream["entity_path"]
        for stream in spec.streams
        if stream.get("enabled", True)
        and stream.get("entity_path")
        and stream.get("semantic_type") == "state"
    ]
    log_paths = [
        stream["entity_path"]
        for stream in spec.streams
        if stream.get("enabled", True)
        and stream.get("entity_path")
        and stream.get("semantic_type") == "text_log"
    ]

    views = []
    if scalar_paths:
        views.append(rrb.TimeSeriesView(name="Metrics", origin="/metrics"))
    if state_paths:
        views.append(_state_view(rrb, name="States", origin="/states"))
    if log_paths:
        views.append(rrb.TextLogView(name="Logs", origin="/logs"))
    if not views:
        views.append(rrb.TimeSeriesView(name="Data", origin="/"))

    blueprint = rrb.Blueprint(rrb.Grid(*views), collapse_panels=True)
    _save_blueprint(blueprint, spec.app_id, path)


def save_cv_detection_blueprint(spec: MappingSpec, path: str | Path) -> None:
    import rerun.blueprint as rrb

    has_scores = any(
        stream.get("enabled", True) and stream.get("role") == "pred_scores"
        for stream in spec.streams
    )
    views = [
        rrb.Spatial2DView(
            name="Image + Detections",
            origin="/camera",
            contents=["/camera/image", "/camera/gt/**", "/camera/pred/**"],
        )
    ]
    if has_scores:
        views.append(rrb.TimeSeriesView(name="Prediction Scores", origin="/camera/pred/scores"))

    blueprint = rrb.Blueprint(rrb.Grid(*views, grid_columns=1), collapse_panels=True)
    _save_blueprint(blueprint, spec.app_id, path)


def save_robotics_debug_blueprint(spec: MappingSpec, path: str | Path) -> None:
    import rerun.blueprint as rrb

    semantic_types = {
        stream.get("semantic_type")
        for stream in spec.streams
        if stream.get("enabled", True)
    }
    views = [
        rrb.Spatial3DView(
            name="World",
            origin="/",
            contents=["/world/**", "/sensors/lidar/**", "/sensors/**"],
        )
    ]
    if "image" in semantic_types:
        views.append(rrb.Spatial2DView(name="Camera", origin="/sensors/camera"))
    if {"scalar", "scalar_group"} & semantic_types:
        views.append(rrb.TimeSeriesView(name="Robot Metrics", origin="/metrics"))
    if "text_log" in semantic_types:
        views.append(rrb.TextLogView(name="Diagnostics", origin="/logs"))

    blueprint = rrb.Blueprint(rrb.Grid(*views, grid_columns=2), collapse_panels=True)
    _save_blueprint(blueprint, spec.app_id, path)


def save_experiment_compare_blueprint(spec: MappingSpec, path: str | Path) -> None:
    import rerun.blueprint as rrb

    blueprint = rrb.Blueprint(
        rrb.Grid(
            rrb.TimeSeriesView(name="Comparison Metrics", origin="/metrics"),
            _state_view(rrb, name="State Comparison", origin="/states"),
            grid_columns=1,
        ),
        collapse_panels=True,
    )
    _save_blueprint(blueprint, spec.app_id, path)


def save_generic_blueprint(spec: MappingSpec, path: str | Path) -> None:
    import rerun.blueprint as rrb

    blueprint = rrb.Blueprint(rrb.Grid(rrb.TimeSeriesView(name="Data", origin="/")), collapse_panels=True)
    _save_blueprint(blueprint, spec.app_id, path)


def _state_view(rrb, *, name: str, origin: str):
    import rerun as rr

    view_type = rrb.TimeSeriesView if hasattr(rr, "StateChange") else rrb.TextLogView
    return view_type(name=name, origin=origin)


def _save_blueprint(blueprint, app_id: str, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    blueprint.save(app_id, str(output))
