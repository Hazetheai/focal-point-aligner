"""
Opening screen for the Focal Point Aligner GUI.
Allows users to select input folder, output folder, target size, and presets.
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QSpinBox, QGroupBox,
    QFileDialog, QMessageBox, QGridLayout
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData

import styles


CONFIG_FILE = Path(__file__).parent.parent / "config.json"


class OpenerScreen(QWidget):
    """Opening screen for folder selection and configuration."""
    
    # Signal emitted when user clicks Start, with config dict
    start_clicked = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_config()
        self._build_ui()
        
        # Restore persisted settings after widgets exist
        last_input = self._config.get('last_input_dir', '')
        last_output = self._config.get('last_output_dir', '')
        if last_input and Path(last_input).exists():
            self.input_path.setText(last_input)
        if last_output and Path(last_output).exists():
            self.output_path.setText(last_output)
        self.width_spin.setValue(self._config.get('target_width', 2560))
        self.height_spin.setValue(self._config.get('target_height', 1440))
    
    def _load_config(self):
        """Load persisted settings from config file."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self._config = json.load(f)
            except Exception:
                self._config = {}
        else:
            self._config = {}
    
    def _save_config(self):
        """Save current settings to config file."""
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save config: {e}")
    
    def _build_ui(self):
        self.setWindowTitle("Focal Point Aligner")
        
        # Get the screen geometry and size to 90% of available screen
        screen = self.screen()
        if screen:
            screen_geometry = screen.availableGeometry()
            new_width = int(screen_geometry.width() * 0.9)
            new_height = int(screen_geometry.height() * 0.9)
            self.resize(new_width, new_height)
        
        # Apply palette
        self.setPalette(styles.get_palette())
        
        layout = QVBoxLayout()
        layout.setSpacing(styles.SPACING['md'])
        layout.setContentsMargins(styles.SPACING['xl'], styles.SPACING['xl'], 
                                  styles.SPACING['xl'], styles.SPACING['xl'])
        
        # Title
        title = QLabel("Focal Point Aligner")
        title.setStyleSheet(styles.TITLE_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Welcome text
        welcome = QLabel(
            "Select an input folder containing images, configure target dimensions,\n"
            "and click Start to begin aligning your images by focal points."
        )
        welcome.setStyleSheet(styles.LABEL_STYLE)
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome)
        
        layout.addSpacing(styles.SPACING['lg'])
        
        # Input folder section
        input_group = QGroupBox("Input Folder")
        input_group.setStyleSheet(styles.CARD_STYLE)
        input_layout = QHBoxLayout()
        input_layout.setSpacing(styles.SPACING['sm'])
        
        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText("Select folder containing images...")
        self.input_path.setReadOnly(True)
        self.input_path.setStyleSheet(styles.INPUT_FIELD)
        self.input_path.setAcceptDrops(True)
        
        self.input_btn = QPushButton("Browse")
        self.input_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        self.input_btn.clicked.connect(self.browse_input_folder)
        
        input_layout.addWidget(self.input_path, 1)
        input_layout.addWidget(self.input_btn)
        input_group.setLayout(input_layout)
        layout.addWidget(input_group)
        
        # Target size section
        size_group = QGroupBox("Target Dimensions")
        size_group.setStyleSheet(styles.CARD_STYLE)
        size_layout = QGridLayout()
        size_layout.setSpacing(styles.SPACING['md'])
        
        # Width
        width_label = QLabel("Width:")
        width_label.setStyleSheet(styles.LABEL_STYLE)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(100, 10000)
        self.width_spin.setValue(2560)
        self.width_spin.setStyleSheet(styles.SPIN_BOX)
        
        # Height
        height_label = QLabel("Height:")
        height_label.setStyleSheet(styles.LABEL_STYLE)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(100, 10000)
        self.height_spin.setValue(1440)
        self.height_spin.setStyleSheet(styles.SPIN_BOX)
        
        size_layout.addWidget(width_label, 0, 0)
        size_layout.addWidget(self.width_spin, 0, 1)
        size_layout.addWidget(height_label, 0, 2)
        size_layout.addWidget(self.height_spin, 0, 3)
        
        # Presets
        presets_label = QLabel("Presets:")
        presets_label.setStyleSheet(styles.LABEL_STYLE)
        size_layout.addWidget(presets_label, 1, 0)
        
        preset_btn_1 = QPushButton("16:9 Landscape")
        preset_btn_1.setStyleSheet(styles.BUTTON_OUTLINE)
        preset_btn_1.clicked.connect(lambda: self.apply_preset(2560, 1440))
        
        preset_btn_2 = QPushButton("9:16 Portrait")
        preset_btn_2.setStyleSheet(styles.BUTTON_OUTLINE)
        preset_btn_2.clicked.connect(lambda: self.apply_preset(1440, 2560))
        
        preset_btn_3 = QPushButton("1:1 Square")
        preset_btn_3.setStyleSheet(styles.BUTTON_OUTLINE)
        preset_btn_3.clicked.connect(lambda: self.apply_preset(1440, 1440))
        
        size_layout.addWidget(preset_btn_1, 1, 1)
        size_layout.addWidget(preset_btn_2, 1, 2)
        size_layout.addWidget(preset_btn_3, 1, 3)
        
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)
        
        # Output folder section
        output_group = QGroupBox("Output Folder (defaults to input location)")
        output_group.setStyleSheet(styles.CARD_STYLE)
        output_layout = QHBoxLayout()
        output_layout.setSpacing(styles.SPACING['sm'])
        
        self.output_path = QLineEdit()
        self.output_path.setPlaceholderText("Will default to input folder + '_aligned'")
        self.output_path.setReadOnly(True)
        self.output_path.setStyleSheet(styles.INPUT_FIELD)
        self.output_path.setAcceptDrops(True)
        
        self.output_btn = QPushButton("Browse")
        self.output_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        self.output_btn.clicked.connect(self.browse_output_folder)
        
        output_layout.addWidget(self.output_path, 1)
        output_layout.addWidget(self.output_btn)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        layout.addStretch()
        
        # Start button
        self.start_btn = QPushButton("🚀  Start")
        self.start_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.start_btn.setMinimumHeight(50)
        self.start_btn.clicked.connect(self.on_start_clicked)
        layout.addWidget(self.start_btn)
        
        self.setLayout(layout)
    
    def browse_input_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Input Folder",
            str(Path.home())
        )
        if folder:
            self.input_path.setText(folder)
            # Auto-fill output if not set
            if not self.output_path.text():
                output_folder = Path(folder).parent / f"{Path(folder).name}_aligned"
                self.output_path.setText(str(output_folder))
    
    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            self.input_path.text() or str(Path.home())
        )
        if folder:
            self.output_path.setText(folder)
    
    def apply_preset(self, width, height):
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

    def dragEnterEvent(self, event):
        """Handle drag enter events to accept folder drops."""
        if event.mimeData().hasUrls():
            # Check if any of the URLs are local files/directories
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """Handle drop events to process dropped folders."""
        if event.mimeData().hasUrls():
            # Get the first URL that is a local file
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    folder_path = url.toLocalFile()
                    # Determine which field received the drop by checking mouse position
                    # Since we can't easily tell which widget received the event,
                    # we'll check which field has focus or is under the cursor
                    pos = event.position()
                    widget = self.childAt(pos.toPoint())
                    
                    is_input_field = widget == self.input_path or self.input_path.hasFocus()
                    is_output_field = widget == self.output_path or self.output_path.hasFocus()
                    
                    # Default to input field if neither has focus (more common use case)
                    if not is_input_field and not is_output_field:
                        is_input_field = True
                    
                    self.handle_folder_drop(folder_path, is_input_field)
                    event.acceptProposedAction()
                    return
        event.ignore()

    def handle_folder_drop(self, folder_path, is_input_field=False):
        """Process a dropped folder path."""
        folder_path = Path(folder_path)
        if folder_path.exists() and folder_path.is_dir():
            if is_input_field:
                self.input_path.setText(str(folder_path))
                # Auto-update output path when input changes via drag/drop
                output_folder = folder_path.parent / f"{folder_path.name}_aligned"
                self.output_path.setText(str(output_folder))
            else:
                self.output_path.setText(str(folder_path))
            
            # Update and save config
            self._config['last_input_dir'] = self.input_path.text().strip()
            self._config['last_output_dir'] = self.output_path.text().strip()
            self._save_config()
        else:
            # Show error - not a valid directory
            QMessageBox.warning(self, "Invalid Folder", "The dropped item is not a valid folder.")

    def on_start_clicked(self):
        # Save config before starting
        self._config['last_input_dir'] = self.input_path.text().strip()
        self._config['last_output_dir'] = self.output_path.text().strip()
        self._config['target_width'] = self.width_spin.value()
        self._config['target_height'] = self.height_spin.value()
        self._save_config()
        
        # Validate inputs
        input_folder = self.input_path.text().strip()
        
        if not input_folder:
            QMessageBox.warning(
                self, 
                "No Input Folder", 
                "Please select an input folder containing images."
            )
            return
        
        input_path = Path(input_folder)
        if not input_path.exists() or not input_path.is_dir():
            QMessageBox.warning(
                self,
                "Invalid Input Folder",
                "The selected input folder does not exist."
            )
            return
        
        # Check for images
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
        images = [f for f in input_path.iterdir() 
                  if f.is_file() and f.suffix.lower() in extensions]
        
        if not images:
            QMessageBox.warning(
                self,
                "No Images Found",
                "The selected folder contains no images."
            )
            return
        
        # Get output folder
        output_folder = self.output_path.text().strip()
        if not output_folder:
            output_folder = str(input_path.parent / f"{input_path.name}_aligned")
        
        # Build config
        config = {
            'input_folder': input_folder,
            'output_folder': output_folder,
            'target_width': self.width_spin.value(),
            'target_height': self.height_spin.value(),
        }
        
        # Emit signal with config
        self.start_clicked.emit(config)