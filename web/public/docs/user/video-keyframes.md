# Video & keyframes

Supported video extensions: `.mp4`, `.mov`, `.m4v`, `.webm`, `.hap` (plus the usual still formats).

## Scrubber (Original)

- Drag the playhead for the **work** frame (thumbs / Preview use this).
- Drag **In** / **Out** handles to trim (export uses in…out inclusive).
- **Shift+click** the track between In and Out to add a **keyframe** at the current focal + crop scale.
- Click a diamond marker to set ease (linear / ease-in / ease-out / ease-in-out) or Delete.
- Drag markers to retime (they cannot cross neighbors).
- Moving the focal while on a video writes/updates the keyframe at the playhead.
- **Del** clears all keyframes (and the focal) for that clip.

## Preview play

**Play** / **Space** loops the trimmed span with the same ease curves used on export. The Keyframes popover shows `selected/total` and jumps by ordinal.

## Export

Videos export as `{idx:04d}.mp4` via ffmpeg (`libx264` / `yuv420p`). Install ffmpeg and keep it on your `PATH`. Missing ffmpeg shows a per-item export error.
