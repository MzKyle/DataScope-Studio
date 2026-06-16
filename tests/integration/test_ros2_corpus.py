from __future__ import annotations

import os
from pathlib import Path

import pytest

from datascope_core.workspace import Workspace


def test_external_humble_jazzy_corpus(tmp_path: Path) -> None:
    configured = os.environ.get("DATASCOPE_ROS2_CORPUS")
    if not configured:
        pytest.skip("DATASCOPE_ROS2_CORPUS is not configured")
    corpus = Path(configured).expanduser().resolve()
    assert corpus.is_dir()

    metadata_bags = {path.parent for path in corpus.rglob("metadata.yaml")}
    standalone_db3 = {
        path
        for path in corpus.rglob("*.db3")
        if not any(parent in metadata_bags for parent in path.parents)
    }
    bags = sorted([*metadata_bags, *standalone_db3], key=str)
    assert bags, f"No ROS2 bags found under {corpus}"

    workspace = Workspace(tmp_path / "workspace")
    project = workspace.create_project("ROS2 Corpus")
    distros: set[str] = set()
    for bag in bags:
        source = workspace.add_source(
            project["id"],
            str(bag),
            storage_mode="reference",
        )
        inspection = workspace.inspect_source(source["id"])
        metadata = inspection["source"]["metadata"]
        distros.add(metadata["effective_ros_distro"])
        assert metadata["topic_count"] > 0
        assert metadata["convertible_topic_count"] > 0

    assert {"humble", "jazzy"}.issubset(distros)
