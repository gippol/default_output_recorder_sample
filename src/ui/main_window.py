"""
Main Application Window for the Audio Recorder.
Combines Core Engine, Reactive EventBus, Visualizers, and History into a sleek UI.
"""

import os
from typing import Optional
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QGroupBox,
    QPushButton,
    QComboBox,
    QLabel,
    QCheckBox,
    QLineEdit,
    QFileDialog,
    QMessageBox,
)

from src.core.models import (
    AudioChunk,
    AudioTelemetry,
    Marker,
    OutputFormat,
    RecordingConfig,
    RecordingState,
)
from src.core.event_bus import EventBus, EventType
from src.core.engine import RecordingEngine
from src.ui.styles.theme import MODERN_DARK_THEME
from src.ui.components.level_meter import AudioLevelMeter
from src.ui.components.visualizer import WaveformVisualizer
from src.ui.components.history_panel import HistoryPanel
from src.ui.ai_dialog import AIDialog


class QtEventBridge(QObject):
    """Bridges non-Qt engine threads to Qt Main Thread via signals."""
    telemetry_received = Signal(object)
    chunk_received = Signal(object)
    state_changed = Signal(object, object)
    recording_stopped = Signal(str, float, list)
    error_received = Signal(str)


class MainWindow(QMainWindow):
    """
    Sleek, modern Desktop Audio Recording Application.
    """

    def __init__(self, engine: Optional[RecordingEngine] = None):
        super().__init__()
        self.engine = engine or RecordingEngine()
        self.event_bus = EventBus()
        self.bridge = QtEventBridge()

        self.setWindowTitle("🎙️ System Audio Recorder - Silicon Valley Edition")
        self.resize(750, 720)
        self.setStyleSheet(MODERN_DARK_THEME)

        self._init_ui()
        self._setup_event_listeners()
        self._populate_devices()

        # UI Refresh Timer for duration
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_timer_display)
        self.timer.start(100)

        # Start background buffering (time-shift pre-recording)
        self.engine.start_buffering()

    def _init_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Device & Settings Section
        settings_group = QGroupBox("⚙️ 設定 & 入力デバイス (Settings & Device)")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setSpacing(10)

        # Device Combo
        settings_layout.addWidget(QLabel("録音対象 (Audio Output):"), 0, 0)
        self.device_combo = QComboBox()
        settings_layout.addWidget(self.device_combo, 0, 1, 1, 3)

        # Format & Bitrate
        settings_layout.addWidget(QLabel("保存形式 (Format):"), 1, 0)
        self.format_combo = QComboBox()
        for fmt in OutputFormat:
            self.format_combo.addItem(fmt.name, fmt)
        self.format_combo.setCurrentText(OutputFormat.WAV.name)
        settings_layout.addWidget(self.format_combo, 1, 1)

        settings_layout.addWidget(QLabel("ビットレート:"), 1, 2)
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(["128 kbps", "192 kbps", "256 kbps", "320 kbps (最高音質)"])
        self.bitrate_combo.setCurrentIndex(3)
        settings_layout.addWidget(self.bitrate_combo, 1, 3)

        # Save Directory
        settings_layout.addWidget(QLabel("保存先フォルダ:"), 2, 0)
        self.dir_input = QLineEdit(os.path.abspath("./recordings"))
        settings_layout.addWidget(self.dir_input, 2, 1, 1, 2)

        self.browse_btn = QPushButton("参照...")
        self.browse_btn.clicked.connect(self._browse_directory)
        settings_layout.addWidget(self.browse_btn, 2, 3)

        # Checkbox Options (Time-Shift & VAD)
        options_layout = QHBoxLayout()
        self.timeshift_check = QCheckBox("🕒 タイムシフト録音（直前30秒も含めて保存）")
        self.timeshift_check.setChecked(True)
        options_layout.addWidget(self.timeshift_check)

        self.vad_check = QCheckBox("✂️ 無音区間の自動スキップ (VAD)")
        self.vad_check.setChecked(False)
        options_layout.addWidget(self.vad_check)

        options_layout.addStretch()
        settings_layout.addLayout(options_layout, 3, 0, 1, 4)

        main_layout.addWidget(settings_group)

        # 2. Visualizers & Live Telemetry Section
        monitor_group = QGroupBox("📊 リアルタイム・オーディオモニター (Live Monitor)")
        monitor_layout = QVBoxLayout(monitor_group)
        monitor_layout.setSpacing(10)

        # Timer & Status Row
        status_row = QHBoxLayout()
        self.status_label = QLabel("● 待機中 (IDLE / BUFFERING)")
        self.status_label.setStyleSheet("font-weight: bold; color: #10B981; font-size: 13px;")
        status_row.addWidget(self.status_label)

        status_row.addStretch()

        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("font-family: 'Consolas', monospace; font-size: 24px; font-weight: bold; color: #60A5FA;")
        status_row.addWidget(self.time_label)
        monitor_layout.addLayout(status_row)

        # Level Meter
        self.level_meter = AudioLevelMeter()
        monitor_layout.addWidget(self.level_meter)

        # Waveform Visualizer
        self.waveform = WaveformVisualizer()
        monitor_layout.addWidget(self.waveform)

        main_layout.addWidget(monitor_group)

        # 3. Control Buttons Row
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(12)

        self.record_btn = QPushButton("● 録音開始 (REC)")
        self.record_btn.setObjectName("record_btn")
        self.record_btn.clicked.connect(self._toggle_recording)
        controls_layout.addWidget(self.record_btn)

        self.pause_btn = QPushButton("⏸ 一時停止 (Pause)")
        self.pause_btn.setObjectName("pause_btn")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        controls_layout.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("■ 停止 (STOP)")
        self.stop_btn.setObjectName("stop_btn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_recording)
        controls_layout.addWidget(self.stop_btn)

        self.marker_btn = QPushButton("📌 マーカー (Marker)")
        self.marker_btn.setEnabled(False)
        self.marker_btn.clicked.connect(self._add_marker)
        controls_layout.addWidget(self.marker_btn)

        main_layout.addLayout(controls_layout)

        # 4. History Panel
        self.history_panel = HistoryPanel(on_transcribe_requested=self._open_ai_dialog)
        main_layout.addWidget(self.history_panel)

    def _setup_event_listeners(self):
        self._handlers = {
            EventType.TELEMETRY_UPDATE: lambda t: self._safe_emit(self.bridge.telemetry_received, t),
            EventType.CHUNK_PROCESSED: lambda c: self._safe_emit(self.bridge.chunk_received, c),
            EventType.STATE_CHANGED: lambda o, n: self._safe_emit(self.bridge.state_changed, o, n),
            EventType.RECORDING_STOPPED: lambda path, dur, markers: self._safe_emit(self.bridge.recording_stopped, path, dur, markers),
            EventType.ERROR_OCCURRED: lambda msg, exc: self._safe_emit(self.bridge.error_received, msg),
        }

        for event_type, handler in self._handlers.items():
            self.event_bus.subscribe(event_type, handler)

        # Connect Qt signals to UI methods
        self.bridge.telemetry_received.connect(self.level_meter.update_telemetry)
        self.bridge.chunk_received.connect(self.waveform.push_chunk)
        self.bridge.state_changed.connect(self._on_state_changed)
        self.bridge.recording_stopped.connect(self._on_recording_stopped)
        self.bridge.error_received.connect(self._on_error)

    def _safe_emit(self, signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _populate_devices(self):
        self.device_combo.clear()
        devices = self.engine.get_output_devices()
        default_dev = self.engine.get_default_device()

        for d in devices:
            self.device_combo.addItem(str(d), d)

        if default_dev:
            for idx in range(self.device_combo.count()):
                d = self.device_combo.itemData(idx)
                if d and d.id == default_dev.id:
                    self.device_combo.setCurrentIndex(idx)
                    break

    def _browse_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "保存先フォルダを選択", self.dir_input.text())
        if dir_path:
            self.dir_input.setText(dir_path)

    def _get_current_config(self) -> RecordingConfig:
        dev = self.device_combo.currentData()
        fmt = self.format_combo.currentData() or OutputFormat.WAV
        bitrate_str = self.bitrate_combo.currentText()
        bitrate = int(bitrate_str.split()[0]) if "kbps" in bitrate_str else 320

        return RecordingConfig(
            output_dir=self.dir_input.text(),
            format=fmt,
            bitrate_kbps=bitrate,
            enable_time_shift=self.timeshift_check.isChecked(),
            enable_vad=self.vad_check.isChecked(),
            device_id=dev.id if dev else None
        )

    def _toggle_recording(self):
        if not self.engine.state_machine.is_recording():
            config = self._get_current_config()
            include_shift = self.timeshift_check.isChecked()
            self.engine.start_recording(config, include_time_shift=include_shift)

    def _toggle_pause(self):
        if self.engine.state_machine.is_recording():
            self.engine.pause_recording()
        elif self.engine.state_machine.is_paused():
            self.engine.resume_recording()

    def _stop_recording(self):
        self.engine.stop_recording(keep_buffering=True)

    def _add_marker(self):
        marker = self.engine.add_marker(label="Bookmark")
        if marker:
            self.status_label.setText(f"📌 マーカー追加: {marker.timestamp:.1f}s")

    def _on_state_changed(self, old_state: RecordingState, new_state: RecordingState):
        if new_state == RecordingState.RECORDING:
            self.status_label.setText("🔴 録音中 (RECORDING)")
            self.status_label.setStyleSheet("font-weight: bold; color: #EF4444; font-size: 13px;")
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("⏸ 一時停止")
            self.stop_btn.setEnabled(True)
            self.marker_btn.setEnabled(True)
        elif new_state == RecordingState.PAUSED:
            self.status_label.setText("⏸ 一時停止中 (PAUSED)")
            self.status_label.setStyleSheet("font-weight: bold; color: #FBBF24; font-size: 13px;")
            self.pause_btn.setText("▶ 再開 (Resume)")
        elif new_state in (RecordingState.IDLE, RecordingState.BUFFERING):
            self.status_label.setText("● 待機中 (IDLE / タイムシフト待機)")
            self.status_label.setStyleSheet("font-weight: bold; color: #10B981; font-size: 13px;")
            self.record_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.marker_btn.setEnabled(False)
            self.time_label.setText("00:00:00")
            self.level_meter.reset()

    def _on_recording_stopped(self, filepath: str, duration: float, markers: list):
        self.history_panel.add_recording(filepath, duration)

    def _on_error(self, err_msg: str):
        QMessageBox.critical(self, "エラー", f"録音エラーが発生しました:\n{err_msg}")

    def _update_timer_display(self):
        if self.engine.state_machine.is_recording() or self.engine.state_machine.is_paused():
            dur = self.engine.current_recording_duration
            hours = int(dur // 3600)
            mins = int((dur % 3600) // 60)
            secs = int(dur % 60)
            self.time_label.setText(f"{hours:02d}:{mins:02d}:{secs:02d}")

    def _open_ai_dialog(self, audio_filepath: str):
        dialog = AIDialog(audio_filepath, parent=self)
        dialog.exec()

    def closeEvent(self, event):
        if hasattr(self, "_handlers"):
            for event_type, handler in self._handlers.items():
                self.event_bus.unsubscribe(event_type, handler)
        self.engine.shutdown()
        event.accept()
