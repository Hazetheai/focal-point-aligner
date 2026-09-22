"""Video focal keyframes: ease, interpolate, migrate, trim clamp, AutoArrange in_frame."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from aligner_core import (
    FocalPointAlignerCore,
    apply_ease,
    interpolate_from_keyframes,
    normalize_keyframes,
)


def _write_video(path: Path, frames=12, w=64, h=48, fps=10):
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, float(fps), (w, h))
    assert writer.isOpened()
    for i in range(frames):
        frame = np.full((h, w, 3), (i * 20) % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture
def video_core(tmp_path):
    d = tmp_path / "vids"
    d.mkdir()
    _write_video(d / "clip.mp4", frames=12)
    out = tmp_path / "out"
    core = FocalPointAlignerCore({
        "input_folder": str(d),
        "output_folder": str(out),
        "target_width": 32,
        "target_height": 24,
    })
    return core


def test_apply_ease_endpoints():
    assert apply_ease(0, "linear") == 0
    assert apply_ease(1, "linear") == 1
    assert apply_ease(0.5, "linear") == pytest.approx(0.5)
    assert apply_ease(0.5, "ease-in") < 0.5
    assert apply_ease(0.5, "ease-out") > 0.5


def test_interpolate_linear_midpoint():
    kfs = [
        {"frame": 0, "focal_x": 0, "focal_y": 0, "crop_scale": 1.0, "ease": "linear"},
        {"frame": 10, "focal_x": 100, "focal_y": 50, "crop_scale": 2.0, "ease": "linear"},
    ]
    fx, fy, cs = interpolate_from_keyframes(kfs, 5)
    assert fx == pytest.approx(50)
    assert fy == pytest.approx(25)
    assert cs == pytest.approx(1.5)


def test_normalize_dedupes_and_sorts():
    raw = [
        {"frame": 8, "focal_x": 1, "focal_y": 1, "crop_scale": 1},
        {"frame": 2, "focal_x": 2, "focal_y": 2, "crop_scale": 1},
        {"frame": 8, "focal_x": 9, "focal_y": 9, "crop_scale": 1.5},
    ]
    out = normalize_keyframes(raw, in_f=0, out_f=10)
    assert [k["frame"] for k in out] == [2, 8]
    assert out[1]["focal_x"] == 9


def test_set_focal_seeds_in_out_keyframes(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.current_idx = vidx
    core.set_video_range(vidx, in_frame=1, out_frame=9, work_frame=5)
    core.set_focal_point(20, 30, crop_scale=1.2)
    kfs = core.keyframes_for(vidx)
    frames = {k["frame"] for k in kfs}
    # First focal seeds In/Out and writes the work-frame keyframe.
    assert frames == {1, 5, 9}
    assert next(k for k in kfs if k["frame"] == 1)["focal_x"] == pytest.approx(20)
    assert next(k for k in kfs if k["frame"] == 5)["focal_x"] == pytest.approx(20)
    assert next(k for k in kfs if k["frame"] == 1)["crop_scale"] == pytest.approx(1.2)
    # Explicit mid create at another frame
    assert core.add_or_update_keyframe(vidx, 7, 40, 50, crop_scale=1.5, create=True)
    frames = {k["frame"] for k in core.keyframes_for(vidx)}
    assert frames == {1, 5, 7, 9}
    mid = next(k for k in core.keyframes_for(vidx) if k["frame"] == 7)
    assert mid["focal_x"] == pytest.approx(40)
    # Updating via set_focal at work=5 should rewrite that mid only
    core.work_frames[vidx] = 5
    core.set_focal_point(11, 12, crop_scale=1.1)
    mid = next(k for k in core.keyframes_for(vidx) if k["frame"] == 5)
    assert mid["focal_x"] == pytest.approx(11)
    assert next(k for k in core.keyframes_for(vidx) if k["frame"] == 1)["focal_x"] == pytest.approx(20)
    assert next(k for k in core.keyframes_for(vidx) if k["frame"] == 7)["focal_x"] == pytest.approx(40)


def test_interpolate_focal_at_and_persist(video_core, tmp_path):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.set_video_range(vidx, in_frame=0, out_frame=10, work_frame=0)
    core.add_or_update_keyframe(vidx, 0, 0, 0, crop_scale=1.0, ease="linear")
    core.add_or_update_keyframe(vidx, 10, 100, 40, crop_scale=2.0, ease="linear")
    fx, fy, cs = core.interpolate_focal_at(vidx, 5)
    assert fx == pytest.approx(50)
    assert fy == pytest.approx(20)
    assert cs == pytest.approx(1.5)

    # Reload from JSON
    data = json.loads(core.json_path.read_text())
    name = core.image_files[vidx].name
    assert "keyframes" in data[name]
    core2 = FocalPointAlignerCore({
        "input_folder": str(core.input_folder),
        "output_folder": str(tmp_path / "out2"),
        "target_width": 32,
        "target_height": 24,
    })
    vidx2 = next(i for i, f in enumerate(core2.image_files) if f.name == name)
    assert len(core2.keyframes_for(vidx2)) >= 2


def test_trim_remaps_endpoint_keyframes(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.add_or_update_keyframe(vidx, 0, 10, 10, crop_scale=1.0)
    core.add_or_update_keyframe(vidx, 5, 20, 20, crop_scale=1.5)
    core.add_or_update_keyframe(vidx, 11, 30, 30, crop_scale=2.0)
    core.set_video_range(vidx, in_frame=2, out_frame=8)
    frames = [k["frame"] for k in core.keyframes_for(vidx)]
    assert 2 in frames and 8 in frames and 5 in frames
    assert 0 not in frames and 11 not in frames
    assert next(k for k in core.keyframes_for(vidx) if k["frame"] == 2)["focal_x"] == pytest.approx(10)
    assert next(k for k in core.keyframes_for(vidx) if k["frame"] == 8)["focal_x"] == pytest.approx(30)


def test_delete_mid_keeps_endpoints_no_extras(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.set_video_range(vidx, in_frame=2, out_frame=9, work_frame=5)
    core.add_or_update_keyframe(vidx, 2, 1, 1)
    core.add_or_update_keyframe(vidx, 5, 2, 2)
    core.add_or_update_keyframe(vidx, 9, 3, 3)
    assert core.delete_keyframe(vidx, 5) is True
    assert core.delete_keyframe(vidx, 2) is False  # endpoints cannot be deleted
    frames = [k["frame"] for k in core.keyframes_for(vidx)]
    assert frames == [2, 9]


def test_trim_clamps_keyframes(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.add_or_update_keyframe(vidx, 0, 10, 10)
    core.add_or_update_keyframe(vidx, 5, 20, 20)
    core.add_or_update_keyframe(vidx, 11, 30, 30)
    core.set_video_range(vidx, in_frame=2, out_frame=8)
    frames = [k["frame"] for k in core.keyframes_for(vidx)]
    assert all(2 <= f <= 8 for f in frames)
    assert 5 in frames
    assert 0 not in frames
    assert 11 not in frames


def test_auto_arrange_uses_in_frame(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.set_video_range(vidx, in_frame=3, out_frame=10, work_frame=7)
    captured = {}

    def fake_sort(paths, progress=None, frame_indices=None):
        captured["frame_indices"] = list(frame_indices or [])
        return list(range(len(paths))), ["x"] * len(paths)

    with patch("arrange_auto.sort_indices_by_color", side_effect=fake_sort):
        ok, _ = core.auto_arrange("color", {})
    assert ok
    assert captured["frame_indices"][vidx] == 3


def test_hap_extension_recognized():
    from aligner_core import VIDEO_EXTENSIONS, is_video_path
    assert ".hap" in VIDEO_EXTENSIONS
    assert is_video_path(Path("clip.hap"))


def test_duplicate_copies_keyframes_independently(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.current_idx = vidx
    core.set_video_range(vidx, in_frame=0, out_frame=11, work_frame=5)
    core.add_or_update_keyframe(vidx, 0, 10, 10, crop_scale=1.0)
    core.add_or_update_keyframe(vidx, 5, 50, 40, crop_scale=1.5)
    core.add_or_update_keyframe(vidx, 11, 90, 80, crop_scale=2.0)
    ok, err = core.duplicate_current()
    assert ok, err
    dup_idx = core.current_idx
    assert dup_idx == vidx + 1
    assert core.is_video(dup_idx)
    assert core.keyframes_for(dup_idx) == core.keyframes_for(vidx)
    # Mutating the duplicate must not change the source.
    core.add_or_update_keyframe(dup_idx, 5, 1, 2, crop_scale=0.5)
    src_mid = next(k for k in core.keyframes_for(vidx) if k["frame"] == 5)
    dup_mid = next(k for k in core.keyframes_for(dup_idx) if k["frame"] == 5)
    assert src_mid["focal_x"] == pytest.approx(50)
    assert dup_mid["focal_x"] == pytest.approx(1)
    assert core.in_frames[dup_idx] == core.in_frames[vidx]
    assert core.out_frames[dup_idx] == core.out_frames[vidx]


def test_clear_focal_removes_all_video_keyframes(video_core):
    core = video_core
    vidx = next(i for i, f in enumerate(core.image_files) if f.suffix == ".mp4")
    core.current_idx = vidx
    core.set_video_range(vidx, in_frame=1, out_frame=9, work_frame=5)
    core.add_or_update_keyframe(vidx, 1, 10, 10)
    core.add_or_update_keyframe(vidx, 5, 20, 20)
    core.add_or_update_keyframe(vidx, 9, 30, 30)
    assert core.keyframes_for(vidx)
    core.clear_focal_point()
    assert core.keyframes_for(vidx) == []
    assert vidx not in core.focal_points
    assert vidx not in core.completed
