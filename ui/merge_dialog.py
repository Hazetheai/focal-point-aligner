"""
Merge dialog: combine images from multiple folders into one output folder,
prefixing each file with its source folder name.
"""

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QLineEdit, QMessageBox, QFileDialog, QListWidget, QDialogButtonBox
)

import styles
from batch import merge_folders


class MergeDialog(QDialog):
    """Multi-folder merge dialog. Emits merge_complete(dict) on success."""

    merge_complete = pyqtSignal(dict)

    def __init__(self, sources=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge Folders")
        self.setMinimumSize(520, 420)
        self.setModal(True)
        self.setPalette(styles.get_palette())
        self._build_ui()
        if sources:
            for src in sources:
                self._add_source(Path(src))

    def _build_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        title = QLabel("Merge Folders")
        title.setStyleSheet(styles.TITLE_LABEL)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        help_label = QLabel(
            "Combines images from the selected folders into one output folder.\n"
            "Each file is prefixed with its source folder name (e.g. fuji_img_0042.jpg).\n"
            "If a folder has an aligned output, its aligned images are used instead."
        )
        help_label.setStyleSheet(styles.LABEL_STYLE)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.source_list = QListWidget()
        layout.addWidget(self.source_list, 1)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add folders…")
        add_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        add_btn.clicked.connect(self._browse_add)
        remove_btn = QPushButton("Remove selected")
        remove_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder:"))
        self.output_edit = QLineEdit()
        self.output_edit.setStyleSheet(styles.INPUT_FIELD)
        out_row.addWidget(self.output_edit, 1)
        browse_btn = QPushButton("Browse")
        browse_btn.setStyleSheet(styles.BUTTON_OUTLINE)
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        self.aligned_check = QCheckBox("Use aligned outputs when present")
        self.aligned_check.setChecked(True)
        self.aligned_check.setStyleSheet(styles.LABEL_STYLE)
        layout.addWidget(self.aligned_check)

        buttons = QDialogButtonBox()
        back_btn = buttons.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        merge_btn = buttons.addButton("Merge", QDialogButtonBox.ButtonRole.AcceptRole)
        back_btn.setStyleSheet(styles.BUTTON_SECONDARY)
        merge_btn.setStyleSheet(styles.BUTTON_PRIMARY)
        buttons.accepted.connect(self._on_merge)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def _add_source(self, folder):
        self.source_list.addItem(str(folder))

    def _remove_selected(self):
        for item in self.source_list.selectedItems():
            self.source_list.takeItem(self.source_list.row(item))

    def _browse_add(self):
        dlg = QFileDialog.getExistingDirectory(self, "Add Folder", str(Path.home()))
        if dlg:
            self._add_source(Path(dlg))

    def _browse_output(self):
        dlg = QFileDialog.getExistingDirectory(
            self, "Output Folder", self.output_edit.text() or str(Path.home()))
        if dlg:
            self.output_edit.setText(dlg)

    def _on_merge(self):
        sources = [Path(self.source_list.item(i).text())
                   for i in range(self.source_list.count())]
        if not sources:
            QMessageBox.warning(self, "No Folders", "Add at least one folder to merge.")
            return
        output = self.output_edit.text().strip()
        if not output:
            output = str(sources[0].parent / "merged")
        report = merge_folders(
            sources, output, use_aligned=self.aligned_check.isChecked())
        QMessageBox.information(
            self,
            "Merge Complete",
            f"Merged {report['merged_count']} images into:\n{report['dest']}\n\n"
            + (f"{report['skipped']} skipped.\n" if report["skipped"] else "")
            + ("Warnings:\n" + "\n".join(report["warnings"]) if report["warnings"] else "")
        )
        self.merge_complete.emit(report)
        self.accept()