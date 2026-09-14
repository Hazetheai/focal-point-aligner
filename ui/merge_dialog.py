"""
Merge dialog: combine images from multiple folders into one output folder,
prefixing each file with its source folder name.
"""

import os
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QLineEdit, QMessageBox, QFileDialog, QListWidget, QDialogButtonBox,
    QAbstractItemView,
)

import styles
from batch import merge_folders, folder_is_aligned


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
            "If a folder has an aligned output, its aligned images are used instead.\n"
            "Tip: Ctrl/Shift-click to select multiple folders. If every selected\n"
            "folder is aligned, '_aligned' is appended to the output name.\n"
            "'Delete source folders' removes each folder only after all its images\n"
            "were copied; folders that failed are kept."
        )
        help_label.setStyleSheet(styles.LABEL_STYLE)
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.source_list = QListWidget()
        self.source_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
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

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Merged folder name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setText("merged")
        self.name_edit.setStyleSheet(styles.INPUT_FIELD)
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        self.aligned_check = QCheckBox("Use aligned outputs when present")
        self.aligned_check.setChecked(True)
        self.aligned_check.setStyleSheet(styles.LABEL_STYLE)
        layout.addWidget(self.aligned_check)

        self.delete_check = QCheckBox("Delete source folders after merging")
        self.delete_check.setChecked(False)
        self.delete_check.setStyleSheet(styles.LABEL_STYLE)
        layout.addWidget(self.delete_check)

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

    def _on_merge(self):
        sources = [Path(self.source_list.item(i).text())
                   for i in range(self.source_list.count())]
        if not sources:
            QMessageBox.warning(self, "No Folders", "Add at least one folder to merge.")
            return
        name = self.name_edit.text().strip() or "merged"
        if all(folder_is_aligned(s) for s in sources) and not name.lower().endswith("_aligned"):
            name += "_aligned"
        if len(sources) == 1:
            parent = sources[0].parent
        else:
            try:
                parent = Path(os.path.commonpath([str(s) for s in sources]))
            except ValueError:
                parent = sources[0].parent
        output = parent / name
        report = merge_folders(
            sources, output, use_aligned=self.aligned_check.isChecked(),
            delete_sources=self.delete_check.isChecked())
        msg = f"Merged {report['merged_count']} images into:\n{report['dest']}\n\n"
        if report["skipped"]:
            msg += f"{report['skipped']} skipped.\n"
        if report["deleted"]:
            msg += "Deleted source folder(s):\n" + "\n".join(report["deleted"]) + "\n"
        if report["warnings"]:
            msg += "Warnings:\n" + "\n".join(report["warnings"]) + "\n"
        QMessageBox.information(self, "Merge Complete", msg)
        self.merge_complete.emit(report)
        self.accept()