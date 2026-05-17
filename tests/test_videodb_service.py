from __future__ import annotations

from types import SimpleNamespace

from screen_aware.event_store import EventStore
from screen_aware.videodb_service import VideoDBService


def test_visual_batch_config_includes_select_frames(tmp_path):
    settings = SimpleNamespace(visual_batch_seconds=3, visual_frame_count=3)
    service = VideoDBService(settings, EventStore(tmp_path))  # type: ignore[arg-type]

    config = service._visual_batch_config()

    assert config == {
        "type": "time",
        "value": 3,
        "frame_count": 3,
        "select_frames": ["first", "middle", "last"],
    }


def test_visual_batch_config_never_omits_select_frames(tmp_path):
    settings = SimpleNamespace(visual_batch_seconds=5, visual_frame_count=0)
    service = VideoDBService(settings, EventStore(tmp_path))  # type: ignore[arg-type]

    config = service._visual_batch_config()

    assert config["frame_count"] == 1
    assert config["select_frames"] == ["first"]

