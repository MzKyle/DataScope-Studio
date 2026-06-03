import pytest

from datascope_core.cv_schema import parse_cv_sidecar


def test_parse_cv_sidecar_accepts_datascope_boxes() -> None:
    sidecar = parse_cv_sidecar(
        {
            "classes": [{"id": 1, "label": "person", "color": [255, 80, 80]}],
            "frames": [
                {
                    "image": "images/000001.png",
                    "time": 0.0,
                    "boxes": [{"bbox": [10, 20, 30, 40], "class_id": 1, "score": 0.9}],
                }
            ],
        },
        "annotations.json",
        "annotations",
    )

    assert sidecar.frames[0].boxes[0].bbox == [10.0, 20.0, 30.0, 40.0]
    assert sidecar.classes[0].label == "person"


def test_parse_cv_sidecar_rejects_invalid_bbox_shape() -> None:
    with pytest.raises(ValueError, match="bbox must be"):
        parse_cv_sidecar(
            {
                "frames": [
                    {
                        "image": "images/000001.png",
                        "boxes": [{"bbox": [10, 20, 30]}],
                    }
                ]
            },
            "annotations.json",
            "annotations",
        )

