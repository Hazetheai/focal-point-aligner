"""Tests for batch.py - UI-free batch pipeline logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from batch import (
    BatchManager, IMAGE_EXTENSIONS, merge_folders, move_aligned_outputs,
)


def _img(p: Path, name="0001.jpg"):
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_bytes(b"xx")


def _make_root(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    _img(root / "beach")
    _img(root / "city")
    _img(root / "forest")
    # Output folder that will count as "done"
    _img(root / "city_aligned", "0000.jpg")
    # Things that must be ignored
    (root / "discarded").mkdir()
    (root / "city" / "stray").mkdir()
    (root / "beach_extra.txt").write_text("not image")
    return root


def test_discovery_skips_outputs_and_junk(tmp_path):
    root = _make_root(tmp_path)
    found = BatchManager(root).discover_subfolders()
    names = sorted(p.name for p in found)
    assert names == ["beach", "city", "forest"]


def test_is_done_only_when_aligned_output_has_images(tmp_path):
    root = _make_root(tmp_path)
    bm = BatchManager(root)
    assert not bm.is_done(root / "beach")
    assert not bm.is_done(root / "forest")
    assert bm.is_done(root / "city")


def test_empty_aligned_output_is_not_done(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _img(root / "a")
    (root / "a_aligned").mkdir()
    assert not BatchManager(root).is_done(root / "a")


def test_build_queue_marks_done(tmp_path):
    root = _make_root(tmp_path)
    q = BatchManager(root).build_queue()
    by_name = {item["name"]: item for item in q}
    assert by_name["city"]["done"] is True
    assert by_name["beach"]["done"] is False


def test_next_pending_skips_done(tmp_path):
    root = _make_root(tmp_path)
    nxt = BatchManager(root).next_pending()
    assert nxt is not None
    assert nxt.name in ("beach", "forest")


def test_loose_images_in_root_are_an_implicit_batch(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _img(root, "loose1.jpg")
    _img(root / "sub")
    bm = BatchManager(root)
    names = sorted(p.name for p in bm.discover_subfolders())
    assert "sub" in names
    assert bm.aligned_output_for(root) == root.parent / "root_aligned"


def test_merge_prefixes_and_copies_all(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _img(root / "fuji", "img_0042.jpg")
    _img(root / "nikon", "img_0007.jpg")
    dest = tmp_path / "merged"
    report = merge_folders([root / "fuji", root / "nikon"], dest, use_aligned=False)
    files = sorted(p.name for p in dest.iterdir())
    assert files == ["fuji_img_0042.jpg", "nikon_img_0007.jpg"]
    assert report["merged_count"] == 2
    assert report["skipped"] == 0


def test_merge_uses_aligned_output_when_flagged(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    folder = root / "set_a"
    _img(folder / "originals", "raw1.jpg")
    _img(root / "set_a_aligned", "0000.jpg")
    dest = tmp_path / "merged"
    report = merge_folders([folder], dest, use_aligned=True)
    files = sorted(p.name for p in dest.iterdir())
    assert files == ["set_a_0000.jpg"]          # aligned image, not originals
    assert report["warnings"] == []


def test_merge_uses_raw_when_no_aligned_output(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    folder = root / "set_b"
    _img(folder, "raw1.jpg")
    dest = tmp_path / "merged"
    report = merge_folders([folder], dest, use_aligned=True)
    assert [p.name for p in dest.iterdir()] == ["set_b_raw1.jpg"]


def test_merge_dedupes_name_collisions(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    a = root / "a"
    b = root / "b"
    _img(a, "img.jpg")
    _img(b, "img.jpg")
    dest = tmp_path / "merged"
    merge_folders([a, b], dest, use_aligned=False)
    files = sorted(p.name for p in dest.iterdir())
    assert files == ["a_img.jpg", "b_img.jpg"]  # prefixes make them unique


def test_move_aligned_outputs(tmp_path):
    root = tmp_path / "photos"
    root.mkdir()
    _img(root / "a_aligned", "0000.jpg")
    _img(root / "b_aligned", "0001.jpg")
    _img(root / "plain")            # untouched raw folder
    report = move_aligned_outputs(root)
    dest = tmp_path / "photos_aligned"
    assert report["dest"] == str(dest)
    assert (dest / "a_aligned" / "0000.jpg").exists()
    assert (dest / "b_aligned" / "0001.jpg").exists()
    assert not (root / "a_aligned").exists()
    assert (root / "plain").exists()


def test_move_aligned_destination_name(tmp_path):
    root = tmp_path / "whatever"
    root.mkdir()
    _img(root / "c_aligned", "0000.jpg")
    report = move_aligned_outputs(root)
    assert tmp_path.joinpath("whatever_aligned").is_dir()
    assert set(report["moved"]) == {str(tmp_path / "whatever_aligned" / "c_aligned")}


def test_discover_all_includes_aligned_folders(tmp_path):
    root = _make_root(tmp_path)
    found = BatchManager(root).discover_all_folders()
    names = sorted(p.name for p in found)
    assert "city_aligned" in names
    assert names == ["beach", "city", "city_aligned", "forest"]


def test_discover_all_excludes_discarded_and_preview(tmp_path):
    root = _make_root(tmp_path)
    _img(root / "preview_cache_preview_landscape")
    found = BatchManager(root).discover_all_folders()
    names = sorted(p.name for p in found)
    assert "discarded" not in names
    assert "preview_cache_preview_landscape" not in names


def test_aligned_folder_in_queue_is_done(tmp_path):
    root = _make_root(tmp_path)
    q = BatchManager(root).build_queue()
    by_name = {item["name"]: item for item in q}
    assert by_name["city_aligned"]["done"] is True


def test_discover_subfolders_still_skips_aligned(tmp_path):
    root = _make_root(tmp_path)
    found = BatchManager(root).discover_subfolders()
    assert sorted(p.name for p in found) == ["beach", "city", "forest"]


def test_folder_is_aligned(tmp_path):
    from batch import folder_is_aligned
    root = _make_root(tmp_path)
    assert folder_is_aligned(root / "city_aligned") is True
    assert folder_is_aligned(root / "city") is True
    assert folder_is_aligned(root / "beach") is False