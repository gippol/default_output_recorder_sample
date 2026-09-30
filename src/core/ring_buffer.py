"""
Thread-safe, high-performance circular ring buffer for audio chunks.
Enables time-shift (retroactive / pre-roll) recording and smooth streaming.
"""

from collections import deque
import threading
from typing import List, Optional
import numpy as np
from src.core.models import AudioChunk, AudioFormat


class AudioRingBuffer:
    """
    Maintains a rolling window of the most recent N seconds of audio in memory.
    Thread-safe for concurrent writes from audio capture and reads from record-trigger.
    """

    def __init__(self, capacity_seconds: float = 30.0, audio_format: Optional[AudioFormat] = None):
        self.capacity_seconds = capacity_seconds
        self.format = audio_format or AudioFormat()
        self._chunks: deque[AudioChunk] = deque()
        self._lock = threading.Lock()
        self._current_duration = 0.0

    def set_capacity(self, capacity_seconds: float) -> None:
        """Update buffer capacity in seconds."""
        with self._lock:
            self.capacity_seconds = max(1.0, capacity_seconds)
            self._trim_excess()

    def push(self, chunk: AudioChunk) -> None:
        """Add a new audio chunk to the ring buffer, dropping oldest if full."""
        with self._lock:
            self._chunks.append(chunk)
            self._current_duration += chunk.duration
            self._trim_excess()

    def _trim_excess(self) -> None:
        """Remove old chunks until duration is within capacity."""
        while self._current_duration > self.capacity_seconds and len(self._chunks) > 1:
            removed = self._chunks.popleft()
            self._current_duration -= removed.duration

    def get_snapshot(self) -> List[AudioChunk]:
        """
        Get a shallow copy list of all chunks currently in the ring buffer.
        Safe to call while capture thread is actively pushing.
        """
        with self._lock:
            return list(self._chunks)

    def get_concatenated_array(self) -> np.ndarray:
        """
        Concatenates all buffered chunks into a single contiguous numpy array.
        Returns empty array if buffer is empty.
        """
        with self._lock:
            if not self._chunks:
                return np.empty((0, self.format.channels), dtype=np.float32)
            return np.concatenate([c.data for c in self._chunks], axis=0)

    @property
    def current_duration(self) -> float:
        """Total duration of audio currently stored in buffer."""
        with self._lock:
            return self._current_duration

    @property
    def is_empty(self) -> bool:
        with self._lock:
            return len(self._chunks) == 0

    def clear(self) -> None:
        """Clear all buffered data."""
        with self._lock:
            self._chunks.clear()
            self._current_duration = 0.0
