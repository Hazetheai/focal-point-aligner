# Workflow

## Opener

1. Choose **Single**, **Batch**, or **Import**.
2. Set target size (ratio chips + resolution presets, or manual width × height).
3. Pick folders / URLs, then **Start**.

Header **theme** toggles light / dark / system preference.

## Original

- Left click / drag sets a pending focal; wheel grows or shrinks the crop box.
- **Enter** or double-click saves and advances.
- **X** or **Shift+middle-click** discards.
- **D** duplicates the current file on disk and inserts it after the current index.
- Videos: scrubber under the stage sets work / in / out; **Shift+click** the track adds a keyframe.

## Preview

Aligned crop of the **same** image as Original.

- Drag to pan the focal; middle-drag or wheel to zoom.
- **Flip X** / **Flip Y**, Overlay neighbors, **Compare** (C), **Commit** (Enter when dirty).
- Videos: **Play** / **Space** loops the trim with interpolated keyframes.

## Arrange

- Original / Aligned thumbs, Reverse, slots **0–6**, Zoom.
- AutoArrange: Color / Depth / Lead / Faces on the action bar.
- Drag thumbnails to reorder (multi-select with Cmd/Ctrl or Shift).

## Export

**E** or the Export button writes `{idx:04d}.jpg` for images and `{idx:04d}.mp4` for videos. Focals stay in `<input>/focal_points.json`.

**Esc** returns to the Opener (in batch mode, opens the next pending folder).
