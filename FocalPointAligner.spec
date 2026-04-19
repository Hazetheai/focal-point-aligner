# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Get Qt plugin path
import os
from PyQt6.QtCore import QLibraryInfo

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include Qt plugins - platforms and imageformats are essential
        (QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath) + '/platforms', 'qt6/plugins/platforms'),
        (QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath) + '/imageformats', 'qt6/plugins/imageformats'),
        (QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath) + '/iconengines', 'qt6/plugins/iconengines'),
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'cv2',
        'numpy',
        'PIL',
        'PIL.Image',
        'sklearn',  # Sometimes needed by opencv
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    macos_no_prefer_redirects=False,
    upx_exclude=[],
    user=None,
    encrypt_session_key=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    convert_empty_confs=True,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FocalPointAligner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx_exclude=[],
    console=False,  # Don't show console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx_exclude=[],
    upx=True,
    name='FocalPointAligner',
)

# For macOS .app bundle
app = BUNDLE(
    coll,
    name='FocalPointAligner.app',
    console=False,  # GUI app, no console
    bundle_identifier='com.ceangailte.focalpointaligner',
    info_plist={
        'CFBundleName': 'FocalPointAligner',
        'CFBundleDisplayName': 'Focal Point Aligner',
        'CFBundleIdentifier': 'com.ceangailte.focalpointaligner',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundlePackageType': 'APPL',
        'CFBundleExecutable': 'FocalPointAligner',
        'LSMinimumSystemVersion': '10.15',
        'NSHighResolutionCapable': True,
        'QT_QPA_PLATFORM': 'cocoa',  # Use Cocoa platform (not xcb)
    },
)
