"""
Opening screen for the Focal Point Aligner GUI.
Allows users to select input folder, output folder, target size, and presets.
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QLineEdit, QSpinBox, QGroupBox,
    QFileDialog, QMessageBox, QGridLayout, QStackedWidget,
    QListWidget, QListWidgetItem, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, pyqtSignal

import styles
from batch import BatchManager
from ui.merge_dialog import MergeDialog
from aligner_core import DEFAULT_MAX_ZOOM


CONFIG_FILE = Path(__file__).parent.parent / "config.json"


class OpenerScreen(QWidget):
    """Opening screen for folder selection and configuration."""
    
    # Signal emitted when user clicks Start in single-folder mode, with config dict
    start_clicked = pyqtSignal(dict)
    # Signal emitted when user clicks Start in batch mode
    batch_started = pyqtSignal(dict)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._load_config()
        self._mode = self._config.get('mode', 'single')
        self._batch_root = Path(self._config.get('last_batch_root_dir', '')) if self._config.get('last_batch_root_dir') else None
        self.batch_manager = None
        self._merge_dialog = None
        self._build_ui()
        
        print("[DRAG] OpenerScreen init - enabling drag/drop on widget")
        self.setAcceptDrops(True)
        
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
            "and click Start to begin aligning your images by focal points.\n"
            "<span style='color:#60E080;'>💡 Drag & drop a folder anywhere on this screen to set the input path</span>"
        )
        welcome.setStyleSheet(styles.LABEL_STYLE)
        welcome.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(welcome)
        
        layout.addSpacing(styles.SPACING['lg'])
        
        layout.addLayout(self._build_mode_row())
        
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
        
        self._config_stack = QStackedWidget()
        self._single_page = QWidget()
        single_lay = QVBoxLayout(self._single_page)
        single_lay.setSpacing(styles.SPACING['md'])
        single_lay.addWidget(input_group)
        
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
        single_lay.addWidget(size_group)
        
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
        single_lay.addWidget(output_group)
        single_lay.addStretch()
        
        self._config_stack.addWidget(self._single_page)
        self._config_stack.addWidget(self._build_batch_page())
        layout.addWidget(self._config_stack, 1)
        
        layout.addStretch()
        
        # Bottom buttons
        btn_row = QHBoxLayout()
        self.merge_btn = QPushButton("Merge…")
        self.merge_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        self.merge_btn.setToolTip("Merge selected folders into one (work in any mode)")
        self.merge_btn.clicked.connect(self._on_merge)
        btn_row.addWidget(self.merge_btn)
        btn_row.addStretch()
        
        # Start button
        self.start_btn = QPushButton("🚀  Start")
        self.start_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.start_btn.setMinimumHeight(50)
        self.start_btn.clicked.connect(self.on_start_clicked)
        btn_row.addWidget(self.start_btn)
        layout.addLayout(btn_row)
        
        self.setLayout(layout)
        self._update_mode_display()
    
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
        """Handle drag enter events - accept folder drops."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dragLeaveEvent(self, event):
        """Handle drag leave events."""
        event.accept()

    def dragMoveEvent(self, event):
        """Handle drag move events - accept valid drops."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """Handle drop events - accept folders dropped anywhere."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    folder_path = url.toLocalFile()
                    # Set as input path
                    self.input_path.setText(folder_path)
                    # Auto-generate output path
                    output_folder = Path(folder_path).parent / f"{Path(folder_path).name}_aligned"
                    self.output_path.setText(str(output_folder))
                    # Save config
                    self._config['last_input_dir'] = folder_path
                    self._config['last_output_dir'] = str(output_folder)
                    self._save_config()
                    event.acceptProposedAction()
                    return
        event.ignore()

    def on_start_clicked(self):
        # Save config before starting
        self._config['last_input_dir'] = self.input_path.text().strip()
        self._config['last_output_dir'] = self.output_path.text().strip()
        self._config['target_width'] = self.width_spin.value()
        self._config['target_height'] = self.height_spin.value()
        self._save_config()
        
        # Batch mode
        if self._mode == 'batch':
            self._save_batch_config()
            config = self._apply_batch_config()
            if config:
                self.batch_started.emit(config)
            return
        
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
            'max_zoom': self._config.get('max_zoom', DEFAULT_MAX_ZOOM),
        }
        
        # Emit signal with config
        self.start_clicked.emit(config)
    
    def _build_mode_row(self):
        row = QHBoxLayout()
        row.addStretch()
        self._single_radio = QRadioButton("Single Folder")
        self._batch_radio = QRadioButton("Batch (Root)")
        for rb in (self._single_radio, self._batch_radio):
            rb.setStyleSheet(styles.LABEL_STYLE)
        group = QButtonGroup(self)
        group.addButton(self._single_radio)
        group.addButton(self._batch_radio)
        row.addWidget(self._single_radio)
        row.addWidget(self._batch_radio)
        row.addStretch()
        # Set initial state before connecting so toggling doesn't fire
        # _on_radio_changed during construction (when _config_stack doesn't exist).
        self._single_radio.setChecked(self._mode == 'single')
        self._batch_radio.setChecked(self._mode == 'batch')
        self._single_radio.toggled.connect(self._on_radio_changed)
        return row

    def _on_radio_changed(self):
        self._mode = 'batch' if self._batch_radio.isChecked() else 'single'
        self._config['mode'] = self._mode
        self._save_config()
        self._update_mode_display()

    def _on_merge(self):
        self._merge_dialog = MergeDialog(parent=self)
        self._merge_dialog.show()

    def _update_mode_display(self):
        is_batch = self._mode == 'batch'
        self._config_stack.setCurrentIndex(1 if is_batch else 0)
        self.start_btn.setText("🚀  Start Batch" if is_batch else "🚀  Start")

    def _build_batch_page(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(styles.SPACING['md'])

        root_group = QGroupBox("Root Folder (contains one sub-folder per batch)")
        root_group.setStyleSheet(styles.CARD_STYLE)
        root_row = QHBoxLayout()
        self.batch_root_edit = QLineEdit()
        self.batch_root_edit.setReadOnly(True)
        self.batch_root_edit.setStyleSheet(styles.INPUT_FIELD)
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        browse_btn.clicked.connect(self.browse_batch_root)
        root_row.addWidget(self.batch_root_edit, 1)
        root_row.addWidget(browse_btn)
        root_group.setLayout(root_row)
        lay.addWidget(root_group)

        list_group = QGroupBox("Batches")
        list_group.setStyleSheet(styles.CARD_STYLE)
        list_lay = QVBoxLayout()
        self.batch_list = QListWidget()
        list_lay.addWidget(self.batch_list, 1)
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        refresh_btn.clicked.connect(self.refresh_batch_queue)
        merge_btn = QPushButton("Merge selected…")
        merge_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        merge_btn.clicked.connect(self._on_merge_selected)
        move_btn = QPushButton("Move aligned → root_aligned")
        move_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        move_btn.clicked.connect(self._on_move_aligned)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(merge_btn)
        btn_row.addWidget(move_btn)
        btn_row.addStretch()
        list_lay.addLayout(btn_row)
        list_group.setLayout(list_lay)
        lay.addWidget(list_group, 1)
        return page

    def browse_batch_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Root Folder", str(Path.home()))
        if folder:
            self.set_batch_root(Path(folder))

    def set_batch_root(self, root):
        self._batch_root = Path(root)
        self.batch_root_edit.setText(str(self._batch_root))
        self._config['last_batch_root_dir'] = str(self._batch_root)
        self._save_config()
        self.refresh_batch_queue()

    def _save_batch_config(self):
        self._config['mode'] = 'batch'
        self._config['last_batch_root_dir'] = str(self._batch_root) if self._batch_root else ''
        self._config['target_width'] = self.width_spin.value()
        self._config['target_height'] = self.height_spin.value()
        self._save_config()

    def refresh_batch_queue(self):
        if not self._batch_root or not Path(self._batch_root).is_dir():
            if hasattr(self, 'batch_list'):
                self.batch_list.clear()
            return
        self.batch_manager = BatchManager(self._batch_root)
        self.set_batch_queue(self.batch_manager.build_queue())

    def set_batch_queue(self, queue):
        self.batch_list.clear()
        for item in queue:
            status = "✅ done" if item["done"] else "⏳ pending"
            entry = QListWidgetItem(f"{status}   {item['name']}")
            entry.setData(Qt.ItemDataRole.UserRole, item["path"])
            self.batch_list.addItem(entry)

    def get_selected_batch_paths(self):
        return [item.data(Qt.ItemDataRole.UserRole)
                for item in self.batch_list.selectedItems()]

    def _on_merge_selected(self):
        paths = self.get_selected_batch_paths()
        if not paths:
            QMessageBox.information(self, "No Selection", "Select at least one batch to merge.")
            return
        self._merge_dialog = MergeDialog(sources=paths, parent=self)
        self._merge_dialog.show()

    def _on_move_aligned(self):
        if not self._batch_root or not Path(self._batch_root).is_dir():
            QMessageBox.warning(self, "No Root", "Choose a root folder first.")
            return
        from batch import move_aligned_outputs
        report = move_aligned_outputs(self._batch_root)
        self.refresh_batch_queue()
        QMessageBox.information(
            self,
            "Moved Aligned",
            (f"Moved {len(report['moved'])} aligned folder(s) to:\n{report['dest']}"
             if report["moved"] else "No aligned output folders found to move.")
        )

    def _apply_batch_config(self):
        if not self._batch_root or not Path(self._batch_root).is_dir():
            QMessageBox.warning(self, "No Root", "Choose a valid root folder.")
            return None
        if self.batch_manager is None:
            self.refresh_batch_queue()
        pending = self.batch_manager.next_pending() if self.batch_manager else None
        if pending is None:
            QMessageBox.information(self, "All Batches Complete",
                                    "Every batch in this root is already aligned.")
            return None
        return {
            'root': str(self._batch_root),
            'target_width': self.width_spin.value(),
            'target_height': self.height_spin.value(),
            'max_zoom': self._config.get('max_zoom', DEFAULT_MAX_ZOOM),
        }