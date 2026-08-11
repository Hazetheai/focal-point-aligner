"""Tests for the return-to-opener flow: finishing a batch must show the
opener screen again (so multiple folders can be processed in sequence)
instead of quitting the application."""

import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))


def _make_images(img_dir, count=3):
    import cv2
    import numpy as np

    img_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        img[:, :] = (i * 40, i * 40, i * 40)
        cv2.imwrite(str(img_dir / f"img{i:04d}.jpg"), img)


@pytest.fixture
def app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from main import FocalPointAlignerApp

    return FocalPointAlignerApp()


def test_finish_returns_to_opener(app, tmp_path):
    """After a batch finishes, the opener screen is shown again and the
    aligner screen is torn down (instead of the app quitting)."""
    img_dir = tmp_path / "in"
    _make_images(img_dir)
    config = {
        "input_folder": str(img_dir),
        "output_folder": str(tmp_path / "out"),
        "target_width": 640,
        "target_height": 480,
    }

    # Fresh start: opener visible, no aligner.
    app.start()
    assert app.opener is not None
    assert app.opener.isVisible()

    # User picks a folder and starts a batch.
    app.on_start_clicked(config)
    assert app.aligner_screen is not None
    assert not app.opener.isVisible()

    # Batch is finished (Escape, no-images, or export complete).
    app.on_aligner_finished({})

    # Opener must be back; aligner torn down; app still alive.
    assert app.aligner_screen is None
    assert app.opener is not None
    assert app.opener.isVisible(), "opener should be visible after finishing a batch"

    # Starting a second folder works from the same opener instance.
    app.on_start_clicked(config)
    assert app.aligner_screen is not None


def test_batch_auto_advances_and_shows_all_done(app, tmp_path):
    """Two batches: finishing the first opens the second; finishing the last
    returns to an 'all done' batch queue."""
    import cv2
    import numpy as np

    root = tmp_path / "root"
    (root / "set1").mkdir(parents=True)
    (root / "set2").mkdir()
    for folder in ("set1", "set2"):
        img = np.full((80, 120, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(root / folder / "img.jpg"), img)

    def finish_batch(app):        # export simulation: write final output, then finish
        out = Path(app.current_config["output_folder"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "0000.jpg").write_bytes(b"x")
        app.on_aligner_finished({})

    app.start()
    app.on_batch_started({
        "root": str(root),
        "target_width": 120,
        "target_height": 80,
    })
    assert app.batch_mode is True
    assert app.aligner_screen is not None
    assert app.aligner_screen.aligner.input_folder.name == "set1"

    # Export + finish batch 1 -> auto-opens batch 2
    finish_batch(app)
    assert app.aligner_screen is not None
    assert app.aligner_screen.aligner.input_folder.name == "set2"

    # Export + finish batch 2 -> back to opener; queue fully done
    finish_batch(app)
    assert app.aligner_screen is None
    assert app.opener.isVisible()
    assert app.batch_manager.next_pending() is None


def test_batch_escape_without_export_advances_without_looping(app, tmp_path):
    """Escaping a batch without exporting keeps it pending but auto-advance
    must move forward, not reopen the same folder; when every folder has been
    visited, the opener batch list is shown again."""
    import cv2
    import numpy as np

    root = tmp_path / "root"
    (root / "set1").mkdir(parents=True)
    (root / "set2").mkdir()
    for folder in ("set1", "set2"):
        img = np.full((80, 120, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(root / folder / "img.jpg"), img)

    app.start()
    app.on_batch_started({
        "root": str(root),
        "target_width": 120,
        "target_height": 80,
    })
    assert app.aligner_screen.aligner.input_folder.name == "set1"

    # Escape set1 (no export) -> must NOT reopen set1; moves to set2
    app.on_aligner_finished({})
    assert app.aligner_screen is not None
    assert app.aligner_screen.aligner.input_folder.name == "set2"

    # Escape set2 -> all folders visited -> opener batch list shown
    app.on_aligner_finished({})
    assert app.aligner_screen is None
    assert app.opener.isVisible()
    # set1 is still pending (no export), so a fresh Start would resume it
    assert app.batch_manager.next_pending().name == "set1"