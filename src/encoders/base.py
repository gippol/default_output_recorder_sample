"""
Abstract Audio Sink interface for writing audio streams to disk or memory.
"""

from abc import ABC, abstractmethod
from typing import Optional
from src.core.models import AudioChunk, AudioFormat, OutputFormat


class IAudioSink(ABC):
    """Abstract interface for audio output destinations."""

    @abstractmethod
    def open(self, filepath: str, audio_format: AudioFormat, output_format: OutputFormat, bitrate_kbps: int = 320) -> None:
        """Initialize and open the sink for streaming writes."""
        pass

    @abstractmethod
    def write_chunk(self, chunk: AudioChunk) -> None:
        """Write an audio chunk to the sink."""
        pass

    @abstractmethod
    def close(self) -> str:
        """
        Finalize and close the sink.
        Returns the final saved file path.
        """
        pass

    @abstractmethod
    def is_open(self) -> bool:
        """Returns True if sink is ready to accept chunks."""
        pass
