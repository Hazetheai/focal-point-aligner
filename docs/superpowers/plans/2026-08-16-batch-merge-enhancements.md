# Batch Merge Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Ctrl/Shift multi-select in the batch and merge lists, let the user name the merged folder, show every folder (including `*_aligned`) in the batch list, and auto-suffix `_aligned` when all merged sources are aligned.

**Architecture:** Two layers. `batch.py` (UI-free) gains `discover_all_folders()` for the batch *list* (keeping `discover_subfolders()` narrow for auto-advance) and a `folder_is_aligned()` predicate. The Qt layer (`ui/opener_screen.py`, `ui/merge_dialog.py`) wires multi-select, replaces the output-browse with a name field, and computes the destination.

**Tech Stack:** Python, PyQt6, pytest (offscreen), `os.path.commonpath`.

---

### Task 1: `batch.py` — `discover_all_folders()` + `folder_is_aligned()`

**Files:**
- Modify: `batch.py`
- Test: `tests/test_batch.py`

- [ ] **Step 1: Write failing tests for `discover_all_folders`**

Append to `tests/test_batch.py`:

```python
def test_discover_all_includes_aligned_folders(tmp_path):
    root = _make_root(tmp_path)
    found = BatchManager(root).discover_all_folders()
    names = sorted(p.name for p in found)
    assert "city_aligned" in names
    assert names == ["beach", "city", "city_aligned", "forest"]


def test_discover_all_excludes_discarded_and_preview(tmp_path):
    root = _make_root(tmp_path)
    _img(root / "preview_cache_preview_landscape")
    (root / "discarded").mkdir()
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_batch.py::test_discover_all_includes_aligned_folders tests/test_batch.py::test_discover_all_excludes_discarded_and_preview tests/test_batch.py::test_aligned_folder_in_queue_is_done tests/test_batch.py::test_folder_is_aligned -v`
Expected: 4 FAIL (AttributeError / ImportError), `test_discover_subfolders_still_skips_aligned` PASS.

- [ ] **Step 3: Implement in `batch.py`**

In `batch.py`, after `discover_subfolders` (line ~81), add:

```python
    def discover_all_folders(self) -> list:
        """Every image-bearing subfolder, including '*_aligned' outputs,
        for display in the batch list. Discarded and preview caches excluded."""
        folders = []
        for sub in sorted(self.root.iterdir()):
            if not sub.is_dir():
                continue
            name = sub.name.lower()
            if name == "discarded":
                continue
            if "_preview_" in name:
                continue
            if _contains_images(sub):
                folders.append(sub)
        if _contains_images(self.root):
            folders.insert(0, self.root)
        return folders
```

Change `build_queue` (line ~85) to call `discover_all_folders()` and mark aligned folders done:

```python
    def build_queue(self) -> list:
        """List of dicts {name, path, output, done} sorted for the UI."""
        folders = self.discover_all_folders()
        queue = []
        for folder in folders:
            if folder == self.root:
                name = f"{self.root.name} (root files)"
            else:
                name = folder.name
            done = self.is_done(folder)
            if not done and folder.name.lower().endswith("_aligned"):
                done = _contains_images(folder)
            queue.append({
                "name": name,
                "path": str(folder),
                "output": str(self.aligned_output_for(folder)),
                "done": done,
            })
        return queue
```

At module level, after `_aligned_images` (line ~44), add:

```python
def folder_is_aligned(folder) -> bool:
    """True when a folder is aligned output: it is itself an '*_aligned'
    folder containing images, or it has an aligned output containing images."""
    folder = Path(folder)
    if folder.name.lower().endswith("_aligned"):
        return _contains_images(folder)
    return _contains_images(_aligned_output_for(folder))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/test_batch.py -v`
Expected: all PASS (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add batch.py tests/test_batch.py
git commit -m "feat(batch): list aligned folders in queue; add folder_is_aligned"
```

---

### Task 2: `ui/merge_dialog.py` — multi-select + name field + `_aligned` suffix

**Files:**
- Modify: `ui/merge_dialog.py`

- [ ] **Step 1: Multi-select on the source list**

In `_build_ui`, after `self.source_list = QListWidget()` (line ~52) add:

```python
        self.source_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
```

Add `QAbstractItemView` to the `PyQt6.QtWidgets` import block (line ~9-12):

```python
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QLineEdit, QMessageBox, QFileDialog, QListWidget, QDialogButtonBox,
    QAbstractItemView,
)
```

- [ ] **Step 2: Replace output browse with a name field**

Replace the `out_row` block (lines ~67-76) with:

```python
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Merged folder name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setText("merged")
        self.name_edit.setStyleSheet(styles.INPUT_FIELD)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)
```

Remove `_browse_output` (lines ~106-110). Update the help text (lines ~43-50):

```python
        help_label = QLabel(
            "Combines images from the selected folders into one output folder.\n"
            "Each file is prefixed with its source folder name (e.g. fuji_img_0042.jpg).\n"
            "If a folder has an aligned output, its aligned images are used instead.\n"
            "Tip: Ctrl/Shift-click to select multiple folders. If every selected\n"
            "folder is aligned, '_aligned' is appended to the output name."
        )
```

Remove `QFileDialog` from the import block if now unused (it is unused after removing `_browse_add`/`_browse_output` is NOT the case — `_browse_add` still uses it; keep it).

- [ ] **Step 3: Compute destination and auto-suffix in `_on_merge`**

Replace the body of `_on_merge` (lines ~112-131) with:

```python
    def _on_merge(self):
        import os
        from batch import folder_is_aligned

        sources = [Path(self.source_list.item(i).text())
                   for i in range(self.source_list.count())]
        if not sources:
            QMessageBox.warning(self, "No Folders", "Add at least one folder to merge.")
            return
        name = self.name_edit.text().strip() or "merged"
        if all(folder_is_aligned(s) for s in sources) and not name.lower().endswith("_aligned"):
            name += "_aligned"
        try:
            parent = Path(os.path.commonpath([str(s) for s in sources]))
        except ValueError:
            parent = sources[0].parent
        output = parent / name
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

- [ ] **Step 4: Sanity-import the dialog offscreen**

Run:
```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python - <<'PY'
import sys
from PyQt6.QtWidgets import QApplication, QAbstractItemView
app = QApplication([])
from ui.merge_dialog import MergeDialog
d = MergeDialog(sources=["/tmp/a", "/tmp/b"])
assert d.source_list.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
assert d.name_edit.text() == "merged"
print("merge dialog ok")
PY
```
Expected: prints `merge dialog ok`.

- [ ] **Step 5: Commit**

```bash
git add ui/merge_dialog.py
git commit -m "feat(merge): multi-select sources, name the merged folder, auto _aligned suffix"
```

---

### Task 3: `ui/opener_screen.py` — multi-select on the batch list

**Files:**
- Modify: `ui/opener_screen.py`

- [ ] **Step 1: Enable extended selection on `batch_list`**

In `_build_batch_page`, after `self.batch_list = QListWidget()` (line ~431) add:

```python
        self.batch_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
```

Add `QAbstractItemView` to the `PyQt6.QtWidgets` import block (lines ~9-14).

- [ ] **Step 2: Sanity-check `get_selected_batch_paths`**

The existing `get_selected_batch_paths()` (line ~487) already returns
`[item.data(...) for item in self.batch_list.selectedItems()]`, which now
yields multiple paths. No change needed.

- [ ] **Step 3: Import-check the opener offscreen**

Run:
```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python - <<'PY'
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ui.opener_screen import OpenerScreen
o = OpenerScreen()
print("opener ok")
PY
```
Expected: prints `opener ok`.

- [ ] **Step 4: Commit**

```bash
git add ui/opener_screen.py
git commit -m "feat(opener): multi-select batches for merging"
```

---

### Task 4: Full verification + docs

**Files:**
- Modify: `README.md`, `AGENTS.md`
- Test: `tests/test_batch.py`

- [ ] **Step 1: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen ./venv/bin/python -m pytest tests/ -v`
Expected: all tests PASS.

- [ ] **Step 2: Update `README.md` "Merge Folders" section**

Add a sentence: "Ctrl/Shift-click to select multiple folders. You can name the
merged folder (default `merged`); if every selected folder is aligned, the
output is automatically suffixed `_aligned`."

- [ ] **Step 3: Update `AGENTS.md` batch-mode section**

Add bullets:
```markdown
- The batch **list** (`build_queue` via `discover_all_folders`) shows every
  image-bearing subfolder including `*_aligned`; `*_aligned` folders report
  `done=True`. Auto-advance (`next_pending`) uses the narrow
  `discover_subfolders` and never re-opens aligned outputs.
- `batch.folder_is_aligned(folder)` — True when a folder is `*_aligned` with
  images or has an aligned output with images. The merge dialog auto-suffixes
  `_aligned` to the output name when all sources are aligned.
- Merge dialog (`ui/merge_dialog.py`) uses extended selection for multi-select
  and a "Merged folder name:" field; output = common parent of sources / name.
```

- [ ] **Step 4: Mark plan checkboxes done and commit**

```bash
git add README.md AGENTS.md docs/superpowers/plans/2026-08-16-batch-merge-enhancements.md
git commit -m "docs: batch merge multi-select, naming, and aligned-folder listing"
```

---

## Self-Review

- **Spec coverage:** multi-select (Tasks 2-3) · name field (Task 2) ·
  `discover_all_folders` (Task 1) · `_aligned` suffix (Task 2) ·
  docs/tests (Tasks 1, 4). All spec sections map to a task.
- **No placeholders:** every step has concrete code/commands.
- **Type consistency:** `folder_is_aligned`, `discover_all_folders`,
  `name_edit`, `get_selected_batch_paths` all referenced consistently.
