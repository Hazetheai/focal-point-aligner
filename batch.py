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


def folder_is_aligned(folder, use_aligned=True) -> bool:
    """True when merging `folder` contributes aligned output for the given
    checkbox state: the folder itself is an '*_aligned' folder containing
    images, or (only when use_aligned) it has an aligned output with images."""
    folder = Path(folder)
    if folder.name.lower().endswith("_aligned"):
        return _contains_images(folder)
    return use_aligned and _contains_images(_aligned_output_for(folder))


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
            if _contains_images(sub) or _contains_images(_aligned_output_for(sub)):
                folders.append(sub)
        if _contains_images(self.root):
            folders.insert(0, self.root)
        return folders

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
            output = self.aligned_output_for(folder)
            if folder.name.lower().endswith("_aligned"):
                output = folder
            queue.append({
                "name": name,
                "path": str(folder),
                "output": str(output),
                "done": done,
            })
        return queue

    def next_pending(self):
        """First not-done folder, or None when every batch is finished."""
        for folder in self.discover_subfolders():
            if not self.is_done(folder):
                return folder
        return None


def merge_folders(sources, dest, use_aligned=True, delete_sources=False) -> dict:
    """Copy images from each source folder into dest, prefixing each file with
    its source folder name. Returns a report dict.

    dest is created lazily, only when the first image is copied. When
    delete_sources is True, every source whose images were fully merged is
    removed afterwards (by rmtree); failed sources are never deleted."""
    dest = Path(dest)

    merged_count = 0
    skipped = 0
    warnings = []
    deleted = []
    failed_sources = set()
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
                failed_sources.add(Path(src))
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
                if merged_count == 0:
                    dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img, dest / new_name)
                merged_count += 1
            except OSError as e:
                skipped += 1
                failed_sources.add(Path(src))
                warnings.append(f"Could not copy {img.name} from {src_name}: {e}")

    if delete_sources:
        for src in sources:
            src = Path(src)
            if src in failed_sources:
                continue
            if not src.exists():
                continue
            if Path(dest) == src or Path(dest).is_relative_to(src):
                warnings.append(f"Not deleting {src}: merged output lies inside it")
                continue
            try:
                shutil.rmtree(src)
                deleted.append(str(src))
            except OSError as e:
                warnings.append(f"Could not delete {src}: {e}")

    return {
        "merged_count": merged_count,
        "skipped": skipped,
        "warnings": warnings,
        "deleted": deleted,
        "dest": str(dest),
    }


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