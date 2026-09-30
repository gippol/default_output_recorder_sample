"""
UI Integration Tests for PySide6 MainWindow.
"""

import os
import sys
import pytest
from PySide6.QtWidgets import QApplication

from src.core.engine import RecordingEngine
from src.drivers.mock_driver import MockAudioDriver
from src.ui.main_window import MainWindow

# Ensure single QApplication per test session
app = QApplication.instance() or QApplication(sys.argv)


def test_main_window_lifecycle(tmp_path):
    """Test MainWindow initialization, controls, and recording lifecycle."""
    mock_driver = MockAudioDriver(frequency=440.0)
    engine = RecordingEngine(driver=mock_driver)

    window = MainWindow(engine=engine)
    window.dir_input.setText(str(tmp_path))

    # Verify initial state
    assert window.record_btn.isEnabled()
    assert not window.pause_btn.isEnabled()
    assert not window.stop_btn.isEnabled()

    # Start Recording
    window.record_btn.click()
    assert not window.record_btn.isEnabled()
    assert window.pause_btn.isEnabled()
    assert window.stop_btn.isEnabled()

    # Add Marker
    window.marker_btn.click()
    assert len(engine._markers) >= 1

    # Pause
    window.pause_btn.click()
    assert engine.state_machine.is_paused()

    # Resume
    window.pause_btn.click()
    assert engine.state_machine.is_recording()

    # Stop Recording
    window.stop_btn.click()
    assert window.record_btn.isEnabled()

    # Verify history list
    assert window.history_panel.list_widget.count() >= 1

    window.close()
