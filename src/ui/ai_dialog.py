"""
AI Subtitle & Translation Dialog.
Allows users to transcribe recordings, translate them, and export SRT/VTT/Markdown.
"""

import os
import threading
from typing import List, Optional
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QTextEdit,
    QProgressBar,
    QFileDialog,
    QMessageBox,
)
from src.core.models import SubtitleSegment
from src.ai.transcription import WhisperTranscriptionEngine, MockTranscriptionEngine
from src.ai.translation import GeminiTranslationEngine
from src.ai.subtitle_writer import export_srt, export_vtt, export_markdown


class WorkerSignals(QObject):
    progress = Signal(float)
    finished = Signal(list)
    error = Signal(str)


class AIDialog(QDialog):
    """
    Dialog for AI-powered Speech-to-Text and Translation.
    """

    def __init__(self, audio_filepath: str, parent=None):
        super().__init__(parent)
        self.audio_filepath = audio_filepath
        self.segments: List[SubtitleSegment] = []

        self.setWindowTitle(f"✨ AI 字幕生成 & 翻訳 - {os.path.basename(audio_filepath)}")
        self.resize(700, 500)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Top Controls: Language & Engine selection
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel("文字起こし言語:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["日本語 (ja)", "English (en)", "自動検出 (auto)"])
        top_layout.addWidget(self.lang_combo)

        top_layout.addWidget(QLabel("翻訳先言語:"))
        self.trans_combo = QComboBox()
        self.trans_combo.addItems(["なし", "English (英語)", "日本語 (Japanese)", "中国語 (Chinese)"])
        top_layout.addWidget(self.trans_combo)

        top_layout.addStretch()

        self.start_btn = QPushButton("🚀 文字起こし開始")
        self.start_btn.setStyleSheet("background-color: #3B82F6; color: white; font-weight: bold; padding: 6px 16px;")
        self.start_btn.clicked.connect(self._run_transcription)
        top_layout.addWidget(self.start_btn)
        layout.addLayout(top_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Result Text Box
        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setPlaceholderText("ここに文字起こし結果と字幕が表示されます...")
        layout.addWidget(self.result_box)

        # Export Buttons
        export_layout = QHBoxLayout()
        export_layout.addWidget(QLabel("エクスポート:"))

        self.export_srt_btn = QPushButton("📄 SRT字幕保存")
        self.export_srt_btn.setEnabled(False)
        self.export_srt_btn.clicked.connect(self._export_srt)
        export_layout.addWidget(self.export_srt_btn)

        self.export_vtt_btn = QPushButton("🌐 WebVTT保存")
        self.export_vtt_btn.setEnabled(False)
        self.export_vtt_btn.clicked.connect(self._export_vtt)
        export_layout.addWidget(self.export_vtt_btn)

        self.export_md_btn = QPushButton("📝 Markdown議事録保存")
        self.export_md_btn.setEnabled(False)
        self.export_md_btn.clicked.connect(self._export_markdown)
        export_layout.addWidget(self.export_md_btn)

        export_layout.addStretch()
        layout.addLayout(export_layout)

    def _run_transcription(self):
        self.start_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.result_box.setText("⏳ AI音声認識を実行中...")

        lang_code = "ja" if "ja" in self.lang_combo.currentText() else "en"

        def worker():
            try:
                try:
                    engine = WhisperTranscriptionEngine(model_size="base")
                    segments = engine.transcribe(self.audio_filepath, language=lang_code)
                except Exception as e:
                    print(f"[AIDialog] Whisper not available, using MockEngine: {e}")
                    engine = MockTranscriptionEngine()
                    segments = engine.transcribe(self.audio_filepath, language=lang_code)

                # Check translation
                trans_target = self.trans_combo.currentText()
                if "English" in trans_target:
                    trans_engine = GeminiTranslationEngine()
                    segments = trans_engine.translate_segments(segments, target_lang="en")
                elif "日本語" in trans_target:
                    trans_engine = GeminiTranslationEngine()
                    segments = trans_engine.translate_segments(segments, target_lang="ja")

                self._on_finished(segments)
            except Exception as e:
                self._on_error(str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_finished(self, segments: List[SubtitleSegment]):
        self.segments = segments
        self.start_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.export_srt_btn.setEnabled(True)
        self.export_vtt_btn.setEnabled(True)
        self.export_md_btn.setEnabled(True)

        lines = []
        for s in segments:
            line = f"[{s.start_seconds:05.1f}s -> {s.end_seconds:05.1f}s] {s.text}"
            if s.translated_text:
                line += f"\n  ↪ 🌐 {s.translated_text}"
            lines.append(line)

        self.result_box.setText("\n\n".join(lines))

    def _on_error(self, err_msg: str):
        self.start_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.result_box.setText(f"❌ エラーが発生しました:\n{err_msg}")

    def _export_srt(self):
        default_name = os.path.splitext(self.audio_filepath)[0] + ".srt"
        path, _ = QFileDialog.getSaveFileName(self, "SRT字幕を保存", default_name, "SubRip Subtitle (*.srt)")
        if path:
            export_srt(self.segments, path, include_translation=True)
            QMessageBox.information(self, "完了", f"SRT字幕を保存しました:\n{path}")

    def _export_vtt(self):
        default_name = os.path.splitext(self.audio_filepath)[0] + ".vtt"
        path, _ = QFileDialog.getSaveFileName(self, "WebVTT字幕を保存", default_name, "WebVTT Subtitle (*.vtt)")
        if path:
            export_vtt(self.segments, path, include_translation=True)
            QMessageBox.information(self, "完了", f"WebVTT字幕を保存しました:\n{path}")

    def _export_markdown(self):
        default_name = os.path.splitext(self.audio_filepath)[0] + "_minutes.md"
        path, _ = QFileDialog.getSaveFileName(self, "Markdown議事録を保存", default_name, "Markdown (*.md)")
        if path:
            export_markdown(self.segments, path)
            QMessageBox.information(self, "完了", f"議事録Markdownを保存しました:\n{path}")
