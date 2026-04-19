"""
End menu dialog for the Focal Point Aligner GUI.
Allows users to export final aligned images.
"""

import shutil
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QGroupBox, QRadioButton,
    QMessageBox, QProgressBar, QFileDialog, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal

import styles


class EndMenu(QDialog):
    """End menu dialog showing final export options."""
    
    go_back_clicked = pyqtSignal()
    export_complete = pyqtSignal(dict)

    def __init__(self, aligner, parent=None):
        self.aligner = aligner
        super().__init__(parent)
        self._output_folder = self.aligner.output_folder
        self._load_current_orientation()
        self.init_ui()
    
    def _load_current_orientation(self):
        self._current_alignment_mode = self.aligner.alignment_mode
    
    def init_ui(self):
        self.setWindowTitle("Generate Final Images")
        self.setMinimumSize(500, 400)
        self.setModal(True)
        
        self.setPalette(styles.get_palette())
        
        layout = QVBoxLayout()
        layout.setSpacing(styles.SPACING['md'])
        layout.setContentsMargins(styles.SPACING['xl'], styles.SPACING['xl'],
                            styles.SPACING['xl'], styles.SPACING['xl'])
        
        title = QLabel("Generate Final Images")
        title.setStyleSheet(styles.TITLE_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        layout.addSpacing(styles.SPACING['md'])
        
        summary_group = QGroupBox("Summary")
        summary_group.setStyleSheet(styles.CARD_STYLE)
        summary_layout = QVBoxLayout()
        summary_layout.setSpacing(styles.SPACING['sm'])
        
        total = self.aligner.total_images
        completed = self.aligner.completed_count
        
        total_label = QLabel(f"Total images: {total}")
        total_label.setStyleSheet(styles.LABEL_STYLE)
        
        completed_label = QLabel(f"Images with focal points: {completed}")
        completed_label.setStyleSheet(styles.LABEL_STYLE)
        
        pending_label = QLabel(f"Images without focal points: {total - completed}")
        pending_label.setStyleSheet(styles.LABEL_STYLE)
        
        summary_layout.addWidget(total_label)
        summary_layout.addWidget(completed_label)
        summary_layout.addWidget(pending_label)
        
        summary_group.setLayout(summary_layout)
        layout.addWidget(summary_group)
        
        orientation_group = QGroupBox("Select Orientation")
        orientation_group.setStyleSheet(styles.CARD_STYLE)
        orientation_layout = QVBoxLayout()
        orientation_layout.setSpacing(styles.SPACING['sm'])
        
        target_w = self.aligner.target_width
        target_h = self.aligner.target_height
        
        self.landscape_rb = QRadioButton(f"Landscape ({target_w}x{target_h})")
        self.landscape_rb.setStyleSheet(styles.LABEL_STYLE)
        
        self.portrait_rb = QRadioButton(f"Portrait ({target_h}x{target_w})")
        self.portrait_rb.setStyleSheet(styles.LABEL_STYLE)
        
        current_mode = getattr(self, '_current_alignment_mode', None)
        if current_mode == "landscape":
            self.landscape_rb.setChecked(True)
        elif current_mode == "portrait":
            self.portrait_rb.setChecked(True)
        elif target_w > target_h:
            self.landscape_rb.setChecked(True)
        else:
            self.portrait_rb.setChecked(True)
        
        orientation_layout.addWidget(self.landscape_rb)
        orientation_layout.addWidget(self.portrait_rb)
        
        orientation_group.setLayout(orientation_layout)
        layout.addWidget(orientation_group)
        
        output_group = QGroupBox("Output Folder")
        output_group.setStyleSheet(styles.CARD_STYLE)
        output_layout = QVBoxLayout()
        output_layout.setSpacing(styles.SPACING['sm'])
        
        self.output_label = QLabel(str(self._output_folder))
        self.output_label.setStyleSheet("color: #A0A0B0; font-size: 12px;")
        self.output_label.setWordWrap(True)
        
        browse_btn = QPushButton("Browse...")
        browse_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        browse_btn.clicked.connect(self.on_browse_output)
        
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(browse_btn)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2D2D44;
                border: 1px solid #4D4D64;
                border-radius: 4px;
                text-align: center;
                color: #FFFFFF;
            }
            QProgressBar::chunk {
                background-color: #2ECC71;
            }
        """)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        layout.addStretch()
        
        button_layout = QHBoxLayout()
        button_layout.setSpacing(styles.SPACING['md'])
        
        self.back_btn = QPushButton("←  Go Back")
        self.back_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        self.back_btn.clicked.connect(self.on_go_back)
        
        self.export_btn = QPushButton("✨  Export")
        self.export_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        self.export_btn.clicked.connect(self.on_export)
        
        button_layout.addWidget(self.back_btn)
        button_layout.addWidget(self.export_btn)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def on_go_back(self):
        self.go_back_clicked.emit()
        self.close()
    
    def on_browse_output(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            str(self._output_folder)
        )
        if folder:
            self._output_folder = Path(folder)
            self.output_label.setText(str(self._output_folder))
    
    def on_export(self):
        orientation = "landscape" if self.landscape_rb.isChecked() else "portrait"
        
        self.aligner.set_alignment_mode(orientation)
        
        preview_folder = self.aligner.get_preview_folder(orientation)
        
        if not preview_folder or not preview_folder.exists():
            QMessageBox.critical(
                self,
                "Error",
                f"Preview folder not found for {orientation} orientation.\n"
                "Please switch to Preview mode and generate previews first."
            )
            return
        
        reply = QMessageBox.question(
            self,
            "Confirm Export",
            f"Export to:\n{self._output_folder}\n\n"
            "This will also delete the preview directories.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, self.aligner.total_images)
        self.progress_bar.setValue(0)
        self.export_btn.setEnabled(False)
        self.back_btn.setEnabled(False)
        
        def do_export():
            total = self.aligner.total_images
            for i in range(total):
                src = preview_folder / f"{i + 1:04d}.jpg"
                dst = self._output_folder / f"{i + 1:04d}.jpg"
                if src.exists():
                    shutil.copy2(src, dst)
                self.progress_bar.setValue(i + 1)
            
            self.aligner.cleanup_preview_folders()
            self.aligner.delete_focal_points_file()
        
        thread = threading.Thread(target=do_export)
        thread.start()
        thread.join()
        
        self.progress_bar.setVisible(False)
        
        QMessageBox.information(
            self,
            "Export Complete",
            f"Final aligned images have been exported to:\n{self._output_folder}\n\n"
            "Preview directories have been cleaned up."
        )
        
        self.close()
        QApplication.instance().quit()