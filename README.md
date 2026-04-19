# Focal Point Aligner

A PyQt6-based GUI tool for aligning images based on user-defined focal points.

## Features

- **Interactive Focal Point Selection**: Click on images to set focal points
- **Drag-and-Drop Reordering**: Reorder images by dragging navigation dots
- **Preview Mode**: Generate and view aligned previews in landscape or portrait orientation
- **Directory Persistence**: Remembers last used input/output directories
- **Keyboard Shortcuts**: Full keyboard navigation support
- **Batch Processing**: Efficiently process large sets of images
- **Cross-Platform**: Works on macOS, Windows, and Linux

## Requirements

- Python 3.11+
- PyQt6 6.9+
- opencv-python 4.13+
- pillow 12.0+
- numpy 2.0+

## Installation

### Using Conda

```bash
# Create a new conda environment
conda create -n focal-align python=3.11
conda activate focal-align

# Install dependencies
pip install PyQt6>=6.9.0 opencv-python>=4.13.0 pillow>=12.0.0 numpy>=2.0.0
```

### Using pip (with existing Python)

```bash
pip install PyQt6>=6.9.0 opencv-python>=4.13.0 pillow>=12.0.0 numpy>=2.0.0
```

## Usage

```bash
# Activate environment (if using conda)
conda activate focal-align

# Run the application
python FocalPointAligner/main.py
```

On first run, macOS may show a warning about "unidentified developer". To bypass: right-click the app and select "Open".

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
├── requirements.txt        # Python dependencies
├── ui/
│   ├── aligner_screen.py   # Main aligner UI
│   ├── end_menu.py        # Export dialog
│   ├── navigation_dots.py # Navigation dots widget
│   ├── image_display.py   # Image display widget
│   ├── opener_screen.py   # Folder selection screen
│   ├── thumbnail_widget.py# Thumbnail display
│   └── logger.py          # Logging utilities
├── FocalPointAligner.spec  # PyInstaller build config (macOS)
└── build_macos.sh          # Build script for macOS .app
```

## Workflow

1. **Start**: Select input and output folders
2. **Align**: Click on each image to set focal point, then press Enter to save
3. **Preview**: Switch to Preview tab to see aligned images
4. **Reorder**: Drag navigation dots to reorder images
5. **Export**: Press F to open export menu, select orientation, and export

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