"""FastAPI wrapper around FocalPointAlignerCore and batch.py."""

from __future__ import annotations

import json
import os
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


@app.get("/health")
def health():
    return {"ok": True, "has_session": _session is not None}


@app.get("/prefs")
def get_prefs():
    return load_prefs()


@app.post("/prefs")
def post_prefs(body: dict):
    return save_prefs(body)


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


@app.post("/focal")
def set_focal(body: FocalBody):
    core = _core()
    if body.index is not None:
        if not core.navigate_to(body.index):
            raise HTTPException(400, "Index out of range")
    core.set_focal_point(body.x, body.y, auto_center=body.auto_center)
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
        total = core.total_images

        def progress(done, tot, name):
            payload = json.dumps({"done": done, "total": tot, "filename": name})
            events.latest = payload

        events.latest = None
        exported = core.export_aligned(dest, orientation, progress_callback=progress)
        if body.cleanup:
            core.cleanup_preview_folders()
            core.delete_focal_points_file()
        yield f"data: {json.dumps({'done': total, 'total': total, 'exported': exported, 'output_folder': str(dest), 'complete': True})}\n\n"

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
    suffix = path.suffix.lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
    }.get(suffix, "image/jpeg")
    return _media_file(path, mime)


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
