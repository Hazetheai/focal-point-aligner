# Focal Point Aligner

A PyQt6-based GUI tool for aligning images based on user-defined focal points.

## Features

- **Interactive Focal Point Selection**: Click on images to set focal points
- **Drag-and-Drop Reordering**: Reorder images by dragging navigation dots
- **Preview Mode**: Generate and view aligned previews in landscape or portrait orientation
- **Directory Persistence**: Remembers last used input/output directories
- **Keyboard Shortcuts**: Full keyboard navigation support
- **Batch Processing**: Efficiently process large sets of images

## Installation

```bash
conda create -n image-morph python=3.11
conda activate image-morph
pip install PyQt6 opencv-python pillow numpy
```

## Usage

```bash
conda run -n image-morph env QT_QPA_PLATFORM_PLUGIN_PATH=/opt/miniconda3/envs/image-morph/lib/qt6/plugins/platforms python FocalPointAligner/main.py
```

## Keyboard Shortcuts

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
| Escape | Quit application |

## Project Structure

```
FocalPointAligner/
├── main.py                 # Application entry point
├── aligner_core.py         # Core alignment logic
├── styles.py               # UI styling constants
├── ui/
│   ├── aligner_screen.py   # Main aligner UI
│   ├── end_menu.py         # Export dialog
│   ├── navigation_dots.py  # Navigation dots widget
│   ├── image_display.py    # Image display widget
│   ├── opener_screen.py    # Folder selection screen
│   ├── thumbnail_widget.py # Thumbnail display
│   └── logger.py           # Logging utilities
└── config.json             # Configuration (generated)
```

## Workflow

1. **Start**: Select input and output folders
2. **Align**: Click on each image to set focal point, then press Enter to save
3. **Preview**: Switch to Preview tab to see aligned images
4. **Reorder**: Drag navigation dots to reorder images
5. **Export**: Press F to open export menu, select orientation, and export

## Configuration

Configuration is stored in `config.json` next to the application. Preview images are stored in `{output_folder}_preview_landscape` and `{output_folder}_preview_portrait` directories.

## Development

The original OpenCV-based aligner (`align_focal_points.py`) is preserved for backwards compatibility but is not used by the new PyQt6 GUI.