# AGENTS.md

Guidance for AI agents (or humans) working on this project. Read this before making changes.

## What this project is

**Focal Point Aligner** — click a focal point on each photo (or video work-frame) in a folder; export aligned JPEGs / MP4s at a shared target size with that point centered.

Current GUI: **React (Vite) + FastAPI**, with an optional **Tauri** macOS `.app` shell. There is no PyQt GUI.

Workflow:

1. Opener: Single / Batch / **Import** → target size (ratio + resolution presets, or manual W×H) → Start. Import pastes URLs or picks `.txt` / folder-of-lists, downloads into a batch root, then continues as Batch (align → Merge / Move aligned). Header **theme** toggle (light / dark / system) via `web/src/theme.js` (`data-theme` + `fpa-theme` in localStorage).
2. **Original**: click/drag focal; wheel resizes crop box; Enter / double-click saves and advances; **X** / **Shift+middle-click** discards. Stage background is a **theme-aware checkerboard** (light tiles in light mode, dark in dark). Header can change target size mid-session (live crop/preview retarget). Action-bar **Duplicate** is right-aligned. For **videos**, a scrubber under the stage sets work/in/out frames; **Shift+click** the track (between In/Out) adds a **keyframe** at the current focal+crop_scale; click a diamond marker for ease (linear / ease-in / ease-out / ease-in-out) or Delete; drag markers to retime. Focal moves write the keyframe at the playhead. **Del** clears all keyframes (and the focal) for that clip (destructive hotkey styling).
3. **Preview**: aligned crop of the **same** `current_idx`. Drag to pan focal; middle-drag / wheel / Zoom ± to change `crop_scale`; **Flip X** (upside down) / **Flip Y** (left ↔ right) icon toggles (draft dirty includes flips; pan deltas negate under flips); neighbor Overlay (±0.1 opacity, clamped when no neighbor) is **screen-centered** in the toolbar (grid `1fr auto 1fr`); Compare (C) + Commit (**Enter** when draft is dirty and not comparing). For videos: **Play** / **Space** loops the trim with interpolated keyframes; a right-aligned **Keyframes** action-bar popover (same row as Size / Guides / Details) shows `selected/total` and selects by ordinal (1…N); progress shows `i/N` of the trimmed span. Toolbar is one row of compact icon buttons (tooltips on hover): left Compare/Commit/flips/Zoom · center Overlay · right Play/Wrap.
4. **Arrange**: one toolbar row — Original/Aligned + Reverse + slots 0–6 + Zoom. AutoArrange Color/Depth/Lead/Faces icons live on the action bar with an Info popover; progress floats above that cluster. Drag thumbnails to reorder; video thumbs show a small ▶ badge; Reverse toggles order in the active slot (button stays lit while reversed); hotkeys `0`–`6` recall slots; Manual DnD commits to a slot when leaving Arrange.
5. **E** / Export writes `{idx:04d}.jpg` for images and `{idx:04d}.mp4` for videos (ffmpeg required for video; live SSE progress; focals JSON is kept).
6. **Esc** (or Done) returns to the opener; in batch mode it opens the next pending folder.
7. Original **D** duplicates the current media on disk (`name__dup.ext`) and inserts it after the current index with the same focal/crop settings (videos deepcopy keyframes).

## One command for the GUI

```bash
npm run dev
```

(`./dev.sh` is the same.) Creates `./venv` if needed, installs Python + `web/` deps, starts FastAPI on **8765**, Vite on **5173**, opens the browser. Requires Node.js and Python 3.

Opener **Browse** buttons open a native **folder** picker (via `POST /dialog/folder`, or Tauri when running as a desktop shell). Import can also pick a `.txt` via `POST /dialog/file`. In batch mode, Browse + Refresh load the subfolder queue; Merge / Move aligned / Start Batch use that queue.

## Desktop (unsigned Tauri)

- `./build_macos.sh` / `npm run build` → `src-tauri/target/release/bundle/macos/Focal Point Aligner.app`
- `./scripts/open-app.sh` sets `FPA_ROOT` to the repo and opens the `.app`
- First open: Finder → right-click → **Open** (Gatekeeper; unsigned)
- The `.app` embeds the web UI and spawns `./venv/bin/python -m api.app` (needs this checkout + venv, or `FPA_ROOT` / `FPA_PYTHON`)
- Dev shell: `npm run desktop`

## Size presets & live retarget

- Opener and Aligner expose ratio chips (16:9, 2:1, 1:1, 4:5, 4:3) and typical resolutions (720p–4K, social squares, etc.). Width/Height remain editable.
- `POST /session/target` updates `target_width`/`target_height`, prefs, clears preview cache, and marks all previews dirty. Crop overlays and Preview recompute immediately.

## Video media

- Extensions: `.mp4`, `.mov`, `.m4v`, `.webm`, `.hap` (with images under `MEDIA_EXTENSIONS`). Invalid videos go to `discarded/invalid/` like bad images.
- Discovery / batch folders treat videos as media (same queue / merge rules).
- Session images include `media_kind` (`image`|`video`) and for videos: `fps`, `frame_count`, `duration_ms`, `in_frame`, `out_frame`, `work_frame` (defaults `0`, `frame_count-1`, mid), and `keyframes` (list of `{frame, focal_x, focal_y, crop_scale, ease}`).
- Original stage uses `GET /media/frame/{idx}?frame=N` (cached under `.fpa_cache/frames/`). Thumbs / Preview load the **work_frame**. **AutoArrange samples `in_frame`** (trim start).
- Scrubber: In/Out handles + work playhead; Shift+click adds keyframe; marker click → ease popover / Delete; drag to retime (no neighbor crossing). Range: `POST /video/range`. Keyframes: `POST /video/keyframe`, `/move`, `/ease`, `/delete`.
- Keyframes store focal + `crop_scale` (flips stay clip-wide). `ease` on keyframe *i* governs i→i+1. First focal on a video seeds In/Out (+ work) keyframes. Export interpolates per frame; Preview play uses the same curves client-side (`crop.js`).
- Frame decode: OpenCV first; **ffmpeg fallback** for HAP / codecs OpenCV cannot open (`probe` via ffprobe). Aligned export still pipes BGR24 → ffmpeg `libx264`.
- Aligned export: images → `{idx:04d}.jpg`; videos → `{idx:04d}.mp4` (decode in..out inclusive, apply flips + interpolated focal/scale + `render_aligned`, pipe BGR24 to ffmpeg `libx264` / `yuv420p`). Requires system **ffmpeg** on `PATH` (no new pip dep). Missing ffmpeg → per-item SSE `item_error`.
- Persist `in_frame` / `out_frame` / `work_frame` / `keyframes` on video entries in `focal_points.json`.

## Import download

- `import_download.py` — vendored imgtools download helpers (httpx). List naming uses a `{name}` pattern (default `image_urls--{name}` → e.g. `image_urls--cats.txt` → `cats/`). Folder name template (default `{name}`) supports `{name}`, `{n}` / `{nn}` (job index), `{stem}`; persisted as `import_name_pattern` / `import_folder_template` in prefs. `POST /import/download` accepts both.
- `POST /import/download` with `{ dest, name?, name_pattern?, folder_template?, urls? | url_file? | url_folder? }` → SSE progress events, final `{ complete, root, folders }` for batch handoff. Opener shows download progress + action log.

## Theme

- `web/src/theme.js` — `getThemePreference` / `resolveTheme` / `toggleTheme` / `initTheme`. Preference `light` | `dark` | `system` in `localStorage` key `fpa-theme`.
- `document.documentElement[data-theme]` drives CSS variables in `web/src/index.css` (surfaces, panels/popovers, danger/error reds, checkerboard, wells). Early boot script in `web/index.html` avoids FOUC.
- Primary / accent-selected buttons use light text; secondary buttons keep theme text color. Destructive hotkeys (Discard, Del, Reset) use `--error` / `--danger-surface`.

## AutoArrange & history

- `arrange_auto.py`: color (HSV white/gray/black + hue buckets), depth (ONNX Runtime CPU + Depth-Anything ONNX cached in `.fpa_models/`), lead ORB match (uses **selected** image as lead), faces (YuNet / `FaceDetectorYN`, L→R by face center).
- Reverse (`POST /arrange/reverse`) flips the current order and updates the **active** slot in place — does not create a new preset. Session exposes `arrangement_reversed` so the Reverse control stays lit for that slot until reversed again (or a new AutoArrange overwrites the slot).
- Depth AutoArrange is near→far only; use Reverse for far→near. Lead match uses the **selected** thumbnail (hover Lead to pulse its border).
- Arrange: Cmd/Ctrl-click and Shift-click select multiple thumbnails; dragging moves the whole selection as a block.
- `focal_points.json` stores `arrangements` (`original`, `1`…`6`), `arrangement_active`, `arrangement_methods` (per-slot last AutoArrange/manual mode), `arrangement_modified` (true when the user tweaked an AutoArrange slot), and `arrangement_reversed`. Hotkeys `0`–`6` recall; **Backspace** clears the active numeric slot (confirm) and recalls Original. Leaving Arrange commits a manual draft onto the active numeric slot (or slot `1` when on Original). AutoArrange always overwrites the active numeric slot; on Original it always writes slot `1`.
- APIs: `POST /arrange/auto` (SSE progress + final session), `/arrange/slot`, `/arrange/recall`, `/arrange/leave`, `/arrange/reverse`, `/arrange/clear`. Arrange AutoArrange icons highlight the method used for the active slot; modified slots keep that method icon and show a `*` (tooltip includes “Modified”).
- `load_image_safely` always returns 8-bit BGR (scales 10/12/16-bit sources) so Arrange aligned previews / export are not near-white. Preview cache filenames use a `_u8` suffix.

## Focal clicks (Original tab)

- Left click / drag = pending focal (crosshair + crop overlay); drag moves the crop box with live magnified preview.
- Mouse wheel = grow/shrink the crop box (`crop_scale`, aspect locked). Scroll up zooms in.
- **H** = home: center focal + reset `crop_scale` to `1.0`.
- Double-click or **Enter** = save + advance (`set_focal` then `confirm_and_save`), including current `crop_scale`.
- Switching to Preview with a pending click **saves without advancing** so Preview is the same image.
- Right click = image center as pending (`auto_center`); right **double-click** confirms that center focal and advances.
- **Shift+middle click** = discard current image (also works on Arrange thumbs). Shift required so wheel/MMB zoom is not mis-clicks.
- **G** = rule-of-thirds grid (high-contrast). **I** = composition mask (B&W upload; white = guide). Grid and mask can both be on. Invert / opacity / **Contain|Cover** fit live in the Guides panel.
- Coordinates must come from the **displayed** image (`naturalWidth` / canvas bounding rect), not a stale session size. Python load/probe applies **EXIF orientation** so clicks match `cv2` pixels. OpenCV loads normalize high-bit-depth images to uint8 before crop/preview/export.
- After a click, draw a dim overlay on the photo and fill the requested `compute_crop_frame` box with the effective `compute_crop` sample (Preview-equivalent magnification when the frame would leave the image). White border on that box. No zoom-drag overlay.
- Original stage: show the photo as a visible `<img>`; canvas is a transparent overlay for crosshair/crop only. Do not paint from a `display:none` image (cached loads skip `onLoad` and leave a blank stage).
- Header filename truncates; tabs stay in a fixed center column so layout does not jump between images.
- Image facts **Path**: truncated by default; first click expands full path; second click copies; closing Details resets truncation.

## Stack & tests

- Python 3.x, FastAPI, uvicorn, opencv-python, numpy, pillow, httpx, onnxruntime. See `requirements.txt` (no PyQt). System **ffmpeg** required for video split/export (not a pip package).
- Web: Vite + React in `web/`. Root `package.json` launches the stack / Tauri.
- Venv lives at `./venv` (gitignored).
- Tests: `./venv/bin/python -m pytest tests/ -v`

## Architecture / where things live

| Path | Role |
|------|------|
| `scripts/dev.sh` | GUI launcher used by `npm run dev` |
| `scripts/open-app.sh` | Open latest local release `.app` with `FPA_ROOT` |
| `scripts/release.sh` | Local unsigned release into `releases/` |
| `build_macos.sh` | Unsigned Tauri build |
| `api/app.py` | FastAPI: session, focals, navigate, discard, order, export SSE, media, batch/merge, import, arrange, dialogs |
| `web/src/Opener.jsx` | Single / Batch / Import, size presets, merge/move, import naming pattern |
| `web/src/Aligner.jsx` | Original / Preview / Arrange, AutoArrange, slots, nav dots, hotkeys |
| `web/src/theme.js` | Light / dark / system theme preference |
| `web/src/crop.js` | JS port of `compute_crop` / `compute_crop_frame` + keyframe ease/lerp |
| `web/src/presets.js` | Target size ratio + resolution presets |
| `import_download.py` | URL-list download (paste / .txt / folder-of-.txt) + `{name}` list patterns |
| `arrange_auto.py` | Color / depth / lead-match / faces sort helpers |
| `aligner_core.py` | **UI-free core** — state, persistence, crop, discard, reorder, export |
| `batch.py` | **UI-free batch** — discovery, done-detection, `merge_folders()`, `move_aligned_outputs()` |
| `cli.py` / `focalpoint` | CLI over the core |
| `src-tauri/` | Tauri 2 shell (spawns FastAPI from project venv) |

## Core state (`FocalPointAlignerCore`)

- `image_files: list[Path]` — export order. **Order lives here; files on disk stay as-is.**
- `focal_points: dict[int, tuple]` — index → `(fx, fy)` in **oriented** original pixels (EXIF applied).
- `completed: set[int]`, `auto_center_flags`, `image_dimensions`, `preview_dirty`.
- `discarded: set[str]` — filenames.
- `current_idx: int` — shared across Original / Preview / Arrange. Tab switches must not change it.
- `json_path` = `<input_folder>/focal_points.json` (migrates from `<output_folder>/focal_points.json` once if needed). Export cleanup does **not** delete it.
- Session images also expose `bytes`, `dpi`, `format`, `mode`, `megapixels`, `auto_center`, `focal_at_center`, `crop_scale`, `flip_h`, `flip_v`, `media_kind`, and for videos `fps` / `frame_count` / `duration_ms` / `in_frame` / `out_frame` / `work_frame` / `keyframes`.

### Persistence (`focal_points.json`)

- Focals keyed by **filename** (`focal_x`, `focal_y`, `original_width/height`, `auto_center`, `crop_scale`, `flip_h`, `flip_v`, `timestamp`; videos also `in_frame` / `out_frame` / `work_frame` / `media_kind` / `keyframes`). Legacy single-focal videos migrate to In/Out keyframes on load.
- Top-level: `discarded`, `order` (filenames), `current_idx`, `alignment_mode`, `preview_state`, `_meta`, `arrangements`, `arrangement_active`, `arrangement_methods`, `arrangement_reversed`.
- `load_focal_points()` re-applies `order` via `_reorder_files_by_names()`.
- Thumbs/previews: `<input>/.fpa_cache/` keyed by **filename**, not index (reorder must not reuse the wrong JPEG). Media URLs should cache-bust with `?n=<filename>`.
- `config.json` at repo root: opener prefs (`mode`, paths, target size, `import_name_pattern`, etc.). Gitignored.

## Arrange / reorder invariants

1. **`apply_arrange_order(order)`** takes `new_position → old_index`, requires `len(order) == len(image_files)`, returns `False` on mismatch.
2. After a successful reorder, **`current_idx` must follow the same file** (`old_to_new[old_current]`). Silent slot-stay was a bug: Original/Preview showed a different image.
3. **Export order == `image_files` order.** Slot `i` is `image_files[i]` with `focal_points[i]`.
4. **Discards** move the file to `<input>/discarded/` and compact all index dicts (no gaps).
5. Web Arrange uses **filename** as the dnd-kit id (indices remapped 0..n-1 after save). Optimistic reorder then `POST /order`.

## Keyboard

`Enter` save+next (Original) / commit draft (Preview when dirty) · `Space` skip (Original) / play·pause (Preview video) · `←→` navigate (no wrap) · `X` / **Shift+MMB** discard · `D` duplicate (Original) · `Del` clear focal (images) / clear all keyframes (videos) · `P` preview · `O` orientation · `A` arrange · `H` home focal+scale · `G` grid · `I` mask · `R` reset · `E` export · `Esc` opener / next batch · Preview `<` / `,` previous neighbor · `>` / `.` next neighbor (clamped) · Arrange `0`–`6` slots · `C` compare slots.

Hotkey chips are **tab-scoped**: Original shows save/duplicate/grid/mask/home; Preview shows Enter·Commit (when draft dirty and not comparing), Space·Play/Pause (videos), Compare (C), and `<`/`>` neighbor; Arrange shows slot digits. Keys that are not shown for the current tab do nothing. Discard / Del / Reset use `.hotkey.danger` styling.
Preview can toggle **Wrap** so ←→ loop the list; with Wrap off, navigation stops at the ends.

Mouse on Original: left click/drag pending · wheel crop size · left double save+next · right click center pending · right double center save+next · Shift+middle discard · **H** home.

Reorder only on the Arrange tab (drag thumbs); `[`/`]` are not global reorder shortcuts.

Mouse on Preview: left-drag pan focal · middle-drag or wheel zoom · Flip X (upside down) / Flip Y (left ↔ right) · Compare / Commit (Enter) for fine-tune. Stored as `flip_v` / `flip_h` respectively (axis of reflection). Preview draw transforms focal into flipped space and samples the unflipped bitmap. Pan/zoom bakes edge-forced magnification into `crop_scale` so returning to center keeps that zoom; `MIN_CROP_SCALE` is `0.05` (~20× vs base).

## Image-size framing (crop math)

- `compute_crop_frame(...)` — requested target-aspect box centered on the focal for the Original overlay; grows/shrinks with `crop_scale` and **may extend past the photo edges**.
- `compute_crop(...)` — effective in-bounds sample for Preview/export. Always centered on the focal; when the requested frame would leave the image, uses the largest centered fit and upscales (never slides along an edge). Large sources default to a 1:1 target crop at `crop_scale=1`; small or edge focals scale up as needed (`MIN_CROP_SCALE`…`MAX_CROP_SCALE`). Preview interaction uses `bake_crop_scale` / `bakeCropScale` so that edge-forced `s_eff` is written back into `crop_scale`.
 - Source ≥ target and focal centered: **1:1** crop of `(target_w, target_h)`.
 - Source smaller, or focal near an edge: scale up enough to **cover** and keep the focal centered.
- `render_aligned()` crops that rect and resizes to the target. No blur-fill, no max-zoom overlay.
- After a focal is pending or saved, Original fills the **requested** crop box with the effective sample (magnified Preview-equivalent when the frame extends past the photo), dims the rest of the photo, and strokes a white border.
- Per-image `crop_scale` is stored in `focal_points.json` / session snapshot alongside the focal. Leaving an image (nav, tab switch, arrange select) flushes pending Original / Preview crop changes so the next image starts at its own scale (default `1.0` until altered) and returning restores that image’s saved scale.
- `ensure_preview_for_current` / Arrange aligned thumbs may render with a display-only center when unset, but must **not** write `focal_points` / `auto_center_flags`.
- `max_zoom` remains on the API/config for compatibility; framing uses `crop_scale` instead.
- Tests: `tests/test_crop_math.py` (including “focal lands at output center” and crop_scale grow/shrink).

## Pagination

- Pages of **10** images. Page chips first, then the 10 dots for the current page.
- Dot states: unset (gray), focal set (green), center/default focal (gray with green core), current (blue).
- Center = `auto_center` or `focal_at_center` (focal within 1px of image center).

## Tab / selection sync

- One `current_idx` for Original, Preview, Arrange, nav dots, discard.
- Arrow keys do not wrap on any tab (stops at ends). Preview wrap was making tabs feel “on a different image”.
- Nav dots / pagination are hidden on the Arrange tab (thumbnails are the navigator).
- Discard (`POST /discard?index=`) uses that index; all lists compact together.

## Batch mode

- Opener `mode` `"single"` / `"batch"` in `config.json`.
- Auto-advance: next pending subfolder whose `<sub>_aligned` does **not** already contain images.
- Do not loop on escaped batches: skip folders already opened this session; Esc without export leaves the folder pending (focals survive in that folder’s `focal_points.json`).
- Merge (`batch.merge_folders`) prefixes `<source>_`; `delete_sources=True` only after success.
- Move aligned: `<sub>_aligned` → sibling `<root>_aligned`.
- List shows image-bearing subfolders including `*_aligned` (`done=True`); auto-advance never re-opens those.

## Testing

- `tests/test_cli.py` — CLI subprocess (venv Python).
- `tests/test_crop_math.py` — crop / render_aligned.
- `tests/test_api.py` — FastAPI session, media, export, navigate no-op at ends.
- `tests/test_core_io.py` — header probe, EXIF size, filename-keyed cache, confirm does not write full-res.
- `tests/test_batch.py` — discovery, merge, move-aligned.
- `tests/test_arrange_order.py` — discard → reorder → persist; **current_idx follows the file**.
- `tests/test_presets_import_arrange.py` — size retarget, import SSE, list naming patterns, AutoArrange SSE, reverse lit state.
- `tests/test_video_media.py` — mixed discovery, video JSON fields, frame extract, trim/split, MP4 export (skips when ffmpeg missing).
- `tests/test_keyframes.py` — ease/lerp, keyframe seed/persist, trim clamp, AutoArrange uses `in_frame`, `.hap` extension.
- Run: `./venv/bin/python -m pytest tests/ -v`

## Building

- Dev GUI: `npm run dev`
- Tauri window: `npm run desktop`
- Tauri build (unsigned): `./build_macos.sh` or `npm run build`
- Local release pipeline (artifacts in gitignored `releases/`, no remote publish):
  - Once: `./scripts/install-git-hooks.sh` and keep a local `release` branch
  - Ship: `git checkout release && git merge main` (post-merge runs `scripts/release.sh`)
  - Or: `npm run release` / `./scripts/release.sh [--bump patch]`
  - Open: `./scripts/open-app.sh` (prefers `releases/latest`)
  - Docs: `docs/LOCAL_RELEASES.md`

## Conventions

- Crop/reorder/export logic stays in `aligner_core.py` (no React).
- Prefer remapping index dicts from filenames after discard/reorder over ad-hoc UI rebuilds.
- Keep Original / Preview / Arrange on the same `current_idx`.
- Preview/media generation must not invent saved focals for unset images.
- Do not reintroduce a PyQt GUI or PyInstaller packaging.
