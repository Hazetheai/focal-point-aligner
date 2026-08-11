# Batch Mode, Merge & Move Aligned — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add batch (root-folder) mode with automatic advance between sub-folders, a folder-merge tool, and a move-aligned-to-`<root>_aligned` operation.

**Architecture:** A new UI-free core module `batch.py` (`BatchManager` + module functions) provides discovery, done-detection, merge, and move logic — the same pattern as `aligner_core.py`. The opener screen gains a Single/Batch toggle and batch controls; `main.py` handles auto-advance by opening the next pending folder when a batch batch finishes. A new merge dialog reuses `batch.py`.

**Tech Stack:** Python 3, PyQt6, pytest (offscreen Qt for GUI tests). Tests run with `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/`.

---

## File Map

| File | Responsibility | Change |
|------|----------------|--------|
| `batch.py` | UI-free batch logic: `BatchManager`, `merge_folders`, `move_aligned_outputs` | Create |
| `tests/test_batch.py` | Unit tests for `batch.py` | Create |
| `ui/opener_screen.py` | Single/Batch toggle, batch folder list + controls, merge entry | Modify |
| `ui/merge_dialog.py` | Multi-source folder merge dialog | Create |
| `main.py` | Batch state, `_open_next_batch_folder`, batch-aware `on_aligner_finished` | Modify |
| `tests/test_return_to_opener.py` | Add batch auto-advance GUI test | Modify |
| `README.md`, `AGENTS.md` | Docs | Modify |

Conventions: follow existing code (module classes, `logger` from `ui.logger` optional in core — core must NOT import Qt; keep logging optional like `aligner_core.py` does).

---

### Task 1: `batch.py` — discovery, done detection, queue

**Files:**
- Create: `batch.py`
- Create: `tests/test_batch.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for batch.py - UI-free batch pipeline logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from batch import BatchManager, IMAGE_EXTENSIONS


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd FocalPointAligner && QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_batch.py -v`
Expected: `ModuleNotFoundError: No module named 'batch'`

- [ ] **Step 3: Implement `batch.py`**

```python
"""
Batch pipeline logic for the Focal Point Aligner - UI-free.

Provides discovery / done-detection / ordering for batch (root-folder) mode,
plus the merge and move-aligned operations. No Qt imports.
"""

import shutil
from pathlib import Path

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}

try:
    from ui.logger import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


def _contains_images(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        return any(
            f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
            for f in path.iterdir()
        )
    except OSError:
        return False


def _aligned_output_for(folder: Path) -> Path:
    return folder.parent / f"{folder.name}_aligned"


def _aligned_images(folder: Path):
    out = _aligned_output_for(folder)
    if not out.is_dir():
        return None
    imgs = sorted(
        f for f in out.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )
    return imgs or None


class BatchManager:
    """Manages a root folder of sub-folders to be aligned in sequence."""

    def __init__(self, root):
        self.root = Path(root)

    def aligned_output_for(self, folder: Path) -> Path:
        """Output folder for a batch item (matches AlignerScreen defaults)."""
        if Path(folder) == self.root:
            return self.root.parent / f"{self.root.name}_aligned"
        return _aligned_output_for(Path(folder))

    def is_done(self, folder: Path) -> bool:
        """A batch item is done when its aligned output exists and has images."""
        return _contains_images(self.aligned_output_for(folder))

    def discover_subfolders(self) -> list:
        """Folders to process: image-bearing sub-folders (or un-done aligned
        outputs) plus the root itself when it holds loose images."""
        folders = []
        for sub in sorted(self.root.iterdir()):
            if not sub.is_dir():
                continue
            name = sub.name.lower()
            if name in ("discarded",):
                continue
            if name.endswith("_aligned"):
                continue
            if "_preview_" in name:
                continue
            if _contains_images(sub) or _contains_images(_aligned_output_for(sub)):
                folders.append(sub)
        if _contains_images(self.root):
            folders.insert(0, self.root)
        return folders

    def build_queue(self) -> list:
        """List of dicts {name, path, output, done} sorted for the UI."""
        folders = self.discover_subfolders()
        queue = []
        for folder in folders:
            if folder == self.root:
                name = f"{self.root.name} (root files)"
            else:
                name = folder.name
            queue.append({
                "name": name,
                "path": str(folder),
                "output": str(self.aligned_output_for(folder)),
                "done": self.is_done(folder),
            })
        return queue

    def next_pending(self):
        """First not-done folder, or None when every batch is finished."""
        for folder in self.discover_subfolders():
            if not self.is_done(folder):
                return folder
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd FocalPointAligner && QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_batch.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add batch.py tests/test_batch.py
git commit -m "feat(batch): add BatchManager discovery and done detection"
```

---

### Task 2: `batch.py` — merge

- [ ] **Step 1: Write the failing test** (append to `tests/test_batch.py`)

```python
from batch import merge_folders


def _make_aligned_batch(root, name):
    folder = root / name
    raw = folder / "originals"          # raw image also present
    _img(raw)
    out = root / f"{name}_aligned"      # aligned output used for merge
    _img(out, "0000.jpg")
    return folder, out


def test_merge_prefixes_and_copies_all(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    _img(root / "fuji", "img_0042.jpg")
    _img(root / "nikon", "img_0007.jpg")
    dest = tmp_path / "merged"
    report = merge_folders([root / "_x" if False else root / "fuji",
                            root / "nikon"], dest, use_aligned=False)
    files = sorted(p.name for p in dest.iterdir())
    assert files == ["fuji_img_0042.jpg", "nikon_img_0007.jpg"]
    assert report["merged_count"] == 2
    assert report["skipped"] == 0


def test_merge_uses_aligned_output_when_flagged(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    folder, _ = _make_aligned_batch(root, "set_a")
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch.py -v`
Expected: `ImportError: cannot import name 'merge_folders'`

- [ ] **Step 3: Implement merge** (append to `batch.py`)

```python
def merge_folders(sources, dest, use_aligned=True) -> dict:
    """Copy images from each source folder into dest, prefixing each file with
    its source folder name. Returns a report dict."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)

    merged_count = 0
    skipped = 0
    warnings = []
    used_names = set()

    for src in sources:
        src = Path(src)
        src_name = src.name
        if use_aligned:
            imgs = _aligned_images(src) or sorted(
                f for f in src.iterdir()
                if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
            )
        else:
            try:
                imgs = sorted(
                    f for f in src.iterdir()
                    if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
                )
            except OSError as e:
                skipped += 1
                warnings.append(f"{src_name}: {e}")
                continue

        for img in imgs:
            new_name = f"{src_name}_{img.name}"
            if new_name.lower() in used_names:
                stem, ext = img.stem, img.suffix
                k = 2
                while f"{stem}_{k}{ext}" in used_names:
                    k += 1
                new_name = f"{src_name}_{stem}_{k}{ext}"
            used_names.add(new_name.lower())
            try:
                shutil.copy2(img, dest / new_name)
                merged_count += 1
            except OSError as e:
                skipped += 1
                warnings.append(f"Could not copy {img.name} from {src_name}: {e}")

    return {
        "merged_count": merged_count,
        "skipped": skipped,
        "warnings": warnings,
        "dest": str(dest),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_batch.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add batch.py tests/test_batch.py
git commit -m "feat(batch): add merge_folders with prefix + dedupe"
```

---

### Task 3: `batch.py` — move aligned outputs

- [ ] **Step 1: Write the failing test** (append to `tests/test_batch.py`)

```python
from batch import move_aligned_outputs


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch.py -v`
Expected: `ImportError: cannot import name 'move_aligned_outputs'`

- [ ] **Step 3: Implement move** (append to `batch.py`)

```python
def move_aligned_outputs(root: Path) -> dict:
    """Move every '<name>_aligned' folder under root into a sibling folder named
    '<root>_aligned'. Returns {moved, dest}."""
    root = Path(root)
    dest = root.parent / f"{root.name}_aligned"
    dest.mkdir(parents=True, exist_ok=True)
    moved = []

    for sub in sorted(root.iterdir()):
        if not sub.is_dir() or not sub.name.lower().endswith("_aligned"):
            continue
        target = dest / sub.name
        if target.exists():
            for f in sub.iterdir():
                if f.is_file() and not (target / f.name).exists():
                    shutil.move(str(f), str(target / f.name))
            try:
                sub.rmdir()
            except OSError:
                pass
        else:
            shutil.move(str(sub), str(target))
        moved.append(str(target))

    return {"moved": moved, "dest": str(dest)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_batch.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add batch.py tests/test_batch.py
git commit -m "feat(batch): add move_aligned_outputs"
```

---

### Task 4: `ui/opener_screen.py` — mode toggle + batch controls

**Files:**
- Modify: `ui/opener_screen.py`

- [ ] **Step 1: Read current file** to confirm line anchors (it already exists; sections: `__init__`, `_build_ui`, `_browse_*`, `_apply_preset`, drag/drop, `on_start_clicked`).

- [ ] **Step 2: Add signals, mode state and batch widgets**

Add to class header:
```python
    batch_started = pyqtSignal(dict)
```

In `__init__`, after existing state:
```python
        self._mode = self._config.get('mode', 'single')
        self.batch_manager = None
        _ = self._mode
```

- [ ] **Step 3: Add UI elements.** Insert a mode selector under the welcome label, wrap the existing single-folder groups (input/size/output) into `self._general_group`, and add a batch group. Show/hide via `refresh_visibility()`; add `refresh_visibility()` call at end of `_build_ui()`. Add the following methods to the class:

```python
    def refresh_visibility(self):
        """Show either single-folder or batch controls based on _mode."""
        is_batch = self._mode == 'batch'
        self._config_stack.setCurrentIndex(1 if is_batch else 0)
        self.start_btn.setText("🚀  Start" if not is_batch else "🚀  Start Batch")
        self._save_config()
```

**Important:** the remaining steps of this task are intentionally deferred to the concrete wiring step below to keep them inspectable; see Task 6 for the full new/edited code.

- [ ] **Step 4: Commit nothing yet** — Task 6 contains the full file delta. (Tasks 4–6 are edited together to avoid a broken intermediate.)

---

### Task 5: `ui/merge_dialog.py` (new)

- [ ] **Step 1: Write the dialog**

```python
"""
Merge dialog: combine images from multiple folders into one output folder,
prefixing each file with its source folder name.
"""

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QLineEdit, QMessageBox, QFileDialog, QListWidget, QDialogButtonBox
)

import styles
from batch import merge_folders


class MergeDialog(QDialog):
    """Multi-folder merge dialog. Emits merge_complete(dict) on success."""

    merge_complete = pyqtSignal(dict)

    def __init__(self, sources=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge Folders")
        self.setMinimumSize(520, 420)
        self.setModal(True)
        self.setPalette(styles.get_palette())
        self._build_ui()
        if sources:
            for src in sources:
                self._add_source(Path(src))

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        title = QLabel("Merge Folders")
        title.setStyleSheet(styles.TITLE_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        help_label = QLabel(
            "Combines images from the selected folders into one output folder.\n"
            "Each file is prefixed with its source folder name (e.g. fuji_img_0042.jpg).\n"
            "If a folder has an aligned output, its aligned images are used instead."
        )
        help_label.setStyleSheet(styles.LABEL_STYLE)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.source_list = QListWidget()
        layout.addWidget(self.source_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add folders…")
        add_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        add_btn.clicked.connect(self._browse_add)
        remove_btn = QPushButton("Remove selected")
        remove_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder:"))
        self.output_edit = QLineEdit()
        self.output_edit.setStyleSheet(styles.INPUT_FIELD)
        out_row.addWidget(self.output_edit, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        self.aligned_check = QCheckBox("Use aligned outputs when present")
        self.aligned_check.setChecked(True)
        self.aligned_check.setStyleSheet(styles.LABEL_STYLE)
        layout.addWidget(self.aligned_check)

        buttons = QDialogButtonBox()
        back_btn = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        merge_btn = buttons.addButton("Merge", QDialogButtonBox.ButtonRole.AcceptRole)
        back_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        merge_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        buttons.accepted.connect(self._on_merge)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _add_source(self, folder):
        self.source_list.addItem(str(folder))

    def _remove_selected(self):
        for item in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(item))

    def _browse_add(self):
        dlg = QFileDialog.getExistingDirectory(self, "Add Folder", str(Path.home()))
        if dlg:
            self._add_source(Path(dlg))

    def _browse_output(self):
        dlg = QFileDialog.getExistingDirectory(
            self, "Output Folder", self.output_edit.text() or str(Path.home()))
        if dlg:
            self.output_edit.setText(dlg)

    def _on_merge(self):
        sources = [Path(self.source_list.item(i).text())
                   for i in range(self.source_list.count())]
        if not sources:
            QMessageBox.warning(self, "No Folders", "Add at least one folder to merge.")
            return
        output = self.output_edit.text().strip()
        if not output:
            output = str(sources[0].parent / "merged")
        report = merge_folders(
            sources, output, use_aligned=self.aligned_check.isChecked())
        QMessageBox.information(
            self,
            "Merge Complete",
            f"Merged {report['merged_count']} images into:\n{report['dest']}\n\n"
            + (f"{report['skipped']} skipped.\n" if report["skipped"] else "")
            + ("Warnings:\n" + "\n".join(report["warnings"]) if report["warnings"] else "")
        )
        self.merge_complete.emit(report)
        self.accept()
```

- [ ] **Step 2: Run a syntax check**

Run: `./venv/bin/python -m py_compile ui/merge_dialog.py`
Expected: no output (exit 0)

- [ ] **Step 3: Commit**

```bash
git add ui/merge_dialog.py
git commit -m "feat(ui): add MergeDialog"
```

---

### Task 6: Full `ui/opener_screen.py` batch wiring

- [ ] **Step 1: Apply edits to `ui/opener_screen.py`**

Edit 1 — imports (`QListWidget` needs to come from `PyQt6.QtWidgets`):
```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QSpinBox, QGroupBox,
    QFileDialog, QMessageBox, QGridLayout, QStackedWidget,
    QListWidget, QListWidgetItem, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal

import styles
from batch import BatchManager
from ui.merge_dialog import MergeDialog
```

Edit 2 — class signals (add to `OpenerScreen`):
```python
    start_clicked = pyqtSignal(dict)
    batch_started = pyqtSignal(dict)
```

Edit 3 — in `__init__`, add `self._mode` after `_load_config`:
```python
        self._mode = self._config.get('mode', 'single')
        self._batch_root = Path(self._config.get('last_batch_root_dir', '')) if self._config.get('last_batch_root_dir') else None
        self.batch_manager = None
        self._merge_dialog = None
```

Edit 4 — replace the block that adds `input_group`, `size_group`, `output_group`, and the stretch+start button in `_build_ui` with a mode selector, a `QStackedWidget` (page 0 = existing three groups, page 1 = batch widgets), and keep the Start button + a **Merge…** button. Add these new methods to the class:

```python
    def _build_mode_row(self):
        row = QHBoxLayout()
        row.addStretch()
        self._single_radio = QRadioButton("Single Folder")
        self._batch_radio = QRadioButton("Batch (Root)")
        for rb in (self._single_radio, self._batch_radio):
            rb.setStyleSheet(styles.LABEL_STYLE)
        group = QButtonGroup(self)
        group.addButton(self._single_radio)
        group.addButton(self._batch_radio)
        self._single_radio.toggled.connect(self._on_radio_changed)
        row.addWidget(self._single_radio)
        row.addWidget(self._batch_radio)
        row.addStretch()
        # initial state
        self._single_radio.setChecked(self._mode == 'single')
        self._batch_radio.setChecked(self._mode == 'batch')
        return row

    def _on_radio_changed(self):
        self._mode = 'batch' if self._batch_radio.isChecked() else 'single'
        self._config['mode'] = self._mode
        self._save_config()
        self._update_mode_display()

    def _on_merge(self):
        self._merge_dialog = MergeDialog(parent=self)
        self._merge_dialog.show()

    def _update_mode_display(self):
        is_batch = self._mode == 'batch'
        self._config_stack.setCurrentIndex(1 if is_batch else 0)
        self.start_btn.setText("🚀  Start Batch" if is_batch else "🚀  Start")
```

For the batch page, add a `_build_batch_page()` method returning a `QWidget`:
```python
    def _build_batch_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(styles.SPACING['md'])

        root_group = QGroupBox("Root Folder (contains one sub-folder per batch)")
        root_group.setStyleSheet(styles.CARD_STYLE)
        root_row = QHBoxLayout()
        self.batch_root_edit = QLineEdit()
        self.batch_root_edit.setReadOnly(True)
        self.batch_root_edit.setStyleSheet(styles.INPUT_FIELD)
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        browse_btn.clicked.connect(self.browse_batch_root)
        root_row.addWidget(self.batch_root_edit, 1)
        root_row.addWidget(browse_btn)
        root_group.setLayout(root_row)
        lay.addWidget(root_group)

        list_group = QGroupBox("Batches")
        list_group.setStyleSheet(styles.CARD_STYLE)
        list_lay = QVBoxLayout()
        self.batch_list = QListWidget()
        list_lay.addWidget(self.batch_list, 1)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        refresh_btn.clicked.connect(self.refresh_batch_queue)
        merge_btn = QPushButton("Merge selected…")
        merge_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        merge_btn.clicked.connect(self._on_merge_selected)
        move_btn = QPushButton("Move aligned → root_aligned")
        move_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        move_btn.clicked.connect(self._on_move_aligned)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(merge_btn)
        btn_row.addWidget(move_btn)
        btn_row.addStretch()
        list_lay.addLayout(btn_row)
        list_group.setLayout(list_lay)
        lay.addWidget(list_group, 1)
        return page

    def browse_batch_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Root Folder", str(Path.home()))
        if folder:
            self.set_batch_root(Path(folder))

    def set_batch_root(self, root: Path):
        self._batch_root = root
        self.batch_root_edit.setText(str(root))
        self._config['last_batch_root_dir'] = str(root)
        self._save_config()
        self.refresh_batch_queue()

    def refresh_batch_queue(self):
        if not self._batch_root or not self._batch_root.is_dir():
            self.batch_list.clear()
            return
        self.batch_manager = BatchManager(self._batch_root)
        self.set_batch_queue(self.batch_manager.build_queue())

    def set_batch_queue(self, queue: list):
        self.batch_list.clear()
        for item in queue:
            status = "✅ done" if item["done"] else "⏳ pending"
            entry = QListWidgetItem(f"{status}   {item['name']}")
            entry.setData(Qt.ItemDataRole.UserRole, item["path"])
            self.batch_list.addItem(entry)

    def get_selected_batch_paths(self):
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self.batch_list.selectedItems()]

    def _on_merge_selected(self):
        paths = self.get_selected_batch_paths()
        if not paths:
            QMessageBox.info(self, "No Selection", "Select at least one batch to merge.")
            return
        self._merge_dialog = MergeDialog(sources=paths, parent=self)
        self._merge_dialog.show()

    def _on_move_aligned(self):
        if not self._batch_root:
            QMessageBox.warning(self, "No Root", "Choose a root folder first.")
            return
        from batch import move_aligned_outputs
        report = move_aligned_outputs(self._batch_root)
        self.refresh_batch_queue()
        QMessageBox.information(
            self, "Moved Aligned",
            (f"Moved {len(report['moved'])} aligned folder(s) to:\n{report['dest']}"
             if report["moved"] else "No aligned output folders found to move."))

    def _apply_batch_config(self):
        if not self._batch_root or not self._batch_root.is_dir():
            QMessageBox.warning(self, "No Root", "Choose a valid root folder.")
            return None
        if self.batch_manager is None:
            self.refresh_batch_queue()
        pending = self.batch_manager.next_pending() if self.batch_manager else None
        if pending is None:
            QMessageBox.information(self, "All Batches Complete",
                                    "Every batch in this root is already aligned.")
            return None
        return {
            'root': str(self._batch_root),
            'target_width': self.width_spin.value(),
            'target_height': self.height_spin.value(),
        }
```

Modify `on_start_clicked` to branch on mode:
```python
    def on_start_clicked(self):
        if self._mode == 'batch':
            config = self._apply_batch_config()
            if config:
                self.batch_started.emit(config)
            return
        # ... existing single-folder logic unchanged below this line ...
```

- [ ] **Step 2: Compile + smoke test**

Run: `./venv/bin/python -m py_compile ui/opener_screen.py ui/merge_dialog.py batch.py main.py`
Expected: no output (exit 0)

Run existing suite (opener tests) — `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_return_to_opener.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add ui/opener_screen.py ui/merge_dialog.py
git commit -m "feat(ui): add Single/Batch toggle and batch controls to opener"
```

---

### Task 7: `main.py` — batch auto-advance

- [ ] **Step 1: Modify `main.py`**

In `__init__`, add batch fields:
```python
        self.batch_mode = False
        self.batch_root = None
        self.batch_manager = None
        self._batch_target_width = 2560
        self._batch_target_height = 1440
```

Add batch connection in `start()`:
```python
        self.opener.start_clicked.connect(self.on_start_clicked)
        self.opener.batch_started.connect(self.on_batch_started)
```

In `on_start_clicked`, before building the aligner:
```python
        self.batch_mode = False
        self.batch_root = None
        self.batch_manager = None
```

Add new methods:
```python
    def on_batch_started(self, config: dict):
        """Enter batch mode: hide opener and load the first pending sub-folder."""
        from pathlib import Path
        from batch import BatchManager
        self.batch_mode = True
        self.batch_root = Path(config['root'])
        self.batch_manager = BatchManager(self.batch_root)
        self._batch_target_width = config.get('target_width', 2560)
        self._batch_target_height = config.get('target_height', 1440)
        self.opener.hide()
        self._open_next_batch_folder()

    def _open_next_batch_folder(self):
        """Load the next pending batch folder into the aligner, or show the
        all-complete queue."""
        nxt = self.batch_manager.next_pending() if self.batch_manager else None
        if nxt is None:
            self.opener.refresh_batch_queue()
            self.opener.show()
            self.opener.raise_()
            self.opener.activateWindow()
            return
        config = {
            'input_folder': str(nxt),
            'output_folder': str(self.batch_manager.aligned_output_for(nxt)),
            'target_width': self._batch_target_width,
            'target_height': self._batch_target_height,
        }
        self.current_config = config
        self.aligner_screen = AlignerScreen(config)
        self.aligner_screen.aligner_finished.connect(self.on_aligner_finished)
        self.aligner_screen.quit_requested.connect(self.on_aligner_finished)
        self.aligner_screen.show()
```

Modify `on_aligner_finished` (keep return-to-opener for single mode, advance for batch):
```python
    def on_aligner_finished(self, stats: dict):
        """Handle aligner completion. Single mode: return to opener. Batch
        mode: tear down and auto-open the next pending sub-folder."""
        if self.aligner_screen:
            self.aligner_screen.close()
            self.aligner_screen.deleteLater()
            self.aligner_screen = None
        if self.batch_mode and self.batch_manager:
            self._open_next_batch_folder()
        else:
            self._show_opener()
```

- [ ] **Step 2: Verify imports/circularity**

Run: `./venv/bin/python -m py_compile main.py`
Expected: no output (exit 0)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(batch): auto-advance through batch folders in main"
```

---

### Task 8: GUI regression + all-done tests

**Files:**
- Modify: `tests/test_return_to_opener.py`

- [ ] **Step 1: Append batch auto-advance test**

```python
def test_batch_auto_advances_and_shows_all_done(app, tmp_path):
    """Two batches: finishing the first opens the second; finishing the last
    returns to an 'all done' batch queue."""
    root = tmp_path / "root"
    (root / "set1").mkdir(parents=True)
    (root / "set2").mkdir()
    import cv2
    import numpy as np
    for folder in ("set1", "set2"):
        img = np.full((80, 120, 3), 128, dtype=np.uint8)
        cv2.imwrite(str(root / folder / "img.jpg"), img)

    app.start()
    app.on_batch_started({
        "root": str(root),
        "target_width": 120,
        "target_height": 80,
    })
    assert app.batch_mode is True
    assert app.aligner_screen is not None
    assert app.aligner_screen.aligner.input_folder.name == "set1"

    # Finish/quit batch 1 -> auto-opens batch 2
    app.on_aligner_finished({})
    assert app.aligner_screen is not None
    assert app.aligner_screen.aligner.input_folder.name == "set2"

    # Finish batch 2 -> back to opener with empty pending queue
    app.on_aligner_finished({})
    assert app.aligner_screen is None
    assert app.opener.isVisible()
    assert app.batch_manager.next_pending() is None
```

- [ ] **Step 2: Run full test suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -q`
Expected: all tests PASS (existing + new)

- [ ] **Step 3: Commit**

```bash
git add tests/test_return_to_opener.py
git commit -m "test(batch): batch auto-advance and all-done regression"
```

---

### Task 9: Docs

- [ ] **Step 1: Update `README.md`** — add batch workflow to the Workflow section and a short "Batch mode / Merge / Move aligned" subsection describing:
  - Toggle to Batch (Root) on the opener.
  - Start Batch scans the root's sub-folders; finishing a folder auto-loads the next pending one; all-done returns to the list.
  - Merge combines folders (aligned outputs used when present) with `<source>_` prefixes.
  - Move aligned moves all `<sub>_aligned` folders into sibling `<root>_aligned`.

- [ ] **Step 2: Update `AGENTS.md`** — add a row for `batch.py` in the architecture table and a short "Batch mode" note under the return-to-opener section.

- [ ] **Step 3: Commit**

```bash
git add README.md AGENTS.md
git commit -m "docs: batch mode, merge, and move aligned"
```

---

## Self-Review checklist

- [ ] Every spec section maps to a task (1–3 core, 4–6 UI, 7 wiring, 8 tests, 9 docs).
- [ ] No placeholders; every code step includes concrete code.
- [ ] Type/signature consistency: `BatchManager(root)`, `.discover_subfolders()`, `.is_done(folder)`, `.next_pending()`, `.aligned_output_for(folder)`, `.build_queue()`, `merge_folders(sources, dest, use_aligned)`, `move_aligned_outputs(root)` used identically in tests, UI, and main.