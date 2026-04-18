"""
Shared styles and colors for the Focal Point Aligner GUI
"""

from PyQt6.QtGui import QColor, QPalette, QFont

# Color palette
COLORS = {
    'primary': '#2D5A8E',        # Deep blue
    'primary_hover': '#3D6A9E',  # Lighter blue
    'secondary': '#5A8E2D',      # Green
    'secondary_hover': '#6A9E3D',
    'background': '#1E1E2E',     # Dark background
    'surface': '#2D2D44',        # Card/surface background
    'surface_hover': '#3D3D54',
    'text_primary': '#FFFFFF',    # White text
    'text_secondary': '#A0A0B0', # Muted text
    'border': '#4D4D64',          # Border color
    'error': '#E74C3C',           # Red for errors
    'success': '#2ECC71',         # Green for success
    'accent': '#3498DB',          # Light blue accent
}

# Font definitions
FONTS = {
    'title': QFont('Segoe UI', 24, QFont.Weight.Bold),
    'subtitle': QFont('Segoe UI', 18, QFont.Weight.DemiBold),
    'body': QFont('Segoe UI', 12),
    'body_bold': QFont('Segoe UI', 12, QFont.Weight.Bold),
    'button': QFont('Segoe UI', 12, QFont.Weight.Medium),
    'small': QFont('Segoe UI', 10),
}

# Spacing constants
SPACING = {
    'xs': 4,
    'sm': 8,
    'md': 16,
    'lg': 24,
    'xl': 32,
}

# Button style sheets
BUTTON_PRIMARY = f"""
QPushButton {{
    background-color: {COLORS['primary']};
    color: {COLORS['text_primary']};
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font: {FONTS['button'].family()} {FONTS['button'].pointSize()}pt;
}}
QPushButton:hover {{
    background-color: {COLORS['primary_hover']};
}}
QPushButton:pressed {{
    background-color: {COLORS['primary']};
    padding: 13px 24px 11px 24px;
}}
QPushButton:disabled {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_secondary']};
}}
"""

BUTTON_SECONDARY = f"""
QPushButton {{
    background-color: {COLORS['secondary']};
    color: {COLORS['text_primary']};
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font: {FONTS['button'].family()} {FONTS['button'].pointSize()}pt;
}}
QPushButton:hover {{
    background-color: {COLORS['secondary_hover']};
}}
QPushButton:pressed {{
    background-color: {COLORS['secondary']};
    padding: 13px 24px 11px 24px;
}}
"""

BUTTON_OUTLINE = f"""
QPushButton {{
    background-color: transparent;
    color: {COLORS['text_primary']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 22px;
    font: {FONTS['button'].family()} {FONTS['button'].pointSize()}pt;
}}
QPushButton:hover {{
    border-color: {COLORS['primary']};
    background-color: {COLORS['surface']};
}}
"""

# Input field style
INPUT_FIELD = f"""
QLineEdit {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 10px 12px;
    font: {FONTS['body'].family()} {FONTS['body'].pointSize()}pt;
}}
QLineEdit:focus {{
    border-color: {COLORS['primary']};
}}
QLineEdit:disabled {{
    background-color: {COLORS['background']};
    color: {COLORS['text_secondary']};
}}
"""

# Spin box style
SPIN_BOX = f"""
QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 6px;
    padding: 8px 12px;
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLORS['primary']};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    border-left: 1px solid {COLORS['border']};
    width: 20px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    border-left: 1px solid {COLORS['border']};
    width: 20px;
}}
"""

# Card/Panel style
CARD_STYLE = f"""
QWidget {{
    background-color: {COLORS['surface']};
    border-radius: 12px;
    border: 1px solid {COLORS['border']};
}}
"""

# Label style
LABEL_STYLE = f"""
QLabel {{
    color: {COLORS['text_secondary']};
    font: {FONTS['body'].family()} {FONTS['body'].pointSize()}pt;
}}
"""

# Title label style
TITLE_LABEL = f"""
QLabel {{
    color: {COLORS['text_primary']};
    font: {FONTS['title'].family()} {FONTS['title'].pointSize()}pt;
    font-weight: bold;
}}
"""


def get_palette():
    """Return a QPalette configured with the app colors"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS['background']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS['surface']))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS['surface']))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS['surface']))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS['surface']))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(COLORS['text_primary']))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS['primary']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS['text_primary']))
    return palette