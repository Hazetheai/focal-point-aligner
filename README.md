# FocalPointAligner

A tool for aligning images by selecting focal points. Images are processed so that the focal point is centered and the image fills the target frame.

## Features

- Interactive GUI (PyQt6)
- CLI interface for programmatic testing
- Batch processing
- Auto-save with crash recovery
- Preview generation for both landscape and portrait orientations
- **Batch (root-folder) mode** — process many sub-folders in sequence; the next pending folder loads automatically when one finishes
- **Merge folders** — combine several folders (raw or aligned) into one, prefixing each file with its source folder name
- **Move aligned** — gather all `<sub>_aligned` output folders into an adjacent `<root>_aligned` folder

## Installation

```bash
pip install -r requirements.txt
```

Requirements:
- PyQt6>=6.9.0
- opencv-python>=4.13.0
- pillow>=12.0.0
- numpy>=2.0.0

## Quick Start (GUI)

```bash
python main.py
```

## CLI Usage

The CLI interface enables programmatic testing and batch operations.

### Initialize a Project

```bash
python cli.py init --input /path/to/images --output /path/to/output
```

Options:
- `--input` - Input folder containing images (required)
- `--output` - Output folder (default: input_folder_aligned)
- `--width` - Target width (default: 2560)
- `--height` - Target height (default: 1440)

### Check Status

```bash
python cli.py status
```

With JSON output for programmatic parsing:
```bash
python cli.py status --json
```

### Set Focal Points

```bash
# Set focal point for current image
python cli.py set-focal --x 1280 --y 720

# Set focal point for specific image
python cli.py set-focal --index 0 --x 1280 --y 720
```

### Navigate Images

```bash
python cli.py navigate --next
python cli.py navigate --prev
python cli.py navigate --index 5
```

### Save and Advance

```bash
python cli.py save
```

### Skip Without Saving

```bash
python cli.py skip
```

### List Images

```bash
# List all images
python cli.py list-images

# List only images with focal points
python cli.py list-images --with-focal

# List only images without focal points
python cli.py list-images --without-focal

# JSON output
python cli.py list-images --json
```

### Export Aligned Images

```bash
python cli.py export --orientation landscape
python cli.py export --orientation portrait
```

### Get Image Info

```bash
# Get original image info
python cli.py get-image --index 0 --type original

# Save preview image to disk
python cli.py get-image --index 0 --type preview --orientation landscape --save-to /tmp/preview.jpg
```

### Other Commands

```bash
# Clear focal point
python cli.py clear-focal
python cli.py clear-focal --index 5

# Discard image
python cli.py discard
python cli.py discard --index 5

# Reset all (with confirmation)
python cli.py reset

# Reset all (skip confirmation)
python cli.py reset --confirm

# Show statistics
python cli.py stats
python cli.py stats --json
```

## All Commands Reference

| Command | Description | Key Arguments |
|---------|-------------|-----------------|
| `init` | Initialize project | `--input`, `--output`, `--width`, `--height` |
| `status` | Show current status | `--json` |
| `navigate` | Navigate images | `--index N`, `--next`, `--prev` |
| `set-focal` | Set focal point | `--x`, `--y`, `--index` |
| `save` | Save and advance | - |
| `skip` | Skip without saving | - |
| `clear-focal` | Clear focal point | `--index` |
| `discard` | Discard image | `--index` |
| `reset` | Reset all focal points | `--confirm` |
| `export` | Export aligned images | `--orientation` |
| `stats` | Show statistics | `--json` |
| `list-images` | List images | `--with-focal`, `--without-focal`, `--json` |
| `get-image` | Get image info | `--index`, `--type`, `--orientation`, `--save-to` |

## JSON Output

All commands support `--json` flag for programmatic output:

```bash
python cli.py status --json | jq '.'
# Output: {"current_index": 0, "total_images": 10, ...}
```

## Testing

Run CLI tests with pytest:

```bash
pytest tests/test_cli.py -v
```

## Mouse Shortcuts (GUI - Original Tab Only)

| Click | Action |
|------|--------|
| Left single-click | Set pending focal point |
| Left double-click | Save focal point and advance to next |
| Right single-click | Set center as pending focal |
| Right double-click | Set center + save + advance |
| Middle-click | Discard image (with toast notification) |

## Batch Processing (Legacy)

For batch processing without the interactive GUI, use:

```bash
python scripts/align_and_scale_images.py /path/to/images --orientation landscape
```

## Keyboard Shortcuts (GUI)

| Key | Action |
|-----|--------|
| Enter | Save focal point and go to next image |
| Space | Skip to next image without saving |
| Left/Right | Navigate between images |
| P | Toggle preview mode |
| O | Toggle landscape/portrait orientation |
| Delete | Clear focal point from current image |
| X | Remove current image from the set |
| R | Reset all focal points |
| F | Open export menu |
| Escape | Finish batch and return to the opening screen |

## Project Structure

```
FocalPointAligner/
├── cli.py                  # CLI interface
├── main.py                 # PyQt6 GUI entry point
├── batch.py                # Batch/merge/move logic (UI-independent)
├── aligner_core.py         # Core logic (UI-independent)
├── styles.py               # UI styling constants
├── scripts/
│   └── align_and_scale_images.py  # Batch processing
├── ui/                     # PyQt6 UI components
│   ├── aligner_screen.py   # Main aligner UI
│   ├── end_menu.py         # Export dialog
│   ├── merge_dialog.py     # Folder merge dialog
│   ├── navigation_dots.py  # Navigation dots widget
│   ├── image_display.py    # Image display widget
│   ├── opener_screen.py    # Folder selection screen
│   ├── thumbnail_widget.py # Thumbnail display
│   └── logger.py           # Logging utilities
├── tests/
│   ├── test_cli.py         # CLI tests
│   ├── test_batch.py       # Batch/merge/move logic tests
│   └── test_return_to_opener.py  # Return-to-opener + batch flow tests
├── requirements.txt        # Python dependencies
├── FocalPointAligner.spec  # PyInstaller build config (macOS)
└── build_macos.sh          # Build script for macOS .app
```

## Workflow

1. **Start**: Select input and output folders
2. **Align**: Click on each image to set focal point, then press Enter to save
3. **Preview**: Switch to Preview tab to see aligned images
4. **Reorder**: Drag navigation dots (or use the Arrange tab grid) to reorder images
5. **Export**: Press F to open export menu, select orientation, and export
6. **Next batch**: After export (or after pressing Escape to finish a batch), the opening screen returns automatically — pick the next folder and start again

## Batch Mode (Root Folder)

Align a large number of images by putting each group in its own sub-folder under one root folder.

1. On the opening screen, switch the toggle to **Batch (Root)**.
2. **Browse** to select the root folder. The list shows every sub-folder with a status (`✅ done` / `⏳ pending`).
3. Press **Start Batch**. The first pending folder opens in the aligner.
4. When a folder is finished — via **Export** (`F`) or **Escape** — the next pending folder opens automatically, skipping folders that are already aligned (i.e. whose `<sub>_aligned` output folder already contains images).
5. When every folder is done, the list returns with all items marked `✅ done`.

Escaping a folder without exporting keeps it marked pending, so a later **Start Batch** will resume it (focal points are preserved in that folder's `focal_points.json`).

## Merge Folders

The **Merge…** button (available in any mode) combines images from several folders into one output folder. Each image is copied with its source folder name prefixed to the filename, e.g. `img_0042.jpg` from folder `fuji` becomes `fuji_img_0042.jpg`. If a folder has an aligned output, its aligned images are used instead (disable via the "Use aligned outputs when present" checkbox). In batch mode, select batches in the list and use **Merge selected…**. Merge never modifies the source folders.

## Move Aligned

In batch mode, **Move aligned → root_aligned** moves every `<sub>_aligned` output folder under the root into a folder named `<root>_aligned` next to the root (e.g. `photos/` → `photos_aligned/` containing `photos_aligned/<sub>_aligned/`), keeping each folder's name.

## Configuration

Configuration is stored in `config.json` next to the application. Preview images are stored in `{output_folder}_preview_landscape` and `{output_folder}_preview_portrait` directories.

## Building for Distribution

### macOS .app Bundle

```bash
# Install PyInstaller
pip install pyinstaller

# Run the build script
./build_macos.sh
```

Output will be in `dist/FocalPointAligner.app`

## Development

The original OpenCV-based aligner (`align_focal_points.py`) is preserved for backwards compatibility but is not used by the new PyQt6 GUI.

## License

Internal use - Ceangailte Software
