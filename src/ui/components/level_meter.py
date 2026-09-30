"""
Stereo Audio Level Meter with Peak Hold and Clipping Indicator.
Rendered in high-performance QPainter at 60fps.
"""

from typing import List
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QFont
from PySide6.QtWidgets import QWidget
from src.core.models import AudioTelemetry


class AudioLevelMeter(QWidget):
    """
    Renders dynamic stereo audio level bars (dB scale: -60dB to 0dB).
    Includes peak hold and clipping indicator LEDs.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setMinimumWidth(200)

        self._channel_peaks: List[float] = [-60.0, -60.0]
        self._peak_hold: List[float] = [-60.0, -60.0]
        self._is_clipping = False
        self._min_db = -60.0
        self._max_db = 0.0

    def update_telemetry(self, telemetry: AudioTelemetry) -> None:
        """Update meter with latest audio telemetry from pipeline."""
        peaks = telemetry.channel_peaks if len(telemetry.channel_peaks) >= 2 else [telemetry.peak_db, telemetry.peak_db]
        self._channel_peaks = peaks[:2]
        self._is_clipping = telemetry.is_clipping

        # Peak hold with slow decay
        for i in range(len(self._channel_peaks)):
            if self._channel_peaks[i] > self._peak_hold[i]:
                self._peak_hold[i] = self._channel_peaks[i]
            else:
                self._peak_hold[i] = max(self._min_db, self._peak_hold[i] - 0.4)

        self.update()

    def reset(self) -> None:
        """Reset meter display to silence."""
        self._channel_peaks = [self._min_db, self._min_db]
        self._peak_hold = [self._min_db, self._min_db]
        self._is_clipping = False
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()

        # Background
        painter.fillRect(0, 0, width, height, QColor("#14151B"))

        channel_height = (height - 12) / 2
        labels = ["L", "R"]

        for ch in range(2):
            y_offset = 4 + ch * (channel_height + 4)
            db_val = self._channel_peaks[ch] if ch < len(self._channel_peaks) else self._min_db
            hold_val = self._peak_hold[ch] if ch < len(self._peak_hold) else self._min_db

            # Normalize to 0.0 - 1.0 range
            norm_val = max(0.0, min(1.0, (db_val - self._min_db) / (self._max_db - self._min_db)))
            norm_hold = max(0.0, min(1.0, (hold_val - self._min_db) / (self._max_db - self._min_db)))

            # Draw Channel Label
            painter.setPen(QColor("#64748B"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(4, y_offset, 14, channel_height), Qt.AlignmentFlag.AlignCenter, labels[ch])

            bar_x = 22
            bar_w = width - bar_x - 48
            bar_rect = QRectF(bar_x, y_offset, bar_w, channel_height)

            # Bar Background Track
            painter.fillRect(bar_rect, QColor("#1E212B"))

            # Gradient Active Bar (Green -> Yellow -> Red)
            if norm_val > 0.001:
                fill_w = bar_w * norm_val
                gradient = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
                gradient.setColorAt(0.0, QColor("#10B981"))  # Green
                gradient.setColorAt(0.7, QColor("#FBBF24"))  # Yellow
                gradient.setColorAt(0.9, QColor("#EF4444"))  # Red
                gradient.setColorAt(1.0, QColor("#DC2626"))  # Dark Red

                painter.fillRect(QRectF(bar_x, y_offset, fill_w, channel_height), gradient)

            # Peak Hold Indicator Line
            if norm_hold > 0.01:
                hold_x = bar_x + bar_w * norm_hold
                painter.setPen(QColor("#FFFFFF"))
                painter.drawLine(int(hold_x), int(y_offset), int(hold_x), int(y_offset + channel_height))

            # Numeric dB Text
            painter.setPen(QColor("#94A3B8"))
            painter.setFont(QFont("Consolas", 8))
            db_text = f"{db_val:5.1f} dB" if db_val > self._min_db + 0.5 else "  -inf dB"
            painter.drawText(QRectF(width - 44, y_offset, 40, channel_height), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, db_text)

        # Clipping Indicator Dot
        clip_color = QColor("#EF4444") if self._is_clipping else QColor("#2D3139")
        painter.setBrush(clip_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(width - 44, 4, 6, 6)
