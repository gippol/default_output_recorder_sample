"""
Real-time Oscilloscope / Waveform Visualizer.
Smoothly renders incoming audio signals with high-performance QPainter.
"""

from collections import deque
import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QPainterPath
from PySide6.QtWidgets import QWidget
from src.core.models import AudioChunk


class WaveformVisualizer(QWidget):
    """
    Renders a dynamic, glowing audio waveform oscilloscope.
    """

    def __init__(self, parent=None, max_samples: int = 512):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMinimumWidth(200)
        self.max_samples = max_samples
        self._samples = deque([0.0] * max_samples, maxlen=max_samples)

    def push_chunk(self, chunk: AudioChunk) -> None:
        """Push downsampled PCM samples to the visualization buffer."""
        data = chunk.data
        if len(data) == 0:
            return

        # Take mono mixdown
        if data.ndim > 1:
            mono = np.mean(data, axis=1)
        else:
            mono = data

        # Downsample to ~32 samples per chunk to maintain smooth flow
        step = max(1, len(mono) // 32)
        downsampled = mono[::step]

        for s in downsampled:
            self._samples.append(float(s))

        self.update()

    def reset(self) -> None:
        """Clear the waveform."""
        self._samples = deque([0.0] * self.max_samples, maxlen=self.max_samples)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        mid_y = height / 2.0

        # Background
        painter.fillRect(0, 0, width, height, QColor("#121318"))

        # Center reference line
        painter.setPen(QPen(QColor("#20232E"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(0, int(mid_y), width, int(mid_y))

        samples = list(self._samples)
        num_pts = len(samples)
        if num_pts < 2:
            return

        path = QPainterPath()
        dx = width / float(num_pts - 1)

        first_y = mid_y - (samples[0] * mid_y * 0.9)
        path.moveTo(QPointF(0, first_y))

        for i, s in enumerate(samples[1:], start=1):
            x = i * dx
            y = mid_y - (s * mid_y * 0.9)
            path.lineTo(QPointF(x, y))

        # Outer Glow Pen
        painter.setPen(QPen(QColor(59, 130, 246, 60), 3))
        painter.drawPath(path)

        # Crisp Center Waveform Pen
        painter.setPen(QPen(QColor("#60A5FA"), 1.5))
        painter.drawPath(path)
