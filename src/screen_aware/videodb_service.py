from __future__ import annotations

import asyncio
import inspect
import os
import re
import shutil
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .event_store import EventStore
from .formatters import shot_to_dict


VISUAL_PROMPT = """You are the visual perception layer for a developer copilot.
Describe the active application, terminal/editor state, visible errors, file names,
UI controls, and any text that helps debug the user's current workflow.
Prefer concise, factual observations. Include visible terminal output and stack traces."""

AUDIO_PROMPT = """Summarize the developer's spoken issue and intent.
Extract bug symptoms, expected behavior, observed behavior, filenames, commands,
error messages, and hypotheses. Keep the summary grounded in what was said."""

DEFAULT_SELECT_FRAMES = ["first", "middle", "last"]
READY_INDEX_STATUSES = {"ready", "completed", "complete", "indexed", "processed", "success", "succeeded"}
NO_SPEECH_MARKERS = (
    "failed to detect the language",
    "no spoken data found",
    "no speech",
    "no audio",
)


class VideoDBService:
    """Thin compatibility layer around the real VideoDB Python SDK."""

    def __init__(self, settings: Settings, store: EventStore) -> None:
        self.settings = settings
        self.store = store
        self._conn: Any | None = None
        self._coll: Any | None = None

    def _require_key(self) -> None:
        key = self.settings.video_db_api_key or os.getenv("VIDEO_DB_API_KEY") or os.getenv(
            "VIDEODB_API_KEY"
        )
        if not key:
            raise RuntimeError(
                "VideoDB API key is not configured. Set VIDEO_DB_API_KEY in the environment "
                "or in the project .env file."
            )

    def conn(self) -> Any:
        self._require_key()
        if self._conn is None:
            import videodb

            if self.settings.video_db_api_key:
                self._conn = videodb.connect(api_key=self.settings.video_db_api_key)
            else:
                self._conn = videodb.connect()
        return self._conn

    def collection(self) -> Any:
        if self._coll is None:
            conn = self.conn()
            collection_id = self.settings.videodb_collection_id
            try:
                self._coll = conn.get_collection(collection_id)
            except TypeError:
                self._coll = conn.get_collection()
        return self._coll

    async def create_capture_session(
        self,
        *,
        end_user_id: str,
        issue_text: str | None,
        metadata: dict[str, Any] | None,
        ws_connection_id: str | None,
        callback_url: str | None,
    ) -> dict[str, Any]:
        session, token = await asyncio.to_thread(
            self._create_capture_session_sync,
            end_user_id,
            issue_text,
            metadata or {},
            ws_connection_id,
            callback_url,
        )
        session_id = str(getattr(session, "id", None) or getattr(session, "session_id", None))
        record = self.store.upsert_session(
            session_id,
            end_user_id=end_user_id,
            collection_id=getattr(session, "collection_id", None)
            or self.settings.videodb_collection_id,
            status=getattr(session, "status", None) or "created",
            issue_text=issue_text,
            metadata=metadata or {},
            ws_connection_id=ws_connection_id,
            callback_url=callback_url,
        )
        return {
            "session_id": session_id,
            "client_token": token,
            "token_ttl_seconds": self.settings.client_token_ttl_seconds,
            "collection_id": record.get("collection_id"),
            "videodb_api_url": self.settings.videodb_api_url,
        }

    def _create_capture_session_sync(
        self,
        end_user_id: str,
        issue_text: str | None,
        metadata: dict[str, Any],
        ws_connection_id: str | None,
        callback_url: str | None,
    ) -> tuple[Any, str]:
        metadata = {
            "app": "screen-aware",
            "issue_text": issue_text or "",
            **metadata,
        }
        kwargs = {
            "end_user_id": end_user_id,
            "metadata": metadata,
        }
        if ws_connection_id:
            kwargs["ws_connection_id"] = ws_connection_id
        if callback_url:
            kwargs["callback_url"] = callback_url

        coll = self.collection()
        conn = self.conn()
        create_attempts: list[Callable[[], Any]] = [
            lambda: coll.create_capture_session(**kwargs),
            lambda: conn.create_capture_session(
                collection_id=self.settings.videodb_collection_id, **kwargs
            ),
            lambda: conn.create_capture_session(**kwargs),
        ]
        last_error: Exception | None = None
        for attempt in create_attempts:
            try:
                session = attempt()
                break
            except TypeError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Unable to create VideoDB CaptureSession: {last_error}") from last_error

        token_fn = conn.generate_client_token
        try:
            token = token_fn(expires_in=self.settings.client_token_ttl_seconds)
        except TypeError:
            try:
                token = token_fn(self.settings.client_token_ttl_seconds)
            except TypeError:
                token = token_fn()
        return session, str(token)

    async def start_ai_pipelines(self, session_id: str, rtstreams: list[dict[str, Any]]) -> None:
        await asyncio.to_thread(self._start_ai_pipelines_sync, session_id, rtstreams)

    def _start_ai_pipelines_sync(self, session_id: str, rtstreams: list[dict[str, Any]]) -> None:
        session = self.store.get_session(session_id) or {}
        existing_indexes = session.get("indexes") or []
        if existing_indexes:
            return

        ws_id = self.store.read_state().get("backend", {}).get("ws_connection_id")
        indexes: list[dict[str, Any]] = []
        for stream_info in rtstreams:
            rtstream_id = stream_info.get("rtstream_id") or stream_info.get("id")
            if not rtstream_id:
                continue
            media_types = [str(item).lower() for item in stream_info.get("media_types", [])]
            name = stream_info.get("name") or stream_info.get("rtstream_name")
            rtstream = self._get_rtstream(str(rtstream_id))

            if "audio" in media_types or (isinstance(name, str) and "mic" in name):
                transcript_status = self._call_supported(
                    rtstream.start_transcript,
                    ws_connection_id=ws_id,
                    engine=None,
                )
                audio_index = self._call_supported(
                    rtstream.index_audio,
                    prompt=AUDIO_PROMPT,
                    batch_config={"type": "word", "value": self.settings.audio_batch_words},
                    model_name=self.settings.visual_model,
                    name="screen_aware_audio",
                    ws_connection_id=ws_id,
                )
                indexes.append(
                    {
                        "kind": "audio",
                        "rtstream_id": rtstream_id,
                        "rtstream_name": name,
                        "transcript_status": self._safe_repr(transcript_status),
                        "index_id": self._index_id(audio_index),
                    }
                )

            if "video" in media_types or (isinstance(name, str) and "display" in name):
                visual_index = self._call_supported(
                    rtstream.index_visuals,
                    prompt=VISUAL_PROMPT,
                    batch_config=self._visual_batch_config(),
                    model_name=self.settings.visual_model,
                    name="screen_aware_visual",
                    ws_connection_id=ws_id,
                )
                indexes.append(
                    {
                        "kind": "visual",
                        "rtstream_id": rtstream_id,
                        "rtstream_name": name,
                        "index_id": self._index_id(visual_index),
                    }
                )

        self.store.upsert_session(session_id, indexes=indexes, indexing_status="started")

    def ingest_window_capture_segment(
        self,
        *,
        session_id: str,
        file_path: Path,
        sequence: int,
        source_label: str,
        contains_audio: bool,
        started_at_ms: int | None,
        ended_at_ms: int | None,
    ) -> None:
        """Upload a browser-selected window segment to VideoDB and start searchable indexes."""

        segment_name = f"screen-aware-window-{session_id}-{sequence:04d}"
        evidence_frames = self._extract_evidence_frames(
            session_id=session_id,
            file_path=file_path,
            sequence=sequence,
            source_label=source_label,
            max_frames=1,
        )
        try:
            video = self.collection().upload(
                file_path=str(file_path),
                name=segment_name,
                description=f"Screen-Aware window capture segment from {source_label}",
            )
            video_id = self._media_id(video)
            errors: list[str] = []
            visual_index = None
            try:
                visual_index = self._index_video_visuals(video, sequence)
            except Exception as exc:
                errors.append(f"visual: {type(exc).__name__}: {exc}")

            audio_index = None
            transcript_text = None
            audio_notice = None
            if contains_audio:
                try:
                    self._call_supported(video.index_spoken_words, force=True)
                    transcript_text = self._transcript_text(video)
                    if transcript_text:
                        self.store.append_event(
                            {
                                "source": "videodb",
                                "channel": "transcript",
                                "event": "window.segment.transcript",
                                "capture_session_id": session_id,
                                "data": {
                                    "sequence": sequence,
                                    "source_label": source_label,
                                    "video_id": video_id,
                                    "text": transcript_text,
                                },
                            }
                        )
                except Exception as exc:
                    if self._is_no_speech_error(exc):
                        audio_notice = "No spoken data was detected in this segment."
                    else:
                        errors.append(f"transcript: {type(exc).__name__}: {exc}")
                try:
                    audio_index = self._call_supported(
                        video.index_audio,
                        prompt=AUDIO_PROMPT,
                        batch_config={"type": "word", "value": self.settings.audio_batch_words},
                        model_name=self.settings.visual_model,
                        name=f"screen_aware_window_audio_{sequence:04d}",
                    )
                except Exception as exc:
                    errors.append(f"audio: {type(exc).__name__}: {exc}")

            item = {
                "kind": "window_segment",
                "sequence": sequence,
                "source_label": source_label,
                "file_path": str(file_path),
                "video_id": video_id,
                "stream_url": getattr(video, "stream_url", None),
                "player_url": getattr(video, "player_url", None),
                "started_at_ms": started_at_ms,
                "ended_at_ms": ended_at_ms,
                "contains_audio": contains_audio,
                "visual_index_id": self._index_id(visual_index),
                "audio_index_id": self._index_id(audio_index),
                "visual_index_status": self._scene_index_status(video, self._index_id(visual_index)),
                "transcript_text": transcript_text,
                "audio_notice": audio_notice,
                "evidence_frames": evidence_frames,
                "errors": errors,
            }
            self.store.append_session_item(session_id, "uploaded_videos", item)
            indexed = bool(item["visual_index_id"] or item["audio_index_id"] or transcript_text)
            self.store.append_event(
                {
                    "source": "videodb",
                    "channel": "window",
                    "event": "window.segment.indexed" if indexed else "window.segment.index_failed",
                    "capture_session_id": session_id,
                    "data": {
                        **item,
                        "text": self._window_segment_event_text(
                            sequence, source_label, indexed, errors, audio_notice
                        ),
                    },
                }
            )
            self.store.upsert_session(
                session_id,
                indexing_status="window_segments_indexed" if indexed else "window_segment_failed",
                error="; ".join(errors) if errors and not indexed else "",
            )
        except Exception as exc:
            self.store.append_event(
                {
                    "source": "videodb",
                    "channel": "window",
                    "event": "window.segment.index_failed",
                    "capture_session_id": session_id,
                    "data": {
                        "sequence": sequence,
                        "source_label": source_label,
                        "file_path": str(file_path),
                        "error": f"{type(exc).__name__}: {exc}",
                        "text": f"VideoDB failed to index window segment {sequence}: {exc}",
                    },
                }
            )
            self.store.upsert_session(
                session_id,
                indexing_status="window_segment_failed",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _visual_batch_config(self) -> dict[str, Any]:
        frame_count = max(1, self.settings.visual_frame_count)
        return {
            "type": "time",
            "value": self.settings.visual_batch_seconds,
            "frame_count": frame_count,
            "select_frames": DEFAULT_SELECT_FRAMES[: min(frame_count, len(DEFAULT_SELECT_FRAMES))],
        }

    def _video_scene_config(self) -> dict[str, Any]:
        frame_count = max(1, self.settings.visual_frame_count)
        select_frames = DEFAULT_SELECT_FRAMES[: min(frame_count, len(DEFAULT_SELECT_FRAMES))]
        return {
            "time": self.settings.visual_batch_seconds,
            "frame_count": frame_count,
            "select_frames": select_frames,
        }

    def _index_video_visuals(self, video: Any, sequence: int) -> Any:
        try:
            from videodb import SceneExtractionType
        except Exception:
            SceneExtractionType = None  # type: ignore[assignment]

        if hasattr(video, "index_scenes") and SceneExtractionType is not None:
            try:
                return self._call_supported(
                    video.index_scenes,
                    extraction_type=SceneExtractionType.time_based,
                    extraction_config=self._video_scene_config(),
                    prompt=VISUAL_PROMPT,
                    model_name=self.settings.visual_model,
                    name=f"screen_aware_window_visual_{sequence:04d}",
                )
            except Exception as exc:
                existing = self._index_id_from_error(exc)
                if existing:
                    return existing
                raise

        return self._call_supported(
            video.index_visuals,
            prompt=VISUAL_PROMPT,
            batch_config=self._visual_batch_config(),
            model_name=self.settings.visual_model,
            name=f"screen_aware_window_visual_{sequence:04d}",
        )

    @staticmethod
    def _transcript_text(video: Any) -> str | None:
        try:
            text = video.get_transcript_text()
        except Exception:
            return None
        if isinstance(text, str):
            stripped = text.strip()
            return stripped or None
        return None

    @staticmethod
    def _window_segment_event_text(
        sequence: int,
        source_label: str,
        indexed: bool,
        errors: list[str],
        audio_notice: str | None = None,
    ) -> str:
        suffix = f" {audio_notice}" if audio_notice else ""
        if indexed and errors:
            return (
                f"VideoDB partially indexed window segment {sequence} from {source_label}; "
                f"{'; '.join(errors)}"
            )
        if indexed:
            return f"VideoDB indexed window segment {sequence} from {source_label}.{suffix}"
        return f"VideoDB failed to index window segment {sequence}: {'; '.join(errors)}"

    def _extract_evidence_frames(
        self,
        *,
        session_id: str,
        file_path: Path,
        sequence: int,
        source_label: str,
        max_frames: int,
    ) -> list[dict[str, Any]]:
        ffmpeg = self._ffmpeg_path()
        if not ffmpeg or max_frames <= 0:
            return []
        if not file_path.exists() or file_path.stat().st_size <= 0:
            return []

        evidence_dir = self.settings.data_dir / "evidence-frames" / self._safe_path_part(session_id)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        output_pattern = evidence_dir / f"segment-{sequence:04d}-frame-%02d.jpg"
        command = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(file_path),
            "-vf",
            "fps=1/3,scale=1280:-1",
            "-frames:v",
            str(max_frames),
            str(output_pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                detail = f"{detail}; {exc.stderr.strip()}"
            self.store.append_event(
                {
                    "source": "local",
                    "channel": "visual_frame",
                    "event": "window.segment.frame_failed",
                    "capture_session_id": session_id,
                    "data": {
                        "sequence": sequence,
                        "source_label": source_label,
                        "file_path": str(file_path),
                        "error": detail,
                        "text": f"Local screen evidence frame extraction failed for segment {sequence}: {detail}",
                    },
                }
            )
            return []

        frames: list[dict[str, Any]] = []
        for frame_path in sorted(evidence_dir.glob(f"segment-{sequence:04d}-frame-*.jpg")):
            item = {
                "sequence": sequence,
                "source_label": source_label,
                "path": str(frame_path.resolve()),
                "file_path": str(file_path),
                "text": f"Local screen evidence frame for segment {sequence} from {source_label}.",
            }
            frames.append(item)
            self.store.append_session_item(session_id, "evidence_frames", item, max_items=150)
            self.store.append_event(
                {
                    "source": "local",
                    "channel": "visual_frame",
                    "event": "window.segment.frame_extracted",
                    "capture_session_id": session_id,
                    "data": item,
                }
            )
        return frames

    async def local_visual_evidence(
        self, *, session_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._local_visual_evidence_sync, session_id, limit)

    def _local_visual_evidence_sync(
        self, session_id: str | None, limit: int
    ) -> list[dict[str, Any]]:
        session = self.store.get_session(session_id)
        if not session or limit <= 0:
            return []

        frames = [
            frame
            for frame in session.get("evidence_frames") or []
            if isinstance(frame, dict) and self._frame_exists(frame)
        ]
        if len(frames) >= limit:
            return self._sorted_frames(frames)[-limit:]

        known = {str(frame.get("sequence")) for frame in frames if frame.get("sequence") is not None}
        missing_segments = []
        for segment in reversed(session.get("window_segments") or []):
            if not isinstance(segment, dict):
                continue
            sequence = segment.get("sequence")
            if sequence is None or str(sequence) in known:
                continue
            file_path = segment.get("file_path")
            if not file_path:
                continue
            missing_segments.append(segment)
            if len(missing_segments) >= max(1, min(limit, 4)):
                break

        for segment in reversed(missing_segments):
            extracted = self._extract_evidence_frames(
                session_id=session["session_id"],
                file_path=Path(str(segment["file_path"])),
                sequence=int(segment["sequence"]),
                source_label=str(segment.get("source_label") or "Selected window"),
                max_frames=1,
            )
            frames.extend(extracted)

        return self._sorted_frames([frame for frame in frames if self._frame_exists(frame)])[-limit:]

    @staticmethod
    def _sorted_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            frames,
            key=lambda frame: (
                int(frame.get("sequence", 0)) if str(frame.get("sequence", "")).isdigit() else 0,
                str(frame.get("path") or ""),
            ),
        )

    @staticmethod
    def _frame_exists(frame: dict[str, Any]) -> bool:
        path = frame.get("path")
        return isinstance(path, str) and Path(path).exists()

    @staticmethod
    def _ffmpeg_path() -> str | None:
        try:
            import imageio_ffmpeg

            path = imageio_ffmpeg.get_ffmpeg_exe()
            if path and Path(path).exists():
                return str(path)
        except Exception:
            pass
        return shutil.which("ffmpeg")

    @staticmethod
    def _safe_path_part(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        return cleaned.strip(".-") or "unknown"

    @staticmethod
    def _is_no_speech_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(marker in message for marker in NO_SPEECH_MARKERS)

    @staticmethod
    def _index_id_from_error(exc: Exception) -> str | None:
        match = re.search(r"id\s+([a-f0-9]+)", str(exc), flags=re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _scene_index_status(video: Any, scene_index_id: str | None) -> str | None:
        if not scene_index_id or not hasattr(video, "list_scene_index"):
            return None
        try:
            indexes = video.list_scene_index()
        except Exception:
            return None
        if not isinstance(indexes, list):
            return None
        for item in indexes:
            if not isinstance(item, dict):
                continue
            if str(item.get("scene_index_id") or item.get("id")) == scene_index_id:
                status = item.get("status")
                return str(status) if status is not None else None
        return None

    def _get_rtstream(self, rtstream_id: str) -> Any:
        conn = self.conn()
        if hasattr(conn, "get_rtstream"):
            return conn.get_rtstream(rtstream_id)
        coll = self.collection()
        return coll.get_rtstream(rtstream_id)

    @staticmethod
    def _call_supported(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None

        if signature:
            accepted = {}
            supports_var_kwargs = any(
                param.kind == inspect.Parameter.VAR_KEYWORD
                for param in signature.parameters.values()
            )
            for key, value in kwargs.items():
                if value is None:
                    continue
                if supports_var_kwargs or key in signature.parameters:
                    accepted[key] = value
            try:
                return fn(*args, **accepted)
            except TypeError:
                pass

        try:
            return fn(*args, **{key: value for key, value in kwargs.items() if value is not None})
        except TypeError:
            return fn(*args)

    @staticmethod
    def _index_id(index: Any) -> str | None:
        if isinstance(index, str):
            return index
        for name in ("rtstream_index_id", "rtstreamIndexId", "id", "index_id"):
            value = getattr(index, name, None)
            if value:
                return str(value)
        return None

    @staticmethod
    def _media_id(media: Any) -> str | None:
        for name in ("id", "video_id", "videoId", "media_id", "mediaId"):
            value = getattr(media, name, None)
            if value:
                return str(value)
        if isinstance(media, dict):
            for name in ("id", "video_id", "videoId", "media_id", "mediaId"):
                value = media.get(name)
                if value:
                    return str(value)
        return None

    @staticmethod
    def _safe_repr(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool, dict, list)):
            return value
        return repr(value)

    async def search_session(
        self,
        *,
        query: str,
        session_id: str | None,
        modalities: set[str],
        limit: int,
        score_threshold: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return await asyncio.to_thread(
            self._search_session_sync,
            query,
            session_id,
            modalities,
            limit,
            score_threshold,
        )

    def _search_session_sync(
        self,
        query: str,
        session_id: str | None,
        modalities: set[str],
        limit: int,
        score_threshold: float,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        session = self.store.get_session(session_id)
        warnings: list[str] = []
        if not session:
            return [], ["No active Screen-Aware session is recorded in local state."]

        candidates = self._matching_rtstreams(session, modalities)
        shots: list[dict[str, Any]] = []
        for stream in candidates:
            if len(shots) >= limit:
                break
            rtstream_id = stream.get("rtstream_id") or stream.get("id")
            if not rtstream_id:
                continue
            try:
                result = self._search_rtstream(str(rtstream_id), query, score_threshold, limit)
                for shot in result:
                    shot.setdefault("rtstream_id", rtstream_id)
                    shot.setdefault("rtstream_name", stream.get("name"))
                    shots.append(shot)
                    if len(shots) >= limit:
                        break
            except Exception as exc:  # VideoDB SDK exposes several runtime exceptions.
                warnings.append(f"VideoDB RTStream search failed for {rtstream_id}: {type(exc).__name__}: {exc}")

        if len(shots) < limit:
            for item in reversed(session.get("uploaded_videos") or []):
                if len(shots) >= limit:
                    break
                video_id = item.get("video_id") if isinstance(item, dict) else None
                if not video_id:
                    continue
                try:
                    segment_shots = self._search_exported_video(
                        str(video_id),
                        query,
                        score_threshold,
                        limit - len(shots),
                        scene_index_ids=[
                            str(index_id)
                            for index_id in (item.get("visual_index_id"),)
                            if index_id
                        ],
                    )
                    for shot in segment_shots:
                        shot.setdefault("video_id", video_id)
                        shot.setdefault("source_label", item.get("source_label"))
                        shot.setdefault("window_sequence", item.get("sequence"))
                        shots.append(shot)
                except Exception as exc:
                    warnings.append(
                        f"VideoDB window segment search failed for {video_id}: {type(exc).__name__}: {exc}"
                    )

        if len(shots) < limit and session.get("exported_video_id"):
            try:
                shots.extend(
                    self._search_exported_video(
                        str(session["exported_video_id"]), query, score_threshold, limit - len(shots)
                    )
                )
            except Exception as exc:
                warnings.append(f"VideoDB exported-video search failed: {type(exc).__name__}: {exc}")
        return shots[:limit], warnings

    @staticmethod
    def _matching_rtstreams(session: dict[str, Any], modalities: set[str]) -> list[dict[str, Any]]:
        result = []
        for stream in session.get("rtstreams") or []:
            media_types = {str(item).lower() for item in stream.get("media_types", [])}
            name = str(stream.get("name", "")).lower()
            include = False
            if "visual" in modalities and ("video" in media_types or "display" in name):
                include = True
            if "audio" in modalities and ("audio" in media_types or "mic" in name):
                include = True
            if include:
                result.append(stream)
        return result

    def _search_rtstream(
        self, rtstream_id: str, query: str, score_threshold: float, limit: int
    ) -> list[dict[str, Any]]:
        rtstream = self._get_rtstream(rtstream_id)
        try:
            result = rtstream.search(
                query=query,
                score_threshold=score_threshold,
                result_threshold=limit,
            )
        except TypeError:
            result = rtstream.search(
                {
                    "query": query,
                    "scoreThreshold": score_threshold,
                    "resultThreshold": limit,
                }
            )
        return self._shots_from_result(result)

    def _search_exported_video(
        self,
        video_id: str,
        query: str,
        score_threshold: float,
        limit: int,
        scene_index_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        video = self.collection().get_video(video_id)
        attempts: list[Callable[[], Any]] = []
        for scene_index_id in scene_index_ids or []:
            attempts.append(
                lambda scene_index_id=scene_index_id: video.search(
                    query=query,
                    search_type="semantic",
                    index_type="scene",
                    scene_index_id=scene_index_id,
                    score_threshold=score_threshold,
                    result_threshold=limit,
                )
            )
        attempts.extend(
            [
                lambda: video.search(
                    query=query,
                    score_threshold=score_threshold,
                    result_threshold=limit,
                ),
                lambda: video.search(query),
            ]
        )
        last_error: Exception | None = None
        for attempt in attempts:
            try:
                return self._shots_from_result(attempt())
            except Exception as exc:
                if not self._recoverable_search_error(exc):
                    raise
                last_error = exc
                continue
        if last_error and isinstance(last_error, TypeError):
            raise last_error
        return []

    @staticmethod
    def _recoverable_search_error(exc: Exception) -> bool:
        if isinstance(exc, TypeError):
            return True
        message = str(exc).lower()
        return "no results found" in message or "not found" in message

    @staticmethod
    def _shots_from_result(result: Any) -> list[dict[str, Any]]:
        if result is None:
            return []
        if hasattr(result, "get_shots"):
            raw = result.get_shots()
        elif hasattr(result, "getShots"):
            raw = result.getShots()
        else:
            raw = getattr(result, "shots", [])
        return [shot_to_dict(shot) if not isinstance(shot, dict) else shot for shot in raw]

    async def run_websocket_listener(
        self,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        backoff = 1.0
        while not stop_event.is_set():
            try:
                await self._listen_once(on_event, stop_event)
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.update_backend(ws_status="error", last_error=f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _listen_once(
        self,
        on_event: Callable[[dict[str, Any]], Awaitable[None]],
        stop_event: asyncio.Event,
    ) -> None:
        wrapper = await asyncio.to_thread(self._connect_websocket)
        ws = await self._maybe_await(wrapper.connect())
        connection_id = getattr(ws, "connection_id", None) or getattr(wrapper, "connection_id", None)
        self.store.update_backend(
            ws_connection_id=connection_id,
            ws_status="connected",
            last_error=None,
        )
        async for event in self._event_stream(ws):
            if stop_event.is_set():
                break
            await on_event(event)

    def _connect_websocket(self) -> Any:
        conn = self.conn()
        try:
            return conn.connect_websocket(collection_id=self.settings.videodb_collection_id)
        except TypeError:
            return conn.connect_websocket()

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _event_stream(self, ws: Any):
        stream = None
        if hasattr(ws, "stream"):
            stream = ws.stream()
        elif hasattr(ws, "receive"):
            stream = ws.receive()
        if stream is None:
            raise RuntimeError("VideoDB WebSocket object does not expose stream() or receive().")
        async for event in stream:
            yield event
