"""FastAPI wrapper around FocalPointAlignerCore and batch.py."""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from aligner_core import DEFAULT_MAX_ZOOM, FocalPointAlignerCore
from batch import BatchManager, folder_is_aligned, merge_folders, move_aligned_outputs

ROOT = Path(__file__).resolve().parent.parent
PREFS_PATH = ROOT / "config.json"

_session: Optional[FocalPointAlignerCore] = None
_batch: Optional[BatchManager] = None
_batch_seen: set[str] = set()


def _core() -> FocalPointAlignerCore:
    if _session is None:
        raise HTTPException(status_code=409, detail="No session. POST /session first.")
    return _session


def load_prefs() -> dict:
    if PREFS_PATH.exists():
        try:
            return json.loads(PREFS_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_prefs(data: dict) -> dict:
    merged = load_prefs()
    merged.update({k: v for k, v in data.items() if v is not None})
    PREFS_PATH.write_text(json.dumps(merged, indent=2))
    return merged


app = FastAPI(title="Focal Point Aligner API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionCreate(BaseModel):
    input_folder: str
    output_folder: Optional[str] = None
    target_width: int = 2560
    target_height: int = 1440
    max_zoom: float = DEFAULT_MAX_ZOOM


class FocalBody(BaseModel):
    x: float
    y: float
    auto_center: bool = False
    index: Optional[int] = None
    crop_scale: Optional[float] = None
    flip_h: Optional[bool] = None
    flip_v: Optional[bool] = None
    keyframe_frame: Optional[int] = None


class NavigateBody(BaseModel):
    index: Optional[int] = None
    direction: Optional[int] = None
    wrap: bool = False


class OrderBody(BaseModel):
    order: list[int]


class ExportBody(BaseModel):
    output_folder: Optional[str] = None
    orientation: str = "landscape"
    cleanup: bool = True


class ModeBody(BaseModel):
    mode: str


class MergeBody(BaseModel):
    sources: list[str]
    dest: str
    use_aligned: bool = True
    delete_sources: bool = False


class BatchRootBody(BaseModel):
    root: str


class FolderDialogBody(BaseModel):
    title: Optional[str] = "Select folder"


class FileDialogBody(BaseModel):
    title: Optional[str] = "Select file"
    types: Optional[list[str]] = None  # e.g. ["txt"]


class TargetBody(BaseModel):
    target_width: int
    target_height: int


class ImportDownloadBody(BaseModel):
    dest: str
    name: Optional[str] = None
    urls: Optional[list[str]] = None
    url_file: Optional[str] = None
    url_folder: Optional[str] = None
    name_pattern: Optional[str] = None
    folder_template: Optional[str] = None
    force: bool = False


class ArrangeAutoBody(BaseModel):
    mode: str  # color | depth | lead | faces
    slot: Optional[str] = None
    near_to_far: bool = True
    lead_index: Optional[int] = None
    axis: str = "x"
    roi: Optional[list[float]] = None


class ArrangeSlotBody(BaseModel):
    slot: str
    order_names: Optional[list[str]] = None


class ArrangeRecallBody(BaseModel):
    slot: str


class ArrangeLeaveBody(BaseModel):
    commit: bool = True


class ArrangeClearBody(BaseModel):
    slot: Optional[str] = None


class VideoRangeBody(BaseModel):
    index: Optional[int] = None
    in_frame: Optional[int] = None
    out_frame: Optional[int] = None
    work_frame: Optional[int] = None


class VideoSplitBody(BaseModel):
    index: Optional[int] = None
    at_frame: int


class VideoKeyframeBody(BaseModel):
    index: Optional[int] = None
    frame: int
    focal_x: Optional[float] = None
    focal_y: Optional[float] = None
    crop_scale: Optional[float] = None
    ease: Optional[str] = None


class VideoKeyframeMoveBody(BaseModel):
    index: Optional[int] = None
    from_frame: int
    to_frame: int


class VideoKeyframeEaseBody(BaseModel):
    index: Optional[int] = None
    frame: int
    ease: str


class VideoKeyframeDeleteBody(BaseModel):
    index: Optional[int] = None
    frame: int


def pick_folder_dialog(title: str = "Select folder") -> Optional[str]:
    """Open a native folder-only picker. Returns an absolute path, or None if cancelled."""
    system = platform.system()
    try:
        if system == "Darwin":
            script = (
                f'POSIX path of (choose folder with prompt "{title.replace(chr(34), "")}")'
            )
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return None
            path = proc.stdout.strip().rstrip("/")
            return path or None
        if system == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                f"$d.Description = '{title.replace(chr(39), '')}'; "
                "$d.ShowNewFolderButton = $true; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }"
            )
            proc = subprocess.run(
                ["powershell", "-STA", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                check=False,
            )
            path = (proc.stdout or "").strip()
            return path or None
        zenity = shutil.which("zenity")
        kdialog = shutil.which("kdialog")
        if zenity:
            proc = subprocess.run(
                [zenity, "--file-selection", "--directory", f"--title={title}"],
                capture_output=True,
                text=True,
                check=False,
            )
            path = (proc.stdout or "").strip()
            return path or None
        if kdialog:
            proc = subprocess.run(
                [kdialog, "--getexistingdirectory", ".", title],
                capture_output=True,
                text=True,
                check=False,
            )
            path = (proc.stdout or "").strip()
            return path or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def pick_file_dialog(title: str = "Select file", types: Optional[list[str]] = None) -> Optional[str]:
    system = platform.system()
    try:
        if system == "Darwin":
            if types:
                type_list = ", ".join(f'"{t}"' for t in types)
                type_clause = f" of type {{{type_list}}}"
            else:
                type_clause = ""
            script = (
                f'POSIX path of (choose file with prompt "{title.replace(chr(34), "")}"{type_clause})'
            )
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return None
            return proc.stdout.strip() or None
        if system == "Windows":
            filt = "All files (*.*)|*.*"
            if types:
                pats = ";".join(f"*.{t}" for t in types)
                filt = f"Text ({pats})|{pats}|All files (*.*)|*.*"
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                f"$d.Title = '{title.replace(chr(39), '')}'; "
                f"$d.Filter = '{filt}'; "
                "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.FileName }"
            )
            proc = subprocess.run(
                ["powershell", "-STA", "-NoProfile", "-Command", ps],
                capture_output=True,
                text=True,
                check=False,
            )
            path = (proc.stdout or "").strip()
            return path or None
        zenity = shutil.which("zenity")
        if zenity:
            cmd = [zenity, "--file-selection", f"--title={title}"]
            if types:
                cmd.append(f"--file-filter=*.{' *.'.join(types)}")
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            path = (proc.stdout or "").strip()
            return path or None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


@app.get("/health")
def health():
    return {"ok": True, "has_session": _session is not None}


@app.get("/prefs")
def get_prefs():
    return load_prefs()


@app.post("/prefs")
def post_prefs(body: dict):
    return save_prefs(body)


@app.post("/dialog/folder")
def dialog_folder(body: Optional[FolderDialogBody] = None):
    """Native OS folder picker. Folder-only — never files."""
    title = (body.title if body else None) or "Select folder"
    path = pick_folder_dialog(title)
    if not path:
        return {"path": None, "cancelled": True}
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_dir():
        raise HTTPException(400, f"Not a directory: {resolved}")
    return {"path": str(resolved), "cancelled": False}


@app.post("/dialog/file")
def dialog_file(body: Optional[FileDialogBody] = None):
    title = (body.title if body else None) or "Select file"
    types = body.types if body else None
    path = pick_file_dialog(title, types)
    if not path:
        return {"path": None, "cancelled": True}
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise HTTPException(400, f"Not a file: {resolved}")
    return {"path": str(resolved), "cancelled": False}


@app.post("/session")
def create_session(body: SessionCreate):
    global _session
    input_folder = Path(body.input_folder).expanduser().resolve()
    if not input_folder.is_dir():
        raise HTTPException(400, f"Not a directory: {input_folder}")
    config = {
        "input_folder": str(input_folder),
        "target_width": body.target_width,
        "target_height": body.target_height,
        "max_zoom": body.max_zoom,
    }
    if body.output_folder:
        config["output_folder"] = str(Path(body.output_folder).expanduser().resolve())
    try:
        _session = FocalPointAlignerCore(config)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    save_prefs({
        "last_input_dir": str(input_folder),
        "last_output_dir": str(_session.output_folder),
        "target_width": body.target_width,
        "target_height": body.target_height,
        "max_zoom": body.max_zoom,
    })
    try:
        _session.ensure_thumbnails()
    except Exception:
        pass
    return _session.session_snapshot()


@app.get("/session")
def get_session():
    return _core().session_snapshot()


@app.delete("/session")
def close_session():
    global _session
    _session = None
    return {"ok": True}


@app.post("/session/target")
def set_session_target(body: TargetBody):
    core = _core()
    if body.target_width < 1 or body.target_height < 1:
        raise HTTPException(400, "target_width/height must be >= 1")
    core.set_target_size(body.target_width, body.target_height)
    save_prefs({
        "target_width": body.target_width,
        "target_height": body.target_height,
    })
    return core.session_snapshot()


@app.post("/import/download")
def import_download(body: ImportDownloadBody):
    """SSE stream of download progress, final event has complete=True and report fields."""
    import threading
    from queue import Queue

    from import_download import download_from_sources, parse_pasted_urls

    dest = Path(body.dest).expanduser().resolve()
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(400, f"Cannot create dest: {e}") from e
    urls = body.urls
    if urls is None and not body.url_file and not body.url_folder:
        raise HTTPException(400, "Provide urls, url_file, or url_folder")
    if isinstance(urls, list) and len(urls) == 1 and "\n" in urls[0]:
        urls = parse_pasted_urls(urls[0])

    q: Queue = Queue()

    def worker():
        try:
            def on_progress(ev):
                q.put(("progress", ev))

            report = download_from_sources(
                str(dest),
                name=body.name,
                urls=urls,
                url_file=body.url_file,
                url_folder=body.url_folder,
                name_pattern=body.name_pattern,
                folder_template=body.folder_template,
                force=body.force,
                progress=on_progress,
            )
            prefs_update = {"last_batch_root_dir": report["root"], "mode": "batch"}
            if body.name_pattern:
                prefs_update["import_name_pattern"] = body.name_pattern
            if body.folder_template:
                prefs_update["import_folder_template"] = body.folder_template
            save_prefs(prefs_update)
            q.put(("done", report))
        except Exception as e:
            q.put(("error", str(e)))

    threading.Thread(target=worker, daemon=True).start()

    def events():
        yield f"data: {json.dumps({'phase': 'start', 'dest': str(dest)})}\n\n"
        while True:
            kind, payload = q.get()
            if kind == "progress":
                yield f"data: {json.dumps({'phase': 'download', **payload})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({**payload, 'phase': 'complete', 'complete': True})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'phase': 'error', 'error': payload, 'complete': True})}\n\n"
                break

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/arrange/auto")
def arrange_auto(body: ArrangeAutoBody):
    """SSE progress while AutoArrange runs; final event includes session + auto_result."""
    core = _core()
    opts = {
        "slot": body.slot,
        "near_to_far": body.near_to_far,
        "lead_index": body.lead_index if body.lead_index is not None else core.current_idx,
        "axis": body.axis,
        "roi": body.roi,
    }

    def events():
        import threading
        from queue import Queue

        q: Queue = Queue()
        total = max(1, core.total_images)

        def on_progress(done, tot, name):
            q.put(("progress", {
                "done": int(done),
                "total": int(tot or total),
                "filename": name or "",
            }))

        def worker():
            try:
                ok, result = core.auto_arrange(body.mode, opts, progress_callback=on_progress)
                if not ok:
                    q.put(("error", str(result)))
                else:
                    q.put(("done", {**core.session_snapshot(), "auto_result": result}))
            except RuntimeError as e:
                q.put(("error", str(e)))
            except Exception as e:
                q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        yield f"data: {json.dumps({'phase': 'start', 'mode': body.mode, 'done': 0, 'total': total})}\n\n"
        while True:
            kind, payload = q.get()
            if kind == "progress":
                yield f"data: {json.dumps({'phase': 'progress', **payload})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({**payload, 'phase': 'complete', 'complete': True})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'phase': 'error', 'error': payload, 'complete': True})}\n\n"
                break

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/arrange/slot")
def arrange_slot(body: ArrangeSlotBody):
    core = _core()
    if not core.save_arrangement_slot(body.slot, body.order_names):
        raise HTTPException(400, "Invalid slot")
    return core.session_snapshot()


@app.post("/arrange/recall")
def arrange_recall(body: ArrangeRecallBody):
    core = _core()
    if not core.recall_arrangement(body.slot):
        raise HTTPException(400, f"No arrangement saved for slot {body.slot}")
    return core.session_snapshot()


@app.post("/arrange/leave")
def arrange_leave(body: Optional[ArrangeLeaveBody] = None):
    core = _core()
    commit = True if body is None else body.commit
    slot = core.commit_arrange_draft_to_next_slot() if commit else None
    if not commit:
        core._arrange_draft = None
    return {**core.session_snapshot(), "committed_slot": slot}


@app.post("/arrange/reverse")
def arrange_reverse():
    """Reverse the current arrangement in place (updates active slot; no new preset)."""
    core = _core()
    if not core.reverse_arrangement_in_place():
        raise HTTPException(400, "Could not reverse arrangement")
    return core.session_snapshot()


@app.post("/arrange/clear")
def arrange_clear(body: ArrangeClearBody = ArrangeClearBody()):
    """Clear a numeric arrangement slot and recall Original."""
    core = _core()
    ok, err = core.clear_arrangement_slot(body.slot)
    if not ok:
        raise HTTPException(400, err or "Could not clear slot")
    return core.session_snapshot()


@app.post("/focal")
def set_focal(body: FocalBody):
    core = _core()
    if body.index is not None:
        if not core.navigate_to(body.index):
            raise HTTPException(400, "Index out of range")
    core.set_focal_point(
        body.x,
        body.y,
        auto_center=body.auto_center,
        crop_scale=body.crop_scale,
        flip_h=body.flip_h,
        flip_v=body.flip_v,
        keyframe_frame=body.keyframe_frame,
    )
    core.save_focal_points()
    return core.session_snapshot()


@app.delete("/focal")
def clear_focal(index: Optional[int] = None):
    core = _core()
    if index is not None:
        core.navigate_to(index)
    core.clear_focal_point()
    return core.session_snapshot()


@app.post("/confirm")
def confirm():
    core = _core()
    ok = core.confirm_and_save()
    if not ok:
        raise HTTPException(400, "Could not confirm current image")
    return core.session_snapshot()


@app.post("/navigate")
def navigate(body: NavigateBody):
    core = _core()
    if body.index is not None:
        if not core.navigate_to(body.index):
            raise HTTPException(400, "Index out of range")
    elif body.direction is not None:
        if body.wrap:
            core.navigate_wrap(body.direction)
        else:
            core.navigate(body.direction)
    core.save_focal_points()
    return core.session_snapshot()


@app.post("/discard")
def discard(index: Optional[int] = None):
    core = _core()
    if index is not None:
        core.navigate_to(index)
    core.discard_current()
    if not core.image_files:
        return {"empty": True, **core.session_snapshot()}
    return core.session_snapshot()


@app.post("/duplicate")
def duplicate_current():
    """Copy the current image on disk and insert it after the current index."""
    core = _core()
    ok, err = core.duplicate_current()
    if not ok:
        raise HTTPException(400, err or "Duplicate failed")
    return core.session_snapshot()


@app.post("/order")
def apply_order(body: OrderBody):
    core = _core()
    if not core.apply_arrange_order(body.order):
        raise HTTPException(400, "Order length mismatch")
    core.save_focal_points()
    return core.session_snapshot()


@app.post("/shift")
def shift(direction: int = Query(..., ge=-1, le=1)):
    core = _core()
    core.shift_current(direction)
    core.save_focal_points()
    return core.session_snapshot()


@app.post("/mode")
def set_mode(body: ModeBody):
    if body.mode not in ("landscape", "portrait"):
        raise HTTPException(400, "mode must be landscape or portrait")
    core = _core()
    core.set_alignment_mode(body.mode)
    return core.session_snapshot()


@app.get("/crop/{idx}")
def get_crop(idx: int, orientation: Optional[str] = None):
    core = _core()
    if not (0 <= idx < core.total_images):
        raise HTTPException(404, "Index out of range")
    crop = core.crop_for(idx, orientation)
    if crop is None:
        raise HTTPException(404, "Could not compute crop")
    return crop


@app.post("/previews")
def generate_previews(orientation: Optional[str] = None):
    core = _core()
    core.prepare_aligned_previews(orientation or core.alignment_mode or "landscape")
    return {"ok": True, "count": core.get_preview_image_count(orientation or "landscape")}


@app.post("/thumbs")
def generate_thumbs():
    core = _core()
    core.ensure_thumbnails()
    return {"ok": True}


@app.post("/reset")
def reset_session():
    core = _core()
    core.reset_all()
    return core.session_snapshot()


@app.post("/export")
def export_images(body: ExportBody):
    core = _core()
    dest = Path(body.output_folder).expanduser().resolve() if body.output_folder else core.output_folder
    orientation = body.orientation if body.orientation in ("landscape", "portrait") else "landscape"

    def events():
        import threading
        from queue import Queue

        total = core.total_images
        q: Queue = Queue()

        def progress(done, tot, name, error=None):
            payload = {"done": done, "total": tot, "filename": name}
            if error:
                payload["error"] = error
                q.put(("item_error", payload))
            else:
                q.put(("progress", payload))

        def worker():
            try:
                exported = core.export_aligned(dest, orientation, progress_callback=progress)
                if body.cleanup:
                    # Clear preview cache only — keep focal_points.json for reopen/edit.
                    core.cleanup_preview_folders()
                q.put(("done", {"exported": exported, "output_folder": str(dest), "total": total}))
            except Exception as e:
                q.put(("error", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        yield f"data: {json.dumps({'phase': 'start', 'done': 0, 'total': total})}\n\n"
        while True:
            kind, payload = q.get()
            if kind == "progress":
                yield f"data: {json.dumps({'phase': 'export', **payload})}\n\n"
            elif kind == "item_error":
                yield f"data: {json.dumps({'phase': 'item_error', **payload})}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({**payload, 'phase': 'complete', 'complete': True, 'done': payload.get('total', total)})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'phase': 'error', 'error': payload, 'complete': True})}\n\n"
                break

    return StreamingResponse(events(), media_type="text/event-stream")


def _media_file(path: Path, media_type: str = "image/jpeg", cache: bool = True):
    if not path.exists():
        raise HTTPException(404, f"Missing: {path.name}")
    headers = {} if cache else {"Cache-Control": "no-store"}
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/media/original/{idx}")
def media_original(idx: int):
    core = _core()
    if not (0 <= idx < core.total_images):
        raise HTTPException(404, "Index out of range")
    path = core.image_files[idx]
    if core.is_video(idx):
        frame_path = core.ensure_frame_jpeg(idx)
        if frame_path is None:
            raise HTTPException(404, "Could not extract video frame")
        return _media_file(frame_path, "image/jpeg", cache=False)
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(suffix, "image/jpeg")
    return _media_file(path, mime)


@app.get("/media/frame/{idx}")
def media_frame(idx: int, frame: Optional[int] = None):
    """JPEG of a specific video frame (defaults to work_frame)."""
    core = _core()
    if not (0 <= idx < core.total_images):
        raise HTTPException(404, "Index out of range")
    if not core.is_video(idx):
        # Images: ignore frame and return the original file as JPEG-ish.
        path = core.image_files[idx]
        return _media_file(path, "image/jpeg", cache=False)
    frame_path = core.ensure_frame_jpeg(idx, frame_idx=frame)
    if frame_path is None:
        raise HTTPException(404, "Could not extract video frame")
    return _media_file(frame_path, "image/jpeg", cache=False)


@app.get("/media/thumb/{idx}")
def media_thumb(idx: int):
    core = _core()
    path = core.ensure_thumbnail(idx)
    if path is None:
        raise HTTPException(404, "No thumbnail")
    return _media_file(path, cache=False)


@app.get("/media/preview/{idx}")
def media_preview(idx: int, orientation: str = "landscape"):
    core = _core()
    if not (0 <= idx < core.total_images):
        raise HTTPException(404, "Index out of range")
    old = core.current_idx
    core.current_idx = idx
    core.ensure_preview_for_current(orientation)
    core.current_idx = old
    path = core.preview_path(core.image_files[idx], orientation)
    return _media_file(path, cache=False)


@app.post("/video/range")
def video_range(body: VideoRangeBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not (0 <= idx < core.total_images):
        raise HTTPException(400, "Index out of range")
    if not core.is_video(idx):
        raise HTTPException(400, "Not a video")
    if not core.set_video_range(
        idx,
        in_frame=body.in_frame,
        out_frame=body.out_frame,
        work_frame=body.work_frame,
    ):
        raise HTTPException(400, "Could not update video range")
    return core.session_snapshot()


@app.post("/video/split")
def video_split(body: VideoSplitBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not (0 <= idx < core.total_images):
        raise HTTPException(400, "Index out of range")
    ok, err = core.split_video_at(idx, body.at_frame)
    if not ok:
        raise HTTPException(400, err or "Split failed")
    return core.session_snapshot()


@app.post("/video/keyframe")
def video_keyframe_upsert(body: VideoKeyframeBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not (0 <= idx < core.total_images):
        raise HTTPException(400, "Index out of range")
    if not core.is_video(idx):
        raise HTTPException(400, "Not a video")
    fx = body.focal_x
    fy = body.focal_y
    if fx is None or fy is None:
        # Default to current focal or center
        if idx in core.focal_points:
            fx, fy = core.focal_points[idx]
        else:
            w, h = core.image_dimensions.get(idx, (0, 0))
            fx, fy = (w / 2.0, h / 2.0)
    if not core.add_or_update_keyframe(
        idx, body.frame, fx, fy,
        crop_scale=body.crop_scale,
        ease=body.ease,
    ):
        raise HTTPException(400, "Could not set keyframe")
    return core.session_snapshot()


@app.post("/video/keyframe/move")
def video_keyframe_move(body: VideoKeyframeMoveBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not core.move_keyframe(idx, body.from_frame, body.to_frame):
        raise HTTPException(400, "Could not move keyframe")
    return core.session_snapshot()


@app.post("/video/keyframe/ease")
def video_keyframe_ease(body: VideoKeyframeEaseBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not core.set_keyframe_ease(idx, body.frame, body.ease):
        raise HTTPException(400, "Could not set ease")
    return core.session_snapshot()


@app.post("/video/keyframe/delete")
def video_keyframe_delete(body: VideoKeyframeDeleteBody):
    core = _core()
    idx = body.index if body.index is not None else core.current_idx
    if not core.delete_keyframe(idx, body.frame):
        raise HTTPException(400, "Could not delete keyframe")
    return core.session_snapshot()


@app.post("/batch")
def open_batch(body: BatchRootBody):
    global _batch, _batch_seen
    root = Path(body.root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(400, f"Not a directory: {root}")
    _batch = BatchManager(root)
    _batch_seen = set()
    save_prefs({"last_batch_root_dir": str(root), "mode": "batch"})
    return {"root": str(root), "queue": _batch.build_queue()}


@app.get("/batch")
def get_batch():
    if _batch is None:
        raise HTTPException(409, "No batch. POST /batch first.")
    return {"root": str(_batch.root), "queue": _batch.build_queue()}


@app.post("/batch/next")
def batch_next():
    """Open the next pending folder as the current session."""
    global _session, _batch_seen
    if _batch is None:
        raise HTTPException(409, "No batch")
    pending = _batch.discover_subfolders()
    prefs = load_prefs()
    tw = prefs.get("target_width", 2560)
    th = prefs.get("target_height", 1440)
    mz = prefs.get("max_zoom", DEFAULT_MAX_ZOOM)
    for folder in pending:
        key = str(folder.resolve())
        if key in _batch_seen:
            continue
        if _batch.is_done(folder):
            continue
        _batch_seen.add(key)
        output = _batch.aligned_output_for(folder)
        _session = FocalPointAlignerCore({
            "input_folder": str(folder),
            "output_folder": str(output),
            "target_width": tw,
            "target_height": th,
            "max_zoom": mz,
        })
        try:
            _session.ensure_thumbnails()
        except Exception:
            pass
        return {"folder": str(folder), "session": _session.session_snapshot()}
    return {"done": True, "session": None}


@app.post("/batch/merge")
def batch_merge(body: MergeBody):
    report = merge_folders(
        [Path(s) for s in body.sources],
        Path(body.dest),
        use_aligned=body.use_aligned,
        delete_sources=body.delete_sources,
    )
    return report


@app.post("/batch/move-aligned")
def batch_move(root: Optional[str] = None):
    if root:
        path = Path(root)
    elif _batch is not None:
        path = _batch.root
    else:
        raise HTTPException(400, "No batch root")
    return move_aligned_outputs(path)


@app.get("/batch/is-aligned")
def batch_is_aligned(folder: str, use_aligned: bool = True):
    return {"aligned": folder_is_aligned(folder, use_aligned=use_aligned)}


def run():
    import uvicorn
    port = int(os.environ.get("FPA_API_PORT", "8765"))
    uvicorn.run("api.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    run()
