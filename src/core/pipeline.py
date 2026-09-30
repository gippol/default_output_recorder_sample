"""
Audio Processing Pipeline and Filter Interceptors.
Follows the Chain of Responsibility pattern for real-time DSP & telemetry.
"""

from abc import ABC, abstractmethod
import math
from typing import List, Optional
import numpy as np
from src.core.models import AudioChunk, AudioTelemetry
from src.core.event_bus import EventBus, EventType


class IAudioFilter(ABC):
    """Abstract interface for audio filters/interceptors in the pipeline."""

    @abstractmethod
    def process(self, chunk: AudioChunk) -> Optional[AudioChunk]:
        """
        Process an incoming audio chunk.
        Return modified AudioChunk, or None if chunk should be dropped (e.g. VAD silence).
        """
        pass


class PeakMeterFilter(IAudioFilter):
    """
    High-performance telemetry calculator using vector operations.
    Calculates peak/RMS in dB and emits AudioTelemetry events for UI 60fps rendering.
    """

    def __init__(self, emit_event: bool = True, min_db: float = -60.0):
        self.emit_event = emit_event
        self.min_db = min_db
        self.event_bus = EventBus()

    def process(self, chunk: AudioChunk) -> Optional[AudioChunk]:
        data = chunk.data
        if len(data) == 0:
            return chunk

        # Vectorized Peak calculation per channel
        # data shape: (frames, channels)
        channel_peaks = []
        for ch in range(data.shape[1] if data.ndim > 1 else 1):
            ch_data = data[:, ch] if data.ndim > 1 else data
            abs_max = float(np.max(np.abs(ch_data)))
            peak_db = 20.0 * math.log10(abs_max) if abs_max > 1e-5 else self.min_db
            channel_peaks.append(max(self.min_db, min(0.0, peak_db)))

        overall_peak_db = max(channel_peaks) if channel_peaks else self.min_db

        # RMS calculation
        rms_val = float(np.sqrt(np.mean(data ** 2)))
        rms_db = 20.0 * math.log10(rms_val) if rms_val > 1e-5 else self.min_db
        rms_db = max(self.min_db, min(0.0, rms_db))

        is_clipping = overall_peak_db >= -0.05
        is_speaking = not chunk.is_silent

        telemetry = AudioTelemetry(
            peak_db=overall_peak_db,
            rms_db=rms_db,
            channel_peaks=channel_peaks,
            is_clipping=is_clipping,
            is_speaking=is_speaking,
        )

        if self.emit_event:
            self.event_bus.publish(EventType.TELEMETRY_UPDATE, telemetry)

        return chunk


class VADFilter(IAudioFilter):
    """
    Voice Activity Detector (VAD) filter based on energy thresholding.
    Can mark chunk as silent or optionally drop silence chunks.
    """

    def __init__(self, threshold_db: float = -45.0, drop_silence: bool = False):
        self.threshold_db = threshold_db
        self.drop_silence = drop_silence

    def process(self, chunk: AudioChunk) -> Optional[AudioChunk]:
        data = chunk.data
        if len(data) == 0:
            return chunk

        # Calculate signal energy
        rms_val = float(np.sqrt(np.mean(data ** 2)))
        rms_db = 20.0 * math.log10(rms_val) if rms_val > 1e-5 else -100.0

        is_silent = rms_db < self.threshold_db
        chunk.is_silent = is_silent

        if is_silent and self.drop_silence:
            return None  # Drop chunk to save disk space

        return chunk


class GainNormalizerFilter(IAudioFilter):
    """
    Applies automatic gain or fixed amplification to prevent quiet recordings.
    """

    def __init__(self, target_peak_db: float = -1.0, max_gain_factor: float = 4.0):
        self.target_peak_db = target_peak_db
        self.max_gain_factor = max_gain_factor

    def process(self, chunk: AudioChunk) -> Optional[AudioChunk]:
        data = chunk.data
        if len(data) == 0:
            return chunk

        abs_max = float(np.max(np.abs(data)))
        if abs_max > 1e-4:
            target_linear = 10.0 ** (self.target_peak_db / 20.0)
            gain = min(target_linear / abs_max, self.max_gain_factor)
            normalized_data = np.clip(data * gain, -1.0, 1.0)
            chunk.data = normalized_data

        return chunk


class AudioPipeline:
    """
    Composite pipeline that executes a chain of audio filters sequentially.
    """

    def __init__(self):
        self._filters: List[IAudioFilter] = []

    def add_filter(self, audio_filter: IAudioFilter) -> "AudioPipeline":
        """Add a filter to the end of the processing chain."""
        self._filters.append(audio_filter)
        return self

    def process(self, chunk: AudioChunk) -> Optional[AudioChunk]:
        """
        Pass audio chunk through all filters sequentially.
        If any filter returns None, chunk processing is aborted (dropped).
        """
        current_chunk: Optional[AudioChunk] = chunk
        for f in self._filters:
            if current_chunk is None:
                break
            current_chunk = f.process(current_chunk)
        return current_chunk

    def clear(self) -> None:
        """Clear all registered filters."""
        self._filters.clear()
