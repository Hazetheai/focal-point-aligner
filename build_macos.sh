#!/bin/bash
# Build script for FocalPointAligner macOS .app bundle

set -e  # Exit on error

echo "=== FocalPointAligner Build Script ==="
echo ""

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "Error: conda not found. Please install Miniconda."
    exit 1
fi

# Activate the environment
ENV_NAME="image-morph"
echo "Activating conda environment: $ENV_NAME"

# Set Qt plugin path for PyInstaller
export QT_QPA_PLATFORM_PLUGIN_PATH="/opt/miniconda3/envs/image-morph/lib/qt6/plugins/platforms"

# Clean previous builds
echo ""
echo "Cleaning previous builds..."
rm -rf build dist

# Run PyInstaller
echo ""
echo "Running PyInstaller..."
conda run -n $ENV_NAME pyinstaller FocalPointAligner.spec --clean

echo ""
echo "=== Build Complete ==="
echo ""
echo "Output location: dist/"
echo "App bundle: dist/FocalPointAligner.app"
echo ""
echo "To create a ZIP file for distribution:"
echo "  cd dist"
echo "  zip -r FocalPointAligner-macOS.zip FocalPointAligner.app"
echo ""
echo "To run the app:"
echo "  open dist/FocalPointAligner.app"
echo ""
echo "Note: On first run, macOS may show a warning about unidentified developer."
echo "To bypass: Right-click the app and select 'Open', then click 'Open' in the dialog."
