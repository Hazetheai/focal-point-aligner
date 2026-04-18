"""
Closing screen for the Focal Point Aligner GUI.
Shows summary stats and allows export or new batch.
"""

import subprocess
import sys

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGroupBox, QComboBox, QSpinBox,
    QFileDialog, QMessageBox, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal

import styles


class CloserScreen(QWidget):
    """Closing screen showing summary and export options."""
    
    # Signal emitted when user wants to start a new batch
    new_batch_clicked = pyqtSignal()
    
    # Signal emitted when user wants to exit
    exit_clicked = pyqtSignal()
    
    def __init__(self, stats: dict, parent=None):
        """
        Initialize the closer screen.
        
        Args:
            stats: Dictionary containing:
                - total: total number of images
                - with_focal: images with focal points
                - center_focal: images with center focal points
                - without_focal: images without focal points
                - input_folder: path to input
                - output_folder: path to output
                - target_width: target width
                - target_height: target height
        """
        self.stats = stats
        super().__init__(parent)
        self.init_ui()
    
    def init_ui(self):
        self.setWindowTitle("Processing Complete")
        self.setMinimumSize(700, 500)
        
        # Apply palette
        self.setPalette(styles.get_palette())
        
        layout = QVBoxLayout()
        layout.setSpacing(styles.SPACING['md'])
        layout.setContentsMargins(styles.SPACING['xl'], styles.SPACING['xl'],
                                  styles.SPACING['xl'], styles.SPACING['xl'])
        
        # Title
        title = QLabel("Processing Complete")
        title.setStyleSheet(styles.TITLE_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        layout.addSpacing(styles.SPACING['md'])
        
        # Summary stats
        summary_group = QGroupBox("Summary")
        summary_group.setStyleSheet(styles.CARD_STYLE)
        summary_layout = QVBoxLayout()
        summary_layout.setSpacing(styles.SPACING['sm'])
        
        total_label = QLabel(f"✓ Total images: {self.stats['total']}")
        total_label.setStyleSheet(styles.LABEL_STYLE)
        
        focal_label = QLabel(f"✓ Images with focal points: {self.stats['with_focal']}")
        focal_label.setStyleSheet(styles.LABEL_STYLE)
        
        center_label = QLabel(f"⚠ Images with center focal (no real alignment): {self.stats['center_focal']}")
        center_label.setStyleSheet(styles.LABEL_STYLE)
        
        no_focal_label = QLabel(f"○ Images without focal points: {self.stats['without_focal']}")
        no_focal_label.setStyleSheet(styles.LABEL_STYLE)
        
        summary_layout.addWidget(total_label)
        summary_layout.addWidget(focal_label)
        summary_layout.addWidget(center_label)
        summary_layout.addWidget(no_focal_label)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        # Export options
        export_group = QGroupBox("Export Options")
        export_group.setStyleSheet(styles.CARD_STYLE)
        export_layout = QGridLayout()
        export_layout.setSpacing(styles.SPACING['md'])
        
        # Format
        format_label = QLabel("Format:")
        format_label.setStyleSheet(styles.LABEL_STYLE)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["JPEG", "PNG"])
        self.format_combo.setStyleSheet("""
            QComboBox {
                background-color: #2D2D44;
                color: #FFFFFF;
                border: 1px solid #4D4D64;
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        
        # Quality
        quality_label = QLabel("Quality:")
        quality_label.setStyleSheet(styles.LABEL_STYLE)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(95)
        self.quality_spin.setStyleSheet(styles.SPIN_BOX)
        
        # Output location
        output_label = QLabel("Output folder:")
        output_label.setStyleSheet(styles.LABEL_STYLE)
        
        output_path_layout = QHBoxLayout()
        self.output_path = QLineEdit(self.stats.get('output_folder', ''))
        self.output_path.setStyleSheet(styles.INPUT_FIELD)
        self.output_path.setReadOnly(True)
        
        self.output_btn = QPushButton("Change")
        self.output_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        self.output_btn.clicked.connect(self.browse_output_folder)
        
        output_path_layout.addWidget(self.output_path, 1)
        output_path_layout.addWidget(self.output_btn)
        
        export_layout.addWidget(format_label, 0, 0)
        export_layout.addWidget(self.format_combo, 0, 1)
        export_layout.addWidget(quality_label, 0, 2)
        export_layout.addWidget(self.quality_spin, 0, 3)
        export_layout.addWidget(output_label, 1, 0)
        export_layout.addWidget(output_path_layout, 1, 1, 1, 3)
        
        export_group.setLayout(export_layout)
        layout.addWidget(export_group)
        
        layout.addStretch()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(styles.SPACING['md'])
        
        self.new_batch_btn = QPushButton("🔄  New Batch")
        self.new_batch_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        self.new_batch_btn.clicked.connect(self.on_new_batch)
        
        self.export_btn = QPushButton("📤  Export & Exit")
        self.export_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.export_btn.clicked.connect(self.on_export)
        
        button_layout.addWidget(self.new_batch_btn)
        button_layout.addWidget(self.export_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            self.output_path.text() or str(Path.home())
        )
        if folder:
            self.output_path.setText(folder)
    
    def on_new_batch(self):
        self.new_batch_clicked.emit()
    
    def on_export(self):
        output_folder = self.output_path.text().strip()
        if not output_folder:
            output_folder = self.stats.get('output_folder', '')
        
        if not output_folder:
            QMessageBox.warning(
                self,
                "No Output Folder",
                "Please select an output folder."
            )
            return
        
        # Show progress message
        msg = QMessageBox(self)
        msg.setWindowTitle("Exporting...")
        msg.setText("Running alignment export...\nThis may take a while.")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.show()
        
        # Determine target dimensions based on orientation
        target_w = self.stats.get('target_width', 2560)
        target_h = self.stats.get('target_height', 1440)
        
        # Determine orientation based on dimensions
        if target_w > target_h:
            orientation = "landscape"
        else:
            orientation = "portrait"
        
        # Try to run the export script
        try:
            # Get the scripts directory
            script_dir = Path(__file__).parent.parent / "scripts"
            export_script = script_dir / "align_and_scale_images.py"
            
            if not export_script.exists():
                # Try the parent directory as fallback
                export_script = Path(__file__).parent.parent / "align_and_scale_images.py"
            
            if export_script.exists():
                input_folder = self.stats.get('input_folder', '')
                
                result = subprocess.run(
                    [
                        sys.executable,
                        str(export_script),
                        input_folder,
                        "--output", output_folder,
                        "--orientation", orientation
                    ],
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    QMessageBox.information(
                        self,
                        "Export Complete",
                        f"Images have been exported to:\n{output_folder}"
                    )
                else:
                    QMessageBox.critical(
                        self,
                        "Export Failed",
                        f"Error during export:\n{result.stderr}"
                    )
            else:
                QMessageBox.warning(
                    self,
                    "Export Script Not Found",
                    "The alignment script was not found. Please run it manually."
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Error running export: {str(e)}"
            )
        finally:
            msg.close()
        
        # Emit exit signal
        self.exit_clicked.emit()