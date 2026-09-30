"""
Application Entry Point.
Launches the System Audio Recorder GUI with High-DPI support.
"""

import argparse
import os
import sys

# Ensure src/ is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from src.drivers.factory import get_audio_driver
from src.core.engine import RecordingEngine
from src.ui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="System Output Audio Recorder")
    parser.add_argument("--mock", action="store_true", help="Use Mock Audio Driver for testing without audio devices")
    args = parser.parse_args()

    # Enable High DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("DefaultOutputRecorder")
    app.setOrganizationName("AudioIntelligence")

    # Instantiate Driver and Core Engine
    driver = get_audio_driver(force_mock=args.mock)
    engine = RecordingEngine(driver=driver)

    window = MainWindow(engine=engine)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
