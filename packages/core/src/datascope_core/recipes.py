from __future__ import annotations

from copy import deepcopy
from typing import Any


BUILTIN_RECIPES: list[dict[str, Any]] = [
    {
        "id": "sensor_csv_health",
        "name": "Sensor CSV Health",
        "version": "0.1.0",
        "source_family": "tabular",
        "visual_template_id": "sensor_monitor",
        "mapping_template_id": None,
        "diagnostic_preset": "balanced",
        "recommended_queries": ["low_battery", "find_errors", "state_duration"],
        "description": "Inspect sensor tables, scalar trends, states, logs, and general data quality.",
    },
    {
        "id": "robot_bag_health",
        "name": "Robot Bag Health",
        "version": "0.1.0",
        "source_family": "mcap",
        "visual_template_id": "robotics_debug",
        "mapping_template_id": None,
        "diagnostic_preset": "balanced",
        "recommended_queries": ["topic_summary", "time_sync", "find_errors"],
        "description": "Review robotics recordings for topic coverage, convertibility, timing, and logs.",
    },
    {
        "id": "cv_detection_review",
        "name": "CV Detection Review",
        "version": "0.1.0",
        "source_family": "image_folder",
        "visual_template_id": "cv_detection",
        "mapping_template_id": None,
        "diagnostic_preset": "balanced",
        "recommended_queries": ["detection_failure"],
        "description": "Review image folders, annotations, predictions, and low-confidence detections.",
    },
    {
        "id": "point_cloud_review",
        "name": "Point Cloud Run Review",
        "version": "0.1.0",
        "source_family": "point_cloud",
        "visual_template_id": "robotics_debug",
        "mapping_template_id": None,
        "diagnostic_preset": "balanced",
        "recommended_queries": [],
        "description": "Inspect point-cloud sources with default spatial visualization and data checks.",
    },
]


def list_builtin_recipes() -> list[dict[str, Any]]:
    return deepcopy(BUILTIN_RECIPES)
