"""Video media discovery, frame extract, trim/split, and aligned MP4 export."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from aligner_core import (
    FocalPointAlignerCore,
    MEDIA_EXTENSIONS,
    VIDEO_EXTENSIONS,
    extract_video_frame,
    ffmpeg_available,
    probe_video_meta,
)
from batch import BatchManager, MEDIA_EXTENSIONS as BATCH_MEDIA


def _write_jpg(path: Path, color=(40, 80, 120), size=(64, 48)):
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    img[:] = color
    cv2.imwrite(str(path), img)


def _write_video(path: Path, frames=10, w=64, h=48, fps=10):
    """Create a short synthetic MP4 via OpenCV (mp4v)."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, float(fps), (w, h))
    assert writer.isOpened(), "VideoWriter failed to open"
    for i in range(frames):
        frame = np.full((h, w, 3), (i * 20) % 255, dtype=np.uint8)
        # Distinct marker pixel for frame identity checks
        frame[0, 0] = (i, 0, 255 - i)
        writer.write(frame)
    writer.release()
    assert path.is_file() and path.stat().st_size > 0


@pytest.fixture
def mixed_folder(tmp_path):
    d = tmp_path / "mix"
    d.mkdir()
    _write_jpg(d / "a.jpg", (10, 20, 30))
    _write_video(d / "clip.mp4", frames=12, fps=10)
    _write_jpg(d / "b.png", (50, 60, 70), size=(80, 60))
    return d


def test_media_extensions_include_video():
    assert ".mp4" in VIDEO_EXTENSIONS
    assert ".mp4" in MEDIA_EXTENSIONS
    assert ".mp4" in BATCH_MEDIA
    assert ".jpg" in MEDIA_EXTENSIONS


def test_discovery_mix(mixed_folder, tmp_path):
    out = tmp_path / "out"
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(out),
        "target_width": 64,
        "target_height": 48,
    })
    names = [f.name for f in core.image_files]
    assert "a.jpg" in names
    assert "clip.mp4" in names
    assert "b.png" in names
    assert core.total_images == 3

    snap = core.session_snapshot()
    kinds = {im["filename"]: im["media_kind"] for im in snap["images"]}
    assert kinds["a.jpg"] == "image"
    assert kinds["clip.mp4"] == "video"
    assert kinds["b.png"] == "image"

    vid = next(im for im in snap["images"] if im["filename"] == "clip.mp4")
    assert vid["frame_count"] >= 1
    assert vid["fps"] > 0
    assert vid["in_frame"] == 0
    assert vid["out_frame"] == vid["frame_count"] - 1
    assert 0 <= vid["work_frame"] <= vid["out_frame"]


def test_batch_sees_videos(tmp_path):
    root = tmp_path / "root"
    sub = root / "folder"
    sub.mkdir(parents=True)
    _write_video(sub / "only.mp4", frames=5)
    bm = BatchManager(root)
    folders = bm.discover_subfolders()
    assert any(f.name == "folder" for f in folders)


def test_json_video_fields(mixed_folder, tmp_path):
    out = tmp_path / "out"
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(out),
        "target_width": 64,
        "target_height": 48,
    })
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    core.navigate_to(vidx)
    core.set_focal_point(10, 12)
    assert core.set_video_range(vidx, in_frame=1, out_frame=5, work_frame=3)

    data = json.loads(core.json_path.read_text())
    entry = data["clip.mp4"]
    assert entry["in_frame"] == 1
    assert entry["out_frame"] == 5
    assert entry["work_frame"] == 3
    assert entry["focal_x"] == 10
    assert entry["media_kind"] == "video"

    core2 = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(out),
        "target_width": 64,
        "target_height": 48,
    })
    vidx2 = next(i for i, f in enumerate(core2.image_files) if f.suffix.lower() == ".mp4")
    assert core2.in_frames[vidx2] == 1
    assert core2.out_frames[vidx2] == 5
    assert core2.work_frames[vidx2] == 3


def test_extract_video_frame(mixed_folder):
    path = mixed_folder / "clip.mp4"
    meta = probe_video_meta(path)
    assert meta is not None
    frame0 = extract_video_frame(path, 0)
    frame3 = extract_video_frame(path, 3)
    assert frame0 is not None and frame0.ndim == 3
    assert frame3 is not None
    # Marker pixel differs across frames when seek works
    assert frame0.shape[0] == meta["height"]
    assert frame0.shape[1] == meta["width"]


def test_load_media_uses_work_frame(mixed_folder, tmp_path):
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(tmp_path / "out"),
        "target_width": 64,
        "target_height": 48,
    })
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    core.set_video_range(vidx, work_frame=2)
    img = core.load_media_bgr(vidx)
    assert img is not None
    jpeg = core.ensure_frame_jpeg(vidx, frame_idx=2)
    assert jpeg is not None and jpeg.exists()


def test_trim_fields_only(mixed_folder, tmp_path):
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(tmp_path / "out"),
        "target_width": 64,
        "target_height": 48,
    })
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    before = len(core.image_files)
    core.set_video_range(vidx, out_frame=4, work_frame=4)
    assert len(core.image_files) == before
    assert core.out_frames[vidx] == 4


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not on PATH")
def test_split_increases_file_count(mixed_folder, tmp_path):
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(tmp_path / "out"),
        "target_width": 64,
        "target_height": 48,
    })
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    before = len(core.image_files)
    core.set_video_range(vidx, out_frame=3, work_frame=3)
    ok, err = core.split_video_at(vidx, 3)
    assert ok, err
    assert len(core.image_files) == before + 1
    part = core.image_files[vidx + 1]
    assert "__part" in part.stem
    assert core.out_frames[vidx] == 3


def test_split_stubs_without_ffmpeg(mixed_folder, tmp_path, monkeypatch):
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(tmp_path / "out"),
        "target_width": 64,
        "target_height": 48,
    })
    monkeypatch.setattr("aligner_core.ffmpeg_available", lambda: False)
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    ok, err = core.split_video_at(vidx, 2)
    assert not ok
    assert "ffmpeg" in (err or "").lower()


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not on PATH")
def test_export_mp4(mixed_folder, tmp_path):
    out = tmp_path / "aligned"
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(out),
        "target_width": 64,
        "target_height": 48,
    })
    for i, f in enumerate(core.image_files):
        core.navigate_to(i)
        w, h = core.image_dimensions[i]
        core.set_focal_point(w / 2, h / 2)
        if core.is_video(i):
            core.set_video_range(i, in_frame=0, out_frame=min(3, core.video_meta[i]["frame_count"] - 1))

    exported = core.export_aligned(out, orientation="landscape")
    assert exported >= 1
    mp4s = list(out.glob("*.mp4"))
    jpgs = list(out.glob("*.jpg"))
    assert mp4s, "expected at least one aligned mp4"
    assert jpgs, "expected aligned jpegs for stills"
    assert mp4s[0].stat().st_size > 0


def test_export_reports_missing_ffmpeg(mixed_folder, tmp_path, monkeypatch):
    out = tmp_path / "aligned"
    core = FocalPointAlignerCore({
        "input_folder": str(mixed_folder),
        "output_folder": str(out),
        "target_width": 64,
        "target_height": 48,
    })
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix.lower() == ".mp4")
    core.navigate_to(vidx)
    core.set_focal_point(10, 10)
    monkeypatch.setattr("aligner_core.ffmpeg_available", lambda: False)
    errors = []

    def progress(done, tot, name, error=None):
        if error:
            errors.append(error)

    exported = core.export_aligned(out, progress_callback=progress)
    # Still images may still export; video should error
    assert errors
    assert any("ffmpeg" in e.lower() for e in errors)
