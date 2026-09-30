"""
Recording History Panel with playback preview, folder access, and AI actions.
"""

import os
import subprocess
import sys
from typing import Callable, Optional
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
    QMessageBox,
)


class HistoryPanel(QWidget):
    """
    Displays recent recordings with actions:
    - Open File / Play
    - Open Containing Folder
    - Transcribe / Translate (TODO Hook)
    """

    def __init__(self, parent=None, on_transcribe_requested: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self.on_transcribe_requested = on_transcribe_requested

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("📁 録音履歴 (Recent Recordings)")
        title.setStyleSheet("font-weight: bold; color: #94A3B8; font-size: 12px;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.clear_btn = QPushButton("クリア")
        self.clear_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.clear_btn.clicked.connect(self._clear_history)
        header_layout.addWidget(self.clear_btn)
        layout.addLayout(header_layout)

        # File List
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget)

        # Action Buttons
        btn_layout = QHBoxLayout()
        self.play_btn = QPushButton("▶ 再生 (Play)")
        self.play_btn.clicked.connect(self._play_selected)
        btn_layout.addWidget(self.play_btn)

        self.folder_btn = QPushButton("📂 フォルダを開く")
        self.folder_btn.clicked.connect(self._open_folder)
        btn_layout.addWidget(self.folder_btn)

        self.ai_btn = QPushButton("✨ AI字幕・翻訳")
        self.ai_btn.setStyleSheet("background-color: #3B82F6; color: white;")
        self.ai_btn.clicked.connect(self._request_ai_transcription)
        btn_layout.addWidget(self.ai_btn)

        layout.addLayout(btn_layout)

    def add_recording(self, filepath: str, duration: float) -> None:
        """Add a newly recorded file to the history list."""
        if not os.path.exists(filepath):
            return

        filename = os.path.basename(filepath)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        dur_mins = int(duration // 60)
        dur_secs = int(duration % 60)

        label_text = f"{filename}  ({dur_mins:02d}:{dur_secs:02d} / {size_mb:.2f} MB)"
        item = QListWidgetItem(label_text)
        item.setData(Qt.ItemDataRole.UserRole, filepath)
        self.list_widget.insertItem(0, item)
        self.list_widget.setCurrentItem(item)

    def _get_selected_filepath(self) -> Optional[str]:
        current_item = self.list_widget.currentItem()
        if not current_item:
            return None
        return current_item.data(Qt.ItemDataRole.UserRole)

    def _play_selected(self) -> None:
        path = self._get_selected_filepath()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "エラー", "再生するファイルが選択されていないか、存在しません。")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._play_selected()

    def _open_folder(self) -> None:
        path = self._get_selected_filepath()
        folder = os.path.dirname(path) if path else os.getcwd()

        if sys.platform.startswith("win"):
            if path and os.path.exists(path):
                subprocess.run(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(folder)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _request_ai_transcription(self) -> None:
        path = self._get_selected_filepath()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "エラー", "文字起こしするファイルを選択してください。")
            return
        if self.on_transcribe_requested:
            self.on_transcribe_requested(path)
        else:
            QMessageBox.information(self, "AI字幕・翻訳 (TODO)", f"選択中の音声: {os.path.basename(path)}\nAI文字起こし・翻訳モジュールを呼び出します。")

    def _clear_history(self) -> None:
        self.list_widget.clear()
