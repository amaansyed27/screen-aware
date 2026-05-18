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


def test_video_scene_config_uses_vod_shape(tmp_path):
    settings = SimpleNamespace(visual_batch_seconds=4, visual_frame_count=2)
    service = VideoDBService(settings, EventStore(tmp_path))  # type: ignore[arg-type]

    config = service._video_scene_config()

    assert config == {
        "time": 4,
        "frame_count": 2,
        "select_frames": ["first", "middle"],
    }


def test_search_exported_video_treats_no_results_as_empty(tmp_path):
    class FakeVideo:
        def search(self, *args, **kwargs):
            raise RuntimeError("Invalid request: No results found.")

    class FakeCollection:
        def get_video(self, video_id):
            assert video_id == "video-1"
            return FakeVideo()

    settings = SimpleNamespace(visual_batch_seconds=3, visual_frame_count=3)
    service = VideoDBService(settings, EventStore(tmp_path))  # type: ignore[arg-type]
    service._coll = FakeCollection()

    assert service._search_exported_video("video-1", "anything", 0.3, 4, ["idx-1"]) == []


def test_local_visual_evidence_returns_existing_frames(tmp_path):
    settings = SimpleNamespace(
        visual_batch_seconds=3,
        visual_frame_count=3,
        data_dir=tmp_path,
    )
    store = EventStore(tmp_path)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake image")
    store.append_session_item(
        "cap-1",
        "evidence_frames",
        {"sequence": 2, "source_label": "Window", "path": str(frame)},
    )
    service = VideoDBService(settings, store)  # type: ignore[arg-type]

    evidence = service._local_visual_evidence_sync("cap-1", 5)

    assert len(evidence) == 1
    assert evidence[0]["sequence"] == 2
    assert evidence[0]["source_label"] == "Window"
    assert evidence[0]["path"] == str(frame)
